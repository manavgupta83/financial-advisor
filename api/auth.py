"""
api/auth.py
-----------
Authentication utilities for Phase 6.

Responsibilities:
  - Generate and verify 6-digit OTPs (hashed with bcrypt, stored in users.otp_hash)
  - Create and decode JWT access tokens (15-min TTL) and refresh tokens (7-day TTL)
  - OTP delivery: logs to console in DEV mode; swap for Twilio/SendGrid in production
    by setting SEND_OTP_MODE=sms or SEND_OTP_MODE=email in .env

JWT payload schema:
  { "sub": "<user_id>", "role": "<role>", "type": "access"|"refresh", "exp": <unix_ts> }
"""

import os
import random
import string
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from jose import JWTError, jwt

from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — loaded from environment / .env
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_use_openssl_rand_hex_32")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
OTP_EXPIRE_MINUTES: int = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))
SEND_OTP_MODE: str = os.getenv("SEND_OTP_MODE", "dev")   # "dev" | "sms" | "email"
DEV_MODE: bool = os.getenv("ENVIRONMENT", "development") == "development"

# ---------------------------------------------------------------------------
# Password / OTP hashing
# ---------------------------------------------------------------------------

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_otp(otp: str) -> str:
    return _pwd_ctx.hash(otp)


def _verify_otp_hash(otp: str, hashed: str) -> bool:
    return _pwd_ctx.verify(otp, hashed)


# ---------------------------------------------------------------------------
# OTP generation & delivery
# ---------------------------------------------------------------------------

def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP of the given length."""
    return "".join(random.choices(string.digits, k=length))


def send_otp(email: str, phone: str, otp: str) -> None:
    """
    Deliver the OTP to the user.
    In DEV mode: log to console (otp also returned in API response for testing).
    In production: integrate Twilio (sms) or SendGrid (email).
    """
    if SEND_OTP_MODE == "dev":
        logger.info("DEV OTP for %s / %s: %s", email, phone, otp)
        return

    if SEND_OTP_MODE == "sms":
        _send_otp_sms(phone, otp)
    elif SEND_OTP_MODE == "email":
        _send_otp_email(email, otp)


def _send_otp_sms(phone: str, otp: str) -> None:
    """Twilio SMS stub — populate with real Twilio client in Phase 8."""
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER")
    if not all([twilio_sid, twilio_token, twilio_from]):
        logger.warning("Twilio credentials missing — OTP not sent via SMS")
        return
    # from twilio.rest import Client
    # client = Client(twilio_sid, twilio_token)
    # client.messages.create(body=f"Your MF Advisor OTP: {otp}", from_=twilio_from, to=phone)
    logger.info("SMS OTP stub called for %s", phone)


def _send_otp_email(email: str, otp: str) -> None:
    """SendGrid email stub — populate in Phase 8."""
    logger.info("Email OTP stub called for %s", email)


# ---------------------------------------------------------------------------
# OTP persistence — store hash in users.otp_hash, validated at verify step
# ---------------------------------------------------------------------------

def store_otp_hash(user_id: int, otp_hash: str) -> None:
    """Write the hashed OTP to users.otp_hash; also records issued_at for expiry check."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            "UPDATE users SET otp_hash = ?, otp_issued_at = ? WHERE id = ?",
            (otp_hash, datetime.now(timezone.utc).isoformat(), user_id),
        )


def get_otp_record(user_id: int) -> tuple[str | None, str | None]:
    """Returns (otp_hash, otp_issued_at_iso) for the user, or (None, None)."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            "SELECT otp_hash, otp_issued_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def verify_otp_for_user(user_id: int, otp: str) -> bool:
    """
    Returns True if OTP matches the stored hash and has not expired.
    Clears the hash after successful verification (single-use).
    """
    otp_hash, issued_at_iso = get_otp_record(user_id)
    if not otp_hash or not issued_at_iso:
        return False

    # Expiry check
    issued_at = datetime.fromisoformat(issued_at_iso)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > issued_at + timedelta(minutes=OTP_EXPIRE_MINUTES):
        logger.warning("OTP expired for user_id=%d", user_id)
        return False

    if not _verify_otp_hash(otp, otp_hash):
        return False

    # Invalidate hash — OTP is single-use
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            "UPDATE users SET otp_hash = NULL, otp_issued_at = NULL WHERE id = ?",
            (user_id,),
        )
    return True


# ---------------------------------------------------------------------------
# JWT token creation and decoding
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    Raises jose.JWTError on invalid / expired tokens — callers should handle.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
