from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import help_content as hc

UUID = "0a1b2c3d-1111-2222-3333-444455556666"


def test_sanitizer_removes_scripts_handlers_and_foreign_media() -> None:
    html, plain = hc.sanitize_help_html(
        '<p onclick="x()">Hello <script>alert(1)</script><strong>world</strong></p>'
        '<img src="https://evil.example/a.png" onerror="x()">'
        '<a href="javascript:alert(1)">bad</a><a href="https://ok.example/p">ok</a>'
        '<style>p{}</style><svg onload="x()"><circle/></svg>'
    )
    assert "<script" not in html and "onclick" not in html and "onerror" not in html
    assert "<img" not in html  # only platform media may be embedded
    assert "javascript:" not in html and "<svg" not in html and "<style" not in html
    assert '<a href="https://ok.example/p" rel="noopener noreferrer" target="_blank">ok</a>' in html
    assert plain.startswith("Hello world")


def test_sanitizer_keeps_platform_images_and_videos() -> None:
    html, _ = hc.sanitize_help_html(
        f'<figure><img src="/v1/help/media/{UUID}" alt="شکل ۱" width="640" height="x">'
        f"<figcaption>توضیح</figcaption></figure>"
        f'<video src="/v1/help/media/{UUID}" poster="/v1/help/media/{UUID}"'
        ' preload="metadata"></video>'
    )
    assert f'<img src="/v1/help/media/{UUID}" alt="شکل ۱" width="640" loading="lazy">' in html
    assert "height=" not in html  # non-numeric size dropped
    assert f'<video src="/v1/help/media/{UUID}"' in html and " controls" in html
    assert "<figcaption>توضیح</figcaption>" in html


@pytest.mark.parametrize(
    "src",
    [
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://www.aparat.com/video/video/embed/videohash/abc12/vt/frame",
    ],
)
def test_sanitizer_allows_only_known_embed_hosts_with_forced_sandbox(src: str) -> None:
    html, _ = hc.sanitize_help_html(f'<iframe src="{src}" onload="x()" srcdoc="<script>"></iframe>')
    assert f'src="{src}"' in html
    assert 'sandbox="allow-scripts allow-same-origin allow-presentation"' in html
    assert "onload" not in html and "srcdoc" not in html


@pytest.mark.parametrize(
    "src",
    [
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://evil.example/embed/x",
        "javascript:alert(1)",
        "https://www.youtube-nocookie.com.evil.example/embed/dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/../x",
    ],
)
def test_sanitizer_drops_unknown_embeds(src: str) -> None:
    html, _ = hc.sanitize_help_html(f'<iframe src="{src}"></iframe>')
    assert "iframe" not in html


def test_sanitizer_closes_unbalanced_markup() -> None:
    html, _ = hc.sanitize_help_html("<ul><li>one<li>two</ul><p>open")
    assert html.count("<li>") == html.count("</li>") and html.endswith("</p>")


