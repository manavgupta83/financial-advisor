"""
engine/performance_engine.py
-----------------------------
Performance analytics engine for the AI Financial Advisory Tool.

Computes XIRR, CAGR, and Sharpe ratio for client holdings.

UI-compatible wrappers allow Streamlit pages to call simpler signatures
without needing full date objects or NAV series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from scipy.optimize import brentq
from sqlalchemy.orm import Session

from data.database import engine, NAVHistory, ClientHolding


RISK_FREE_RATE_ANNUAL = 0.065
TRADING_DAYS_PER_YEAR = 252


def _get_risk_free_rate() -> float:
    return RISK_FREE_RATE_ANNUAL


# ---------------------------------------------------------------------------
# NAV helpers
# ---------------------------------------------------------------------------

def get_nav_series(scheme_code: int) -> list[tuple[date, float]]:
    with Session(engine) as session:
        rows = (
            session.query(NAVHistory.nav_date, NAVHistory.nav)
            .filter(NAVHistory.scheme_code == scheme_code)
            .order_by(NAVHistory.nav_date.asc())
            .all()
        )
    return [(r.nav_date, r.nav) for r in rows]


def get_latest_nav(scheme_code: int) -> Optional[tuple[date, float]]:
    with Session(engine) as session:
        row = (
            session.query(NAVHistory.nav_date, NAVHistory.nav)
            .filter(NAVHistory.scheme_code == scheme_code)
            .order_by(NAVHistory.nav_date.desc())
            .first()
        )
    return (row.nav_date, row.nav) if row else None


def get_nav_on_or_before(nav_series, target_date):
    lo, hi, result = 0, len(nav_series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if nav_series[mid][0] <= target_date:
            result = nav_series[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


# ---------------------------------------------------------------------------
# simulate_sip_cashflows — supports both original and UI-compat signatures
# ---------------------------------------------------------------------------

def simulate_sip_cashflows(
    invested_amount: float = None,
    current_value: float = None,
    start_date: date = None,
    end_date: Optional[date] = None,
    total_invested: float = None,
    months: int = None,
    final_value: float = None,
) -> list[tuple[date, float]]:
    """
    Two supported call signatures:
      Original : simulate_sip_cashflows(invested_amount, current_value, start_date)
      UI compat: simulate_sip_cashflows(total_invested=x, months=n, final_value=y)
    """
    if total_invested is not None:
        invested_amount = total_invested
    if final_value is not None:
        current_value = final_value
    if months is not None and start_date is None:
        start_date = date.today() - timedelta(days=months * 30)
    if start_date is None:
        start_date = date.today().replace(year=date.today().year - 3)
    if current_value is None:
        current_value = invested_amount or 0
    if end_date is None:
        end_date = date.today()

    cashflow_dates = []
    cur = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    while cur <= end_month:
        cashflow_dates.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    n = len(cashflow_dates)
    if n == 0:
        return [(end_date, current_value - (invested_amount or 0))]

    monthly_sip = (invested_amount or 0) / n
    cashflows = [(d, -monthly_sip) for d in cashflow_dates]
    cashflows.append((end_date, current_value))
    return cashflows


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------

def _xirr_npv(rate, cashflows):
    t0 = cashflows[0][0]
    return sum(cf / math.pow(1 + rate, (d - t0).days / 365.0) for d, cf in cashflows)


def compute_xirr(cashflows):
    if not cashflows:
        return None
    if not any(cf > 0 for _, cf in cashflows) or not any(cf < 0 for _, cf in cashflows):
        return None
    try:
        return brentq(_xirr_npv, a=-0.999, b=100.0, args=(cashflows,), xtol=1e-8, maxiter=1000)
    except (ValueError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# CAGR — supports both original and UI-compat signatures
# ---------------------------------------------------------------------------

def compute_cagr(
    invested_amount: float = None,
    current_value: float = None,
    start_date: date = None,
    end_date: Optional[date] = None,
    initial_value: float = None,
    final_value: float = None,
    years: float = None,
) -> Optional[float]:
    """
    Two supported call signatures:
      Original : compute_cagr(invested_amount, current_value, start_date)
      UI compat: compute_cagr(initial_value=x, final_value=y, years=n)
    """
    if initial_value is not None:
        invested_amount = initial_value
    if final_value is not None:
        current_value = final_value
    if not invested_amount or invested_amount <= 0 or current_value is None:
        return None
    if years is not None:
        return math.pow(current_value / invested_amount, 1 / years) - 1 if years > 0 else None
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = date.today().replace(year=date.today().year - 3)
    days = (end_date - start_date).days
    return math.pow(current_value / invested_amount, 1 / (days / 365.25)) - 1 if days > 0 else None


# ---------------------------------------------------------------------------
# Sharpe — both NAV-series and scalar versions
# ---------------------------------------------------------------------------

def compute_sharpe(nav_series, start_date=None):
    """Compute Sharpe from NAV history series."""
    if not nav_series or len(nav_series) < 30:
        return None
    series = [(d, n) for d, n in nav_series if d >= start_date] if start_date else nav_series
    if len(series) < 30:
        return None
    daily_returns = [(series[i][1] - series[i-1][1]) / series[i-1][1]
                     for i in range(1, len(series)) if series[i-1][1] > 0]
    if len(daily_returns) < 30:
        return None
    n = len(daily_returns)
    mean_r = sum(daily_returns) / n
    std_dev = math.sqrt(sum((r - mean_r)**2 for r in daily_returns) / (n - 1))
    return ((mean_r * TRADING_DAYS_PER_YEAR - _get_risk_free_rate()) /
            (std_dev * math.sqrt(TRADING_DAYS_PER_YEAR))) if std_dev > 0 else None


def compute_sharpe_ratio(annual_return: float, risk_free_rate: float = 0.065, volatility: float = 0.15) -> float:
    """UI-compat: compute Sharpe from scalar annual return and estimated volatility."""
    return (annual_return - risk_free_rate) / volatility if volatility > 0 else 0.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HoldingPerformance:
    scheme_code: int
    scheme_name: str
    invested_amount: float
    current_value: float
    absolute_gain: float
    gain_pct: float
    xirr: Optional[float]
    cagr: Optional[float]
    sharpe: Optional[float]
    latest_nav: Optional[float]
    latest_nav_date: Optional[date]
    nav_available: bool


@dataclass
class PortfolioPerformance:
    total_invested: float
    total_current: float
    absolute_gain: float
    gain_pct: float
    xirr: Optional[float]
    holdings: list[HoldingPerformance]


# ---------------------------------------------------------------------------
# Main analytics
# ---------------------------------------------------------------------------

def analyse_holding(holding, scheme_name, start_date=None):
    if start_date is None:
        start_date = date.today().replace(year=date.today().year - 3)
    nav_series    = get_nav_series(holding.scheme_code)
    latest        = get_latest_nav(holding.scheme_code)
    nav_available = bool(nav_series)
    if latest:
        current_value, latest_nav, latest_nav_date = holding.units * latest[1], latest[1], latest[0]
    else:
        current_value, latest_nav, latest_nav_date = holding.invested_amount, None, None
    absolute_gain = current_value - holding.invested_amount
    gain_pct      = (absolute_gain / holding.invested_amount * 100) if holding.invested_amount > 0 else 0.0
    cashflows     = simulate_sip_cashflows(holding.invested_amount, current_value, start_date)
    return HoldingPerformance(
        scheme_code=holding.scheme_code, scheme_name=scheme_name,
        invested_amount=holding.invested_amount, current_value=current_value,
        absolute_gain=absolute_gain, gain_pct=gain_pct,
        xirr=compute_xirr(cashflows),
        cagr=compute_cagr(holding.invested_amount, current_value, start_date),
        sharpe=compute_sharpe(nav_series, start_date=start_date),
        latest_nav=latest_nav, latest_nav_date=latest_nav_date, nav_available=nav_available,
    )


def analyse_portfolio(client_id: int) -> PortfolioPerformance:
    with Session(engine) as session:
        holdings = session.query(ClientHolding).filter(ClientHolding.client_id == client_id).all()
        from data.database import Fund
        scheme_names = {f.scheme_code: f.scheme_name for f in session.query(Fund).all()}
    start_date = date.today().replace(year=date.today().year - 3)
    holding_perfs, all_cashflows = [], []
    for h in holdings:
        perf = analyse_holding(h, scheme_names.get(h.scheme_code, f"Scheme {h.scheme_code}"), start_date)
        holding_perfs.append(perf)
        all_cashflows.extend(simulate_sip_cashflows(h.invested_amount, perf.current_value, start_date))
    total_invested = sum(p.invested_amount for p in holding_perfs)
    total_current  = sum(p.current_value   for p in holding_perfs)
    absolute_gain  = total_current - total_invested
    all_cashflows.sort(key=lambda x: x[0])
    return PortfolioPerformance(
        total_invested=total_invested, total_current=total_current,
        absolute_gain=absolute_gain,
        gain_pct=(absolute_gain / total_invested * 100) if total_invested > 0 else 0.0,
        xirr=compute_xirr(all_cashflows) if all_cashflows else None,
        holdings=holding_perfs,
    )


def format_performance(perf: PortfolioPerformance) -> str:
    lines = [
        f"  {'Fund':<50} {'Invested':>12}  {'Current':>12}  {'Gain%':>7}  {'XIRR':>7}  {'CAGR':>7}  {'Sharpe':>7}",
        "  " + "-" * 110,
    ]
    for h in perf.holdings:
        lines.append(
            f"  {(h.scheme_name + ('' if h.nav_available else ' *')):<50} "
            f"Rs{h.invested_amount:>10,.0f}  Rs{h.current_value:>10,.0f}  {h.gain_pct:>6.1f}%  "
            f"{'N/A' if h.xirr is None else f'{h.xirr*100:.1f}%':>7}  "
            f"{'N/A' if h.cagr is None else f'{h.cagr*100:.1f}%':>7}  "
            f"{'N/A' if h.sharpe is None else f'{h.sharpe:.2f}':>7}"
        )
    lines += [
        "  " + "-" * 110,
        f"  {'PORTFOLIO TOTAL':<50} Rs{perf.total_invested:>10,.0f}  Rs{perf.total_current:>10,.0f}  "
        f"{perf.gain_pct:>6.1f}%  {'N/A' if perf.xirr is None else f'{perf.xirr*100:.1f}%':>7}",
        "",
        "  * NAV data not in DB — run nav_fetcher for this scheme",
    ]
    return "\n".join(lines)
