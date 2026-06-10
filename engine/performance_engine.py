"""
engine/performance_engine.py
-----------------------------
Performance analytics engine for the AI Financial Advisory Tool.

Computes three core metrics for a client's mutual fund holdings:
  - XIRR  : Extended Internal Rate of Return (true time-weighted return on SIPs)
  - CAGR  : Compound Annual Growth Rate (point-to-point return)
  - Sharpe: Risk-adjusted return = (annualised_return - risk_free_rate) / annualised_volatility

Transaction simulation:
  Since client_holdings stores only current position (units, avg_nav, invested_amount)
  and not individual SIP dates, we simulate a monthly SIP history by back-calculating
  equal monthly investments from the start date to today.

  Simulated cashflows:
    - Outflows: equal monthly SIP = invested_amount / months, on the 1st of each month
    - Inflow  : current value (units × latest NAV) on today's date

Risk-free rate:
  Fixed at 6.5% (RBI repo rate as of 2025).
  TODO: replace _get_risk_free_rate() with a live fetch from RBI / FBIL when available.

Dependencies:
  - scipy.optimize.brentq  for XIRR root-finding
  - data from nav_history table (SQLAlchemy session)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from scipy.optimize import brentq
from sqlalchemy.orm import Session

from data.database import engine, NAVHistory, ClientHolding


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_FREE_RATE_ANNUAL = 0.065   # 6.5% — RBI repo rate (fixed, see TODO above)
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Risk-free rate
# ---------------------------------------------------------------------------

def _get_risk_free_rate() -> float:
    """
    Returns the annual risk-free rate for Sharpe ratio calculation.
    Currently returns a fixed constant.
    TODO: fetch from https://www.fbil.org.in or RBI API for live rate.
    """
    return RISK_FREE_RATE_ANNUAL


# ---------------------------------------------------------------------------
# NAV helpers
# ---------------------------------------------------------------------------

def get_nav_series(scheme_code: int) -> list[tuple[date, float]]:
    """
    Fetch full NAV history for a scheme from the DB.
    Returns list of (nav_date, nav) sorted ascending by date.
    """
    with Session(engine) as session:
        rows = (
            session.query(NAVHistory.nav_date, NAVHistory.nav)
            .filter(NAVHistory.scheme_code == scheme_code)
            .order_by(NAVHistory.nav_date.asc())
            .all()
        )
    return [(r.nav_date, r.nav) for r in rows]


def get_latest_nav(scheme_code: int) -> Optional[tuple[date, float]]:
    """Returns the most recent (date, nav) for a scheme."""
    with Session(engine) as session:
        row = (
            session.query(NAVHistory.nav_date, NAVHistory.nav)
            .filter(NAVHistory.scheme_code == scheme_code)
            .order_by(NAVHistory.nav_date.desc())
            .first()
        )
    return (row.nav_date, row.nav) if row else None


def get_nav_on_or_before(
    nav_series: list[tuple[date, float]],
    target_date: date,
) -> Optional[float]:
    """
    Binary search for the NAV on or before target_date.
    Returns None if no NAV exists before target_date.
    """
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
# Transaction simulation
# ---------------------------------------------------------------------------

def simulate_sip_cashflows(
    invested_amount: float,
    current_value: float,
    start_date: date,
    end_date: Optional[date] = None,
) -> list[tuple[date, float]]:
    """
    Simulate monthly SIP cashflows for XIRR calculation.

    Strategy:
      - Divide invested_amount equally across months from start_date to end_date
      - Each monthly outflow is negative (money going out)
      - Final inflow (current_value) is positive (money coming back)

    Returns list of (date, cashflow) sorted ascending.
    Convention: outflows are negative, inflow is positive.
    """
    if end_date is None:
        end_date = date.today()

    # Build monthly dates from start to end (1st of each month)
    cashflow_dates: list[date] = []
    current = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while current <= end_month:
        cashflow_dates.append(current)
        # Advance one month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    n_months = len(cashflow_dates)
    if n_months == 0:
        return [(end_date, current_value - invested_amount)]

    monthly_sip = invested_amount / n_months

    cashflows: list[tuple[date, float]] = []
    for d in cashflow_dates:
        cashflows.append((d, -monthly_sip))   # outflow

    # Final inflow: current value on end_date
    cashflows.append((end_date, current_value))

    return cashflows


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------

def _xirr_npv(rate: float, cashflows: list[tuple[date, float]]) -> float:
    """NPV of cashflows at a given annual rate, with dates as day fractions."""
    t0 = cashflows[0][0]
    total = 0.0
    for d, cf in cashflows:
        days = (d - t0).days
        total += cf / math.pow(1 + rate, days / 365.0)
    return total


def compute_xirr(cashflows: list[tuple[date, float]]) -> Optional[float]:
    """
    Compute XIRR (annualised IRR for irregular cashflows).

    Uses Brent's method to find the rate r such that NPV(cashflows, r) = 0.
    Returns None if no solution found (e.g. all cashflows same sign).

    Parameters
    ----------
    cashflows : list of (date, amount) — outflows negative, inflows positive

    Returns
    -------
    XIRR as a decimal (e.g. 0.142 = 14.2%) or None
    """
    if not cashflows:
        return None

    # Need at least one positive and one negative cashflow
    has_positive = any(cf > 0 for _, cf in cashflows)
    has_negative = any(cf < 0 for _, cf in cashflows)
    if not (has_positive and has_negative):
        return None

    try:
        result = brentq(
            _xirr_npv,
            a=-0.999,
            b=100.0,
            args=(cashflows,),
            xtol=1e-8,
            maxiter=1000,
        )
        return result
    except (ValueError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------

def compute_cagr(
    invested_amount: float,
    current_value: float,
    start_date: date,
    end_date: Optional[date] = None,
) -> Optional[float]:
    """
    Compute CAGR = (current_value / invested_amount)^(1/years) - 1.

    Returns None if duration < 1 day or invested_amount <= 0.
    """
    if end_date is None:
        end_date = date.today()

    if invested_amount <= 0:
        return None

    days = (end_date - start_date).days
    if days <= 0:
        return None

    years = days / 365.25
    return math.pow(current_value / invested_amount, 1 / years) - 1


# ---------------------------------------------------------------------------
# Sharpe Ratio
# ---------------------------------------------------------------------------

def compute_sharpe(
    nav_series: list[tuple[date, float]],
    start_date: Optional[date] = None,
) -> Optional[float]:
    """
    Compute annualised Sharpe ratio from NAV history.

    Sharpe = (annualised_return - risk_free_rate) / annualised_volatility

    Where:
      - annualised_return    = mean(daily_returns) × 252
      - annualised_volatility = std(daily_returns) × sqrt(252)
      - daily_returns         = (NAV[t] - NAV[t-1]) / NAV[t-1]

    Parameters
    ----------
    nav_series  : list of (date, nav) sorted ascending
    start_date  : optional — only use NAVs from this date onwards

    Returns
    -------
    Sharpe ratio as a float, or None if insufficient data
    """
    if not nav_series or len(nav_series) < 30:
        return None

    # Filter to start_date if provided
    series = nav_series
    if start_date:
        series = [(d, n) for d, n in nav_series if d >= start_date]

    if len(series) < 30:
        return None

    # Compute daily returns
    daily_returns: list[float] = []
    for i in range(1, len(series)):
        prev_nav = series[i - 1][1]
        curr_nav = series[i][1]
        if prev_nav > 0:
            daily_returns.append((curr_nav - prev_nav) / prev_nav)

    if len(daily_returns) < 30:
        return None

    n = len(daily_returns)
    mean_return = sum(daily_returns) / n
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / (n - 1)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return None

    annualised_return     = mean_return * TRADING_DAYS_PER_YEAR
    annualised_volatility = std_dev * math.sqrt(TRADING_DAYS_PER_YEAR)
    risk_free             = _get_risk_free_rate()

    return (annualised_return - risk_free) / annualised_volatility


# ---------------------------------------------------------------------------
# Dataclass for results
# ---------------------------------------------------------------------------

@dataclass
class HoldingPerformance:
    scheme_code:      int
    scheme_name:      str
    invested_amount:  float
    current_value:    float
    absolute_gain:    float
    gain_pct:         float
    xirr:             Optional[float]   # annualised, e.g. 0.142
    cagr:             Optional[float]   # annualised, e.g. 0.118
    sharpe:           Optional[float]
    latest_nav:       Optional[float]
    latest_nav_date:  Optional[date]
    nav_available:    bool              # False if no NAV data in DB


@dataclass
class PortfolioPerformance:
    total_invested:   float
    total_current:    float
    absolute_gain:    float
    gain_pct:         float
    xirr:             Optional[float]   # blended portfolio XIRR
    holdings:         list[HoldingPerformance]


# ---------------------------------------------------------------------------
# Main analytics function
# ---------------------------------------------------------------------------

def analyse_holding(
    holding: ClientHolding,
    scheme_name: str,
    start_date: Optional[date] = None,
) -> HoldingPerformance:
    """
    Compute full performance metrics for a single holding.

    Parameters
    ----------
    holding     : ClientHolding ORM row (or dataclass with same fields)
    scheme_name : display name for the fund
    start_date  : when the client started investing (defaults to 3 years ago)
    """
    if start_date is None:
        start_date = date.today().replace(year=date.today().year - 3)

    # Fetch NAV data
    nav_series   = get_nav_series(holding.scheme_code)
    latest       = get_latest_nav(holding.scheme_code)
    nav_available = bool(nav_series)

    # Current value: units × latest NAV, or fall back to invested_amount
    if latest:
        current_value = holding.units * latest[1]
        latest_nav     = latest[1]
        latest_nav_date = latest[0]
    else:
        current_value   = holding.invested_amount
        latest_nav      = None
        latest_nav_date = None

    absolute_gain = current_value - holding.invested_amount
    gain_pct      = (absolute_gain / holding.invested_amount * 100
                     if holding.invested_amount > 0 else 0.0)

    # XIRR
    cashflows = simulate_sip_cashflows(
        invested_amount=holding.invested_amount,
        current_value=current_value,
        start_date=start_date,
    )
    xirr = compute_xirr(cashflows)

    # CAGR
    cagr = compute_cagr(
        invested_amount=holding.invested_amount,
        current_value=current_value,
        start_date=start_date,
    )

    # Sharpe
    sharpe = compute_sharpe(nav_series, start_date=start_date)

    return HoldingPerformance(
        scheme_code=holding.scheme_code,
        scheme_name=scheme_name,
        invested_amount=holding.invested_amount,
        current_value=current_value,
        absolute_gain=absolute_gain,
        gain_pct=gain_pct,
        xirr=xirr,
        cagr=cagr,
        sharpe=sharpe,
        latest_nav=latest_nav,
        latest_nav_date=latest_nav_date,
        nav_available=nav_available,
    )


def analyse_portfolio(client_id: int) -> PortfolioPerformance:
    """
    Compute performance for all holdings of a client.
    Blends cashflows across all holdings for a portfolio-level XIRR.
    """
    with Session(engine) as session:
        holdings = (
            session.query(ClientHolding)
            .filter(ClientHolding.client_id == client_id)
            .all()
        )
        # Fetch scheme names
        from data.database import Fund
        scheme_names = {
            f.scheme_code: f.scheme_name
            for f in session.query(Fund).all()
        }

    start_date = date.today().replace(year=date.today().year - 3)

    holding_perfs: list[HoldingPerformance] = []
    all_cashflows: list[tuple[date, float]] = []

    for h in holdings:
        name = scheme_names.get(h.scheme_code, f"Scheme {h.scheme_code}")
        perf = analyse_holding(h, name, start_date)
        holding_perfs.append(perf)

        # Accumulate cashflows for blended portfolio XIRR
        cfs = simulate_sip_cashflows(
            h.invested_amount, perf.current_value, start_date
        )
        all_cashflows.extend(cfs)

    total_invested = sum(p.invested_amount for p in holding_perfs)
    total_current  = sum(p.current_value   for p in holding_perfs)
    absolute_gain  = total_current - total_invested
    gain_pct       = (absolute_gain / total_invested * 100
                      if total_invested > 0 else 0.0)

    # Sort and merge cashflows for blended XIRR
    all_cashflows.sort(key=lambda x: x[0])
    portfolio_xirr = compute_xirr(all_cashflows) if all_cashflows else None

    return PortfolioPerformance(
        total_invested=total_invested,
        total_current=total_current,
        absolute_gain=absolute_gain,
        gain_pct=gain_pct,
        xirr=portfolio_xirr,
        holdings=holding_perfs,
    )


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def format_performance(perf: PortfolioPerformance) -> str:
    lines = [
        f"  {'Fund':<50} {'Invested':>12}  {'Current':>12}  "
        f"{'Gain%':>7}  {'XIRR':>7}  {'CAGR':>7}  {'Sharpe':>7}",
        "  " + "-" * 110,
    ]
    for h in perf.holdings:
        xirr_str   = f"{h.xirr*100:>6.1f}%"   if h.xirr   is not None else "   N/A "
        cagr_str   = f"{h.cagr*100:>6.1f}%"   if h.cagr   is not None else "   N/A "
        sharpe_str = f"{h.sharpe:>6.2f} "      if h.sharpe is not None else "   N/A "
        nav_note   = "" if h.nav_available else " *"
        lines.append(
            f"  {(h.scheme_name + nav_note):<50} "
            f"₹{h.invested_amount:>10,.0f}  "
            f"₹{h.current_value:>10,.0f}  "
            f"{h.gain_pct:>6.1f}%  "
            f"{xirr_str}  {cagr_str}  {sharpe_str}"
        )
    lines += [
        "  " + "-" * 110,
        f"  {'PORTFOLIO TOTAL':<50} "
        f"₹{perf.total_invested:>10,.0f}  "
        f"₹{perf.total_current:>10,.0f}  "
        f"{perf.gain_pct:>6.1f}%  "
        f"{'N/A' if perf.xirr is None else f'{perf.xirr*100:.1f}%':>7}",
        "",
        "  * NAV data not in DB — run nav_fetcher for this scheme",
    ]
    return "\n".join(lines)
