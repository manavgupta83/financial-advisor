"""
api/routers/goals.py
---------------------
Goal management endpoints.

Routes:
  POST   /goals/plan                  -> compute FV + SIP (no DB write)
  GET    /goals/{client_id}           -> list goals
  POST   /goals/{client_id}           -> create and persist goal
  PUT    /goals/{client_id}/{id}      -> update goal
  DELETE /goals/{client_id}/{id}      -> delete goal
"""

import sqlite3
import logging
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Depends

from api.dependencies import require_advisor, require_advisor_owns_client
from api.schemas.goals import (
    GoalCreateBody, GoalPlanRequestBody,
    GoalResponse, GoalPlanResponse, AllGoalPlansResponse,
)
from engine.goal_engine import GoalInput, GoalType, plan_all_goals
from data.client_manager import add_goal, get_goals_for_client
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/goals", tags=["goals"])


def _goal_type_to_enum(goal_type: str) -> GoalType:
    mapping = {
        "retirement": GoalType.RETIREMENT, "education": GoalType.EDUCATION,
        "house": GoalType.HOUSE, "emergency": GoalType.EMERGENCY,
        "wedding": GoalType.WEDDING, "travel": GoalType.TRAVEL, "custom": GoalType.CUSTOM,
    }
    try:
        return mapping[goal_type.lower()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown goal_type: {goal_type}")


def _plan_to_response(plan) -> GoalPlanResponse:
    return GoalPlanResponse(
        goal_name=plan.input.name, goal_type=plan.input.goal_type.value,
        future_value=plan.future_value, monthly_sip_required=plan.monthly_sip_required,
        adjusted_sip=plan.adjusted_sip, lumpsum_required=plan.lumpsum_required,
        feasibility=plan.feasibility, feasibility_notes=plan.feasibility_notes,
        expected_annual_return=plan.expected_annual_return, years_to_goal=plan.input.years_to_goal,
    )


@router.post("/plan", response_model=AllGoalPlansResponse)
def compute_goal_plans(body: GoalPlanRequestBody):
    """Compute FV + SIP for a list of goals. Does NOT persist to DB."""
    goal_inputs = [
        GoalInput(
            goal_type=_goal_type_to_enum(g.goal_type), name=g.goal_name,
            target_amount_today=g.target_amount_today, years_to_goal=g.years_to_goal,
            existing_investment=g.existing_investment, inflation_rate=g.inflation_rate,
            monthly_expense_at_goal=g.monthly_expense_at_goal,
        )
        for g in body.goals
    ]
    plans = plan_all_goals(goals=goal_inputs, risk_profile=body.risk_profile, monthly_income=body.monthly_income)
    total_sip = sum(p.adjusted_sip for p in plans)
    sip_pct = (total_sip / body.monthly_income * 100) if body.monthly_income else 0
    infeasible = [p for p in plans if p.feasibility == "Infeasible"]
    stretch = [p for p in plans if p.feasibility == "Stretch"]
    if infeasible:
        summary = f"{len(infeasible)} goal(s) infeasible at current income"
    elif stretch:
        summary = f"{len(stretch)} goal(s) are a stretch -- review SIP capacity"
    else:
        summary = "All goals feasible within 40% income cap"
    return AllGoalPlansResponse(
        plans=[_plan_to_response(p) for p in plans],
        total_monthly_sip=total_sip, sip_as_pct_income=round(sip_pct, 1),
        feasibility_summary=summary,
    )


@router.get("/{client_id}", response_model=list[GoalResponse])
def list_goals(client_id: int, client=Depends(require_advisor_owns_client),
              user: Annotated[dict, Depends(require_advisor)] = None):
    goals = get_goals_for_client(client_id)
    return [
        GoalResponse(
            id=g.id, client_id=g.client_id, goal_name=g.goal_name, goal_type=g.goal_type,
            target_amount=g.target_amount, target_year=g.target_year,
            current_savings=g.current_savings, monthly_sip=g.monthly_sip,
            priority=g.priority if hasattr(g, "priority") else 1,
            risk_override=g.risk_override if hasattr(g, "risk_override") else None,
        )
        for g in goals
    ]


@router.post("/{client_id}", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(client_id: int, body: GoalCreateBody,
               client=Depends(require_advisor_owns_client),
               user: Annotated[dict, Depends(require_advisor)] = None):
    target_year = date.today().year + body.years_to_goal
    monthly_income = client["monthly_income"] or (client["annual_income"] / 12)
    risk_profile = client["risk_profile"] or "Moderate"
    goal_input = GoalInput(
        goal_type=_goal_type_to_enum(body.goal_type), name=body.goal_name,
        target_amount_today=body.target_amount_today, years_to_goal=body.years_to_goal,
        existing_investment=body.existing_investment, inflation_rate=body.inflation_rate,
        monthly_expense_at_goal=body.monthly_expense_at_goal,
    )
    from engine.goal_engine import plan_goal
    plan = plan_goal(goal_input, risk_profile, monthly_income)
    db_goal = add_goal(
        client_id=client_id, goal_name=body.goal_name, goal_type=body.goal_type,
        target_amount=plan.future_value, target_year=target_year,
        current_savings=body.existing_investment, monthly_sip=plan.adjusted_sip, priority=body.priority,
    )
    return GoalResponse(
        id=db_goal.id, client_id=db_goal.client_id, goal_name=db_goal.goal_name,
        goal_type=db_goal.goal_type, target_amount=db_goal.target_amount,
        target_year=db_goal.target_year, current_savings=db_goal.current_savings,
        monthly_sip=db_goal.monthly_sip, priority=body.priority, risk_override=None,
    )


@router.put("/{client_id}/{goal_id}", response_model=GoalResponse)
def update_goal(client_id: int, goal_id: int, body: GoalCreateBody,
               client=Depends(require_advisor_owns_client),
               user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute("SELECT id FROM client_goals WHERE id = ? AND client_id = ?", (goal_id, client_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    target_year = date.today().year + body.years_to_goal
    monthly_income = client["monthly_income"] or (client["annual_income"] / 12)
    risk_profile = client["risk_profile"] or "Moderate"
    goal_input = GoalInput(
        goal_type=_goal_type_to_enum(body.goal_type), name=body.goal_name,
        target_amount_today=body.target_amount_today, years_to_goal=body.years_to_goal,
        existing_investment=body.existing_investment, inflation_rate=body.inflation_rate,
        monthly_expense_at_goal=body.monthly_expense_at_goal,
    )
    from engine.goal_engine import plan_goal
    plan = plan_goal(goal_input, risk_profile, monthly_income)
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            """UPDATE client_goals SET goal_name=?, goal_type=?, target_amount=?,
               target_year=?, current_savings=?, monthly_sip=?, priority=?
               WHERE id=? AND client_id=?""",
            (body.goal_name, body.goal_type, plan.future_value, target_year,
             body.existing_investment, plan.adjusted_sip, body.priority, goal_id, client_id),
        )
    return GoalResponse(
        id=goal_id, client_id=client_id, goal_name=body.goal_name, goal_type=body.goal_type,
        target_amount=plan.future_value, target_year=target_year,
        current_savings=body.existing_investment, monthly_sip=plan.adjusted_sip,
        priority=body.priority, risk_override=None,
    )


@router.delete("/{client_id}/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(client_id: int, goal_id: int, client=Depends(require_advisor_owns_client),
               user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        result = conn.execute("DELETE FROM client_goals WHERE id = ? AND client_id = ?", (goal_id, client_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Goal not found")
    return None
