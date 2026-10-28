from __future__ import annotations

import subprocess

from scripts import install_project_dependencies as installer


def test_index_urls_are_ordered_and_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "https://primary.example/simple/")
    monkeypatch.setenv(
        "PIP_FALLBACK_INDEX_URLS",
        "https://fallback.example/simple/ https://primary.example/simple/",
    )

    assert installer._index_urls() == [
        "https://primary.example/simple/",
        "https://fallback.example/simple/",
    ]


def test_install_retries_each_index_without_extra_indexes(monkeypatch) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "https://primary.example/simple/")
    monkeypatch.setenv(
        "PIP_FALLBACK_INDEX_URLS",
        "https://fallback.example/simple/",
    )
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://unsafe.example/simple/")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command, *, check, env):
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0)

    monkeypatch.setattr(installer.subprocess, "run", run)

    installer._install(["fastapi>=0.115.0"], allow_source=False)

    assert len(calls) == 2
    assert calls[0][0][calls[0][0].index("--index-url") + 1] == (
        "https://primary.example/simple/"
    )
    assert calls[1][0][calls[1][0].index("--index-url") + 1] == (
        "https://fallback.example/simple/"
    )
    assert all("PIP_EXTRA_INDEX_URL" not in environment for _, environment in calls)
    assert all("--only-binary=:all:" in command for command, _ in calls)


def test_install_fails_after_all_indexes_fail(monkeypatch) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "https://primary.example/simple/")
    monkeypatch.setenv("PIP_FALLBACK_INDEX_URLS", "")

    def run(command, *, check, env):
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(installer.subprocess, "run", run)

    try:
        installer._install(["fastapi>=0.115.0"], allow_source=True)
    except subprocess.CalledProcessError as error:
        assert error.returncode == 2
        assert "--only-binary=:all:" not in error.cmd
    else:
        raise AssertionError("expected dependency installation to fail")