def test_media_sniffing_trusts_bytes_not_declared_type() -> None:
    assert hc.sniff_media(b"\x89PNG\r\n\x1a\n" + b"0" * 20) == ("image", "image/png")
    assert hc.sniff_media(b"\xff\xd8\xff\xe0" + b"0" * 20) == ("image", "image/jpeg")
    assert hc.sniff_media(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("image", "image/webp")
    assert hc.sniff_media(b"GIF89a" + b"0" * 10) == ("image", "image/gif")
    assert hc.sniff_media(b"\x00\x00\x00\x18ftypmp42" + b"0" * 10) == ("video", "video/mp4")
    assert hc.sniff_media(b"\x1a\x45\xdf\xa3" + b"0" * 10) == ("video", "video/webm")
    assert hc.sniff_media(b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()">') is None
    assert hc.sniff_media(b"<html><script>") is None
    assert hc.sniff_media(b"") is None


def test_media_limits_and_extensions_are_defined_for_every_allowed_type() -> None:
    for content_type in (*hc.IMAGE_TYPES, *hc.VIDEO_TYPES):
        assert hc.media_extension(content_type).startswith(".")
    assert hc.media_limit("image") < hc.media_limit("video")


@pytest.mark.parametrize("slug", ["a", "ssl-error", "ss-upl-0401", "v2-install"])
def test_valid_slugs(slug: str) -> None:
    assert hc.SLUG_RE.match(slug)


@pytest.mark.parametrize("slug", ["", "Bad", "a_b", "-a", "a-", "a--b", "a b", "../x", "a.b"])
def test_invalid_slugs(slug: str) -> None:
    assert not hc.SLUG_RE.match(slug)


def test_error_code_pattern_accepts_module_and_api_codes_only() -> None:
    for code in ("SS-UPL-0401", "unauthorized", "asr_provider_credit"):
        assert hc.ERROR_CODE_RE.match(code)
    for code in ("", "a", "x" * 41, "SS UPL", "SS/UPL", "SS-UPL-0401;"):
        assert not hc.ERROR_CODE_RE.match(code)


def test_module_error_catalog_is_well_formed() -> None:
    catalog = hc.module_error_catalog()
    codes = [entry["code"] for entry in catalog]
    assert len(codes) == len(set(codes)) and len(codes) >= 70
    for entry in catalog:
        assert re.match(r"^SS-[A-Z]{3,4}-\d{4}$", entry["code"])
        assert entry["severity"] in {"info", "warning", "error", "critical"}
        assert entry["title"] and entry["action"]
        assert hc.ERROR_CODE_RE.match(entry["code"])


def test_module_error_catalog_matches_the_php_source_when_present() -> None:
    php = (
        Path(__file__).resolve().parents[2]
        / "freepbx-module"
        / "engine"
        / "src"
        / "ErrorCatalog.php"
    )
    if not php.exists():
        pytest.skip("freepbx-module ErrorCatalog.php is not on this branch")
    source = php.read_text(encoding="utf-8")
    php_codes = re.findall(r"^\s+'(SS-[A-Z]{3,4}-\d{4})' => \[", source, flags=re.MULTILINE)
    assert sorted(php_codes) == sorted(e["code"] for e in hc.module_error_catalog()), (
        "Regenerate app/data/module_error_codes.json from ErrorCatalog.php "
        "(see docs/help-center.md)"
    )


def test_help_routes_are_registered_and_staff_writes_need_super_admin() -> None:
    from app.main import create_app
    from app.routers.help import router

    schema = create_app().openapi()["paths"]
    for path, method in [
        ("/v1/help/articles", "get"),
        ("/v1/help/articles/{slug}", "get"),
        ("/v1/help/errors/{code}", "get"),
        ("/v1/help/media/{media_id}", "get"),
        ("/v1/admin/help/articles", "post"),
        ("/v1/admin/help/media", "post"),
        ("/v1/admin/help/error-codes/seed-module", "post"),
    ]:
        assert method in schema.get(path, {}), (path, method)

    writers = [
        route
        for route in router.routes
        if route.path.startswith("/v1/admin/help/")  # type: ignore[attr-defined]
        and set(route.methods) & {"POST", "PUT", "PATCH", "DELETE"}  # type: ignore[attr-defined]
    ]
    assert len(writers) >= 10
    for route in writers:
        calls = [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]
        # Every authoring route depends on the super_admin guard built by require_staff_roles.
        assert any("require_staff_roles" in getattr(call, "__qualname__", "") for call in calls), (
            route.path
        )  # type: ignore[attr-defined]


def test_public_article_list_accepts_kind_filter_only_from_known_kinds() -> None:
    from app.main import create_app

    params = create_app().openapi()["paths"]["/v1/help/articles"]["get"]["parameters"]
    kind = next(p for p in params if p["name"] == "kind")
    assert kind["schema"]["anyOf"][0]["pattern"] == "^(article|error|faq)$"
