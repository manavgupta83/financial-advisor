"""
test_phase3.py
--------------
Tests for Phase 3: Analytics Engine.

Tests:
  1. Performance engine — XIRR, CAGR, Sharpe, cashflow simulation
  2. Overlap engine     — pairwise overlap, overlap matrix
  3. Sector engine      — per-fund and portfolio sector allocation

Run:
  PYTHONPATH=/Users/manavgupta/financial_advisor python test_phase3.py
"""

import sys
import os
import traceback
from datetime import date, timedelta

sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

PASSED = []
FAILED = []

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def ok(msg):
    print(f"  ✓  {msg}")
    PASSED.append(msg)

def fail(msg, err=""):
    print(f"  ✗  {msg}")
    if err:
        for line in err.strip().splitlines()[-6:]:
            print(f"     {line}")
    FAILED.append(msg)


# ============================================================
# 1. Performance Engine — pure math (no DB needed)
# ============================================================
section("1. Performance Engine — pure calculations")

try:
    from engine.performance_engine import (
        simulate_sip_cashflows, compute_xirr, compute_cagr,
        compute_sharpe, _get_risk_free_rate,
    )
    ok("Imported performance_engine")

    # Risk-free rate
    rfr = _get_risk_free_rate()
    assert 0.04 <= rfr <= 0.10, f"Unexpected risk-free rate: {rfr}"
    ok(f"Risk-free rate: {rfr*100:.1f}%")

    # --- simulate_sip_cashflows ---
    start = date(2022, 1, 1)
    end   = date(2024, 12, 1)
    cfs   = simulate_sip_cashflows(120_000, 150_000, start, end)
    assert any(cf > 0 for _, cf in cfs),  "No positive cashflow (inflow)"
    assert any(cf < 0 for _, cf in cfs),  "No negative cashflow (outflow)"
    assert cfs[-1][1] == 150_000,         "Last cashflow should be current value"
    outflows = sum(-cf for _, cf in cfs if cf < 0)
    assert abs(outflows - 120_000) < 1,   f"Outflows don't sum to invested: {outflows}"
    ok(f"simulate_sip_cashflows: {len(cfs)} cashflows, outflows sum = ₹{outflows:,.0f}")

    # --- compute_xirr ---
    # Simple known case: invest 1000/month for 12 months, get back 13000 → positive XIRR
    base = date(2023, 1, 1)
    known_cfs = [(date(2023, m, 1), -1000.0) for m in range(1, 13)]
    known_cfs.append((date(2023, 12, 31), 13_000.0))
    xirr = compute_xirr(known_cfs)
    assert xirr is not None,          "XIRR returned None for valid cashflows"
    assert xirr > 0,                  f"XIRR should be positive, got {xirr}"
    ok(f"compute_xirr: {xirr*100:.1f}% for 12-month SIP with gain")

    # XIRR with loss
    loss_cfs = [(date(2023, m, 1), -1000.0) for m in range(1, 13)]
    loss_cfs.append((date(2023, 12, 31), 9_000.0))
    xirr_loss = compute_xirr(loss_cfs)
    assert xirr_loss is not None and xirr_loss < 0
    ok(f"compute_xirr: {xirr_loss*100:.1f}% for 12-month SIP with loss")

    # XIRR None for all-negative cashflows
    bad_cfs = [(date(2023, m, 1), -1000.0) for m in range(1, 13)]
    assert compute_xirr(bad_cfs) is None
    ok("compute_xirr returns None for all-negative cashflows")

    # --- compute_cagr ---
    cagr = compute_cagr(100_000, 161_000, date(2020, 1, 1), date(2025, 1, 1))
    assert cagr is not None
    assert 0.09 < cagr < 0.11, f"Expected ~10% CAGR, got {cagr*100:.1f}%"
    ok(f"compute_cagr: {cagr*100:.1f}% over 5 years (expected ~10%)")

    assert compute_cagr(0, 100_000, date(2020,1,1)) is None
    ok("compute_cagr returns None for zero invested")

    # --- compute_sharpe ---
    # Simulate a rising NAV series (positive Sharpe)
    import math, random
    random.seed(42)
    nav_series = []
    nav = 10.0
    d   = date(2022, 1, 1)
    for _ in range(500):
        nav *= (1 + random.gauss(0.0004, 0.008))   # slight positive drift
        nav_series.append((d, nav))
        d += timedelta(days=1)

    sharpe = compute_sharpe(nav_series)
    assert sharpe is not None,   "Sharpe returned None for valid NAV series"
    ok(f"compute_sharpe: {sharpe:.2f} for simulated positive-drift NAV")

    # Too few data points → None
    assert compute_sharpe(nav_series[:10]) is None
    ok("compute_sharpe returns None for < 30 data points")

except Exception as e:
    fail("Performance engine calculations", traceback.format_exc())


# ============================================================
# 2. Performance Engine — DB integration
# ============================================================
section("2. Performance Engine — DB integration")

