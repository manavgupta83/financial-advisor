"""
engine/sector_engine.py
------------------------
Sector allocation analyser for the AI Financial Advisory Tool.

Computes how a client's portfolio is distributed across market sectors
(Financials, IT, Healthcare, etc.) by blending the stock-level holdings
of each fund, weighted by the client's investment in that fund.

Data sources:
  - fund_holdings  : stock weights per fund (from holdings_fetcher)
  - sector_map     : sector per ISIN (from holdings_fetcher + LLM fallback in Phase 4)
  - client_holdings: client's investment amount per fund

Output:
  - Sector breakdown as % of total portfolio
  - Per-fund sector breakdown
  - Concentration warnings (e.g. >40% in a single sector)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from data.database import engine, FundHolding, SectorMap, Fund, ClientHolding


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SectorWeight:
    sector:     str
    weight_pct: float              # % of total portfolio in this sector
    stocks:     list[tuple[str, str, float]] = field(default_factory=list)
    # (isin, stock_name, contribution_pct)


@dataclass
class FundSectorBreakdown:
    scheme_code:   int
    scheme_name:   str
    invested_amount: float
    portfolio_weight: float        # % of client's total portfolio in this fund
    sectors:       list[SectorWeight] = field(default_factory=list)
    unmapped_pct:  float = 0.0     # % with no sector data


@dataclass
class PortfolioSectorAllocation:
    total_invested:    float
    sector_summary:    list[SectorWeight]    # blended across all funds
    fund_breakdowns:   list[FundSectorBreakdown]
    unmapped_pct:      float                 # % of portfolio with no sector mapping
    warnings:          list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _get_latest_holdings_with_sectors(
    scheme_code: int,
) -> list[dict]:
    """
    Fetch the most recent holdings for a fund, joined with sector data.
    Returns list of {isin, stock_name, weight_pct, sector}.
    """
    with Session(engine) as session:
        # Get latest holding date
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
            .filter(
                FundHolding.scheme_code == scheme_code,
                FundHolding.holding_date == latest[0],
            )
            .all()
        )

        # Build ISIN → sector lookup from sector_map
        isins = [r.isin for r in rows if r.isin]
        sector_map = {}
        if isins:
            sm_rows = (
                session.query(SectorMap)
                .filter(SectorMap.isin.in_(isins))
                .all()
            )
            sector_map = {s.isin: s.sector for s in sm_rows}

    return [
        {
            "isin":       row.isin,
            "stock_name": row.stock_name or "",
            "weight_pct": row.weight_pct or 0.0,
            "sector":     sector_map.get(row.isin, "Unknown"),
        }
        for row in rows
        if row.isin
    ]


def _get_scheme_name(scheme_code: int) -> str:
    with Session(engine) as session:
        fund = session.query(Fund).filter_by(scheme_code=scheme_code).first()
    return fund.scheme_name if fund else f"Scheme {scheme_code}"


# ---------------------------------------------------------------------------
# Per-fund sector breakdown
# ---------------------------------------------------------------------------

def analyse_fund_sectors(
    scheme_code: int,
    invested_amount: float,
    total_portfolio: float,
) -> FundSectorBreakdown:
    """
    Compute sector allocation for a single fund.

    Parameters
    ----------
    scheme_code      : AMFI scheme code
    invested_amount  : client's investment in this fund (₹)
    total_portfolio  : client's total portfolio value (₹) — for weighting

    Returns
    -------
    FundSectorBreakdown
    """
    name             = _get_scheme_name(scheme_code)
    portfolio_weight = (invested_amount / total_portfolio * 100
                        if total_portfolio > 0 else 0.0)
    holdings         = _get_latest_holdings_with_sectors(scheme_code)

    if not holdings:
        return FundSectorBreakdown(
            scheme_code=scheme_code,
            scheme_name=name,
            invested_amount=invested_amount,
            portfolio_weight=portfolio_weight,
            unmapped_pct=100.0,
        )

    # Group by sector
    sector_data: dict[str, list[tuple[str, str, float]]] = {}
    unmapped_weight = 0.0

    for h in holdings:
        sector = h["sector"] if h["sector"] not in ("", None) else "Unknown"
        if sector == "Unknown":
            unmapped_weight += h["weight_pct"]
        sector_data.setdefault(sector, []).append(
            (h["isin"], h["stock_name"], h["weight_pct"])
        )

    sectors: list[SectorWeight] = []
    for sector, stocks in sector_data.items():
        total_weight = sum(s[2] for s in stocks)
        sectors.append(SectorWeight(
            sector=sector,
            weight_pct=round(total_weight, 2),
            stocks=sorted(stocks, key=lambda x: x[2], reverse=True),
        ))

    sectors.sort(key=lambda x: x.weight_pct, reverse=True)

    return FundSectorBreakdown(
        scheme_code=scheme_code,
        scheme_name=name,
        invested_amount=invested_amount,
        portfolio_weight=portfolio_weight,
        sectors=sectors,
        unmapped_pct=round(unmapped_weight, 2),
    )


# ---------------------------------------------------------------------------
# Portfolio-level sector allocation
# ---------------------------------------------------------------------------

def analyse_portfolio_sectors(client_id: int) -> PortfolioSectorAllocation:
    """
    Compute blended sector allocation across a client's full portfolio.

    Each fund's sector weights are scaled by that fund's share of the
    total portfolio before blending.

    Parameters
    ----------
    client_id : client primary key

    Returns
    -------
    PortfolioSectorAllocation
    """
    with Session(engine) as session:
        holdings = (
            session.query(ClientHolding)
            .filter(ClientHolding.client_id == client_id)
            .all()
        )

    if not holdings:
        return PortfolioSectorAllocation(
            total_invested=0,
            sector_summary=[],
            fund_breakdowns=[],
            unmapped_pct=0.0,
            warnings=["No holdings found for this client."],
        )

    total_invested = sum(h.invested_amount for h in holdings)

    # Per-fund breakdown
    fund_breakdowns: list[FundSectorBreakdown] = []
    for h in holdings:
        bd = analyse_fund_sectors(h.scheme_code, h.invested_amount, total_invested)
        fund_breakdowns.append(bd)

    # Blend sectors weighted by fund's portfolio share
    blended: dict[str, float] = {}
    blended_stocks: dict[str, list[tuple[str, str, float]]] = {}
    total_unmapped = 0.0

    for bd in fund_breakdowns:
        fund_share = bd.portfolio_weight / 100  # as decimal
        total_unmapped += bd.unmapped_pct * fund_share

        for sw in bd.sectors:
            blended_weight = sw.weight_pct * fund_share
            blended[sw.sector] = blended.get(sw.sector, 0.0) + blended_weight
            blended_stocks.setdefault(sw.sector, []).extend(
                [(isin, name, w * fund_share) for isin, name, w in sw.stocks]
            )

    # Build sector summary
    sector_summary: list[SectorWeight] = []
    for sector, weight in sorted(blended.items(), key=lambda x: x[1], reverse=True):
        stocks = sorted(blended_stocks[sector], key=lambda x: x[2], reverse=True)
        sector_summary.append(SectorWeight(
            sector=sector,
            weight_pct=round(weight, 2),
            stocks=stocks,
        ))

    # Concentration warnings
    warnings: list[str] = []
    for sw in sector_summary:
        if sw.sector == "Unknown":
            continue
        if sw.weight_pct >= 40:
            warnings.append(
                f"High concentration: {sw.weight_pct:.1f}% in {sw.sector}. "
                f"Consider diversifying across sectors."
            )
        elif sw.weight_pct >= 25:
            warnings.append(
                f"Elevated exposure: {sw.weight_pct:.1f}% in {sw.sector}."
            )

    if total_unmapped > 20:
        warnings.append(
            f"{total_unmapped:.1f}% of portfolio has no sector mapping. "
            f"Run sector_engine with LLM fallback (Phase 4) to fill gaps."
        )

    return PortfolioSectorAllocation(
        total_invested=total_invested,
        sector_summary=sector_summary,
        fund_breakdowns=fund_breakdowns,
        unmapped_pct=round(total_unmapped, 2),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_sector_allocation(alloc: PortfolioSectorAllocation) -> str:
    lines = [
        f"  Portfolio Sector Allocation  (Total invested: ₹{alloc.total_invested:,.0f})",
        f"  {'Sector':<30} {'Weight':>8}  {'Bar'}",
        f"  {'-'*30} {'-'*8}  {'-'*30}",
    ]
    for sw in alloc.sector_summary:
        bar   = "█" * int(sw.weight_pct / 2)
        lines.append(f"  {sw.sector:<30} {sw.weight_pct:>7.1f}%  {bar}")

    if alloc.unmapped_pct > 0:
        lines.append(
            f"  {'Unknown / Unmapped':<30} {alloc.unmapped_pct:>7.1f}%"
        )

    if alloc.warnings:
        lines.append("")
        for w in alloc.warnings:
            lines.append(f"  ⚠  {w}")

    return "\n".join(lines)


def format_fund_sector_breakdown(bd: FundSectorBreakdown) -> str:
    lines = [
        f"  {bd.scheme_name}",
        f"  Invested: ₹{bd.invested_amount:,.0f}  |  "
        f"Portfolio weight: {bd.portfolio_weight:.1f}%",
        f"  {'Sector':<30} {'Weight':>8}",
        f"  {'-'*30} {'-'*8}",
    ]
    for sw in bd.sectors:
        lines.append(f"  {sw.sector:<30} {sw.weight_pct:>7.1f}%")
    if bd.unmapped_pct > 0:
        lines.append(f"  {'Unknown':<30} {bd.unmapped_pct:>7.1f}%")
    return "\n".join(lines)
