from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import UploadFile

from app.errors import ApiError
from app.services.audio import AudioProbe, probe_wav_file

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_MEDIA = {
    "audio/webm",
    "video/webm",
    "audio/ogg",
    "application/ogg",
    "audio/mp4",
    "video/mp4",
    "audio/aac",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
}


async def normalize_upload(
    file: UploadFile, folder: Path, max_seconds: int
) -> tuple[Path, AudioProbe]:
    media_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_MEDIA:
        raise ApiError("unsupported_audio", "فرمت فایل صوتی پشتیبانی نمی‌شود.")
    source, target = folder / "recording", folder / "normalized.wav"
    size = 0
    with source.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise ApiError("archive_too_large", "حجم فایل صوتی بیش از ۲۰ مگابایت است.")
            handle.write(chunk)
    if size == 0:
        raise ApiError("unsupported_audio", "فایل ضبط‌شده خالی است.")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        "wav,matroska,webm,mov,ogg,mp3,aac",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-t",
        str(max_seconds + 1),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=45)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode:
        raise ApiError("unsupported_audio", "فایل صوتی قابل تبدیل نیست؛ دوباره ضبط کنید.")
    probe = await probe_wav_file(target)
    if probe.duration_ms > max_seconds * 1000 + 100:
        raise ApiError("unsupported_audio", "مدت فایل صوتی از سقف مجاز بیشتر است.")
    if probe.duration_ms < 500:
        raise ApiError("unsupported_audio", "ضبط خیلی کوتاه است؛ حداقل نیم ثانیه صحبت کنید.")
    return target, probe
