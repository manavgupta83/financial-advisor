"""
api/schemas/holdings.py
------------------------
Pydantic v2 request/response models for /holdings/ and /portfolio/ endpoints.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class HoldingCreateBody(BaseModel):
    scheme_code: int = Field(..., gt=0)
    units: float = Field(..., gt=0)
    avg_nav: float = Field(..., gt=0)
    invested_amount: float = Field(..., gt=0)
    goal_id: Optional[int] = None


class HoldingUpdateBody(BaseModel):
    units: Optional[float] = Field(None, gt=0)
    avg_nav: Optional[float] = Field(None, gt=0)
    invested_amount: Optional[float] = Field(None, gt=0)
    goal_id: Optional[int] = None


class HoldingResponse(BaseModel):
    id: int
    client_id: int
    scheme_code: int
    scheme_name: str
    units: float
    avg_nav: float
    invested_amount: float
    current_value: float
    cagr: Optional[float]
    goal_id: Optional[int]
    model_config = {"from_attributes": True}


class PortfolioSummaryResponse(BaseModel):
    num_holdings: int
    total_invested: float
    total_current: float
    absolute_gain: float
    gain_percentage: float
    blended_xirr: Optional[float]
    blended_cagr: Optional[float]
    blended_sharpe: Optional[float]


class SectorAllocationItem(BaseModel):
    sector: str
    weight_pct: float


class SectorAllocationResponse(BaseModel):
    client_id: int
    allocations: list[SectorAllocationItem]
    concentration_warnings: list[str]


class OverlapPairItem(BaseModel):
    fund_a_code: int
    fund_a_name: str
    fund_b_code: int
    fund_b_name: str
    overlap_pct: float
    warning_level: str


class OverlapMatrixResponse(BaseModel):
    client_id: int
    pairs: list[OverlapPairItem]
    warnings: list[str]


class StockExposureItem(BaseModel):
    isin: str
    stock_name: str
    sector: Optional[str]
    exposure_inr: float
    exposure_pct: float
    fund_count: int
    is_redundant: bool


class StockExposureResponse(BaseModel):
    client_id: int
    stocks: list[StockExposureItem]
    redundant_flags: list[str]
    data_gaps: list[str]
