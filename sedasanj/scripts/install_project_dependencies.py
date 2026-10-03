from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9_.-]+")


def _dependencies(
    pyproject_path: Path,
    *,
    extra: str | None,
    extra_only: bool,
    excluded: set[str],
) -> list[str]:
    with pyproject_path.open("rb") as file:
        project = tomllib.load(file)["project"]

    dependencies = [] if extra_only else list(project.get("dependencies", []))
    if extra is not None:
        dependencies.extend(project.get("optional-dependencies", {}).get(extra, []))

    selected = []
    for requirement in dependencies:
        match = _REQUIREMENT_NAME.match(requirement)
        if match is None:
            raise ValueError(f"invalid dependency requirement: {requirement}")
        if match.group(0).lower() not in excluded:
            selected.append(requirement)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--extra")
    parser.add_argument("--extra-only", action="store_true")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--no-binary", action="append", default=[])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    dependencies = _dependencies(
        args.pyproject,
        extra=args.extra,
        extra_only=args.extra_only,
        excluded={name.lower() for name in args.exclude},
    )
    if not dependencies:
        raise SystemExit("no dependencies selected")
    if args.list:
        print("\n".join(dependencies))
        return

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--only-binary=:all:",
        "--retries",
        "5",
        "--timeout",
        "120",
    ]
    command.extend(f"--no-binary={name}" for name in args.no_binary)
    subprocess.run([*command, *dependencies], check=True)


if __name__ == "__main__":
    main()
