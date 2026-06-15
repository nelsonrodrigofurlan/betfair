from datetime import datetime
from zoneinfo import ZoneInfo

from palpitaria.services.ledger import bet_local_period, close_past_months, current_period, period_label


def test_period_label():
    assert period_label(2026, 6) == "Junho/2026"


def test_bet_local_period_uses_app_timezone():
    # 2026-06-01 02:00 UTC = 2026-05-31 23:00 São Paulo
    utc = datetime(2026, 6, 1, 2, 0, 0)
    assert bet_local_period(utc) == (2026, 5)


def test_close_past_months_archives_previous_month(db_session):
    from palpitaria.models import Bet, Branch, BranchMonthlySummary

    branch = Branch(name="Test Branch", slug="test_branch", description="x", commission_rate=6.5)
    db_session.add(branch)
    db_session.flush()

    # Bet in May 2026 (UTC that maps to May in SP)
    bet = Bet(
        branch_id=branch.id,
        description="Jogo teste ledger",
        odds=1.5,
        stake=100.0,
        outcome="WIN",
        profit_loss=46.5,
        created_at=datetime(2026, 5, 15, 15, 0, 0),
    )
    db_session.add(bet)
    db_session.commit()
    bet_id = bet.id

    # Simulate we're in June 2026
    original = current_period

    try:
        import palpitaria.services.ledger as ledger_mod

        ledger_mod.current_period = lambda: (2026, 6)
        created = close_past_months(db_session)
    finally:
        import palpitaria.services.ledger as ledger_mod

        ledger_mod.current_period = original

    assert len(created) == 1
    assert created[0].year == 2026
    assert created[0].month == 5
    assert created[0].win_count == 1
    assert created[0].total_pl == 46.5

    assert db_session.query(Bet).filter_by(id=bet_id).count() == 0
    summary = (
        db_session.query(BranchMonthlySummary)
        .filter_by(branch_id=branch.id, year=2026, month=5)
        .one_or_none()
    )
    assert summary is not None
    assert summary.win_count == 1
