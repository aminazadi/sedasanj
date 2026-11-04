from __future__ import annotations

from collections.abc import Iterable

INTERNAL_CALLER_LABEL = "همکار تماس‌گیرنده"
INTERNAL_CALLEE_LABEL = "همکار پاسخ‌دهنده"


def speaker_labels(direction: str | None, speaker_mode: str | None) -> dict[int, str]:
    """Channel to speaker mapping; mirrors the labels shown on the call detail page."""
    if (speaker_mode or "").startswith("mono"):
        return {0: "گوینده ۱", 1: "گوینده ۲"}
    if direction == "inbound":
        return {0: "مشتری", 1: "اپراتور"}
    if direction == "outbound":
        return {0: "اپراتور", 1: "مشتری"}
    if direction == "internal":
        return {0: INTERNAL_CALLER_LABEL, 1: INTERNAL_CALLEE_LABEL}
    return {0: "کانال ۱", 1: "کانال ۲"}


def speaker_mode(audio_channels: int, *, diarized: bool) -> str:
    if audio_channels == 2:
        return "dual_channel"
    return "mono_diarized" if diarized else "mono_unknown"


def render_turns(
    turns: Iterable[tuple[int, int, str]],
    direction: str | None,
    mode: str | None,
) -> str:
    """Render channel-tagged turns for the stored transcript and analysis prompt."""
    labels = speaker_labels(direction, mode)
    aliases = {
        "مشتری": "caller",
        "اپراتور": "agent",
        INTERNAL_CALLER_LABEL: "caller",
        INTERNAL_CALLEE_LABEL: "agent",
    }
    lines = []
    for channel, start_ms, content in sorted(turns, key=lambda turn: (turn[1], turn[0])):
        seconds = max(start_ms, 0) // 1000
        label = aliases.get(labels.get(channel, ""), f"speaker_{channel + 1}")
        lines.append(f"[{label} {seconds // 60:02d}:{seconds % 60:02d}] {content}".strip())
    return "\n".join(lines)
