from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("/etc/cbi-agent/cbi-agent.toml")


@dataclass(frozen=True)
class ServerConfig:
    base_url: str
    timeout_seconds: int = 60


@dataclass(frozen=True)
class AsteriskConfig:
    ami_host: str
    ami_port: int
    ami_user: str
    ami_secret: str
    monitor_dir: Path


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 8000
    channels: int = 2
    delete_after_upload: bool = True


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 100
    backoff_seconds: int = 30
    retry_max_seconds: int = 3600
    credit_retry_seconds: int = 3600


@dataclass(frozen=True)
class ArchiveConfig:
    format: str = "wav"
    password: str | None = None


@dataclass(frozen=True)
class AgentConfig:
    server: ServerConfig
    api_key: str
    asterisk: AsteriskConfig
    audio: AudioConfig
    retry: RetryConfig
    archive: ArchiveConfig = ArchiveConfig()
    spool_dir: Path = Path("/var/lib/cbi-agent/spool")


def load_config(path: Path = DEFAULT_PATH) -> AgentConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    server = raw.get("server", {})
    asterisk = raw.get("asterisk", {})
    audio = raw.get("audio", {})
    retry = raw.get("retry", {})
    archive = raw.get("archive", {})
    archive_format = str(archive.get("format", "wav")).lower()
    archive_password = archive.get("password")
    if archive_format not in {"wav", "gzip", "zip"}:
        raise ValueError("archive.format must be wav, gzip, or zip")
    if archive_format != "zip" and archive_password:
        raise ValueError("archive.password is only supported for zip")
    if archive_password is not None and not 12 <= len(str(archive_password)) <= 128:
        raise ValueError("archive.password must be between 12 and 128 characters")
    return AgentConfig(
        server=ServerConfig(
            base_url=str(server["base_url"]).rstrip("/"),
            timeout_seconds=int(server.get("timeout_seconds", 60)),
        ),
        api_key=str(raw["auth"]["api_key"]),
        asterisk=AsteriskConfig(
            ami_host=str(asterisk.get("ami_host", "127.0.0.1")),
            ami_port=int(asterisk.get("ami_port", 5038)),
            ami_user=str(asterisk["ami_user"]),
            ami_secret=str(asterisk["ami_secret"]),
            monitor_dir=Path(str(asterisk.get("monitor_dir", "/var/spool/asterisk/monitor"))),
        ),
        audio=AudioConfig(
            sample_rate=int(audio.get("sample_rate", 8000)),
            channels=int(audio.get("channels", 2)),
            delete_after_upload=bool(audio.get("delete_after_upload", True)),
        ),
        retry=RetryConfig(
            max_attempts=int(retry.get("max_attempts", 100)),
            backoff_seconds=int(retry.get("backoff_seconds", 30)),
            retry_max_seconds=int(retry.get("retry_max_seconds", 3600)),
            credit_retry_seconds=int(retry.get("credit_retry_seconds", 3600)),
        ),
        archive=ArchiveConfig(
            format=archive_format,
            password=str(archive_password) if archive_password is not None else None,
        ),
        spool_dir=Path(str(raw.get("spool", {}).get("dir", "/var/lib/cbi-agent/spool"))),
    )
