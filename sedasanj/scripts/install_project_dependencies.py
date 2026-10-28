from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9_.-]+")


def _index_urls() -> list[str]:
    configured = [
        os.environ.get("PIP_INDEX_URL", ""),
        *shlex.split(os.environ.get("PIP_FALLBACK_INDEX_URLS", "")),
    ]
    return list(dict.fromkeys(url for url in configured if url))


def _install(dependencies: list[str], *, allow_source: bool) -> None:
    indexes = _index_urls()
    if not indexes:
        raise SystemExit("no package index configured")

    last_failure: subprocess.CompletedProcess[bytes] | None = None
    for index_url in indexes:
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--retries",
            "5",
            "--timeout",
            "120",
            "--index-url",
            index_url,
        ]
        if not allow_source:
            command.append("--only-binary=:all:")

        environment = os.environ.copy()
        environment.pop("PIP_EXTRA_INDEX_URL", None)
        last_failure = subprocess.run(
            [*command, *dependencies],
            check=False,
            env=environment,
        )
        if last_failure.returncode == 0:
            return

    assert last_failure is not None
    raise subprocess.CalledProcessError(last_failure.returncode, last_failure.args)


def _dependencies(
    pyproject_path: Path,
    *,
    extra: str | None,
    extra_only: bool,
    excluded: set[str],
) -> list[str]:
    with pyproject_path.open("rb") as file:
        project = tomllib.load(file)["project"]

    dependencies = [] if extra_only else list(project.get("dependencies", []))
    if extra is not None:
        dependencies.extend(project.get("optional-dependencies", {}).get(extra, []))

    selected = []
    for requirement in dependencies:
        match = _REQUIREMENT_NAME.match(requirement)
        if match is None:
            raise ValueError(f"invalid dependency requirement: {requirement}")
        if match.group(0).lower() not in excluded:
            selected.append(requirement)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--extra")
    parser.add_argument("--extra-only", action="store_true")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--allow-source", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    dependencies = _dependencies(
        args.pyproject,
        extra=args.extra,
        extra_only=args.extra_only,
        excluded={name.lower() for name in args.exclude},
    )
    if not dependencies:
        raise SystemExit("no dependencies selected")
    if args.list:
        print("\n".join(dependencies))
        return

    _install(dependencies, allow_source=args.allow_source)


if __name__ == "__main__":
    main()
