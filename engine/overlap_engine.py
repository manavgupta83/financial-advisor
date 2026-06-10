"""
engine/overlap_engine.py
-------------------------
Portfolio overlap analyser.
UI-compatible wrapper compute_overlap_matrix(scheme_codes, db_path=None)
added at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from data.database import engine, FundHolding, Fund


@dataclass
class StockOverlap:
    isin:        str
    stock_name:  str
    weight_a:    float
    weight_b:    float
    min_weight:  float


@dataclass
class FundOverlap:
    scheme_code_a:  int
    scheme_name_a:  str
    scheme_code_b:  int
    scheme_name_b:  str
    overlap_pct:    float
    common_stocks:  list[StockOverlap] = field(default_factory=list)
    total_stocks_a: int = 0
    total_stocks_b: int = 0
    holding_date_a: Optional[date] = None
    holding_date_b: Optional[date] = None
    warning:        Optional[str]  = None


@dataclass
class OverlapMatrix:
    scheme_codes: list[int]
    scheme_names: dict[int, str]
    matrix:       dict[tuple[int, int], float]
    details:      list[FundOverlap]


def _get_latest_holdings(scheme_code: int) -> tuple[Optional[date], dict[str, tuple[str, float]]]:
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
            .filter(FundHolding.scheme_code == scheme_code, FundHolding.holding_date == latest_date[0])
            .all()
        )
    return latest_date[0], {row.isin: (row.stock_name or "", row.weight_pct or 0.0) for row in rows if row.isin}


def _get_scheme_name(scheme_code: int) -> str:
    with Session(engine) as session:
        fund = session.query(Fund).filter_by(scheme_code=scheme_code).first()
    return fund.scheme_name if fund else f"Scheme {scheme_code}"


def compute_overlap(scheme_code_a: int, scheme_code_b: int) -> FundOverlap:
    name_a = _get_scheme_name(scheme_code_a)
    name_b = _get_scheme_name(scheme_code_b)
    date_a, holdings_a = _get_latest_holdings(scheme_code_a)
    date_b, holdings_b = _get_latest_holdings(scheme_code_b)

    if not holdings_a or not holdings_b:
        return FundOverlap(
            scheme_code_a=scheme_code_a, scheme_name_a=name_a,
            scheme_code_b=scheme_code_b, scheme_name_b=name_b,
            overlap_pct=0.0,
            warning="Holdings data missing. Run holdings_fetcher to populate.",
        )

    shared = set(holdings_a.keys()) & set(holdings_b.keys())
    common_stocks, overlap_score = [], 0.0
    for isin in shared:
        name_stock, w_a = holdings_a[isin]
        _, w_b = holdings_b[isin]
        min_w = min(w_a, w_b)
        overlap_score += min_w
        common_stocks.append(StockOverlap(isin=isin, stock_name=name_stock, weight_a=w_a, weight_b=w_b, min_weight=min_w))
    common_stocks.sort(key=lambda x: x.min_weight, reverse=True)

    warning = None
    if overlap_score >= 60:
        warning = f"Very high overlap ({overlap_score:.1f}%) — consider removing one fund."
    elif overlap_score >= 40:
        warning = f"High overlap ({overlap_score:.1f}%) — limited diversification benefit."
    elif overlap_score >= 20:
        warning = f"Moderate overlap ({overlap_score:.1f}%)."

    return FundOverlap(
        scheme_code_a=scheme_code_a, scheme_name_a=name_a,
        scheme_code_b=scheme_code_b, scheme_name_b=name_b,
        overlap_pct=round(overlap_score, 2), common_stocks=common_stocks,
        total_stocks_a=len(holdings_a), total_stocks_b=len(holdings_b),
        holding_date_a=date_a, holding_date_b=date_b, warning=warning,
    )


def compute_overlap_matrix(
    scheme_codes: list[int],
    db_path: str = None,          # UI-compat kwarg (ignored — uses SQLAlchemy engine)
    portfolio_weights: dict = None,  # UI-compat kwarg (ignored)
) -> dict[tuple[int, int], float]:
    """
    UI-compatible wrapper.
    Returns dict {(code_a, code_b): overlap_pct} for all pairs.
    (The UI indexes this as overlap_matrix.get((sc1, sc2), 0.0).)
    """
    matrix: dict[tuple[int, int], float] = {}
    for i in range(len(scheme_codes)):
        for j in range(i + 1, len(scheme_codes)):
            a, b = scheme_codes[i], scheme_codes[j]
            overlap = compute_overlap(a, b)
            matrix[(a, b)] = overlap.overlap_pct / 100  # UI multiplies by 100 itself
            matrix[(b, a)] = overlap.overlap_pct / 100
    return matrix


def compute_overlap_matrix_full(scheme_codes: list[int]) -> OverlapMatrix:
    """Original full-detail version."""
    scheme_names = {code: _get_scheme_name(code) for code in scheme_codes}
    matrix, details = {}, []
    for i in range(len(scheme_codes)):
        for j in range(i + 1, len(scheme_codes)):
            a, b = scheme_codes[i], scheme_codes[j]
            overlap = compute_overlap(a, b)
            matrix[(a, b)] = overlap.overlap_pct
            matrix[(b, a)] = overlap.overlap_pct
            details.append(overlap)
    return OverlapMatrix(scheme_codes=scheme_codes, scheme_names=scheme_names, matrix=matrix, details=details)


def format_overlap(overlap: FundOverlap, top_n: int = 10) -> str:
    lines = [
        f"  Fund A : {overlap.scheme_name_a}",
        f"  Fund B : {overlap.scheme_name_b}",
        f"  Overlap: {overlap.overlap_pct:.1f}%",
    ]
    if overlap.warning:
        lines.append(f"  ⚠  {overlap.warning}")
    for s in overlap.common_stocks[:top_n]:
        lines.append(f"  {s.stock_name:<40} A:{s.weight_a:.2f}%  B:{s.weight_b:.2f}%  min:{s.min_weight:.2f}%")
    return "\n".join(lines)
