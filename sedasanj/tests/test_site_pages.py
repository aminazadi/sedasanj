from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.services import site_pages as sp


@pytest.mark.parametrize("slug", sp.PAGE_SLUGS)
def test_every_default_is_valid_and_stable(slug: str) -> None:
    content = sp.default_content(slug)
    assert sp.validate_content(slug, content) == content


def test_missing_or_corrupt_storage_falls_back_to_default() -> None:
    default = sp.default_content("about")
    assert sp.load_content("about", None) == (default, True)
    assert sp.load_content("about", "{not json") == (default, True)
    assert sp.load_content("about", json.dumps({"hero_title": ["wrong type"]})) == (default, True)


def test_stored_content_round_trips() -> None:
    content = sp.default_content("contact")
    content["hero_title"] = "عنوان تازه"
    loaded, is_default = sp.load_content("contact", sp.dump_content(content))
    assert not is_default
    assert loaded["hero_title"] == "عنوان تازه"


@pytest.mark.parametrize(
    "link", ["javascript:alert(1)", "http://insecure.example", "//evil.example", "data:text/html,x"]
)
def test_unsafe_links_are_rejected(link: str) -> None:
    about = sp.default_content("about")
    about["outcome_link"] = link
    with pytest.raises(ValidationError):
        sp.validate_content("about", about)
    contact = sp.default_content("contact")
    contact["methods"][0]["href"] = link
    with pytest.raises(ValidationError):
        sp.validate_content("contact", contact)


@pytest.mark.parametrize(
    "link", ["/contact", "https://example.com/a", "tel:+989121234567", "mailto:a@b.co", ""]
)
def test_safe_links_are_accepted(link: str) -> None:
    about = sp.default_content("about")
    about["outcome_link"] = link
    assert sp.validate_content("about", about)["outcome_link"] == link


def test_limits_are_enforced_and_legacy_fields_dropped() -> None:
    legal = sp.default_content("terms")
    legal["sections"] = [{"title": "t", "body": "x"}] * 41
    with pytest.raises(ValidationError):
        sp.validate_content("terms", legal)
    legal = sp.default_content("terms")
    legal["kicker"] = "legacy field from an older version"
    assert "kicker" not in sp.validate_content("terms", legal)
    with pytest.raises(ValidationError):
        sp.validate_content("terms", None)


def test_landing_video_defaults_and_media_ids() -> None:
    content = sp.default_content("landing_video")
    assert content["title"] == "چرا صداسنج؟"
    assert content["avatar_media_id"] == content["video_media_id"] == ""
    content["video_media_id"] = "3F2504E0-4F89-41D3-9A0C-0305E82C3301"
    assert (
        sp.validate_content("landing_video", content)["video_media_id"]
        == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    )
    for bad in ("../etc/passwd", "javascript:alert(1)", "not-a-uuid"):
        content["avatar_media_id"] = bad
        with pytest.raises(ValidationError):
            sp.validate_content("landing_video", content)
