"""
api/routers/clients.py
-----------------------
Client management endpoints (advisor-only CRUD + investor self-view).

Routes:
  GET    /clients/me                 -> investor: own profile
  GET    /clients/                   -> advisor: list assigned clients
  POST   /clients/                   -> advisor: create new client
  GET    /clients/{id}               -> advisor (owns) or investor (self)
  PUT    /clients/{id}               -> advisor (owns)
  DELETE /clients/{id}               -> admin only
  PUT    /clients/{id}/risk-profile  -> advisor override with mandatory audit log
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Depends

from api.dependencies import (
    get_current_user, require_advisor, require_admin,
    require_advisor_owns_client, require_investor,
)
from api.audit import log_audit
from api.schemas.clients import (
    ClientCreateBody, ClientUpdateBody, RiskProfileOverrideBody,
    ClientResponse, ClientSummaryResponse,
)
from data.client_manager import create_client as _engine_create_client
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clients", tags=["clients"])


def _row_to_client_response(row: sqlite3.Row) -> ClientResponse:
    d = dict(row)
    return ClientResponse(
        id=d["id"],
        name=d["name"],
        email=d["email"],
        phone=d["phone"],
        age=d["age"],
        annual_income=d["annual_income"],
        monthly_income=d.get("monthly_income") or d["annual_income"] / 12,
        dependants=d.get("dependants", 0),
        pan=d.get("pan", ""),
        risk_profile=d.get("risk_profile"),
        risk_score=d.get("risk_score"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


@router.get("/me", response_model=ClientResponse)
def get_own_profile(user: Annotated[dict, Depends(require_investor)]):
    """Investor: fetch their own client profile via clients.user_id."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE user_id = ?", (user["id"],)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No client profile linked to this account")
    return _row_to_client_response(row)


@router.get("/", response_model=list[ClientSummaryResponse])
def list_clients(
    user: Annotated[dict, Depends(require_advisor)],
    risk_profile: str | None = None,
):
    """Advisor: list all assigned clients, optionally filtered by risk_profile."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        else:
            rows = conn.execute(
                """SELECT c.* FROM clients c
                   JOIN advisor_clients ac ON ac.client_id = c.id
                   WHERE ac.advisor_id = ? AND ac.status = 'active'
                   ORDER BY c.name""",
                (user["id"],),
            ).fetchall()

    results = [dict(r) for r in rows]
    if risk_profile:
        results = [r for r in results if r.get("risk_profile") == risk_profile]

    return [
        ClientSummaryResponse(
            id=r["id"], name=r["name"], email=r["email"], age=r["age"],
            annual_income=r["annual_income"], risk_profile=r.get("risk_profile"),
            created_at=r.get("created_at"),
        )
        for r in results
    ]


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client_endpoint(
    body: ClientCreateBody,
    user: Annotated[dict, Depends(require_advisor)],
):
    """Advisor: create a new client and auto-assign to self."""
    client = _engine_create_client(
        name=body.name, email=body.email, phone=body.phone,
        age=body.age, annual_income=body.annual_income,
        dependants=body.dependants, pan=body.pan,
    )
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO advisor_clients (advisor_id, client_id, assigned_at, status) VALUES (?, ?, ?, 'active')",
                (user["id"], client.id, ts),
            )
        except sqlite3.Error:
            pass

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client.id,)).fetchone()
    return _row_to_client_response(row)


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: int, user: Annotated[dict, Depends(get_current_user)]):
    """Advisor (owns) or investor (self only). Admins see all."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if user["role"] == "investor":
        if row["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    elif user["role"] == "advisor":
        with sqlite3.connect(DATABASE_PATH) as conn:
            link = conn.execute(
                "SELECT id FROM advisor_clients WHERE advisor_id = ? AND client_id = ? AND status='active'",
                (user["id"], client_id),
            ).fetchone()
        if link is None:
            raise HTTPException(status_code=403, detail="Not assigned to this client")

    return _row_to_client_response(row)


@router.put("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: int,
    body: ClientUpdateBody,
    client: Annotated[sqlite3.Row, Depends(require_advisor_owns_client)],
    user: Annotated[dict, Depends(require_advisor)],
):
    """Advisor: update mutable client fields."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "annual_income" in updates:
        updates["monthly_income"] = updates["annual_income"] / 12
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [client_id]
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(f"UPDATE clients SET {set_clause} WHERE id = ?", values)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row_to_client_response(row)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_client(client_id: int, user: Annotated[dict, Depends(require_admin)]):
    """Admin only: soft-deactivate a client."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute("UPDATE advisor_clients SET status = 'inactive' WHERE client_id = ?", (client_id,))
    log_audit(user_id=user["id"], action_type="client_deactivate", entity_type="client",
              entity_id=client_id, old_value="active", new_value="inactive", reason="Admin deactivation")
    return None


@router.put("/{client_id}/risk-profile", response_model=ClientResponse)
def override_risk_profile(
    client_id: int,
    body: RiskProfileOverrideBody,
    client: Annotated[sqlite3.Row, Depends(require_advisor_owns_client)],
    user: Annotated[dict, Depends(require_advisor)],
):
    """Advisor: override risk profile with mandatory audit log entry."""
    old_profile = client["risk_profile"] or "None"
    old_score = str(client["risk_score"] or 0)
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            "UPDATE clients SET risk_profile = ?, risk_score = ?, updated_at = ? WHERE id = ?",
            (body.risk_profile, body.risk_score, datetime.now(timezone.utc).isoformat(), client_id),
        )
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    log_audit(
        user_id=user["id"], action_type="risk_override", entity_type="client", entity_id=client_id,
        old_value=f"{old_profile} (score={old_score})",
        new_value=f"{body.risk_profile} (score={body.risk_score})",
        reason=body.reason,
    )
    return _row_to_client_response(row)
