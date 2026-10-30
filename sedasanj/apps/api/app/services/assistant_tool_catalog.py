"""Searchable capability metadata for the assistant's bounded discovery phase."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import assistant_tools

SEARCH_NAME = "search_tools"
MAX_DISCOVERY_ROUNDS = 2
KEYWORDS = {
    "get_current_time": "زمان تاریخ ساعت امروز time date now",
    "search_calls": "تماس تلفن پیدا جستجو search calls phone",
    "get_call_details": "تماس جزئیات مشخصات details metadata",
    "search_transcripts": "متن مکالمه رونوشت جستجو transcript conversation text search",
    "get_call_analysis": "تحلیل خلاصه احساس فروش analysis summary sentiment sales crm",
    "get_call_analytics": "آمار تعداد مجموع تماس statistics analytics count",
    "get_operator_performance": "اپراتور عملکرد امتیاز operator performance score",
    "visualize_statistics": "نمودار آمار نمایش chart graph visualize statistics",
    "export_data": (
        "فایل خروجی دانلود دریافت اکسل پی دی اف گزارش "
        "file export download excel xlsx csv json pdf markdown txt"
    ),
}


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("describe the required capability")
        return value.strip()


def schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": SEARCH_NAME,
            "description": (
                "Search the available tool catalog by capability in Persian or English. "
                "Returns matching tool names, descriptions and argument schemas; no organization "
                "data is accessed. Then select and call one or several matching tools."
            ),
            "parameters": SearchArguments.model_json_schema(),
        },
    }


def _words(value: str) -> set[str]:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ي", "ی").replace("ك", "ک")
    return set(re.findall(r"[^\W_]+", text.replace("\u200c", " ")))


def search(arguments: SearchArguments, enabled: set[str] | None) -> dict[str, Any]:
    words = _words(arguments.query)
    ranked = []
    for tool in assistant_tools.TOOLS:
        if enabled is not None and tool.name not in enabled:
            continue
        primary = _words(f"{tool.name} {tool.title} {KEYWORDS.get(tool.name, '')}")
        secondary = _words(tool.description)
        score = len(words & primary) * 3 + len(words & secondary)
        if score:
            ranked.append((score, tool))
    ranked.sort(key=lambda item: -item[0])
    items = [
        {
            "name": tool.name,
            "title": tool.title,
            "description": tool.description,
            "parameters": tool.arguments.model_json_schema(),
        }
        for _score, tool in ranked[: arguments.limit]
    ]
    return {"count": len(items), "items": items}
