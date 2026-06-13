"""
api/schemas/reports.py
-----------------------
Pydantic v2 request/response models for /reports/, /funds/, /recommendations/,
/agents/, and /admin/ endpoints.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ReportGenerateBody(BaseModel):
    client_id: int
    report_type: str = Field("advisory", pattern=r"^(advisory|periodic_review)$")
    period: str = Field(..., description="e.g. '2026-Q2'")


class ReportApproveBody(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


class ReportDispatchBody(BaseModel):
    recipient_email: str


class ReportResponse(BaseModel):
    id: int
    client_id: int
    advisor_id: Optional[int]
    report_type: str
    period: str
    file_path: Optional[str]
    sent_at: Optional[datetime]
    approval_status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class FundScreenerParams(BaseModel):
    category: Optional[str] = None
    sub_category: Optional[str] = None
    fund_house: Optional[str] = None
    plan_type: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class FundSummaryResponse(BaseModel):
    scheme_code: int
    scheme_name: str
    fund_house: Optional[str]   # NULL in some legacy rows
    category: Optional[str]     # NULL in some legacy rows
    sub_category: Optional[str]
    plan_type: Optional[str]    # NULL in some legacy rows
    ai_summary: Optional[str]


class NAVHistoryItem(BaseModel):
    nav_date: str
    nav: float


class FundFactsheetResponse(BaseModel):
    scheme_code: int
    scheme_name: str
    fund_house: Optional[str]
    category: Optional[str]
    sub_category: Optional[str]
    plan_type: Optional[str]
    ai_summary: Optional[str]
    nav_history: list[NAVHistoryItem]
    top_holdings: list[dict]


class RecommendationRequest(BaseModel):
    client_id: int


class CategoryAllocationItem(BaseModel):
    category: str
    weight: float
    funds: list[dict]


class GoalRecommendationResponse(BaseModel):
    goal_name: str
    goal_type: str
    risk_profile: str
    horizon_bucket: str
    target_sip: float
    allocations: list[CategoryAllocationItem]


class AllRecommendationsResponse(BaseModel):
    client_id: int
    recommendations: list[GoalRecommendationResponse]


class AgentRunResponse(BaseModel):
    run_id: str
    agent_name: str
    trigger_type: str
    client_id: Optional[int]
    inputs_summary: str
    decision_made: str
    action_taken: str
    approval_status: str
    approver_id: Optional[int]
    status: str
    failure_reason: Optional[str]
    timestamp: datetime
    model_config = {"from_attributes": True}


class AgentApproveBody(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


class UserCreateBody(BaseModel):
    email: str
    phone: str
    role: str = Field(..., pattern=r"^(investor|advisor|admin)$")


class UserResponse(BaseModel):
    id: int
    email: str
    phone: str
    role: str
    created_at: datetime
    model_config = {"from_attributes": True}


class AdvisorClientAssignBody(BaseModel):
    advisor_id: int
    client_id: int


class PendingPreferenceResponse(BaseModel):
    id: int
    client_id: int
    preference_summary: str
    session_id: str
    status: str
    advisor_id: Optional[int]
    created_at: datetime
    model_config = {"from_attributes": True}


class PreferenceActionBody(BaseModel):
    action: str = Field(..., pattern=r"^(accept|dismiss)$")
    notes: Optional[str] = Field(None, max_length=300)
