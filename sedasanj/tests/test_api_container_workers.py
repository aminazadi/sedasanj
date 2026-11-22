from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "deploy" / "Dockerfile.api"


def test_api_runs_single_uvicorn_worker() -> None:
    """Engine.IO keeps sessions per process and the proxy has no sticky routing.

    Two workers make polling and websocket upgrades land on a worker that does not know the
    session, which surfaces as "Invalid session" and a slow or failing assistant socket connect.
    """
    cmd_lines = [line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD ")]
    assert len(cmd_lines) == 1
    cmd = cmd_lines[0]
    assert '"--workers", "1"' in cmd
    assert '"--workers", "2"' not in cmd
