"""Executable snippets explicitly trusted by the platform super administrator."""

import hashlib
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import PlatformSetting

KEY = "site_scripts"
Scope = Literal["public", "customer"]
Placement = Literal["head", "body"]


class ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script" or self.current is not None:
            raise ValueError("only script tags are supported")
        allowed = {"src", "type", "async", "defer", "crossorigin", "integrity", "referrerpolicy"}
        allowed.update({"id", "charset", "nomodule"})
        if any(key not in allowed and not key.startswith("data-") for key, _ in attrs):
            raise ValueError("unsupported script attribute")
        self.current = {key: value or "" for key, value in attrs}
        src = self.current.get("src")
        if "src" in self.current:
            url = urlsplit(src or "")
            if (
                not src
                or not (
                    (
                        url.scheme == "https"
                        and url.hostname
                        and not url.username
                        and not url.password
                    )
                    or (src.startswith("/") and not src.startswith("//") and "\\" not in src)
                )
                or any(character.isspace() for character in src)
            ):
                raise ValueError("use an HTTPS or same-origin script URL")
        if self.current.get("type", "") not in {
            "",
            "text/javascript",
            "application/javascript",
            "module",
        }:
            raise ValueError("unsupported script type")
        self.current["code"] = ""

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current["code"] += data
        elif data.strip():
            raise ValueError("wrap JavaScript in script tags")

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self.current is None:
            raise ValueError("unmatched script tag")
        self.scripts.append(self.current)
        self.current = None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raise ValueError("script tags must have closing tags")

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def parse_scripts(value: str) -> list[dict[str, str]]:
    try:
        parser = ScriptParser()
        parser.feed(value)
        parser.close()
        if parser.current is not None or len(parser.scripts) > 30:
            raise ValueError("unclosed script or too many scripts")
        return parser.scripts
    except ValueError:
        raise ApiError(
            "site_scripts_invalid",
            "Use at most 30 closed script tags per field with HTTPS or same-origin src URLs; "
            "remove other HTML and unsupported attributes, then save again.",
        ) from None


class ScriptSlots(BaseModel):
    head: str = Field(default="", max_length=100_000)
    body: str = Field(default="", max_length=100_000)


class SiteScripts(BaseModel):
    public: ScriptSlots = Field(default_factory=ScriptSlots)
    customer: ScriptSlots = Field(default_factory=ScriptSlots)

    def validate_snippets(self) -> None:
        for slots in (self.public, self.customer):
            for snippet in (slots.head, slots.body):
                parse_scripts(snippet)


async def get_settings(session: AsyncSession) -> SiteScripts:
    row = await session.get(PlatformSetting, KEY)
    return SiteScripts.model_validate_json(row.value) if row else SiteScripts()


def version(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()
