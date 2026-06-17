from __future__ import annotations
from sqlalchemy.orm import Session
from palpitaria.models import Cycle, CycleStep
from datetime import datetime

def get_active_cycle(db: Session, user_id: int) -> Cycle | None:
    return db.query(Cycle).filter(Cycle.user_id == user_id, Cycle.status == "ACTIVE").first()

def calculate_next_step_target(cycle: Cycle) -> float:
    """
    Calcula a meta percentual para o próximo jogo.
    Regra: Começa em 5%, reduz 2,5% (do valor da meta) a cada acerto.
    """
    base_target = 5.0
    reduction_factor = 0.025 # 2.5%
    
    wins = sum(1 for s in cycle.steps if s.outcome == "WIN")
    
    # Meta_n = Meta_0 * (1 - fator)^n
    target = base_target * ((1 - reduction_factor) ** wins)
    return round(target, 2)

def add_cycle_step(db: Session, cycle: Cycle, description: str, fixture_id: int | None = None) -> CycleStep:
    target_pct = calculate_next_step_target(cycle)
    step = CycleStep(
        cycle_id=cycle.id,
        fixture_id=fixture_id,
        description=description,
        stake=cycle.current_amount,
        target_profit_pct=target_pct,
        outcome="PENDING"
    )
    db.add(step)
    db.commit()
    return step

def resolve_step(db: Session, step_id: int, outcome: str) -> CycleStep | None:
    step = db.query(CycleStep).filter(CycleStep.id == step_id).first()
    if not step:
        return None
    
    cycle = step.cycle
    if cycle.status != "ACTIVE":
        return step
    
    step.outcome = outcome
    
    if outcome == "WIN":
        # Lucro = stake * (target_pct / 100)
        profit = round(step.stake * (step.target_profit_pct / 100), 2)
        step.actual_profit_loss = profit
        cycle.current_amount = round(cycle.current_amount + profit, 2)
        
        # Verificar se dobrou a banca (objetivo do ciclo)
        if cycle.current_amount >= cycle.target_amount:
            cycle.status = "COMPLETED"
            cycle.completed_at = datetime.utcnow()
            
    elif outcome == "LOSS":
        # Perda total da stake do passo (que é a banca atual do ciclo)
        step.actual_profit_loss = -step.stake
        cycle.current_amount = 0.0
        cycle.status = "FAILED"
        cycle.completed_at = datetime.utcnow()
        
    db.commit()
    return step
