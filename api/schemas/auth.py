"""
api/schemas/auth.py
-------------------
Pydantic v2 request/response models for authentication endpoints.
"""

from pydantic import BaseModel, EmailStr, Field


class OTPRequestBody(BaseModel):
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15, pattern=r"^\+?[0-9]{10,15}$")


class OTPVerifyBody(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)


class TokenRefreshBody(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: int


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OTPRequestResponse(BaseModel):
    message: str
    otp_dev: str | None = None
