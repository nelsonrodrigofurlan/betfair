from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from palpitaria.models import Fixture

DATA_PATH = Path(__file__).parent.parent / "data" / "wc2026_venues.json"


@lru_cache(maxsize=1)
def _load_venues() -> dict[str, dict]:
    if not DATA_PATH.exists():
        return {}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def get_venue(external_id: int) -> dict | None:
    return _load_venues().get(str(external_id))


def venue_label(venue: dict | None) -> str | None:
    if not venue:
        return None
    city = venue.get("city") or ""
    state = venue.get("state") or ""
    if city and state:
        return f"{city}, {state}"
    return city or state or None


def apply_venue(fixture: Fixture) -> None:
    venue = get_venue(fixture.external_id)
    if not venue:
        return
    fixture.venue_stadium = venue.get("stadium")
    fixture.venue_city = venue.get("city")
    fixture.venue_state = venue.get("state")
