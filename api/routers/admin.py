"""
api/routers/admin.py
---------------------
Admin-only endpoints for platform management.

Routes:
  GET    /admin/users                       -> list all users
  POST   /admin/users                       -> create advisor/admin user
  PUT    /admin/users/{id}/role             -> change role (audit logged)
  POST   /admin/advisor-clients             -> assign advisor to client
  DELETE /admin/advisor-clients             -> remove advisor-client link
  GET    /admin/audit-log                   -> full platform audit log
  GET    /admin/pending-preferences         -> investor preferences awaiting review
  POST   /admin/preferences/{id}/action     -> accept or dismiss preference
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import require_admin, require_advisor
from api.audit import log_audit
from api.schemas.reports import (
    UserCreateBody, UserResponse, AdvisorClientAssignBody,
    PendingPreferenceResponse, PreferenceActionBody,
)
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class RoleChangeBody(BaseModel):
    role: str = Field(..., pattern=r"^(investor|advisor|admin)$")
    reason: str = Field(..., min_length=5, max_length=300)


@router.get("/users", response_model=list[UserResponse])
def list_users(user: Annotated[dict, Depends(require_admin)], role: str | None = Query(None)):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if role:
            rows = conn.execute("SELECT id, email, phone, role, created_at FROM users WHERE role = ? ORDER BY created_at DESC", (role,)).fetchall()
        else:
            rows = conn.execute("SELECT id, email, phone, role, created_at FROM users ORDER BY created_at DESC").fetchall()
    return [UserResponse(**dict(r)) for r in rows]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(body: UserCreateBody, user: Annotated[dict, Depends(require_admin)]):
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as conn:
        try:
            cur = conn.execute("INSERT INTO users (email, phone, role, created_at) VALUES (?, ?, ?, ?)", (body.email, body.phone, body.role, ts))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="User with this email already exists")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, email, phone, role, created_at FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    log_audit(user_id=user["id"], action_type="user_create", entity_type="user", entity_id=row["id"],
              old_value="", new_value=f"role={body.role}", reason=f"Admin created {body.role} account for {body.email}")
    return UserResponse(**dict(row))


@router.put("/users/{target_user_id}/role")
def change_user_role(target_user_id: int, body: RoleChangeBody, user: Annotated[dict, Depends(require_admin)]):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id, email, role FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = target["role"]
    if old_role == body.role:
        raise HTTPException(status_code=400, detail="User already has this role")
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, target_user_id))
    log_audit(user_id=user["id"], action_type="role_change", entity_type="user", entity_id=target_user_id,
              old_value=old_role, new_value=body.role, reason=body.reason)
    return {"message": f"Role changed from {old_role} to {body.role}", "user_id": target_user_id, "email": target["email"]}


@router.post("/advisor-clients", status_code=201)
def assign_advisor_to_client(body: AdvisorClientAssignBody, user: Annotated[dict, Depends(require_admin)]):
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as conn:
        try:
            conn.execute("INSERT INTO advisor_clients (advisor_id, client_id, assigned_at, status) VALUES (?, ?, ?, 'active')", (body.advisor_id, body.client_id, ts))
        except sqlite3.IntegrityError:
            conn.execute("UPDATE advisor_clients SET status = 'active', assigned_at = ? WHERE advisor_id = ? AND client_id = ?", (ts, body.advisor_id, body.client_id))
    log_audit(user_id=user["id"], action_type="advisor_assign", entity_type="client", entity_id=body.client_id,
              old_value="unassigned", new_value=f"advisor_id={body.advisor_id}",
              reason=f"Admin assigned advisor {body.advisor_id} to client {body.client_id}")
    return {"message": "Advisor assigned", "advisor_id": body.advisor_id, "client_id": body.client_id}


@router.delete("/advisor-clients")
def remove_advisor_client(advisor_id: int = Query(...), client_id: int = Query(...),
                          user: Annotated[dict, Depends(require_admin)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        result = conn.execute(
            "UPDATE advisor_clients SET status = 'inactive' WHERE advisor_id = ? AND client_id = ? AND status = 'active'",
            (advisor_id, client_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Active relationship not found")
    log_audit(user_id=user["id"], action_type="advisor_unassign", entity_type="client", entity_id=client_id,
              old_value=f"advisor_id={advisor_id}", new_value="unassigned",
              reason=f"Admin removed advisor {advisor_id} from client {client_id}")
    return {"message": "Advisor-client relationship deactivated"}


@router.get("/audit-log")
def export_audit_log(user: Annotated[dict, Depends(require_admin)],
                     action_type: str | None = Query(None), limit: int = Query(500, ge=1, le=5000)):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if action_type:
            rows = conn.execute("SELECT * FROM audit_log WHERE action_type = ? ORDER BY timestamp DESC LIMIT ?", (action_type, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/pending-preferences", response_model=list[PendingPreferenceResponse])
def list_pending_preferences(user: Annotated[dict, Depends(require_advisor)],
                             status: str = Query("pending", pattern=r"^(pending|accepted|dismissed)$")):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM pending_preferences WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT pp.* FROM pending_preferences pp JOIN advisor_clients ac ON ac.client_id = pp.client_id "
                "WHERE ac.advisor_id = ? AND ac.status = 'active' AND pp.status = ? ORDER BY pp.created_at DESC",
                (user["id"], status),
            ).fetchall()
    return [PendingPreferenceResponse(**dict(r)) for r in rows]


@router.post("/preferences/{preference_id}/action")
def action_preference(preference_id: int, body: PreferenceActionBody, user: Annotated[dict, Depends(require_advisor)]):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        pref = conn.execute("SELECT * FROM pending_preferences WHERE id = ?", (preference_id,)).fetchone()
    if not pref:
        raise HTTPException(status_code=404, detail="Preference not found")
    if pref["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Already actioned: status='{pref['status']}'")
    new_status = "accepted" if body.action == "accept" else "dismissed"
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute("UPDATE pending_preferences SET status = ?, advisor_id = ? WHERE id = ?", (new_status, user["id"], preference_id))
    log_audit(user_id=user["id"], action_type=f"preference_{new_status}", entity_type="client", entity_id=pref["client_id"],
              old_value="pending", new_value=new_status,
              reason=body.notes or f"Advisor {new_status} preference: {pref['preference_summary'][:100]}")
    return {"message": f"Preference {new_status}", "preference_id": preference_id, "new_status": new_status}
