"""Apply Betfair reconciliation fixes for nelson.r.furlan@gmail.com."""

from __future__ import annotations

from palpitaria.database import SessionLocal
from palpitaria.models import Bet, Branch, User
from palpitaria.services.ledger import compute_bet_pl

USER_EMAIL = "nelson.r.furlan@gmail.com"
COMMISSION = 6.5


def get_or_create_branch(
    db,
    user_id: int,
    *,
    name: str,
    slug: str,
    side: str,
    description: str,
) -> Branch:
    branch = db.query(Branch).filter(Branch.slug == slug).first()
    if branch:
        return branch
    branch = Branch(
        user_id=user_id,
        name=name,
        slug=slug,
        description=description,
        commission_rate=COMMISSION,
        side=side,
    )
    db.add(branch)
    db.flush()
    return branch


def main() -> None:
    db = SessionLocal()
    user = db.query(User).filter(User.email == USER_EMAIL).first()
    if not user:
        raise SystemExit(f"User not found: {USER_EMAIL}")

    trader_lay = get_or_create_branch(
        db,
        user.id,
        name="Trader — LAY",
        slug=f"trader_lay_{user.id}",
        side="LAY",
        description="Hedges e cashout in-play (LAY). Não misturar com filiais pré-live BACK.",
    )
    trader_back = get_or_create_branch(
        db,
        user.id,
        name="Trader — BACK",
        slug=f"trader_back_{user.id}",
        side="BACK",
        description="Entradas live/trader em BACK (ex.: under no jogo).",
    )
    handicap = get_or_create_branch(
        db,
        user.id,
        name="Handicap (AH)",
        slug=f"handicap_ah_{user.id}",
        side="BACK",
        description="Asian Handicap e mercados +1/-1 (neto quando houver hedge).",
    )

    deleted: list[int] = []
    updated: list[int] = []

    # 1. Duplicata Turquia x EUA — remove id maior (85)
    dup = db.get(Bet, 85)
    if dup and dup.description == "Turquia x Estados Unidos":
        db.delete(dup)
        deleted.append(85)

    # 2. Entrada fantasma França x Iraque @ 1.03
    phantom = db.get(Bet, 66)
    if phantom and "Iraque" in phantom.description and phantom.odds == 1.03:
        db.delete(phantom)
        deleted.append(66)

    # 3. Panamá 1X2 — odd 1.52 e P&L recalculado
    panama = db.get(Bet, 73)
    if panama and "Panamá" in panama.description:
        panama.odds = 1.52
        panama.outcome = "WIN"
        panama.profit_loss = round(
            compute_bet_pl(100.0, 1.52, "WIN", COMMISSION, side="BACK"), 2
        )
        updated.append(73)

    # 4. Alemanha — hedges para filiais Trader
    alemanha_moves = {
        47: {
            "branch_id": trader_lay.id,
            "description": "Alemanha x Marfim — LAY Under 2.5 (trader)",
            "odds": 2.52,
            "stake": 0.51,
            "outcome": "WIN",
            "side": "LAY",
        },
        48: {
            "branch_id": trader_back.id,
            "description": "Alemanha x Marfim — BACK Under 2.5 (trader)",
            "odds": 2.52,
            "stake": 65.2,
            "outcome": "LOSS",
            "side": "BACK",
        },
        49: {
            "branch_id": trader_lay.id,
            "description": "Alemanha x Marfim — LAY Alemanha (trader)",
            "odds": 2.58,
            "stake": 0.45,
            "outcome": "LOSS",
            "side": "LAY",
        },
        50: {
            "branch_id": trader_lay.id,
            "description": "Alemanha x Marfim — LAY Alemanha (trader)",
            "odds": 2.58,
            "stake": 58.46,
            "outcome": "LOSS",
            "side": "LAY",
        },
    }
    for bet_id, spec in alemanha_moves.items():
        bet = db.get(Bet, bet_id)
        if not bet:
            continue
        bet.branch_id = spec["branch_id"]
        bet.description = spec["description"]
        bet.odds = spec["odds"]
        bet.stake = spec["stake"]
        bet.outcome = spec["outcome"]
        bet.profit_loss = round(
            compute_bet_pl(
                spec["stake"],
                spec["odds"],
                spec["outcome"],
                COMMISSION,
                side=spec["side"],
            ),
            2,
        )
        updated.append(bet_id)

    # 5. Cabo Verde +1 AH — neto das 3 linhas Betfair (2 BACK + 1 LAY)
    cabo = db.get(Bet, 88)
    if cabo and "Cabo Verde" in cabo.description:
        cabo.branch_id = handicap.id
        cabo.description = "Cabo Verde x Arábia Saudita (+1 AH — neto Betfair)"
        cabo.odds = 1.55
        cabo.stake = 100.0
        cabo.outcome = "WIN"
        # Neto bruto Betfair: +54 +56.65 -55.91 = +54.74; wins com comissão 6.5%
        cabo.profit_loss = round(54.0 * 0.935 + 56.65 * 0.935 - 55.91, 2)
        updated.append(88)

    db.commit()

    # Resumo
    branches = db.query(Branch).filter(Branch.user_id == user.id).all()
    bets = db.query(Bet).join(Branch).filter(Branch.user_id == user.id).all()
    print("Correcoes aplicadas.")
    print(f"  Removidas: {deleted}")
    print(f"  Atualizadas: {updated}")
    print(f"  Novas filiais: Trader LAY id={trader_lay.id}, Trader BACK id={trader_back.id}, AH id={handicap.id}")
    print("\nFILIAIS:")
    for br in sorted(branches, key=lambda b: b.id):
        bb = [b for b in bets if b.branch_id == br.id]
        pl = sum(b.profit_loss for b in bb)
        print(f"  {br.name} ({br.side}): {len(bb)} entradas, P&L R$ {pl:,.2f}")
    print(f"\nTOTAL APP: R$ {sum(b.profit_loss for b in bets):,.2f} ({len(bets)} entradas)")
    db.close()


if __name__ == "__main__":
    main()
