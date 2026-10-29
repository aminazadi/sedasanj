"""Iran provinces and cities for the phonebook (data: `app/data/iran_geo.json`).

The dataset comes from the MIT-licensed `iran-cities-json` npm package; regenerate it with
`scripts/build_iran_geo.py`. Matching ignores spaces, half-spaces, Arabic ي/ك and a leading
"استان", so spreadsheet values such as "كرمان" or "استان تهران" resolve to the canonical name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "iran_geo.json"


def _key(value: str) -> str:
    text = value.replace("ي", "ی").replace("ك", "ک")
    return "".join(ch for ch in text.lower() if ch.isalnum())


@dataclass(frozen=True)
class Province:
    name: str
    cities: tuple[str, ...]
    city_keys: dict[str, str]


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Any], dict[str, Province]]:
    raw = json.loads(DATA_PATH.read_text("utf-8"))
    provinces = {
        _key(item["name"]): Province(
            item["name"], tuple(item["cities"]), {_key(city): city for city in item["cities"]}
        )
        for item in raw["provinces"]
    }
    return raw, provinces


def dataset() -> dict[str, Any]:
    return _load()[0]


def match_province(value: str) -> Province | None:
    key = _key(value)
    if key.startswith("استان"):
        key = key[len("استان") :]
    return _load()[1].get(key)


def match_city(province: Province, value: str) -> str | None:
    return province.city_keys.get(_key(value))