try:
    from engine.performance_engine import (
        get_nav_series, get_latest_nav, get_nav_on_or_before,
        analyse_portfolio, format_performance,
    )
    ok("Imported DB-dependent performance functions")

    # get_nav_series — should return list even if empty (no crash)
    series = get_nav_series(999999)   # non-existent scheme
    assert isinstance(series, list)
    ok(f"get_nav_series on unknown scheme returns empty list")

    # get_latest_nav — returns None for unknown scheme
    latest = get_latest_nav(999999)
    assert latest is None
    ok("get_latest_nav on unknown scheme returns None")

    # get_nav_on_or_before
    test_series = [
        (date(2024, 1, 1), 100.0),
        (date(2024, 3, 1), 110.0),
        (date(2024, 6, 1), 120.0),
    ]
    assert get_nav_on_or_before(test_series, date(2024, 2, 1)) == 100.0
    assert get_nav_on_or_before(test_series, date(2024, 3, 1)) == 110.0
    assert get_nav_on_or_before(test_series, date(2023, 1, 1)) is None
    ok("get_nav_on_or_before binary search works correctly")

    # analyse_portfolio — use client_id=1 if it exists, else skip gracefully
    from data.client_manager import list_clients
    clients = list_clients()
    if clients:
        client_id = clients[0].id
        perf = analyse_portfolio(client_id)
        assert isinstance(perf.total_invested, float)
        assert isinstance(perf.holdings, list)
        ok(f"analyse_portfolio: client {client_id} — "
           f"₹{perf.total_invested:,.0f} invested, {len(perf.holdings)} holdings")
        if perf.holdings:
            fmt = format_performance(perf)
            assert "₹" in fmt
            ok("format_performance returned valid output")
            print()
            print(fmt)
    else:
        ok("No clients in DB — skipping live analyse_portfolio test")

except Exception as e:
    fail("Performance engine DB integration", traceback.format_exc())


# ============================================================
# 3. Overlap Engine
# ============================================================
section("3. Overlap Engine")

try:
    from engine.overlap_engine import (
        compute_overlap, compute_overlap_matrix,
        format_overlap, format_overlap_matrix,
    )
    ok("Imported overlap_engine")

    # Two schemes with no holdings → should return gracefully with warning
    ov = compute_overlap(999991, 999992)
    assert ov.overlap_pct == 0.0
    assert ov.warning is not None
    ok("compute_overlap with no holdings returns 0% with warning")

    # Overlap matrix on non-existent schemes
    om = compute_overlap_matrix([999991, 999992, 999993])
    assert len(om.details) == 3    # C(3,2) = 3 pairs
    assert len(om.matrix)  == 6    # symmetric: 3 pairs × 2 directions
    ok(f"compute_overlap_matrix: {len(om.details)} pairs computed")

    # format_overlap doesn't crash
    fmt = format_overlap(ov)
    assert "Overlap" in fmt
    ok("format_overlap returned valid string")

    # format_overlap_matrix doesn't crash
    fmt_m = format_overlap_matrix(om)
    assert "Overlap" in fmt_m
    ok("format_overlap_matrix returned valid string")

    # Live test: if PPFAS holdings are in DB, test real overlap
    from data.database import engine as db_engine, FundHolding
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        codes_with_holdings = [
            r[0] for r in
            s.query(FundHolding.scheme_code).distinct().limit(5).all()
        ]

    if len(codes_with_holdings) >= 2:
        a, b = codes_with_holdings[0], codes_with_holdings[1]
        ov_live = compute_overlap(a, b)
        assert isinstance(ov_live.overlap_pct, float)
        ok(f"Live overlap {a} vs {b}: {ov_live.overlap_pct:.1f}% "
           f"({len(ov_live.common_stocks)} common stocks)")
        print()
        print(format_overlap(ov_live))
    else:
        ok("< 2 funds with holdings in DB — skipping live overlap test")

except Exception as e:
    fail("Overlap engine", traceback.format_exc())


# ============================================================
# 4. Sector Engine
# ============================================================
section("4. Sector Engine")

try:
    from engine.sector_engine import (
        analyse_fund_sectors, analyse_portfolio_sectors,
        format_sector_allocation, format_fund_sector_breakdown,
    )
    ok("Imported sector_engine")

    # analyse_fund_sectors on unknown scheme — should not crash
    bd = analyse_fund_sectors(999999, 100_000, 100_000)
    assert bd.scheme_code == 999999
    assert bd.unmapped_pct == 100.0
    ok("analyse_fund_sectors on unknown scheme returns 100% unmapped")

    # analyse_portfolio_sectors on unknown client
    alloc = analyse_portfolio_sectors(client_id=999999)
    assert alloc.total_invested == 0
    assert len(alloc.warnings) > 0
    ok("analyse_portfolio_sectors on unknown client returns warning")

    # Live test: if holdings in DB, run real sector analysis
    from data.database import engine as db_engine, FundHolding
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        codes = [r[0] for r in s.query(FundHolding.scheme_code).distinct().limit(3).all()]

    if codes:
        bd_live = analyse_fund_sectors(codes[0], 500_000, 1_000_000)
        assert isinstance(bd_live.sectors, list)
        ok(f"Live fund sectors for {codes[0]}: "
           f"{len(bd_live.sectors)} sectors, {bd_live.unmapped_pct:.1f}% unmapped")
        print()
        print(format_fund_sector_breakdown(bd_live))
    else:
        ok("No holdings in DB — skipping live sector test")

    # Portfolio sector analysis on first real client
    from data.client_manager import list_clients
    clients = list_clients()
    if clients:
        alloc_live = analyse_portfolio_sectors(clients[0].id)
        assert isinstance(alloc_live.sector_summary, list)
        ok(f"Live portfolio sectors: {len(alloc_live.sector_summary)} sectors, "
           f"{alloc_live.unmapped_pct:.1f}% unmapped")
        print()
        print(format_sector_allocation(alloc_live))
    else:
        ok("No clients in DB — skipping live portfolio sector test")

except Exception as e:
    fail("Sector engine", traceback.format_exc())


# ============================================================
# Summary
# ============================================================
section("SUMMARY")
total = len(PASSED) + len(FAILED)
print(f"\n  Passed : {len(PASSED)}/{total}")
print(f"  Failed : {len(FAILED)}/{total}")
if FAILED:
    print("\n  Failed tests:")
    for f in FAILED:
        print(f"    ✗ {f}")
    sys.exit(1)
else:
    print("\n  All tests passed. Phase 3 is solid. ✓")
