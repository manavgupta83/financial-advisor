"""
engine/stock_exposure_engine.py
--------------------------------
Stock-level and sector-level weighted exposure engine.

For a client holding N mutual funds with invested ₹ amounts per fund,
this engine computes:
  - Per-stock weighted exposure = sum(fund_weight × fund_corpus_₹) across all held funds
  - Per-sector blended exposure = same rolled up via sector_map
  - Redundancy flags: stocks in 2+ funds above a configurable threshold

This is distinct from the pairwise overlap engine (overlap_engine.py).
That engine asks: how similar are two funds?
This engine asks: what is my true stock/sector exposure across my entire corpus?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session
from data.database import engine as db_engine, FundHolding, SectorMap


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StockExposure:
    isin:               str
    stock_name:         str
    sector:             str
    funds_held_in:      list[str]           # scheme names that hold this stock
    exposure_inr:       float               # ₹ weighted exposure across corpus
    exposure_pct:       float               # % of total corpus
    is_redundant:       bool = False        # True if in 2+ funds above threshold


@dataclass
class SectorExposure:
    sector:             str
    exposure_inr:       float
    exposure_pct:       float
    is_concentrated:    bool = False        # True if >25%
    is_highly_concentrated: bool = False   # True if >40%


@dataclass
class PortfolioExposureResult:
    total_corpus_inr:   float
    stock_exposures:    list[StockExposure]
    sector_exposures:   list[SectorExposure]
    redundant_stocks:   list[StockExposure]
    data_gaps:          list[str]           # funds with no holdings data


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def compute_portfolio_exposure(
    holdings: list[dict],
    redundancy_threshold: float = 0.05,    # 5% combined weight = redundant
) -> PortfolioExposureResult:
    """
    Compute stock and sector level exposure across a client's corpus.

    Parameters
    ----------
    holdings : list of dicts with keys:
        scheme_code (int), scheme_name (str), corpus_inr (float)
    redundancy_threshold : float
        Combined effective weight above which a stock is flagged redundant
        if it appears in 2+ funds. Default 5%.

    Returns
    -------
    PortfolioExposureResult
    """
    total_corpus = sum(h["corpus_inr"] for h in holdings)
    if total_corpus <= 0:
        return PortfolioExposureResult(
            total_corpus_inr=0,
            stock_exposures=[],
            sector_exposures=[],
            redundant_stocks=[],
            data_gaps=[]
        )

    # Step 1 — Fetch latest holdings for each fund
    fund_holdings_map: dict[int, dict[str, tuple[str, float]]] = {}
    data_gaps: list[str] = []

    with Session(db_engine) as session:
        for h in holdings:
            sc = h["scheme_code"]
            latest_date = (
                session.query(FundHolding.holding_date)
                .filter(FundHolding.scheme_code == sc)
                .order_by(FundHolding.holding_date.desc())
                .first()
            )
            if not latest_date:
                data_gaps.append(h.get("scheme_name", str(sc)))
                fund_holdings_map[sc] = {}
                continue
            rows = (
                session.query(FundHolding)
                .filter(
                    FundHolding.scheme_code == sc,
                    FundHolding.holding_date == latest_date[0]
                )
                .all()
            )
            fund_holdings_map[sc] = {
                row.isin: (row.stock_name or "", row.weight_pct or 0.0)
                for row in rows if row.isin
            }

        # Step 2 — Sector map lookup
        all_isins = set()
        for hmap in fund_holdings_map.values():
            all_isins.update(hmap.keys())
        sector_rows = session.query(SectorMap).filter(SectorMap.isin.in_(all_isins)).all()
        sector_by_isin = {r.isin: r.sector or "Unknown" for r in sector_rows}

    # Step 3 — Compute weighted ₹ exposure per stock
    stock_agg: dict[str, dict] = {}   # isin -> aggregated data

    for h in holdings:
        sc = h["scheme_code"]
        corpus = h["corpus_inr"]
        name = h.get("scheme_name", str(sc))
        fund_hmap = fund_holdings_map.get(sc, {})

        for isin, (stock_name, weight_pct) in fund_hmap.items():
            weight_decimal = weight_pct / 100.0 if weight_pct > 1 else weight_pct
            exposure_inr = weight_decimal * corpus

            if isin not in stock_agg:
                stock_agg[isin] = {
                    "stock_name": stock_name,
                    "sector": sector_by_isin.get(isin, "Unknown"),
                    "exposure_inr": 0.0,
                    "funds": [],
                }
            stock_agg[isin]["exposure_inr"] += exposure_inr
            stock_agg[isin]["funds"].append(name)

    # Step 4 — Build StockExposure objects + flag redundancy
    stock_exposures: list[StockExposure] = []
    for isin, data in stock_agg.items():
        exp_pct = data["exposure_inr"] / total_corpus
        is_redundant = (
            len(data["funds"]) >= 2 and
            exp_pct >= redundancy_threshold
        )
        stock_exposures.append(StockExposure(
            isin=isin,
            stock_name=data["stock_name"],
            sector=data["sector"],
            funds_held_in=data["funds"],
            exposure_inr=round(data["exposure_inr"], 2),
            exposure_pct=round(exp_pct * 100, 3),
            is_redundant=is_redundant,
        ))

    stock_exposures.sort(key=lambda x: x.exposure_inr, reverse=True)
    redundant = [s for s in stock_exposures if s.is_redundant]

    # Step 5 — Roll up to sector level
    sector_agg: dict[str, float] = {}
    for s in stock_exposures:
        sector_agg[s.sector] = sector_agg.get(s.sector, 0.0) + s.exposure_inr

    sector_exposures: list[SectorExposure] = []
    for sector, inr in sorted(sector_agg.items(), key=lambda x: x[1], reverse=True):
        pct = inr / total_corpus * 100
        sector_exposures.append(SectorExposure(
            sector=sector,
            exposure_inr=round(inr, 2),
            exposure_pct=round(pct, 3),
            is_concentrated=pct >= 25,
            is_highly_concentrated=pct >= 40,
        ))

    return PortfolioExposureResult(
        total_corpus_inr=total_corpus,
        stock_exposures=stock_exposures,
        sector_exposures=sector_exposures,
        redundant_stocks=redundant,
        data_gaps=data_gaps,
    )


def format_exposure_summary(result: PortfolioExposureResult, top_n: int = 15) -> str:
    """Return a human-readable summary of exposure results."""
    lines = [
        f"  Total corpus          : ₹{result.total_corpus_inr:>14,.0f}",
        f"  Stocks tracked        : {len(result.stock_exposures)}",
        f"  Redundant stocks      : {len(result.redundant_stocks)}",
        "",
        f"  Top {top_n} Stock Exposures:",
    ]
    for s in result.stock_exposures[:top_n]:
        flag = " ⚠ REDUNDANT" if s.is_redundant else ""
        lines.append(
            f"    {s.stock_name:<35} ₹{s.exposure_inr:>12,.0f}  "
            f"({s.exposure_pct:.2f}%)  [{s.sector}]{flag}"
        )
    lines += ["", "  Sector Allocation:"]
    for sec in result.sector_exposures:
        warn = " ⚠ HIGH" if sec.is_highly_concentrated else (" ⚠" if sec.is_concentrated else "")
        lines.append(f"    {sec.sector:<30} {sec.exposure_pct:.2f}%{warn}")
    if result.data_gaps:
        lines += ["", "  ⚠ No holdings data for:"]
        for g in result.data_gaps:
            lines.append(f"    - {g}")
    return "\n".join(lines)
