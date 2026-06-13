"""
api/schemas/goals.py
---------------------
Pydantic v2 request/response models for /goals/ endpoints.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

VALID_GOAL_TYPES = r"^(retirement|education|house|emergency|wedding|travel|custom)$"


class GoalCreateBody(BaseModel):
    goal_name: str = Field(..., min_length=2, max_length=120)
    goal_type: str = Field(..., pattern=VALID_GOAL_TYPES)
    target_amount_today: float = Field(0.0, ge=0)
    years_to_goal: int = Field(..., ge=1, le=60)
    existing_investment: float = Field(0.0, ge=0)
    inflation_rate: Optional[float] = Field(None, ge=0.0, le=0.30)
    monthly_expense_at_goal: float = Field(0.0, ge=0)
    priority: int = Field(1, ge=1, le=10)


class GoalPlanRequestBody(BaseModel):
    goals: list[GoalCreateBody]
    risk_profile: str = Field(..., pattern=r"^(Conservative|Moderate|Aggressive|Very Aggressive)$")
    monthly_income: float = Field(..., gt=0)


class GoalPlanResponse(BaseModel):
    goal_name: str
    goal_type: str
    future_value: float
    monthly_sip_required: float
    adjusted_sip: float
    lumpsum_required: float
    feasibility: str
    feasibility_notes: list[str]   # engine returns list[str] -- was incorrectly str
    expected_annual_return: float
    years_to_goal: int


class GoalResponse(BaseModel):
    id: int
    client_id: int
    goal_name: str
    goal_type: str
    target_amount: float
    target_year: int
    current_savings: float
    monthly_sip: float
    priority: int
    risk_override: Optional[str]
    model_config = {"from_attributes": True}


class AllGoalPlansResponse(BaseModel):
    plans: list[GoalPlanResponse]
    total_monthly_sip: float
    sip_as_pct_income: float
    feasibility_summary: str
