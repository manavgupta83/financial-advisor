"""
api/dependencies.py
-------------------
FastAPI Depends() functions for authentication and authorization.

Enforces at the API layer (not just UI convention):
  - get_current_user()        -> validates JWT, returns user dict
  - require_investor()        -> investor role only
  - require_advisor()         -> advisor or admin role
  - require_admin()           -> admin role only
  - require_advisor_owns_client()  -> advisor must be assigned to the client
  - require_investor_owns_client() -> investor's user_id must match clients.user_id
  - get_client_or_404()       -> fetches client row, raises 404 if missing

These functions are referenced in every protected route via Depends().
"""

import sqlite3
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from api.auth import decode_token
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Core: decode JWT and load user from DB
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> dict:
    """
    Extract and validate Bearer JWT from Authorization header.
    Returns a dict: { id, email, phone, role }
    Raises 401 on missing / invalid / expired tokens.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cannot be used as access token",
        )

    user_id = int(payload["sub"])
    role = payload.get("role")

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, email, phone, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if row["role"] != role:
        # Role in token must match DB — catches role downgrades after token issue
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token role mismatch")

    return dict(row)


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------

def require_investor(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] != "investor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Investor access required")
    return user


def require_advisor(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] not in ("advisor", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Advisor or admin access required")
    return user


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Client ownership checks
# ---------------------------------------------------------------------------

def _get_client_row(client_id: int) -> sqlite3.Row:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Client {client_id} not found")
    return row


def require_advisor_owns_client(client_id: int, user: Annotated[dict, Depends(require_advisor)]) -> sqlite3.Row:
    """
    Verifies that the advisor is assigned to this client via the advisor_clients table.
    Admins bypass the ownership check (they see all clients).
    Returns the client row on success.
    """
    client = _get_client_row(client_id)

    if user["role"] == "admin":
        return client

    with sqlite3.connect(DATABASE_PATH) as conn:
        link = conn.execute(
            """SELECT id FROM advisor_clients
               WHERE advisor_id = ? AND client_id = ? AND status = 'active'""",
            (user["id"], client_id),
        ).fetchone()

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this client",
        )
    return client


def require_investor_owns_client(client_id: int, user: Annotated[dict, Depends(require_investor)]) -> sqlite3.Row:
    """
    Verifies that the investor's user_id matches clients.user_id.
    Returns the client row on success.
    """
    client = _get_client_row(client_id)

    client_user_id = client["user_id"] if "user_id" in client.keys() else None
    if client_user_id != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own data",
        )
    return client


def get_client_or_404(client_id: int) -> sqlite3.Row:
    """Fetches the client row for routes that have already had ownership checked."""
    return _get_client_row(client_id)
