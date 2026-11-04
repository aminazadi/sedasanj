"""Jalase-Negar Android releases: APK inspection, update selection and range downloads.

The app asks for an update on every cold start, so selection must be cheap and strict: an offer
is made only when the installed app can really install the APK (same signing certificate, enough
SDK, a matching ABI) and the APK carries a higher ``versionCode``.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from app.config import get_settings
from app.errors import ApiError

PACKAGE_NAME = "app.jalasenegar.jalase_negar"
APK_MIME = "application/vnd.android.package-archive"
KEY_PREFIX = "jalase-negar-releases/"

_VERSION_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")
_ABI_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_CERT_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ENTRIES = 20_000
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
_TOOL_TIMEOUT_SECONDS = 90

# (exit code, stdout)
ToolRunner = Callable[[Sequence[str]], Awaitable[tuple[int, str]]]


@dataclass(frozen=True)
class ApkInspection:
    package_name: str
    version_name: str
    version_code: int
    min_sdk: int
    abis: tuple[str, ...]
    sha256: str
    size: int
    cert_sha256: str


class ReleaseLike(Protocol):
    id: UUID
    version_code: int
    min_sdk: int
    abis: list[str]
    status: str
    signing_cert_sha256: str


# --- configuration ----


def trusted_cert_fingerprints() -> frozenset[str]:
    raw = get_settings().jalase_negar_apk_cert_sha256
    values = {re.sub(r"[^0-9a-f]", "", part.lower()) for part in raw.split(",") if part.strip()}
    return frozenset(value for value in values if _CERT_RE.fullmatch(value))


def normalize_cert(value: str | None) -> str | None:
    cleaned = re.sub(r"[^0-9a-f]", "", (value or "").lower())
    return cleaned if _CERT_RE.fullmatch(cleaned) else None


# --- parsing the output of aapt2 and apksigner ----


def parse_badging(text: str) -> dict[str, Any]:
    """Read package, version, minSdk and native-code ABIs from ``aapt2 dump badging``."""
    package = re.search(
        r"^package: name='([^']*)' versionCode='(\d+)' versionName='([^']*)'", text, re.M
    )
    if package is None:
        raise ApiError("apk_invalid", "the file has no readable Android manifest")
    min_sdk = re.search(r"^(?:minSdkVersion|sdkVersion):'(\d+)'", text, re.M)
    native = re.search(r"^native-code: (.*)$", text, re.M)
    abis = tuple(re.findall(r"'([^']+)'", native.group(1))) if native else ()
    return {
        "package_name": package.group(1),
        "version_code": int(package.group(2)),
        "version_name": package.group(3),
        "min_sdk": int(min_sdk.group(1)) if min_sdk else 1,
        "debuggable": re.search(r"^application-debuggable$", text, re.M) is not None,
        "abis": abis,
    }


_TRUE = r"(?:true|\(type 0x\d+\)0xffffffff)"


def manifest_flags(text: str) -> dict[str, bool]:
    """Flags that make an APK unfit for distribution, from ``aapt2 dump xmltree``."""

    def true_attribute(name: str) -> bool:
        return re.search(rf"android:{name}\(0x[0-9a-f]+\)={_TRUE}", text) is not None

    return {
        "debuggable": true_attribute("debuggable"),
        "test_only": true_attribute("testOnly"),
        "split": re.search(r"^\s*A: split=", text, re.M) is not None
        or true_attribute("isSplitRequired"),
    }


def parse_apksigner(text: str) -> tuple[str, list[str]]:
    """Return (verification summary, signer certificate SHA-256 digests)."""
    if re.search(r"^Verifies\s*$", text, re.M) is None:
        raise ApiError("apk_invalid", "the APK signature is not valid")
    schemes = {
        match.group(1): match.group(2) == "true"
        for match in re.finditer(r"^Verified using v(\S+) scheme[^:]*: (true|false)", text, re.M)
    }
    if not (schemes.get("2") or schemes.get("3") or schemes.get("3.1")):
        raise ApiError("apk_invalid", "the APK must be signed with signature scheme v2 or newer")
    digests = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", text, re.M)
    if len(digests) != 1:
        raise ApiError("apk_invalid", "the APK must have exactly one signer")
    return "verified", [digest.lower() for digest in digests]


# --- running the tools ----


async def run_tool(argv: Sequence[str]) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except (FileNotFoundError, PermissionError) as error:
        raise ApiError(
            "apk_inspection_unavailable",
            "aapt2 or apksigner is not installed on the server; ask the platform operator to "
            "install the Android build-tools or set JALASE_NEGAR_AAPT2_PATH and "
            "JALASE_NEGAR_APKSIGNER_PATH",
        ) from error
    try:
        output, _ = await asyncio.wait_for(process.communicate(), _TOOL_TIMEOUT_SECONDS)
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise ApiError(
            "apk_inspection_unavailable", "APK inspection timed out; upload the file again"
        ) from error
    return process.returncode or 0, output.decode("utf-8", errors="replace")


def _zip_sanity(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ApiError("apk_invalid", "the file is not an APK; upload a signed release APK")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_ENTRIES:
            raise ApiError("apk_invalid", "the APK has too many entries")
        if sum(entry.file_size for entry in entries) > _MAX_UNCOMPRESSED_BYTES:
            raise ApiError("apk_invalid", "the APK expands to an unsafe size")
        names = {entry.filename for entry in entries}
        if "AndroidManifest.xml" not in names:
            hint = (
                " (this looks like an app bundle; build an APK)"
                if "BundleConfig.pb" in names
                else ""
            )
            raise ApiError("apk_invalid", f"the archive has no AndroidManifest.xml{hint}")
        if any(name.startswith(("/", "../")) or "/../" in name for name in names):
            raise ApiError("apk_invalid", "the APK contains unsafe paths")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


async def inspect_apk(path: Path, *, runner: ToolRunner = run_tool) -> ApkInspection:
    """Validate a full, installable, production-signed APK and read its identity."""
    settings = get_settings()
    trusted = trusted_cert_fingerprints()
    if not trusted:
        raise ApiError(
            "apk_inspection_unavailable",
            "no trusted signing certificate is configured; set JALASE_NEGAR_APK_CERT_SHA256 "
            "to the production certificate SHA-256 and restart the API",
        )
    await asyncio.to_thread(_zip_sanity, path)
    aapt2 = settings.jalase_negar_aapt2_path
    code, badging_text = await runner([aapt2, "dump", "badging", str(path)])
    if code != 0:
        raise ApiError("apk_invalid", "the APK manifest could not be read; rebuild the APK")
    badging = parse_badging(badging_text)
    code, manifest_text = await runner(
        [aapt2, "dump", "xmltree", "--file", "AndroidManifest.xml", str(path)]
    )
    if code != 0:
        raise ApiError("apk_invalid", "the APK manifest could not be read; rebuild the APK")
    flags = manifest_flags(manifest_text)
    if flags["debuggable"] or flags["test_only"] or badging["debuggable"]:
        raise ApiError(
            "apk_invalid", "debug or test-only APKs cannot be released; build a release APK"
        )
    if flags["split"]:
        raise ApiError("apk_invalid", "split APKs cannot be released; upload the full APK")
    if badging["package_name"] != PACKAGE_NAME:
        raise ApiError("apk_invalid", f"the APK package must be {PACKAGE_NAME}")
    version_name = str(badging["version_name"])
    if not _VERSION_NAME_RE.fullmatch(version_name):
        raise ApiError("apk_invalid", "the APK versionName has unsupported characters")
    version_code = int(str(badging["version_code"]))
    if version_code < 1 or version_code > 2_100_000_000:
        raise ApiError("apk_invalid", "the APK versionCode is out of range")
    abis = tuple(sorted(badging["abis"]))
    if not all(_ABI_RE.fullmatch(abi) for abi in abis):
        raise ApiError("apk_invalid", "the APK has an unsupported native library layout")

    code, signer_text = await runner(
        [settings.jalase_negar_apksigner_path, "verify", "--print-certs", "-v", str(path)]
    )
    if code != 0:
        raise ApiError("apk_invalid", "the APK signature is not valid; sign the APK again")
    _, certs = parse_apksigner(signer_text)
    if certs[0] not in trusted:
        raise ApiError(
            "apk_invalid",
            "the APK is not signed with the trusted production certificate; sign it with the "
            "release key",
        )
    return ApkInspection(
        package_name=PACKAGE_NAME,
        version_name=version_name,
        version_code=version_code,
        min_sdk=int(str(badging["min_sdk"])),
        abis=abis,
        sha256=await asyncio.to_thread(_sha256, path),
        size=path.stat().st_size,
        cert_sha256=certs[0],
    )


# --- storage keys ----


def artifact_key(release_id: UUID, version_name: str) -> str:
    return f"{KEY_PREFIX}{release_id}/jalase-negar-{version_name}.apk"


def release_id_from_key(key: str) -> UUID | None:
    if not key.startswith(KEY_PREFIX):
        return None
    head = key[len(KEY_PREFIX) :].split("/", 1)[0]
    try:
        return UUID(head)
    except ValueError:
        return None


def orphan_keys(
    stored: Sequence[tuple[str, datetime]],
    known_ids: set[UUID],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Stored keys with no release row once the safe grace period has passed."""
    cutoff = (now or datetime.now(UTC)) - timedelta(
        minutes=get_settings().jalase_negar_orphan_grace_minutes
    )
    stale = []
    for key, modified in stored:
        release_id = release_id_from_key(key)
        if release_id is not None and release_id not in known_ids and modified < cutoff:
            stale.append(key)
    return stale


