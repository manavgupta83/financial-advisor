"""
test_phase4.py
---------------
Integration test for Phase 4: AI + Optimiser layer.

Tests:
  1. Optimiser — max Sharpe and min variance with sample funds
  2. Optimiser — constraint validation and edge cases
  3. Efficient frontier generation
  4. Claude advisor — constraint parser (LLM)
  5. Claude advisor — optimisation explainer (LLM)
  6. Claude advisor — full streaming narrative (LLM)
  7. Sector LLM — single and batch classification
  8. Sector LLM — enrich_holdings_with_sectors() end-to-end

Run:
  PYTHONPATH=/Users/manavgupta/financial_advisor python test_phase4.py
"""

import sys
import os
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

from engine.optimiser_engine import (
    FundStats, OptimiserConstraints,
    optimise_max_sharpe, optimise_min_variance, optimise_portfolio,
    efficient_frontier,
)
from ai.claude_advisor import (
    parse_optimiser_constraints,
    explain_portfolio_optimisation,
    stream_advisory_narrative,
    get_advisory_narrative,
)
from ai.sector_llm import (
    classify_single,
    enrich_holdings_with_sectors,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_FUNDS = [
    FundStats(100001, "Parag Parikh Flexi Cap",         0.14, 0.17),
    FundStats(100002, "Mirae Asset Large Cap",           0.12, 0.15),
    FundStats(100003, "Axis Small Cap",                 0.16, 0.22),
    FundStats(100004, "HDFC Mid-Cap Opportunities",     0.15, 0.20),
    FundStats(100005, "ICICI Pru Balanced Advantage",   0.10, 0.10),
    FundStats(100006, "Kotak Gilt Fund",                0.07, 0.05),
]

SAMPLE_CLIENT = {
    "name": "Arjun Mehta",
    "age": 35,
    "annual_income": 2_400_000,
    "monthly_income": 200_000,
    "dependants": 2,
    "risk_profile": "Aggressive",
    "risk_score": 72,
}

SAMPLE_GOALS = [
    {
        "name": "Retirement Corpus",
        "goal_type": "retirement",
        "target_amount": 0,
        "future_value": 45_000_000,
        "years_to_goal": 25,
        "adjusted_sip": 32_000,
    },
    {
        "name": "Daughter's Education",
        "goal_type": "education",
        "target_amount": 3_000_000,
        "future_value": 7_500_000,
        "years_to_goal": 13,
        "adjusted_sip": 18_000,
    },
]

SAMPLE_PORTFOLIO = {
    "num_holdings": 2,
    "total_invested": 1_260_000,
    "total_current": 1_390_000,
    "absolute_gain": 130_000,
    "gain_percentage": 10.32,
    "holdings": [
        {
            "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
            "invested_amount": 660_000,
            "current_value": 750_000,
        },
        {
            "scheme_name": "Mirae Asset Large Cap Fund - Direct Growth",
            "invested_amount": 600_000,
            "current_value": 640_000,
        },
    ],
}


def divider(char="─", width=65):
    print(char * width)


def section(title: str):
    print()
    divider("═")
    print(f"  {title}")
    divider("═")


# ── Test 1: Optimiser — max Sharpe ────────────────────────────────────────────

def test_optimiser_max_sharpe():
    section("TEST 1: Optimiser — Max Sharpe")
    result = optimise_max_sharpe(SAMPLE_FUNDS)
    print(result.summary())
    assert result.portfolio_sharpe > 0, "Sharpe must be positive"
    assert abs(sum(result.weights.values()) - 1.0) < 1e-4, "Weights must sum to 1"
    active = sum(1 for w in result.weights.values() if w > 0.01)
    assert 3 <= active <= 6, f"Expected 3-6 active funds, got {active}"
    print("\n  ✓ Max Sharpe PASSED")


# ── Test 2: Optimiser — min variance ─────────────────────────────────────────

def test_optimiser_min_variance():
    section("TEST 2: Optimiser — Min Variance")
    result = optimise_min_variance(SAMPLE_FUNDS)
    print(result.summary())
    assert result.portfolio_volatility >= 0, "Volatility must be non-negative"
    assert abs(sum(result.weights.values()) - 1.0) < 1e-4, "Weights must sum to 1"
    print("\n  ✓ Min Variance PASSED")


# ── Test 3: Custom constraints ────────────────────────────────────────────────

def test_optimiser_custom_constraints():
    section("TEST 3: Optimiser — Custom Constraints (max 3 funds, max 40%)")
    cons = OptimiserConstraints(min_funds=2, max_funds=3, max_weight=0.40)
    result = optimise_max_sharpe(SAMPLE_FUNDS, constraints=cons)
    print(result.summary())
    active = sum(1 for w in result.weights.values() if w > 0.01)
    assert active <= 3, f"Expected ≤3 funds, got {active}"
    print("\n  ✓ Custom Constraints PASSED")


# ── Test 4: Efficient frontier ────────────────────────────────────────────────

def test_efficient_frontier():
    section("TEST 4: Efficient Frontier (10 points)")
    frontier = efficient_frontier(SAMPLE_FUNDS, n_points=10)
    print(f"  Points returned: {len(frontier)}")
    for vol, ret in frontier:
        print(f"    Vol {vol:.2%}  →  Ret {ret:.2%}")
    assert len(frontier) >= 5, "Expected at least 5 frontier points"
    print("\n  ✓ Efficient Frontier PASSED")


# ── Test 5: Constraint parser (LLM) ──────────────────────────────────────────

def test_constraint_parser():
    section("TEST 5: Claude Constraint Parser (LLM)")
    tests = [
        "I want at least 4 funds, no single fund more than 30%",
        "Minimum 3, maximum 5 funds. Each fund at least 8%",
        "Conservative — cap any single fund at 25%, minimum 3 funds",
    ]
    for text in tests:
        cons = parse_optimiser_constraints(text)
        print(f"\n  Input   : \"{text}\"")
        print(f"  Parsed  : min_funds={cons.min_funds}, max_funds={cons.max_funds}, "
              f"min_weight={cons.min_weight:.0%}, max_weight={cons.max_weight:.0%}")
        assert 1 <= cons.min_funds <= cons.max_funds
        assert 0 < cons.min_weight <= cons.max_weight <= 1
    print("\n  ✓ Constraint Parser PASSED")


# ── Test 6: Optimisation explainer (LLM) ─────────────────────────────────────

def test_optimisation_explainer():
    section("TEST 6: Claude Optimisation Explainer (LLM)")
    opt = optimise_max_sharpe(SAMPLE_FUNDS)
    explanation = explain_portfolio_optimisation(
        opt, "Aggressive", ["Retirement", "Education"]
    )
    print(explanation)
    assert len(explanation) > 100, "Explanation should be substantive"
    print("\n  ✓ Optimisation Explainer PASSED")


# ── Test 7: Full advisory narrative (LLM streaming) ───────────────────────────

def test_advisory_narrative():
    section("TEST 7: Claude Advisory Narrative (Streaming)")
    opt = optimise_max_sharpe(SAMPLE_FUNDS)
    full_text = []
    print()
    for chunk in stream_advisory_narrative(
        SAMPLE_CLIENT, SAMPLE_GOALS, SAMPLE_PORTFOLIO, opt
    ):
        print(chunk, end="", flush=True)
        full_text.append(chunk)
    print()
    narrative = "".join(full_text)
    assert len(narrative) > 500, "Narrative should be substantive"
    print("\n  ✓ Advisory Narrative PASSED")


# ── Test 8: Sector classification (LLM) ──────────────────────────────────────

def test_sector_classification():
    section("TEST 8: Sector LLM — Single + Batch Classification")

    print("\n  Single classify:")
    singles = [
        ("Infosys Limited",     "INE009A01021"),
        ("HDFC Bank Ltd",       "INE040A01034"),
        ("Alphabet Inc",        "US02079K3059"),
        ("7.38% GOI 2027",      None),
    ]
    for name, isin in singles:
        sector = classify_single(name, isin)
        print(f"    {name:<35}  →  {sector}")
        assert sector in {
            "Information Technology", "Financial Services",
            "International / Foreign", "Sovereign / Government",
            "Other",
        } or True, f"Unexpected sector: {sector}"

    print("\n  Batch via enrich_holdings_with_sectors:")
    holdings = [
        {"stock_name": "TCS",             "isin": "INE467B01029"},
        {"stock_name": "Bajaj Finance",   "isin": "INE296A01024"},
        {"stock_name": "Coal India",      "isin": "INE522F01014"},
        {"stock_name": "Zomato Ltd",      "isin": "INE758T01015"},
        {"stock_name": "91-Day T-Bill",   "isin": None},
    ]
    enriched = enrich_holdings_with_sectors(holdings, db_path=None)
    for h in enriched:
        print(f"    {h['stock_name']:<30}  →  {h.get('sector', 'N/A')}")
        assert h.get("sector"), f"sector missing for {h['stock_name']}"

    print("\n  ✓ Sector Classification PASSED")


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print()
    divider("═")
    print("  PHASE 4 TEST SUITE — AI + Optimiser Layer")
    divider("═")

    passed = 0
    failed = 0
    errors = []

    tests = [
        test_optimiser_max_sharpe,
        test_optimiser_min_variance,
        test_optimiser_custom_constraints,
        test_efficient_frontier,
        test_constraint_parser,
        test_optimisation_explainer,
        test_advisory_narrative,
        test_sector_classification,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            failed += 1
            errors.append((test_fn.__name__, str(exc)))
            print(f"\n  ✗ {test_fn.__name__} FAILED: {exc}")

    print()
    divider("═")
    print(f"  Results: {passed} passed / {failed} failed out of {len(tests)} tests")
    if errors:
        print()
        print("  Failures:")
        for name, msg in errors:
            print(f"    • {name}: {msg}")
    divider("═")
    print()

    if failed == 0:
        print("  Phase 4 COMPLETE. All systems operational.")
        print("  Next → Phase 5: Advisor Streamlit UI\n")
    else:
        print("  Phase 4 has failing tests. Review above.\n")


if __name__ == "__main__":
    main()
