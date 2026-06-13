"""
api/schemas/optimiser.py
-------------------------
Pydantic v2 request/response models for /optimiser/ endpoints.
Advisor-only.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class OptimiserConstraintsBody(BaseModel):
    natural_language: str = Field(..., min_length=5, max_length=1000)


class FundStatsInput(BaseModel):
    scheme_code: int
    scheme_name: str
    expected_return: float = Field(..., ge=0, le=2.0)
    volatility: float = Field(..., ge=0, le=2.0)
    sharpe_ratio: float


class OptimiserRunBody(BaseModel):
    client_id: int
    funds: list[FundStatsInput]
    correlation_matrix: list[list[float]]
    objective: str = Field("max_sharpe", pattern=r"^(max_sharpe|min_variance)$")
    min_funds: int = Field(3, ge=2, le=10)
    max_funds: int = Field(6, ge=2, le=15)
    min_weight: float = Field(0.05, ge=0.01, le=0.5)
    max_weight: float = Field(0.40, ge=0.1, le=1.0)
    natural_language_constraints: Optional[str] = None


class FundWeightItem(BaseModel):
    scheme_code: int
    scheme_name: str
    weight: float
    weight_pct: float


class OptimiserResultResponse(BaseModel):
    objective: str
    weights: list[FundWeightItem]
    expected_portfolio_return: float
    portfolio_volatility: float
    portfolio_sharpe: float
    solver_used: str
    explanation: Optional[str] = None


class FrontierPointItem(BaseModel):
    expected_return: float
    volatility: float
    sharpe: float


class EfficientFrontierResponse(BaseModel):
    client_id: int
    points: list[FrontierPointItem]


class ParsedConstraintsResponse(BaseModel):
    min_funds: int
    max_funds: int
    min_weight: float
    max_weight: float
    risk_free_rate: float
    raw_text: str
