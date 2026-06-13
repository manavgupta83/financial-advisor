"""
api/schemas/clients.py
-----------------------
Pydantic v2 request/response models for /clients/ endpoints.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class ClientCreateBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    age: int = Field(..., ge=18, le=100)
    annual_income: float = Field(..., gt=0)
    dependants: int = Field(0, ge=0, le=20)
    pan: str = Field(..., min_length=10, max_length=10, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


class ClientUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    age: Optional[int] = Field(None, ge=18, le=100)
    annual_income: Optional[float] = Field(None, gt=0)
    dependants: Optional[int] = Field(None, ge=0, le=20)


class RiskProfileOverrideBody(BaseModel):
    risk_profile: str = Field(..., pattern=r"^(Conservative|Moderate|Aggressive|Very Aggressive)$")
    risk_score: float = Field(..., ge=0, le=100)
    reason: str = Field(..., min_length=10, max_length=500)


class ClientResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    age: int
    annual_income: float
    monthly_income: float
    dependants: int
    pan: str
    risk_profile: Optional[str]
    risk_score: Optional[float]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    model_config = {"from_attributes": True}


class ClientSummaryResponse(BaseModel):
    id: int
    name: str
    email: str
    age: int
    annual_income: float
    risk_profile: Optional[str]
    created_at: Optional[datetime]
    model_config = {"from_attributes": True}
