"""Compare Betfair settled CSV with Palpitaria branch bets for a user."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from palpitaria.database import SessionLocal
from palpitaria.models import Bet, Branch, User

CSV_PATH = Path(r"c:\Users\Usuário\Downloads\ExchangeBets_Settled.csv")
USER_EMAIL = "nelson.r.furlan@gmail.com"


def parse_money(raw: str) -> float | None:
    s = (raw or "").strip().replace(" ", "").replace(",", ".")
    if not s or s == "--":
        return None
    return float(s)


def norm_match(desc: str) -> str:
    m = re.match(
        r"^(.+?)\s+(Mais de|Menos de|0 - 0|[A-Za-zÀ-ÿ].*?-Resultado|Cabo Verde \+1)",
        desc,
    )
    if m:
        return m.group(1).strip()
    return desc.split("|")[0].strip()[:60]


def market_key(desc: str) -> str:
    d = desc.lower()
    if "mais de 0,5" in d or "mais de 0.5" in d:
        return "over_0_5"
    if "mais de 1,5" in d or "mais de 1.5" in d:
        return "over_1_5"
    if "mais de 2,5" in d or "mais de 2.5" in d:
        return "over_2_5"
    if "menos de 2,5" in d or "menos de 2.5" in d:
        return "under_2_5"
    if "menos de 4,5" in d or "menos de 4.5" in d:
        return "under_4_5"
    if "placar correto" in d or "0 - 0" in d:
        return "lay_cs"
    if "+1" in d:
        return "ah_plus1"
    if "-resultado" in d:
        return "1x2"
    return "other"


def csv_outcome(status: str, pl: float | None) -> str:
    if status.lower().startswith("ganh"):
        return "WIN"
    if status.lower().startswith("perd"):
        return "LOSS"
    return "WIN" if pl and pl > 0 else "LOSS"


def load_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pl = parse_money(r["Lucro/Perda"])
            stake = parse_money(r["Valor Apostado (R$)"])
            odds = parse_money(r["Cotações"])
            side = "LAY" if r["Tipo"].strip().lower() == "contra" else "BACK"
            desc = r["Descrição"]
            rows.append(
                {
                    "placed": r["Realizada"],
                    "match": norm_match(desc),
                    "market": market_key(desc),
                    "side": side,
                    "odds": round(odds or 0, 2),
                    "stake": round(stake, 2) if stake is not None else None,
                    "pl": round(pl, 2) if pl is not None else None,
                    "outcome": csv_outcome(r["Status"], pl),
                    "raw": desc[:100],
                }
            )
    return rows


def norm_app_desc(desc: str) -> str:
    return re.sub(r"\s+", " ", (desc or "").lower().strip())


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_app_desc(a), norm_app_desc(b)).ratio()


def branch_for_csv_row(row: dict, branches: list[Branch]) -> str | None:
    """Map CSV row to expected branch slug/name."""
    if row["market"] == "over_0_5" and row["side"] == "BACK":
        return "over_0_5"
    if row["market"] in ("over_1_5", "over_2_5") and row["side"] == "BACK":
        return "over_1_5"
    if row["market"] == "lay_cs" and row["side"] == "LAY":
        return "lay_cs"
    if row["side"] == "LAY":
        return "lay_other"
    if row["market"] == "1x2":
        return "1x2"
    if row["market"] == "ah_plus1":
        return "ah"
    if row["market"] == "under_4_5":
        return "under"
    return "other"


def main() -> None:
    if not CSV_PATH.is_file():
        print(f"CSV not found: {CSV_PATH}")
        sys.exit(1)

    csv_rows = load_csv(CSV_PATH)
    db = SessionLocal()
    user = db.query(User).filter(User.email == USER_EMAIL).first()
    if not user:
        print(f"User not found: {USER_EMAIL}")
        sys.exit(1)

    branches = db.query(Branch).filter(Branch.user_id == user.id).all()
    branch_by_id = {b.id: b for b in branches}
    bets = (
        db.query(Bet)
        .join(Branch)
        .filter(Branch.user_id == user.id)
        .order_by(Bet.created_at)
        .all()
    )

    print("=" * 72)
    print(f"Usuário: {user.email}")
    print("=" * 72)
    print("\nFILIAIS NO APP:")
    for b in branches:
        b_bets = [x for x in bets if x.branch_id == b.id]
        pl = sum(x.profit_loss for x in b_bets)
        print(
            f"  • {b.name} (side={b.side}, comissão={b.commission_rate}%) "
            f"— {len(b_bets)} entradas, P&L R$ {pl:,.2f}"
        )

    csv_pl = sum(r["pl"] or 0 for r in csv_rows)
    app_pl = sum(b.profit_loss for b in bets)
    print(f"\nTOTAIS")
    print(f"  Betfair CSV (bruto, sem agrupar hedge): R$ {csv_pl:,.2f} ({len(csv_rows)} linhas)")
    print(f"  App filiais (lançado):                 R$ {app_pl:,.2f} ({len(bets)} entradas)")

    # Match app bets to csv
    used_csv: set[int] = set()
    matched: list[tuple[Bet, dict]] = []
    unmatched_app: list[Bet] = []

    for bet in bets:
        best_i = None
        best_score = 0.0
        for i, row in enumerate(csv_rows):
            if i in used_csv:
                continue
            if abs((row["odds"] or 0) - bet.odds) > 0.05:
                continue
            if row["stake"] and abs(row["stake"] - bet.stake) > 2.0:
                continue
            score = similar(bet.description, row["match"])
            if score > best_score:
                best_score = score
                best_i = i
        if best_i is not None and best_score >= 0.45:
            used_csv.add(best_i)
            matched.append((bet, csv_rows[best_i]))
        else:
            unmatched_app.append(bet)

    unmatched_csv = [r for i, r in enumerate(csv_rows) if i not in used_csv]

    print(f"\nCONFERENCIA APP x CSV")
    print(f"  Casados: {len(matched)} | Só no app: {len(unmatched_app)} | Só na Betfair: {len(unmatched_csv)}")

    pl_mismatch = []
    outcome_mismatch = []
    for bet, row in matched:
        br = branch_by_id[bet.branch_id]
        exp_outcome = row["outcome"]
        if bet.outcome != exp_outcome:
            outcome_mismatch.append((bet, row, br))
        csv_net = row["pl"] or 0
        if abs(bet.profit_loss - csv_net) > 1.5:
            pl_mismatch.append((bet, row, br, csv_net))

    if outcome_mismatch:
        print(f"\n[!] STATUS DIVERGENTE ({len(outcome_mismatch)}):")
        for bet, row, br in outcome_mismatch[:15]:
            print(
                f"  App {bet.outcome} vs Betfair {row['outcome']} | "
                f"{bet.description} | odd {bet.odds} stake {bet.stake} | filial {br.name}"
            )

    if pl_mismatch:
        print(f"\n[!] P&L DIVERGENTE (> R$1,50) ({len(pl_mismatch)}):")
        for bet, row, br, csv_net in pl_mismatch[:20]:
            print(
                f"  App R$ {bet.profit_loss:,.2f} vs Betfair R$ {csv_net:,.2f} | "
                f"{bet.description} | {br.name} ({br.side})"
            )

    if unmatched_app:
        print(f"\n[APP] SO NO APP - nao achei par claro no CSV ({len(unmatched_app)}):")
        for bet in unmatched_app:
            br = branch_by_id[bet.branch_id]
            print(
                f"  {bet.created_at.date()} | {br.name} | {bet.description} | "
                f"odd={bet.odds} stake={bet.stake} {bet.outcome} pl={bet.profit_loss}"
            )

    # Group unmatched csv by category
    if unmatched_csv:
        by_cat: dict[str, list] = defaultdict(list)
        for row in unmatched_csv:
            by_cat[branch_for_csv_row(row, branches)].append(row)
        print(f"\n[BETFAIR] SO NA BETFAIR - nao lancado nas filiais ({len(unmatched_csv)} linhas):")
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            pl_cat = sum(i["pl"] or 0 for i in items)
            print(f"\n  [{cat}] {len(items)} apostas, P&L R$ {pl_cat:,.2f}")
            for row in items[:8]:
                print(
                    f"    {row['placed'][:11]} | {row['side']:4} | {row['match'][:30]:30} | "
                    f"odd={row['odds']} stake={row['stake']} {row['outcome']} pl={row['pl']}"
                )
            if len(items) > 8:
                print(f"    ... +{len(items)-8} mais")

    # Summary by expected branch for ALL csv back bets on overs
    print("\n" + "=" * 72)
    print("RESUMO POR TIPO (CSV Betfair — BACK nos mercados de gols)")
    for label, filt in [
        ("Over 0.5 BACK", lambda r: r["market"] == "over_0_5" and r["side"] == "BACK"),
        ("Over 1.5/2.5 BACK", lambda r: r["market"] in ("over_1_5", "over_2_5") and r["side"] == "BACK"),
        ("1X2 BACK", lambda r: r["market"] == "1x2" and r["side"] == "BACK"),
        ("LAY / hedge / cashout", lambda r: r["side"] == "LAY"),
        ("Outros (under, AH, etc.)", lambda r: r["side"] == "BACK" and r["market"] not in ("over_0_5", "over_1_5", "over_2_5", "1x2")),
    ]:
        subset = [r for r in csv_rows if filt(r)]
        if not subset:
            continue
        wins = sum(1 for r in subset if r["outcome"] == "WIN")
        losses = sum(1 for r in subset if r["outcome"] == "LOSS")
        pl = sum(r["pl"] or 0 for r in subset)
        print(f"  {label}: {len(subset)} | W {wins} L {losses} | P&L R$ {pl:,.2f}")

    db.close()


if __name__ == "__main__":
    main()
