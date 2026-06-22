"""Fontes de scouting cadastradas pelo root — queries extras no DuckDuckGo."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.orm import Session, joinedload

from palpitaria.models import ScoutingSource
from palpitaria.services.team_names import english_team_name


def domain_from_url(url: str) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    host = urlparse(text).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def list_scouting_sources(db: Session, *, active_only: bool = False) -> list[ScoutingSource]:
    query = (
        db.query(ScoutingSource)
        .options(joinedload(ScoutingSource.team))
        .order_by(ScoutingSource.label)
    )
    if active_only:
        query = query.filter(ScoutingSource.is_active.is_(True))
    return query.all()


def add_scouting_source(
    db: Session,
    *,
    label: str,
    url: str,
    team_id: int | None = None,
    competition_code: str | None = None,
    notes: str | None = None,
) -> ScoutingSource:
    domain = domain_from_url(url)
    if not domain:
        raise ValueError("URL inválida")
    row = ScoutingSource(
        label=label.strip() or domain,
        url=url.strip(),
        team_id=team_id,
        competition_code=(competition_code or "").strip().upper() or None,
        notes=(notes or "").strip() or None,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def toggle_scouting_source(db: Session, source_id: int) -> ScoutingSource | None:
    row = db.get(ScoutingSource, source_id)
    if row is None:
        return None
    row.is_active = not row.is_active
    db.commit()
    db.refresh(row)
    return row


def delete_scouting_source(db: Session, source_id: int) -> bool:
    row = db.get(ScoutingSource, source_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _site_filter(domain: str) -> str:
    return f"site:{domain}"


def _query_for_source(
    source: ScoutingSource,
    *,
    team_name: str | None = None,
    external_id: int | None = None,
) -> str | None:
    domain = domain_from_url(source.url)
    if not domain:
        return None
    site = _site_filter(domain)
    if team_name:
        en = english_team_name(team_name, external_id)
        hint = source.notes.strip() if source.notes else "notícias seleção futebol"
        return f"{en} {site} {hint}"
    hint = source.notes.strip() if source.notes else "futebol notícias"
    return f"{site} {hint}"


def scouting_queries_for_team(
    db: Session,
    team_id: int,
    team_name: str,
    *,
    external_id: int | None = None,
    competition_code: str | None = None,
) -> list[str]:
    """Fontes globais + fontes exclusivas desta seleção."""
    rows = list_scouting_sources(db, active_only=True)
    queries: list[str] = []
    for row in rows:
        if row.team_id is not None and row.team_id != team_id:
            continue
        if row.competition_code and competition_code and row.competition_code != competition_code:
            continue
        if row.team_id is None:
            q = _query_for_source(row, team_name=team_name, external_id=external_id)
        else:
            q = _query_for_source(row, team_name=team_name, external_id=external_id)
        if q:
            queries.append(q)
    return queries


def scouting_queries_global(
    db: Session,
    *,
    competition_code: str | None = None,
) -> list[str]:
    rows = list_scouting_sources(db, active_only=True)
    queries: list[str] = []
    for row in rows:
        if row.team_id is not None:
            continue
        if row.competition_code and competition_code and row.competition_code != competition_code:
            continue
        q = _query_for_source(row)
        if q:
            queries.append(q)
    return queries


def append_scouting_queries(
    db: Session,
    base_queries: list[str],
    *,
    team_id: int | None = None,
    team_name: str | None = None,
    external_id: int | None = None,
    competition_code: str | None = None,
) -> list[str]:
    if team_id and team_name:
        extra = scouting_queries_for_team(
            db, team_id, team_name, external_id=external_id, competition_code=competition_code
        )
    else:
        extra = scouting_queries_global(db, competition_code=competition_code)
    if not extra:
        return base_queries
    return base_queries + extra
