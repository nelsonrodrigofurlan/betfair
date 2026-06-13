#!/usr/bin/env python3
"""Gera wc2026_venues.json cruzando calendário FIFA (Roadtrips) com fixtures da API."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from palpitaria.database import SessionLocal
from palpitaria.models import Fixture, Team

SCHEDULE_PATH = Path(__file__).parent.parent / "data" / "wc2026_schedule.txt"

HOST_CITIES: dict[str, tuple[str, str]] = {
    "Mexico City": ("Ciudad de México", "CDMX"),
    "Guadalajara": ("Guadalajara", "Jalisco"),
    "Monterrey": ("Monterrey", "Nuevo León"),
    "Toronto": ("Toronto", "Ontario"),
    "Vancouver": ("Vancouver", "BC"),
    "Los Angeles": ("Los Angeles", "California"),
    "San Francisco Bay Area": ("Santa Clara", "California"),
    "Seattle": ("Seattle", "Washington"),
    "Boston": ("Foxborough", "Massachusetts"),
    "New York/New Jersey": ("East Rutherford", "New Jersey"),
    "Philadelphia": ("Philadelphia", "Pennsylvania"),
    "Miami": ("Miami Gardens", "Florida"),
    "Atlanta": ("Atlanta", "Georgia"),
    "Houston": ("Houston", "Texas"),
    "Dallas": ("Arlington", "Texas"),
    "Kansas City": ("Kansas City", "Missouri"),
}

TEAM_ALIASES: dict[str, str] = {
    "usa": "united states",
    "united states": "united states",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "bosnia and herzegovina": "bosnia-herzegovina",
    "bosnia-herzegovina": "bosnia-herzegovina",
    "cape verde": "cape verde islands",
    "cape verde islands": "cape verde islands",
    "south korea": "south korea",
    "korea republic": "south korea",
    "iran": "iran",
    "ir iran": "iran",
    "curacao": "curacao",
    "cote divoire": "ivory coast",
    "ivory coast": "ivory coast",
}


def normalize_team(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return TEAM_ALIASES.get(text, text)


def parse_schedule(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        raise FileNotFoundError(f"Schedule file not found: {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or " v " not in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 7:
            continue
        if parts[0] in ("Match", "---") or parts[0].startswith("Round"):
            continue
        if not parts[0].isdigit():
            continue

        matchup = parts[4]
        if " v " not in matchup:
            continue
        home, away = [s.strip() for s in matchup.split(" v ", 1)]
        stadium = parts[6] if len(parts) >= 8 else parts[5]
        host_city = parts[7] if len(parts) >= 8 else parts[6]
        city, state = HOST_CITIES.get(host_city, (host_city, ""))

        rows.append(
            {
                "match_num": int(parts[0]),
                "date": parts[1],
                "home": home,
                "away": away,
                "stadium": stadium,
                "host_city": host_city,
                "city": city,
                "state": state,
            }
        )
    return rows


def build_map() -> dict[str, dict]:
    schedule = parse_schedule(SCHEDULE_PATH)
    by_pair: dict[tuple[str, str], dict] = {}
    for row in schedule:
        key = (normalize_team(row["home"]), normalize_team(row["away"]))
        by_pair[key] = row

    db = SessionLocal()
    result: dict[str, dict] = {}
    try:
        fixtures = db.query(Fixture).order_by(Fixture.utc_date).all()
        for fixture in fixtures:
            home = db.get(Team, fixture.home_team_id)
            away = db.get(Team, fixture.away_team_id)
            if not home or not away:
                continue
            key = (normalize_team(home.name), normalize_team(away.name))
            row = by_pair.get(key)
            if not row:
                continue
            result[str(fixture.external_id)] = {
                "stadium": row["stadium"],
                "city": row["city"],
                "state": row["state"],
                "host_city": row["host_city"],
            }
    finally:
        db.close()
    return result


def main() -> None:
    out = Path(__file__).parent.parent / "src" / "palpitaria" / "data" / "wc2026_venues.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    mapping = build_map()
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(mapping)} venues to {out}")

    from palpitaria.services.venues import apply_venue

    db = SessionLocal()
    updated = 0
    try:
        for fixture in db.query(Fixture).all():
            before = (fixture.venue_city, fixture.venue_state)
            apply_venue(fixture)
            after = (fixture.venue_city, fixture.venue_state)
            if after != before and after[0]:
                updated += 1
        db.commit()
        print(f"Backfilled {updated} fixtures in database")
    finally:
        db.close()


if __name__ == "__main__":
    main()
