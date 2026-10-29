"""Rebuild apps/api/app/data/iran_geo.json from the `iran-cities-json` npm package (MIT).

    npm pack iran-cities-json@2.0.0 && tar xzf iran-cities-json-2.0.0.tgz
    python scripts/build_iran_geo.py package

The upstream data joins "و" to the next word in a few province names; they are respaced here, names
are normalised to Persian ی/ک and sorted in Persian alphabetical order.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALPHABET = "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
FIXES = {
    "وبختیاری": " و بختیاری",
    "وبلوچستان": " و بلوچستان",
    "وبویراحمد": " و بویراحمد",
}
OUTPUT = Path(__file__).resolve().parents[1] / "apps" / "api" / "app" / "data" / "iran_geo.json"


def clean(value: str) -> str:
    text = value.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    for broken, fixed in FIXES.items():
        text = text.replace(broken, fixed)
    return " ".join(text.split())


def sort_key(value: str) -> list[int]:
    return [ALPHABET.index(ch) if ch in ALPHABET else len(ALPHABET) for ch in value]


def main(package_dir: Path) -> None:
    provinces = json.loads((package_dir / "ostan.json").read_text("utf-8"))
    cities = json.loads((package_dir / "shahr.json").read_text("utf-8"))
    result = []
    for province in provinces:
        names = {clean(c["name"]) for c in cities if c["ostan"] == province["id"]}
        result.append({"name": clean(province["name"]), "cities": sorted(names, key=sort_key)})
    result.sort(key=lambda item: sort_key(item["name"]))
    payload = {
        "source": "iran-cities-json@2.0.0 (MIT, github.com/jd1378/iran-cities-json)",
        "provinces": result,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{len(result)} provinces, {sum(len(p['cities']) for p in result)} cities")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
