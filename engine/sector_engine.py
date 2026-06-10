"""
engine/sector_engine.py
------------------------
Sector allocation analyser.
UI-compatible wrapper compute_portfolio_sector_allocation(scheme_codes, portfolio_weights, db_path)
added at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from data.database import engine, FundHolding, SectorMap, Fund, ClientHolding


@dataclass
class SectorWeight:
    sector:     str
    weight_pct: float
    stocks:     list[tuple[str, str, float]] = field(default_factory=list)


@dataclass
class FundSectorBreakdown:
    scheme_code:      int
    scheme_name:      str
    invested_amount:  float
    portfolio_weight: float
    sectors:          list[SectorWeight] = field(default_factory=list)
    unmapped_pct:     float = 0.0


@dataclass
class PortfolioSectorAllocation:
    total_invested:  float
    sector_summary:  list[SectorWeight]
    fund_breakdowns: list[FundSectorBreakdown]
    unmapped_pct:    float
    warnings:        list[str] = field(default_factory=list)


def _get_latest_holdings_with_sectors(scheme_code: int) -> list[dict]:
    with Session(engine) as session:
        latest = (
            session.query(FundHolding.holding_date)
            .filter(FundHolding.scheme_code == scheme_code)
            .order_by(FundHolding.holding_date.desc())
            .first()
        )
        if not latest:
            return []
        rows = (
            session.query(FundHolding)
            .filter(FundHolding.scheme_code == scheme_code, FundHolding.holding_date == latest[0])
            .all()
        )
        isins = [r.isin for r in rows if r.isin]
        sector_map = {}
        if isins:
            sector_map = {s.isin: s.sector for s in session.query(SectorMap).filter(SectorMap.isin.in_(isins)).all()}
    return [{"isin": r.isin, "stock_name": r.stock_name or "",
             "weight_pct": r.weight_pct or 0.0, "sector": sector_map.get(r.isin, "Unknown")}
            for r in rows if r.isin]


def _get_scheme_name(scheme_code: int) -> str:
    with Session(engine) as session:
        fund = session.query(Fund).filter_by(scheme_code=scheme_code).first()
    return fund.scheme_name if fund else f"Scheme {scheme_code}"


def analyse_fund_sectors(scheme_code: int, invested_amount: float, total_portfolio: float) -> FundSectorBreakdown:
    name             = _get_scheme_name(scheme_code)
    portfolio_weight = (invested_amount / total_portfolio * 100) if total_portfolio > 0 else 0.0
    holdings         = _get_latest_holdings_with_sectors(scheme_code)
    if not holdings:
        return FundSectorBreakdown(scheme_code=scheme_code, scheme_name=name,
                                   invested_amount=invested_amount, portfolio_weight=portfolio_weight, unmapped_pct=100.0)
    sector_data: dict[str, list] = {}
    unmapped_weight = 0.0
    for h in holdings:
        sector = h["sector"] if h["sector"] else "Unknown"
        if sector == "Unknown":
            unmapped_weight += h["weight_pct"]
        sector_data.setdefault(sector, []).append((h["isin"], h["stock_name"], h["weight_pct"]))
    sectors = [SectorWeight(sector=s, weight_pct=round(sum(x[2] for x in stocks), 2),
                            stocks=sorted(stocks, key=lambda x: x[2], reverse=True))
               for s, stocks in sector_data.items()]
    sectors.sort(key=lambda x: x.weight_pct, reverse=True)
    return FundSectorBreakdown(scheme_code=scheme_code, scheme_name=name, invested_amount=invested_amount,
                               portfolio_weight=portfolio_weight, sectors=sectors, unmapped_pct=round(unmapped_weight, 2))


def analyse_portfolio_sectors(client_id: int) -> PortfolioSectorAllocation:
    with Session(engine) as session:
        holdings = session.query(ClientHolding).filter(ClientHolding.client_id == client_id).all()
    if not holdings:
        return PortfolioSectorAllocation(total_invested=0, sector_summary=[], fund_breakdowns=[],
                                         unmapped_pct=0.0, warnings=["No holdings found."])
    total_invested = sum(h.invested_amount for h in holdings)
    fund_breakdowns = [analyse_fund_sectors(h.scheme_code, h.invested_amount, total_invested) for h in holdings]
    blended: dict[str, float] = {}
    total_unmapped = 0.0
    for bd in fund_breakdowns:
        fund_share = bd.portfolio_weight / 100
        total_unmapped += bd.unmapped_pct * fund_share
        for sw in bd.sectors:
            blended[sw.sector] = blended.get(sw.sector, 0.0) + sw.weight_pct * fund_share
    sector_summary = [SectorWeight(sector=s, weight_pct=round(w, 2))
                      for s, w in sorted(blended.items(), key=lambda x: x[1], reverse=True)]
    warnings = []
    for sw in sector_summary:
        if sw.sector != "Unknown":
            if sw.weight_pct >= 40:
                warnings.append(f"High concentration: {sw.weight_pct:.1f}% in {sw.sector}.")
            elif sw.weight_pct >= 25:
                warnings.append(f"Elevated exposure: {sw.weight_pct:.1f}% in {sw.sector}.")
    return PortfolioSectorAllocation(total_invested=total_invested, sector_summary=sector_summary,
                                     fund_breakdowns=fund_breakdowns, unmapped_pct=round(total_unmapped, 2), warnings=warnings)


def compute_portfolio_sector_allocation(
    scheme_codes: list[int],
    portfolio_weights: dict[int, float] = None,
    db_path: str = None,          # UI-compat kwarg (ignored)
) -> dict[str, float]:
    """
    UI-compatible wrapper.
    Returns {sector_name: weight_as_decimal} blended across given scheme_codes,
    weighted by portfolio_weights (values are fractions summing to 1).
    Returns empty dict if no holdings data.
    """
    if not scheme_codes:
        return {}
    if portfolio_weights is None:
        portfolio_weights = {code: 1.0 / len(scheme_codes) for code in scheme_codes}

    blended: dict[str, float] = {}
    for code in scheme_codes:
        weight = portfolio_weights.get(code, 0.0)
        holdings = _get_latest_holdings_with_sectors(code)
        if not holdings:
            continue
        sector_data: dict[str, float] = {}
        for h in holdings:
            sector = h["sector"] if h["sector"] else "Unknown"
            sector_data[sector] = sector_data.get(sector, 0.0) + h["weight_pct"]
        for sector, pct in sector_data.items():
            blended[sector] = blended.get(sector, 0.0) + (pct / 100) * weight

    return blended  # {sector: decimal_weight}


def format_sector_allocation(alloc: PortfolioSectorAllocation) -> str:
    lines = [f"  Sector Allocation  (Invested: Rs{alloc.total_invested:,.0f})",
             f"  {'Sector':<30} {'Weight':>8}", f"  {'-'*40}"]
    for sw in alloc.sector_summary:
        lines.append(f"  {sw.sector:<30} {sw.weight_pct:>7.1f}%")
    if alloc.warnings:
        lines += [""] + [f"  ⚠  {w}" for w in alloc.warnings]
    return "\n".join(lines)
