"""Fechamento mensal das filiais — consolida e zera o ledger ativo."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from palpitaria.config import settings
from palpitaria.models import Bet, Branch, BranchMonthlySummary


def bet_competition_expr():
    """Apostas antigas sem competition_code contam como Copa (WC)."""
    return func.coalesce(Bet.competition_code, settings.world_cup_code)

VALID_BET_SIDES = frozenset({"BACK", "LAY"})


def normalize_bet_side(side: str | None) -> str:
    """Apostas antigas sem side contam como BACK."""
    if side and side.upper() in VALID_BET_SIDES:
        return side.upper()
    return "BACK"


def compute_bet_pl(
    stake: float,
    odds: float,
    outcome: str,
    commission_rate: float,
    *,
    side: str = "BACK",
) -> float:
    """
    P&L por entrada. stake = valor apostado (BACK) ou stake do backer no lay (LAY).
    LAY green: stake * (1 - comissão); LAY red: -stake * (odds - 1) (liability).
    """
    bet_side = normalize_bet_side(side)
    commission = commission_rate / 100.0
    if outcome == "WIN":
        if bet_side == "LAY":
            return stake * (1 - commission)
        return stake * (odds - 1) * (1 - commission)
    if outcome == "LOSS":
        if bet_side == "LAY":
            return -stake * (odds - 1)
        return -stake
    return 0.0


def infer_branch_side(name: str, slug: str = "", description: str = "") -> str:
    """Heurística para filiais existentes: Correct Score → LAY, demais → BACK."""
    blob = f"{name} {slug} {description or ''}".lower()
    if "correct score" in blob or "placar exato" in blob:
        return "LAY"
    return "BACK"


def migrate_branch_sides(db: Session) -> None:
    """Preenche side em filiais antigas e recalcula P&L de entradas já fechadas."""
    branches = db.query(Branch).all()
    changed = False
    for branch in branches:
        if not branch.side or branch.side not in VALID_BET_SIDES:
            branch.side = infer_branch_side(branch.name, branch.slug, branch.description or "")
            changed = True
        commission = branch.commission_rate
        for bet in branch.bets:
            if bet.outcome in ("WIN", "LOSS"):
                new_pl = compute_bet_pl(
                    bet.stake, bet.odds, bet.outcome, commission, side=branch.side
                )
                if bet.profit_loss != new_pl:
                    bet.profit_loss = new_pl
                    changed = True
    if changed:
        db.commit()


def lay_liability(stake: float, odds: float) -> float:
    """Responsabilidade máxima em um lay (exchange)."""
    return stake * (odds - 1)


MONTHS_PT = (
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def current_period() -> tuple[int, int]:
    now = datetime.now(ZoneInfo(settings.app_timezone))
    return now.year, now.month


def bet_local_period(created_at: datetime) -> tuple[int, int]:
    utc = created_at.replace(tzinfo=ZoneInfo("UTC"))
    local = utc.astimezone(ZoneInfo(settings.app_timezone))
    return local.year, local.month


def period_label(year: int, month: int) -> str:
    name = MONTHS_PT[month] if 1 <= month <= 12 else str(month)
    return f"{name}/{year}"


def close_past_months(db: Session) -> list[BranchMonthlySummary]:
    """
    Arquiva entradas de meses anteriores (por filial e competição) e remove do ledger ativo.
    O mês corrente permanece nos cards de Filiais.
    """
    cy, cm = current_period()
    bets = db.query(Bet).all()
    if not bets:
        return []

    # Agrupar por (ano, mês, branch_id, competition_code)
    groups: dict[tuple[int, int, int, str], list[Bet]] = defaultdict(list)
    for bet in bets:
        y, m = bet_local_period(bet.created_at)
        if (y, m) < (cy, cm):
            comp = bet.competition_code or "WC"
            groups[(y, m, bet.branch_id, comp)].append(bet)

    if not groups:
        return []

    created: list[BranchMonthlySummary] = []
    for (year, month, branch_id, comp_code), branch_bets in sorted(groups.items()):
        existing = (
            db.query(BranchMonthlySummary)
            .filter_by(branch_id=branch_id, year=year, month=month, competition_code=comp_code)
            .one_or_none()
        )
        if existing:
            for bet in branch_bets:
                db.delete(bet)
            continue

        branch = db.query(Branch).filter_by(id=branch_id).one_or_none()
        wins = sum(1 for b in branch_bets if b.outcome == "WIN")
        losses = sum(1 for b in branch_bets if b.outcome == "LOSS")
        pending = sum(1 for b in branch_bets if b.outcome == "PENDING")
        total_pl = round(sum(b.profit_loss for b in branch_bets), 2)
        total_stake = round(sum(b.stake for b in branch_bets), 2)

        summary = BranchMonthlySummary(
            branch_id=branch_id,
            year=year,
            month=month,
            competition_code=comp_code,
            bet_count=len(branch_bets),
            win_count=wins,
            loss_count=losses,
            pending_count=pending,
            total_pl=total_pl,
            total_stake=total_stake,
            commission_rate=branch.commission_rate if branch else 6.5,
            closed_at=datetime.utcnow(),
        )
        db.add(summary)
        created.append(summary)
        for bet in branch_bets:
            db.delete(bet)

    if created or groups:
        db.commit()
    return created
