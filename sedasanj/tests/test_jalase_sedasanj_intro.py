"""The Jalase-Negar SedaSanj drawer settings accept only safe, bounded values."""

import pytest
from pydantic import ValidationError

from app.services.jalase_sedasanj_intro import DEFAULT_BUTTON_URL, SedasanjIntro


def test_defaults_point_to_sedasanj_without_video() -> None:
    value = SedasanjIntro()
    assert value.enabled is True
    assert value.button_url == DEFAULT_BUTTON_URL == "https://sedasanj.ir"
    assert value.video_url == ""
    assert value.delay_days == 3


@pytest.mark.parametrize(
    "bad",
    ["http://x.ir/a.mp4", "javascript:alert(1)", "//x.ir/a.mp4", "https://a b.ir", "/local.mp4"],
)
def test_links_must_be_https(bad: str) -> None:
    with pytest.raises(ValidationError):
        SedasanjIntro(video_url=bad)
    with pytest.raises(ValidationError):
        SedasanjIntro(button_url=bad)


def test_accepts_https_video_and_custom_button() -> None:
    value = SedasanjIntro(
        video_url="https://api.sedasanj.ir/v1/help/media/abc",
        button_url="https://example.ir/x",
        delay_days=0,
    )
    assert value.video_url.startswith("https://")
    assert value.delay_days == 0


def test_bounds_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SedasanjIntro(delay_days=366)
    with pytest.raises(ValidationError):
        SedasanjIntro(title="")
    with pytest.raises(ValidationError):
        SedasanjIntro.model_validate({"surprise": 1})


def test_routes_registered() -> None:
    from app.routers import jalase_sedasanj_intro as r

    paths = {route.path for route in r.router.routes}  # type: ignore[attr-defined]
    assert r.PUBLIC in paths and r.ADMIN in paths
    assert r.PUBLIC.startswith("/v1/jalase-negar/android/")
