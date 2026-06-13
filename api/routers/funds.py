"""
api/routers/funds.py
---------------------
Fund discovery endpoints -- read-only for both investors and advisors.

Routes:
  GET  /funds/screen              -> paginated screener with 5 filters
  GET  /funds/compare             -> side-by-side for up to 3 funds
  GET  /funds/{scheme_code}/nav   -> NAV history (up to 5 years)
  GET  /funds/{scheme_code}       -> full factsheet with AI summary
  POST /funds/summaries/refresh   -> on-demand AI summary refresh
"""

import sqlite3
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Query

from api.dependencies import get_current_user, require_advisor
from api.schemas.reports import FundSummaryResponse, FundFactsheetResponse, NAVHistoryItem
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/funds", tags=["funds"])


def _get_fund_or_404(scheme_code: int) -> dict:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM funds WHERE scheme_code = ?", (scheme_code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Fund {scheme_code} not found")
    return dict(row)


def _get_ai_summary(scheme_code: int) -> str | None:
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute("SELECT summary_text FROM fund_summaries WHERE scheme_code = ?", (scheme_code,)).fetchone()
    return row[0] if row else None


@router.get("/screen", response_model=list[FundSummaryResponse])
def screen_funds(
    user: Annotated[dict, Depends(get_current_user)],
    category: str | None = Query(None), sub_category: str | None = Query(None),
    fund_house: str | None = Query(None), plan_type: str | None = Query(None),
    search: str | None = Query(None), page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    conditions, params = [], []
    if category: conditions.append("category = ?"); params.append(category)
    if sub_category: conditions.append("sub_category = ?"); params.append(sub_category)
    if fund_house: conditions.append("fund_house LIKE ?"); params.append(f"%{fund_house}%")
    if plan_type: conditions.append("plan_type = ?"); params.append(plan_type)
    if search: conditions.append("scheme_name LIKE ?"); params.append(f"%{search}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM funds {where} ORDER BY scheme_name LIMIT ? OFFSET ?",
                            params + [page_size, offset]).fetchall()
    return [FundSummaryResponse(scheme_code=d["scheme_code"], scheme_name=d["scheme_name"],
                                fund_house=d["fund_house"], category=d["category"],
                                sub_category=d.get("sub_category"), plan_type=d.get("plan_type", "Direct"),
                                ai_summary=_get_ai_summary(d["scheme_code"])) for d in [dict(r) for r in rows]]


@router.get("/compare")
def compare_funds(user: Annotated[dict, Depends(get_current_user)],
                  scheme_codes: list[int] = Query(..., description="Up to 3 scheme codes")):
    if len(scheme_codes) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 funds for comparison")
    results = []
    for sc in scheme_codes:
        fund = _get_fund_or_404(sc)
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            latest_nav = conn.execute("SELECT nav, nav_date FROM nav_history WHERE scheme_code = ? ORDER BY nav_date DESC LIMIT 1", (sc,)).fetchone()
        results.append({"scheme_code": sc, "scheme_name": fund["scheme_name"], "fund_house": fund["fund_house"],
                        "category": fund["category"], "sub_category": fund.get("sub_category"),
                        "plan_type": fund.get("plan_type"), "latest_nav": latest_nav["nav"] if latest_nav else None,
                        "nav_date": latest_nav["nav_date"] if latest_nav else None, "ai_summary": _get_ai_summary(sc)})
    return results


@router.get("/{scheme_code}/nav", response_model=list[NAVHistoryItem])
def get_nav_history(scheme_code: int, user: Annotated[dict, Depends(get_current_user)],
                    days: int = Query(365, ge=30, le=1825)):
    _get_fund_or_404(scheme_code)
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT nav_date, nav FROM nav_history WHERE scheme_code = ? AND nav_date >= date('now', ? || ' days') ORDER BY nav_date ASC",
            (scheme_code, f"-{days}"),
        ).fetchall()
    return [NAVHistoryItem(nav_date=r["nav_date"], nav=r["nav"]) for r in rows]


@router.get("/{scheme_code}", response_model=FundFactsheetResponse)
def get_fund_factsheet(scheme_code: int, user: Annotated[dict, Depends(get_current_user)]):
    fund = _get_fund_or_404(scheme_code)
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nav_rows = conn.execute(
            "SELECT nav_date, nav FROM nav_history WHERE scheme_code = ? AND nav_date >= date('now', '-365 days') ORDER BY nav_date ASC",
            (scheme_code,)).fetchall()
        holding_rows = conn.execute(
            "SELECT fh.stock_name, fh.isin, fh.weight_pct, sm.sector FROM fund_holdings fh "
            "LEFT JOIN sector_map sm ON sm.isin = fh.isin WHERE fh.scheme_code = ? ORDER BY fh.weight_pct DESC LIMIT 10",
            (scheme_code,)).fetchall()
    return FundFactsheetResponse(
        scheme_code=scheme_code, scheme_name=fund["scheme_name"], fund_house=fund["fund_house"],
        category=fund["category"], sub_category=fund.get("sub_category"),
        plan_type=fund.get("plan_type", "Direct"), ai_summary=_get_ai_summary(scheme_code),
        nav_history=[NAVHistoryItem(nav_date=r["nav_date"], nav=r["nav"]) for r in nav_rows],
        top_holdings=[dict(r) for r in holding_rows],
    )


@router.post("/summaries/refresh")
def refresh_fund_summaries(user: Annotated[dict, Depends(require_advisor)], max_funds: int = Query(50, ge=1, le=200)):
    try:
        from agents.fund_summary_agent import run_fund_summary_cron
        result = run_fund_summary_cron(max_funds=max_funds, sleep_between=1.0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Refresh failed: {exc}")
    return result
