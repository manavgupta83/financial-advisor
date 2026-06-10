"""
engine/overlap_engine.py
-------------------------
Portfolio overlap analyser for the AI Financial Advisory Tool.

Computes the stock-level overlap between any two mutual funds in the portfolio.
High overlap means the investor is paying for diversification they aren't getting.

Two metrics:
  1. Overlap %  — what fraction of Fund A's holdings (by weight) are also in Fund B
                  Formula: sum of min(weight_A, weight_B) for shared ISINs
  2. Common stocks — the actual list of shared holdings with weights from both funds

Data source: fund_holdings table (populated by holdings_fetcher.py)

Usage:
  overlap = compute_overlap(scheme_a, scheme_b)
  matrix  = compute_overlap_matrix([code1, code2, code3])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from data.database import engine, FundHolding, Fund


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StockOverlap:
    isin:        str
    stock_name:  str
    weight_a:    float   # % in fund A
    weight_b:    float   # % in fund B
    min_weight:  float   # min(weight_a, weight_b) — contribution to overlap score


@dataclass
class FundOverlap:
    scheme_code_a:  int
    scheme_name_a:  str
    scheme_code_b:  int
    scheme_name_b:  str
    overlap_pct:    float              # 0-100, higher = more overlap
    common_stocks:  list[StockOverlap] = field(default_factory=list)
    total_stocks_a: int = 0
    total_stocks_b: int = 0
    holding_date_a: Optional[date] = None
    holding_date_b: Optional[date] = None
    warning:        Optional[str]  = None   # e.g. "High overlap — consider consolidating"


@dataclass
class OverlapMatrix:
    scheme_codes: list[int]
    scheme_names: dict[int, str]
    matrix:       dict[tuple[int, int], float]   # (code_a, code_b) → overlap_pct
    details:      list[FundOverlap]


# ---------------------------------------------------------------------------
# Holdings fetcher
# ---------------------------------------------------------------------------

def _get_latest_holdings(scheme_code: int) -> tuple[Optional[date], dict[str, tuple[str, float]]]:
    """
    Fetch the most recent holdings for a fund from the DB.
    Returns (holding_date, {isin: (stock_name, weight_pct)}).
    """
    with Session(engine) as session:
        latest_date = (
            session.query(FundHolding.holding_date)
            .filter(FundHolding.scheme_code == scheme_code)
            .order_by(FundHolding.holding_date.desc())
            .first()
        )
        if not latest_date:
            return None, {}

        rows = (
            session.query(FundHolding)
            .filter(
                FundHolding.scheme_code == scheme_code,
                FundHolding.holding_date == latest_date[0],
            )
            .all()
        )

    holdings = {
        row.isin: (row.stock_name or "", row.weight_pct or 0.0)
        for row in rows
        if row.isin
    }
    return latest_date[0], holdings


def _get_scheme_name(scheme_code: int) -> str:
    with Session(engine) as session:
        fund = session.query(Fund).filter_by(scheme_code=scheme_code).first()
    return fund.scheme_name if fund else f"Scheme {scheme_code}"


# ---------------------------------------------------------------------------
# Core overlap calculation
# ---------------------------------------------------------------------------

def compute_overlap(
    scheme_code_a: int,
    scheme_code_b: int,
) -> FundOverlap:
    """
    Compute stock-level overlap between two funds.

    Overlap score = sum of min(weight_A, weight_B) for all shared ISINs.
    This represents the % of a blended portfolio that is duplicated.

    Parameters
    ----------
    scheme_code_a, scheme_code_b : AMFI scheme codes

    Returns
    -------
    FundOverlap with overlap_pct and list of common stocks
    """
    name_a = _get_scheme_name(scheme_code_a)
    name_b = _get_scheme_name(scheme_code_b)

    date_a, holdings_a = _get_latest_holdings(scheme_code_a)
    date_b, holdings_b = _get_latest_holdings(scheme_code_b)

    if not holdings_a or not holdings_b:
        return FundOverlap(
            scheme_code_a=scheme_code_a, scheme_name_a=name_a,
            scheme_code_b=scheme_code_b, scheme_name_b=name_b,
            overlap_pct=0.0,
            warning="Holdings data missing for one or both funds. "
                    "Run holdings_fetcher to populate.",
        )

    # Find shared ISINs
    shared_isins = set(holdings_a.keys()) & set(holdings_b.keys())

    common_stocks: list[StockOverlap] = []
    overlap_score = 0.0

    for isin in shared_isins:
        name_stock, w_a = holdings_a[isin]
        _, w_b           = holdings_b[isin]
        min_w            = min(w_a, w_b)
        overlap_score   += min_w
        common_stocks.append(StockOverlap(
            isin=isin,
            stock_name=name_stock,
            weight_a=w_a,
            weight_b=w_b,
            min_weight=min_w,
        ))

    # Sort by contribution to overlap (highest first)
    common_stocks.sort(key=lambda x: x.min_weight, reverse=True)

    # Warning thresholds
    warning = None
    if overlap_score >= 60:
        warning = (
            f"Very high overlap ({overlap_score:.1f}%) — "
            f"these funds are nearly identical. Consider removing one."
        )
    elif overlap_score >= 40:
        warning = (
            f"High overlap ({overlap_score:.1f}%) — "
            f"limited diversification benefit from holding both."
        )
    elif overlap_score >= 20:
        warning = (
            f"Moderate overlap ({overlap_score:.1f}%) — "
            f"some common holdings but reasonable diversification."
        )

    return FundOverlap(
        scheme_code_a=scheme_code_a, scheme_name_a=name_a,
        scheme_code_b=scheme_code_b, scheme_name_b=name_b,
        overlap_pct=round(overlap_score, 2),
        common_stocks=common_stocks,
        total_stocks_a=len(holdings_a),
        total_stocks_b=len(holdings_b),
        holding_date_a=date_a,
        holding_date_b=date_b,
        warning=warning,
    )


def compute_overlap_matrix(scheme_codes: list[int]) -> OverlapMatrix:
    """
    Compute pairwise overlap for all combinations in a list of scheme codes.
    Returns an OverlapMatrix with full detail for each pair.
    """
    scheme_names = {code: _get_scheme_name(code) for code in scheme_codes}
    matrix: dict[tuple[int, int], float] = {}
    details: list[FundOverlap] = []

    for i in range(len(scheme_codes)):
        for j in range(i + 1, len(scheme_codes)):
            a, b = scheme_codes[i], scheme_codes[j]
            overlap = compute_overlap(a, b)
            matrix[(a, b)] = overlap.overlap_pct
            matrix[(b, a)] = overlap.overlap_pct   # symmetric
            details.append(overlap)

    return OverlapMatrix(
        scheme_codes=scheme_codes,
        scheme_names=scheme_names,
        matrix=matrix,
        details=details,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_overlap(overlap: FundOverlap, top_n: int = 10) -> str:
    lines = [
        f"Overlap Analysis",
        f"  Fund A : {overlap.scheme_name_a} (code: {overlap.scheme_code_a})",
        f"  Fund B : {overlap.scheme_name_b} (code: {overlap.scheme_code_b})",
        f"  Date A : {overlap.holding_date_a}   |   Date B : {overlap.holding_date_b}",
        f"  Stocks : {overlap.total_stocks_a} in A, {overlap.total_stocks_b} in B, "
        f"{len(overlap.common_stocks)} common",
        f"",
        f"  Overlap Score : {overlap.overlap_pct:.1f}%",
    ]
    if overlap.warning:
        lines.append(f"  ⚠  {overlap.warning}")
    if overlap.common_stocks:
        lines += [
            f"",
            f"  Top {min(top_n, len(overlap.common_stocks))} overlapping stocks:",
            f"  {'Stock':<40} {'Wt-A':>7}  {'Wt-B':>7}  {'Min':>7}",
            f"  {'-'*40} {'-'*7}  {'-'*7}  {'-'*7}",
        ]
        for s in overlap.common_stocks[:top_n]:
            lines.append(
                f"  {s.stock_name:<40} {s.weight_a:>6.2f}%  "
                f"{s.weight_b:>6.2f}%  {s.min_weight:>6.2f}%"
            )
    return "\n".join(lines)


def format_overlap_matrix(om: OverlapMatrix) -> str:
    codes = om.scheme_codes
    n     = len(codes)
    # Header row: truncated names
    short = {c: om.scheme_names[c][:20] for c in codes}

    col_w = 22
    header = " " * 22 + "".join(f"{short[c]:<{col_w}}" for c in codes)
    lines = ["Overlap Matrix (%)", header, "-" * (22 + col_w * n)]

    for a in codes:
        row = f"{short[a]:<22}"
        for b in codes:
            if a == b:
                row += f"{'—':<{col_w}}"
            else:
                pct = om.matrix.get((a, b), 0.0)
                row += f"{pct:>5.1f}%{' ' * (col_w - 7)}"
        lines.append(row)

    return "\n".join(lines)
