"""
api/routers/auth.py
--------------------
Authentication endpoints:
  POST /auth/request-otp  -- generates OTP, stores hash, (simulated) delivers via SMS/email
  POST /auth/verify-otp   -- verifies OTP, returns JWT access + refresh tokens
  POST /auth/refresh       -- exchanges refresh token for new access token
  POST /auth/logout        -- client-side token discard (stateless)

New user auto-creation:
  If no users row exists for the given email, one is created with role='investor'.
  Advisors and admins must be provisioned via POST /admin/users before they can log in.
"""

import sqlite3
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status, Depends

from api.auth import (
    generate_otp, send_otp, verify_otp_for_user,
    create_access_token, create_refresh_token, decode_token,
    _hash_otp, DEV_MODE,
)
from api.dependencies import get_current_user
from api.schemas.auth import (
    OTPRequestBody, OTPVerifyBody, TokenRefreshBody,
    OTPRequestResponse, TokenResponse, AccessTokenResponse,
)
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _get_or_create_user(email: str, phone: str) -> dict:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, email, phone, role FROM users WHERE email = ?", (email,)
        ).fetchone()

        if row:
            return dict(row)

        ts = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO users (email, phone, role, created_at) VALUES (?, ?, 'investor', ?)",
            (email, phone, ts),
        )
        return {"id": cur.lastrowid, "email": email, "phone": phone, "role": "investor"}


@router.post("/request-otp", response_model=OTPRequestResponse, status_code=status.HTTP_200_OK)
def request_otp(body: OTPRequestBody):
    """Step 1: generate OTP, store hash, deliver. DEV mode returns otp_dev for testing."""
    user = _get_or_create_user(body.email, body.phone)
    otp = generate_otp()
    hashed = _hash_otp(otp)

    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute(
                "UPDATE users SET otp_hash = ?, otp_issued_at = ? WHERE id = ?",
                (hashed, datetime.now(timezone.utc).isoformat(), user["id"]),
            )
    except sqlite3.OperationalError:
        with sqlite3.connect(DATABASE_PATH) as conn:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN otp_issued_at TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "UPDATE users SET otp_hash = ?, otp_issued_at = ? WHERE id = ?",
                (hashed, datetime.now(timezone.utc).isoformat(), user["id"]),
            )

    send_otp(body.email, body.phone, otp)
    logger.info("OTP issued for user_id=%d email=%s", user["id"], body.email)

    return OTPRequestResponse(
        message="OTP sent successfully",
        otp_dev=otp if DEV_MODE else None,
    )


@router.post("/verify-otp", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def verify_otp(body: OTPVerifyBody):
    """Step 2: verify OTP, return JWT access + refresh tokens."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT id, email, phone, role FROM users WHERE email = ?", (body.email,)
        ).fetchone()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this email. Please request an OTP first.",
        )

    user = dict(user)

    if not verify_otp_for_user(user["id"], body.otp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP",
        )

    access_token = create_access_token(user["id"], user["role"])
    refresh_token = create_refresh_token(user["id"], user["role"])
    logger.info("Login success user_id=%d role=%s", user["id"], user["role"])

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user["role"],
        user_id=user["id"],
    )


@router.post("/refresh", response_model=AccessTokenResponse, status_code=status.HTTP_200_OK)
def refresh_token(body: TokenRefreshBody):
    """Exchange a valid refresh token for a new access token."""
    from jose import JWTError
    try:
        payload = decode_token(body.refresh_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired refresh token: {exc}",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Token is not a refresh token")

    user_id = int(payload["sub"])

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(user["id"], user["role"])
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: dict = Depends(get_current_user)):
    """Stateless logout -- clears pending OTP hash as hygiene measure."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            "UPDATE users SET otp_hash = NULL, otp_issued_at = NULL WHERE id = ?",
            (user["id"],),
        )
    return None
