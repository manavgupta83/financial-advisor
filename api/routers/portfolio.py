"""
api/routers/portfolio.py
-------------------------
Portfolio analytics endpoints -- wraps Phase 3 engines.

Routes:
  GET /portfolio/{client_id}/summary           -> XIRR, CAGR, Sharpe, gain
  GET /portfolio/{client_id}/sector-allocation -> blended sector weights + warnings
  GET /portfolio/{client_id}/overlap           -> N x N overlap matrix
  GET /portfolio/{client_id}/stock-exposure    -> stock-level weighted INR exposure
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends

from api.dependencies import require_advisor, require_advisor_owns_client
from api.schemas.holdings import (
    PortfolioSummaryResponse, SectorAllocationResponse, SectorAllocationItem,
    OverlapMatrixResponse, OverlapPairItem, StockExposureResponse, StockExposureItem,
)
from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _get_client_holdings_enriched(client_id: int) -> list[dict]:
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM client_holdings WHERE client_id = ?", (client_id,)).fetchall()
    holdings = []
    for r in rows:
        d = dict(r)
        scheme_code = d.get("scheme_code")
        units = d.get("units", 0)
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            nav_row = conn.execute("SELECT nav FROM nav_history WHERE scheme_code = ? ORDER BY nav_date DESC LIMIT 1", (scheme_code,)).fetchone() if scheme_code else None
            fund_row = conn.execute("SELECT scheme_name FROM funds WHERE scheme_code = ?", (scheme_code,)).fetchone() if scheme_code else None
        latest_nav = nav_row["nav"] if nav_row else d.get("avg_nav", 0)
        scheme_name = d.get("scheme_name") or (fund_row["scheme_name"] if fund_row else f"Scheme {scheme_code}")
        d["scheme_name"] = scheme_name
        d["current_value"] = units * latest_nav
        d["latest_nav"] = latest_nav
        holdings.append(d)
    return holdings


@router.get("/{client_id}/summary", response_model=PortfolioSummaryResponse)
def get_portfolio_summary(client_id: int, client=Depends(require_advisor_owns_client),
                          user: Annotated[dict, Depends(require_advisor)] = None):
    holdings = _get_client_holdings_enriched(client_id)
    if not holdings:
        return PortfolioSummaryResponse(num_holdings=0, total_invested=0, total_current=0,
                                        absolute_gain=0, gain_percentage=0,
                                        blended_xirr=None, blended_cagr=None, blended_sharpe=None)
    total_invested = sum(h.get("invested_amount", 0) for h in holdings)
    total_current = sum(h.get("current_value", 0) for h in holdings)
    absolute_gain = total_current - total_invested
    gain_pct = (absolute_gain / total_invested * 100) if total_invested else 0
    blended_xirr = blended_cagr = blended_sharpe = None
    try:
        from engine.performance_engine import simulate_sip_cashflows, compute_xirr, compute_cagr, compute_sharpe_ratio
        all_cashflows = []
        for h in holdings:
            invested = h.get("invested_amount", 0)
            current = h.get("current_value", 0)
            if invested > 0 and current > 0:
                all_cashflows.extend(simulate_sip_cashflows(invested, months=36, final_value=current))
        if all_cashflows:
            blended_xirr = compute_xirr(all_cashflows)
        if total_invested > 0 and total_current > 0:
            blended_cagr = compute_cagr(total_invested, total_current, years=3.0)
        if blended_xirr and blended_cagr:
            blended_sharpe = compute_sharpe_ratio(annual_return=blended_cagr, risk_free_rate=0.065, volatility=0.15)
    except Exception as exc:
        logger.warning("Performance metrics error for client %d: %s", client_id, exc)
    return PortfolioSummaryResponse(
        num_holdings=len(holdings), total_invested=round(total_invested, 2),
        total_current=round(total_current, 2), absolute_gain=round(absolute_gain, 2),
        gain_percentage=round(gain_pct, 2),
        blended_xirr=round(blended_xirr * 100, 2) if blended_xirr else None,
        blended_cagr=round(blended_cagr * 100, 2) if blended_cagr else None,
        blended_sharpe=round(blended_sharpe, 2) if blended_sharpe else None,
    )


@router.get("/{client_id}/sector-allocation", response_model=SectorAllocationResponse)
def get_sector_allocation(client_id: int, client=Depends(require_advisor_owns_client),
                          user: Annotated[dict, Depends(require_advisor)] = None):
    holdings = _get_client_holdings_enriched(client_id)
    if not holdings:
        return SectorAllocationResponse(client_id=client_id, allocations=[], concentration_warnings=[])
    total_current = sum(h.get("current_value", 0) for h in holdings)
    if not total_current:
        return SectorAllocationResponse(client_id=client_id, allocations=[], concentration_warnings=[])
    scheme_codes = [h["scheme_code"] for h in holdings if h.get("scheme_code")]
    weights = {h["scheme_code"]: h["current_value"] / total_current for h in holdings if h.get("scheme_code") and total_current > 0}
    try:
        from engine.sector_engine import compute_portfolio_sector_allocation
        sector_map = compute_portfolio_sector_allocation(scheme_codes=scheme_codes, portfolio_weights=weights, db_path=DATABASE_PATH)
    except Exception as exc:
        logger.warning("Sector engine error for client %d: %s", client_id, exc)
        return SectorAllocationResponse(client_id=client_id, allocations=[], concentration_warnings=[])
    allocations = [SectorAllocationItem(sector=s, weight_pct=round(w * 100, 2)) for s, w in sorted(sector_map.items(), key=lambda x: -x[1])]
    warnings = []
    for item in allocations:
        if item.weight_pct >= 40:
            warnings.append(f"HIGH: {item.sector} at {item.weight_pct:.1f}% (threshold: 40%)")
        elif item.weight_pct >= 25:
            warnings.append(f"MEDIUM: {item.sector} at {item.weight_pct:.1f}% (threshold: 25%)")
    return SectorAllocationResponse(client_id=client_id, allocations=allocations, concentration_warnings=warnings)


@router.get("/{client_id}/overlap", response_model=OverlapMatrixResponse)
def get_overlap_matrix(client_id: int, client=Depends(require_advisor_owns_client),
                       user: Annotated[dict, Depends(require_advisor)] = None):
    holdings = _get_client_holdings_enriched(client_id)
    scheme_codes = list({h["scheme_code"] for h in holdings if h.get("scheme_code")})
    if len(scheme_codes) < 2:
        return OverlapMatrixResponse(client_id=client_id, pairs=[], warnings=[])
    try:
        from engine.overlap_engine import compute_overlap_matrix
        matrix = compute_overlap_matrix(scheme_codes)
    except Exception as exc:
        logger.warning("Overlap engine error for client %d: %s", client_id, exc)
        return OverlapMatrixResponse(client_id=client_id, pairs=[], warnings=[])
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        fund_names = {r["scheme_code"]: r["scheme_name"] for r in conn.execute(
            f"SELECT scheme_code, scheme_name FROM funds WHERE scheme_code IN ({','.join('?'*len(scheme_codes))})", scheme_codes).fetchall()}
    pairs = []
    warnings = []
    for (code_a, code_b), overlap_pct in matrix.items():
        pct = round(overlap_pct * 100, 2)
        if pct >= 60:
            level = "high"
            warnings.append(f"HIGH overlap ({pct:.1f}%) between {fund_names.get(code_a, code_a)} and {fund_names.get(code_b, code_b)}")
        elif pct >= 40:
            level = "medium"
            warnings.append(f"MEDIUM overlap ({pct:.1f}%) between {fund_names.get(code_a, code_a)} and {fund_names.get(code_b, code_b)}")
        elif pct >= 20:
            level = "low"
        else:
            level = "none"
        pairs.append(OverlapPairItem(
            fund_a_code=code_a, fund_a_name=fund_names.get(code_a, f"Scheme {code_a}"),
            fund_b_code=code_b, fund_b_name=fund_names.get(code_b, f"Scheme {code_b}"),
            overlap_pct=pct, warning_level=level,
        ))
    return OverlapMatrixResponse(client_id=client_id, pairs=pairs, warnings=warnings)


@router.get("/{client_id}/stock-exposure", response_model=StockExposureResponse)
def get_stock_exposure(client_id: int, client=Depends(require_advisor_owns_client),
                       user: Annotated[dict, Depends(require_advisor)] = None):
    holdings = _get_client_holdings_enriched(client_id)
    if not holdings:
        return StockExposureResponse(client_id=client_id, stocks=[], redundant_flags=[], data_gaps=[])
    engine_holdings = [{"scheme_code": h["scheme_code"], "scheme_name": h["scheme_name"], "corpus_inr": h["current_value"]}
                       for h in holdings if h.get("scheme_code") and h.get("current_value", 0) > 0]
    try:
        from engine.stock_exposure_engine import compute_portfolio_exposure
        result = compute_portfolio_exposure(engine_holdings)
    except Exception as exc:
        logger.warning("Stock exposure engine error for client %d: %s", client_id, exc)
        return StockExposureResponse(client_id=client_id, stocks=[], redundant_flags=[], data_gaps=[])
    total_corpus = sum(h["corpus_inr"] for h in engine_holdings)
    stocks = []
    for exp in result.stock_exposures:
        exposure_pct = (exp.exposure_inr / total_corpus * 100) if total_corpus else 0
        stocks.append(StockExposureItem(
            isin=exp.isin, stock_name=exp.stock_name, sector=exp.sector,
            exposure_inr=round(exp.exposure_inr, 2), exposure_pct=round(exposure_pct, 2),
            fund_count=exp.fund_count, is_redundant=exp.is_redundant,
        ))
    redundant_flags = [f"{s.stock_name} appears in {s.fund_count} funds ({s.exposure_pct:.1f}% of corpus)" for s in stocks if s.is_redundant]
    return StockExposureResponse(
        client_id=client_id, stocks=sorted(stocks, key=lambda s: -s.exposure_inr),
        redundant_flags=redundant_flags, data_gaps=result.data_gaps if hasattr(result, "data_gaps") else [],
    )
