"""
api/routers/holdings.py
------------------------
Holdings management endpoints.

Routes:
  GET    /holdings/{client_id}                -> list holdings with current value
  POST   /holdings/{client_id}                -> add holding manually
  PUT    /holdings/{client_id}/{id}           -> update holding
  DELETE /holdings/{client_id}/{id}           -> remove holding
  POST   /holdings/{client_id}/upload         -> statement ingestion preview
  POST   /holdings/{client_id}/upload/confirm -> commit ingestion to DB

current_value computed at query time as units x latest NAV from nav_history.
"""

import sqlite3
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File

from api.dependencies import require_advisor, require_advisor_owns_client
from api.schemas.holdings import HoldingCreateBody, HoldingUpdateBody, HoldingResponse
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/holdings", tags=["holdings"])


def _enrich_holding(row: dict) -> HoldingResponse:
    scheme_code = row.get("scheme_code")
    units = row.get("units", 0)
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        fund_row = conn.execute("SELECT scheme_name FROM funds WHERE scheme_code = ?", (scheme_code,)).fetchone() if scheme_code else None
        nav_row = conn.execute("SELECT nav FROM nav_history WHERE scheme_code = ? ORDER BY nav_date DESC LIMIT 1", (scheme_code,)).fetchone() if scheme_code else None
    scheme_name = row.get("scheme_name") or (fund_row["scheme_name"] if fund_row else f"Scheme {scheme_code}")
    latest_nav = nav_row["nav"] if nav_row else row.get("avg_nav", 0)
    current_value = units * latest_nav
    invested = row.get("invested_amount", 0)
    cagr = None
    if invested and invested > 0 and current_value > 0:
        try:
            from engine.performance_engine import compute_cagr
            avg_nav = row.get("avg_nav", latest_nav)
            if avg_nav and avg_nav > 0 and latest_nav != avg_nav:
                cagr = compute_cagr(invested, current_value, 2.0)
        except Exception:
            pass
    return HoldingResponse(
        id=row["id"], client_id=row["client_id"], scheme_code=scheme_code or 0,
        scheme_name=scheme_name, units=units, avg_nav=row.get("avg_nav", 0),
        invested_amount=invested, current_value=round(current_value, 2),
        cagr=cagr, goal_id=row.get("goal_id"),
    )


@router.get("/{client_id}", response_model=list[HoldingResponse])
def list_holdings(client_id: int, client=Depends(require_advisor_owns_client),
                 user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM client_holdings WHERE client_id = ?", (client_id,)).fetchall()
    return [_enrich_holding(dict(r)) for r in rows]


@router.post("/{client_id}", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
def add_holding_endpoint(client_id: int, body: HoldingCreateBody,
                         client=Depends(require_advisor_owns_client),
                         user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        fund = conn.execute("SELECT scheme_code FROM funds WHERE scheme_code = ?", (body.scheme_code,)).fetchone()
    if not fund:
        raise HTTPException(status_code=400, detail=f"scheme_code {body.scheme_code} not found in funds table.")
    from data.client_manager import add_holding as _add_holding
    holding = _add_holding(
        client_id=client_id, scheme_code=body.scheme_code, scheme_name="",
        units=body.units, avg_nav=body.avg_nav, invested_amount=body.invested_amount,
        current_value=body.units * body.avg_nav,
    )
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM client_holdings WHERE id = ?", (holding.id,)).fetchone()
    return _enrich_holding(dict(row))


@router.put("/{client_id}/{holding_id}", response_model=HoldingResponse)
def update_holding(client_id: int, holding_id: int, body: HoldingUpdateBody,
                   client=Depends(require_advisor_owns_client),
                   user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM client_holdings WHERE id = ? AND client_id = ?", (holding_id, client_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Holding not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [holding_id, client_id]
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(f"UPDATE client_holdings SET {set_clause} WHERE id = ? AND client_id = ?", values)
        conn.row_factory = sqlite3.Row
        updated = conn.execute("SELECT * FROM client_holdings WHERE id = ?", (holding_id,)).fetchone()
    return _enrich_holding(dict(updated))


@router.delete("/{client_id}/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(client_id: int, holding_id: int, client=Depends(require_advisor_owns_client),
                   user: Annotated[dict, Depends(require_advisor)] = None):
    with sqlite3.connect(DATABASE_PATH) as conn:
        result = conn.execute("DELETE FROM client_holdings WHERE id = ? AND client_id = ?", (holding_id, client_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Holding not found")
    return None


@router.post("/{client_id}/upload", status_code=status.HTTP_200_OK)
async def upload_statement(client_id: int, files: list[UploadFile] = File(...),
                           client=Depends(require_advisor_owns_client),
                           user: Annotated[dict, Depends(require_advisor)] = None):
    """Trigger Statement Ingestion Agent. Returns preview -- does NOT write to DB."""
    from agents.statement_ingestion_agent import ingest_statements
    file_payloads = []
    for f in files:
        content = await f.read()
        file_payloads.append((f.filename, content))
    try:
        result = ingest_statements(files=file_payloads, client_id=client_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Ingestion failed: {exc}")
    return {"preview": result, "message": "Review extracted holdings. POST to /confirm to commit."}


@router.post("/{client_id}/upload/confirm", status_code=status.HTTP_200_OK)
def confirm_statement_ingestion(client_id: int, body: dict,
                                client=Depends(require_advisor_owns_client),
                                user: Annotated[dict, Depends(require_advisor)] = None):
    """Commit a previewed ingestion result to the DB."""
    from agents.statement_ingestion_agent import commit_ingestion, IngestionResult
    try:
        result = IngestionResult(**body.get("result", {}))
        rows_written = commit_ingestion(result=result, client_id=client_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Commit failed: {exc}")
    return {"rows_written": rows_written, "message": "Holdings updated successfully"}
