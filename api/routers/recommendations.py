"""
api/routers/recommendations.py
--------------------------------
Fund recommendation endpoints -- wraps Phase 2 recommendation engine.

Routes:
  GET  /recommendations/{client_id}          -> recommendations for all client goals
  POST /recommendations/{client_id}/override -> advisor overrides fund (audit logged)
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from api.dependencies import require_advisor, require_advisor_owns_client
from api.audit import log_audit
from api.schemas.reports import AllRecommendationsResponse, GoalRecommendationResponse, CategoryAllocationItem
from data.client_manager import get_goals_for_client
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class FundOverrideBody(BaseModel):
    goal_id: int
    original_scheme_code: int
    replacement_scheme_code: int
    reason: str = Field(..., min_length=10, max_length=500)


@router.get("/{client_id}", response_model=AllRecommendationsResponse)
def get_recommendations(client_id: int, client=Depends(require_advisor_owns_client),
                        user: Annotated[dict, Depends(require_advisor)] = None):
    risk_profile = client["risk_profile"]
    if not risk_profile:
        raise HTTPException(status_code=400, detail="Client has no risk profile. Complete the risk questionnaire first.")
    goals = get_goals_for_client(client_id)
    if not goals:
        raise HTTPException(status_code=400, detail="Client has no goals. Add goals first.")
    from engine.goal_engine import GoalInput, GoalType, plan_goal
    from engine.recommendation_engine import recommend_all_goals
    import datetime
    monthly_income = client["monthly_income"] or (client["annual_income"] / 12)
    goal_type_map = {
        "retirement": GoalType.RETIREMENT, "education": GoalType.EDUCATION,
        "house": GoalType.HOUSE, "emergency": GoalType.EMERGENCY,
        "wedding": GoalType.WEDDING, "travel": GoalType.TRAVEL, "custom": GoalType.CUSTOM,
    }
    plans = []
    for g in goals:
        gt = goal_type_map.get(g.goal_type.lower(), GoalType.CUSTOM)
        years_remaining = max(1, g.target_year - datetime.date.today().year)
        goal_input = GoalInput(goal_type=gt, name=g.goal_name, target_amount_today=g.target_amount,
                               years_to_goal=years_remaining, existing_investment=g.current_savings or 0)
        try:
            plan = plan_goal(goal_input, risk_profile, monthly_income)
            plans.append(plan)
        except Exception as exc:
            logger.warning("Goal plan failed for goal_id=%d: %s", g.id, exc)
    if not plans:
        raise HTTPException(status_code=422, detail="Could not compute plans for any goal")
    try:
        recommendations = recommend_all_goals(plans=plans, risk_profile=risk_profile, db_path=DATABASE_PATH)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Recommendation engine error: {exc}")
    response_recs = []
    for rec in recommendations:
        allocations = [CategoryAllocationItem(category=a.category, weight=a.weight, funds=a.funds) for a in rec.allocations]
        response_recs.append(GoalRecommendationResponse(
            goal_name=rec.goal_name, goal_type=rec.goal_type, risk_profile=rec.risk_profile,
            horizon_bucket=rec.horizon_bucket, target_sip=rec.target_sip, allocations=allocations,
        ))
    return AllRecommendationsResponse(client_id=client_id, recommendations=response_recs)


@router.post("/{client_id}/override")
def override_fund_recommendation(client_id: int, body: FundOverrideBody,
                                 user: Annotated[dict, Depends(require_advisor)],
                                 client=Depends(require_advisor_owns_client)):
    import sqlite3
    with sqlite3.connect(DATABASE_PATH) as conn:
        orig = conn.execute("SELECT scheme_name FROM funds WHERE scheme_code = ?", (body.original_scheme_code,)).fetchone()
        replacement = conn.execute("SELECT scheme_name FROM funds WHERE scheme_code = ?", (body.replacement_scheme_code,)).fetchone()
    orig_name = orig[0] if orig else f"Scheme {body.original_scheme_code}"
    repl_name = replacement[0] if replacement else f"Scheme {body.replacement_scheme_code}"
    log_audit(
        user_id=user["id"], action_type="fund_override", entity_type="goal", entity_id=body.goal_id,
        old_value=f"{orig_name} (code={body.original_scheme_code})",
        new_value=f"{repl_name} (code={body.replacement_scheme_code})", reason=body.reason,
    )
    return {"message": "Fund override logged", "goal_id": body.goal_id,
            "replaced": orig_name, "with": repl_name, "reason": body.reason}