# --- update selection ----


def parse_abis(raw: str | None) -> list[str]:
    values = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if len(values) > 12 or not all(_ABI_RE.fullmatch(value) for value in values):
        raise ApiError("invalid_request", "abis must be a comma separated list of ABI names")
    return values


def is_compatible(
    release: ReleaseLike, *, sdk_int: int, abis: Sequence[str], cert_sha256: str | None
) -> bool:
    if cert_sha256 is None or release.signing_cert_sha256.lower() != cert_sha256:
        return False
    if release.min_sdk > sdk_int:
        return False
    # An APK without native libraries runs on every ABI.
    return not release.abis or any(abi in release.abis for abi in abis)


def select_update[R: ReleaseLike](
    releases: Sequence[R],
    *,
    version_code: int,
    sdk_int: int,
    abis: Sequence[str],
    cert_sha256: str | None,
) -> R | None:
    candidates = [
        release
        for release in releases
        if release.status == "published"
        and release.version_code > version_code
        and is_compatible(release, sdk_int=sdk_int, abis=abis, cert_sha256=cert_sha256)
    ]
    return max(candidates, key=lambda release: release.version_code, default=None)


# --- HTTP range handling ----


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """One ``bytes=a-b`` window clamped to the file, or None for an unsatisfiable range."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if match is None or size <= 0:
        return None
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if first == "":
        suffix = int(last)
        if suffix == 0:
            return None
        return max(0, size - suffix), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)
