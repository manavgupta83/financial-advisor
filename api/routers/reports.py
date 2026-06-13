"""
api/routers/reports.py
-----------------------
Report lifecycle endpoints.

Routes:
  POST /reports/generate           -> advisor triggers report generation (draft)
  GET  /reports/{client_id}/list   -> list reports for client
  GET  /reports/{id}/stream        -> stream Claude advisory narrative
  POST /reports/{id}/approve       -> advisor approves draft
  POST /reports/{id}/dispatch      -> send to client (BLOCKED if not approved)
  GET  /reports/{id}/download      -> download Markdown file

GUARDRAIL: dispatch is blocked at API layer if approval_status != 'approved'.
"""

import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse

from api.dependencies import require_advisor, require_advisor_owns_client, get_current_user
from api.audit import log_audit, log_agent_run
from api.schemas.reports import ReportGenerateBody, ReportApproveBody, ReportDispatchBody, ReportResponse
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


def _get_report_or_404(report_id: int) -> dict:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return dict(row)


def _build_client_context(client_id: int) -> dict:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        client = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        goals = conn.execute("SELECT * FROM client_goals WHERE client_id = ?", (client_id,)).fetchall()
        holdings = conn.execute(
            "SELECT ch.*, f.scheme_name as fund_name FROM client_holdings ch "
            "LEFT JOIN funds f ON f.scheme_code = ch.scheme_code WHERE ch.client_id = ?", (client_id,)
        ).fetchall()
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {client_id} not found")
    return {"client": dict(client), "goals": [dict(g) for g in goals], "holdings": [dict(h) for h in holdings]}


@router.post("/generate", response_model=ReportResponse, status_code=201)
def generate_report(body: ReportGenerateBody, user: Annotated[dict, Depends(require_advisor)],
                   client=Depends(lambda client_id=None: None)):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if user["role"] != "admin":
            link = conn.execute(
                "SELECT id FROM advisor_clients WHERE advisor_id=? AND client_id=? AND status='active'",
                (user["id"], body.client_id),
            ).fetchone()
            if not link:
                raise HTTPException(status_code=403, detail="Not assigned to this client")
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO reports (client_id, advisor_id, report_type, period, approval_status, created_at) VALUES (?, ?, ?, ?, 'draft', ?)",
            (body.client_id, user["id"], body.report_type, body.period, ts),
        )
        report_id = cur.lastrowid
    log_agent_run(
        agent_name="report_generation_agent", trigger_type="manual", client_id=body.client_id,
        inputs_summary=f"type={body.report_type}, period={body.period}",
        decision_made="Draft report record created",
        action_taken="Advisor must stream, review, and approve before dispatch",
        approval_status="pending",
    )
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return ReportResponse(**dict(row))


@router.get("/{client_id}/list", response_model=list[ReportResponse])
def list_reports(client_id: int, client=Depends(require_advisor_owns_client),
                 user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reports WHERE client_id = ? ORDER BY created_at DESC", (client_id,)).fetchall()
    return [ReportResponse(**dict(r)) for r in rows]


@router.get("/{report_id}/stream")
def stream_advisory_narrative(report_id: int, user: Annotated[dict, Depends(require_advisor)]):
    report = _get_report_or_404(report_id)
    client_id = report["client_id"]
    if user["role"] != "admin":
        with sqlite3.connect(DATABASE_PATH) as conn:
            link = conn.execute(
                "SELECT id FROM advisor_clients WHERE advisor_id=? AND client_id=? AND status='active'",
                (user["id"], client_id),
            ).fetchone()
        if not link:
            raise HTTPException(status_code=403, detail="Not assigned to this client")
    client_data = _build_client_context(client_id)
    def _stream():
        try:
            from ai.claude_advisor import stream_advisory_narrative as _stream_narrative
            for chunk in _stream_narrative(client_data):
                yield chunk
        except Exception as exc:
            yield f"\n[Streaming error: {exc}]"
    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/{report_id}/approve")
def approve_report(report_id: int, body: ReportApproveBody, user: Annotated[dict, Depends(require_advisor)]):
    report = _get_report_or_404(report_id)
    if report["approval_status"] == "sent":
        raise HTTPException(status_code=400, detail="Report already sent")
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute("UPDATE reports SET approval_status = 'approved' WHERE id = ?", (report_id,))
    log_audit(user_id=user["id"], action_type="report_approve", entity_type="report", entity_id=report_id,
              old_value="draft", new_value="approved", reason=body.notes or "Advisor approved report for dispatch")
    return {"message": "Report approved", "report_id": report_id}


@router.post("/{report_id}/dispatch")
def dispatch_report(report_id: int, body: ReportDispatchBody, user: Annotated[dict, Depends(require_advisor)]):
    report = _get_report_or_404(report_id)
    if report["approval_status"] != "approved":
        raise HTTPException(status_code=403,
                            detail=f"Report cannot be dispatched. Status: '{report['approval_status']}'. Approve first.")
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute("UPDATE reports SET approval_status = 'sent', sent_at = ? WHERE id = ?", (ts, report_id))
    log_audit(user_id=user["id"], action_type="report_dispatch", entity_type="report", entity_id=report_id,
              old_value="approved", new_value="sent", reason=f"Dispatched to {body.recipient_email}")
    return {"message": "Report dispatch recorded (email stub -- enable SendGrid in Phase 8)",
            "report_id": report_id, "recipient": body.recipient_email, "sent_at": ts}


@router.get("/{report_id}/download")
def download_report(report_id: int, user: Annotated[dict, Depends(get_current_user)]):
    report = _get_report_or_404(report_id)
    file_path = report.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Report file not found. Generate narrative first via stream endpoint.")
    return FileResponse(file_path, media_type="text/markdown", filename=f"advisory_report_{report_id}.md")
