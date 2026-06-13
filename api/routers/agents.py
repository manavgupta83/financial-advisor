"""
api/routers/agents.py
----------------------
Agent observability and approval endpoints -- advisor/admin only.

Routes:
  GET  /agents/runs                  -> list agent run log
  GET  /agents/runs/{run_id}         -> single run detail
  POST /agents/runs/{run_id}/approve -> advisor approves pending action
  POST /agents/runs/{run_id}/reject  -> advisor rejects pending action
  GET  /agents/audit-log/{client_id} -> immutable audit log for client
"""

import sqlite3
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Query

from api.dependencies import require_advisor
from api.audit import update_agent_run_approval, log_audit
from api.schemas.reports import AgentRunResponse, AgentApproveBody
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/runs", response_model=list[AgentRunResponse])
def list_agent_runs(user: Annotated[dict, Depends(require_advisor)],
                    client_id: int | None = Query(None), agent_name: str | None = Query(None),
                    approval_status: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    conditions, params = [], []
    if user["role"] != "admin":
        with sqlite3.connect(DATABASE_PATH) as conn:
            assigned = conn.execute("SELECT client_id FROM advisor_clients WHERE advisor_id = ? AND status = 'active'", (user["id"],)).fetchall()
        assigned_ids = [r[0] for r in assigned]
        if not assigned_ids:
            return []
        placeholders = ",".join("?" * len(assigned_ids))
        conditions.append(f"(client_id IN ({placeholders}) OR client_id IS NULL)")
        params.extend(assigned_ids)
    if client_id is not None: conditions.append("client_id = ?"); params.append(client_id)
    if agent_name: conditions.append("agent_name = ?"); params.append(agent_name)
    if approval_status: conditions.append("approval_status = ?"); params.append(approval_status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM agent_runs {where} ORDER BY timestamp DESC LIMIT ?", params + [limit]).fetchall()
    return [AgentRunResponse(**dict(r)) for r in rows]


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(run_id: str, user: Annotated[dict, Depends(require_advisor)]):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return AgentRunResponse(**dict(row))


@router.post("/runs/{run_id}/approve")
def approve_agent_run(run_id: str, body: AgentApproveBody, user: Annotated[dict, Depends(require_advisor)]):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if row["approval_status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve -- status is '{row['approval_status']}'")
    update_agent_run_approval(run_id, "approved", user["id"])
    log_audit(user_id=user["id"], action_type="agent_approve", entity_type="agent_run", entity_id=0,
              old_value="pending", new_value="approved", reason=body.notes or f"Agent run {run_id} approved")
    return {"message": "Agent run approved", "run_id": run_id}


@router.post("/runs/{run_id}/reject")
def reject_agent_run(run_id: str, body: AgentApproveBody, user: Annotated[dict, Depends(require_advisor)]):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if row["approval_status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot reject -- status is '{row['approval_status']}'")
    update_agent_run_approval(run_id, "rejected", user["id"])
    log_audit(user_id=user["id"], action_type="agent_reject", entity_type="agent_run", entity_id=0,
              old_value="pending", new_value="rejected", reason=body.notes or f"Agent run {run_id} rejected")
    return {"message": "Agent run rejected", "run_id": run_id}


@router.get("/audit-log/{client_id}")
def get_audit_log(client_id: int, user: Annotated[dict, Depends(require_advisor)], limit: int = Query(100, ge=1, le=500)):
    if user["role"] != "admin":
        with sqlite3.connect(DATABASE_PATH) as conn:
            link = conn.execute("SELECT id FROM advisor_clients WHERE advisor_id=? AND client_id=? AND status='active'", (user["id"], client_id)).fetchone()
        if not link:
            raise HTTPException(status_code=403, detail="Not assigned to this client")
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM audit_log
               WHERE (entity_type = 'client' AND entity_id = ?)
                  OR (entity_type IN ('goal','holding','report') AND entity_id IN (SELECT id FROM client_goals WHERE client_id = ?))
               ORDER BY timestamp DESC LIMIT ?""",
            (client_id, client_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
