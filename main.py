"""
main.py
--------
Entry point for the AI Financial Advisory Tool.

Phases covered in this demo:
  Phase 2 — Client onboarding, risk profiling, goal planning, fund recommendations
  Phase 3 — Performance metrics (XIRR, CAGR, Sharpe), overlap analysis, sector allocation
  Phase 4 — Portfolio optimisation (max Sharpe / min variance) + Claude AI advisor

Run:
  PYTHONPATH=/Users/manavgupta/financial_advisor python main.py
"""

import sys
import os

sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

from datetime import date

from config.settings import DATABASE_PATH
from data.database import init_db

from data.client_manager import (
    create_client, get_client_by_email, delete_client,
    update_client_risk_profile, add_goal, get_goals_for_client,
    update_goal_sip, add_holding, get_portfolio_summary,
)

from engine.risk_engine import (
    QUESTIONNAIRE, compute_risk_profile, describe_profile
)
from engine.goal_engine import (
    GoalType, GoalInput, plan_all_goals, format_goal_plan
)
from engine.recommendation_engine import (
    recommend_all_goals, format_recommendation
)

# Phase 3
from engine.performance_engine import (
    compute_cagr, compute_sharpe,
    analyse_holding, analyse_portfolio, format_performance,
)
from engine.overlap_engine import (
    compute_overlap_matrix, format_overlap_matrix,
)
from engine.sector_engine import (
    analyse_portfolio_sectors, format_sector_allocation,
)

# Phase 4
from engine.optimiser_engine import (
    FundStats, OptimiserConstraints,
    optimise_max_sharpe, optimise_min_variance,
)
from ai.claude_advisor import (
    explain_portfolio_optimisation,
    stream_advisory_narrative,
)


# ---------------------------------------------------------------------------
# Demo: pre-filled questionnaire answers (0-based option indices)
# Represents a 35-year-old software engineer: Moderate-Aggressive profile
# ---------------------------------------------------------------------------
DEMO_RESPONSES = {
    1: 3,   # Long-term capital growth
    2: 3,   # 5-10 year horizon
    3: 3,   # Buy more on dip
    4: 2,   # 10-20% savings rate
    5: 3,   # Stable salaried
    6: 2,   # 3-6 months emergency fund
    7: 2,   # Moderate mutual fund experience
    8: 3,   # Light debt (home loan only)
    9: 3,   # Accepts large swings
    10: 2,  # ELSS + NPS + some equity
}

DEMO_CLIENT = {
    "name":           "Arjun Mehta",
    "email":          "arjun.mehta@demo.advisor",
    "phone":          "9876543210",
    "age":            35,
    "annual_income":  2_400_000,   # ₹24 LPA
    "dependants":     2,
    "pan":            "ARJPM1234H",
}

DEMO_GOALS = [
    GoalInput(
        goal_type=GoalType.RETIREMENT,
        name="Retirement Corpus",
        target_amount_today=0,
        years_to_goal=25,
        monthly_expense_at_goal=120_000,
    ),
    GoalInput(
        goal_type=GoalType.EDUCATION,
        name="Daughter's Higher Education",
        target_amount_today=3_000_000,
        years_to_goal=13,
        existing_investment=200_000,
    ),
    GoalInput(
        goal_type=GoalType.EMERGENCY,
        name="Emergency Fund",
        target_amount_today=720_000,
        years_to_goal=1,
        inflation_rate=0.0,
    ),
    GoalInput(
        goal_type=GoalType.HOUSE,
        name="House Down Payment",
        target_amount_today=2_500_000,
        years_to_goal=5,
        existing_investment=500_000,
    ),
]

# ---------------------------------------------------------------------------
# Sample funds for Phase 3 overlap + sector demo
# ---------------------------------------------------------------------------

DEMO_FUND_HOLDINGS = {
    119598: {
        "HDFC Bank":        0.0794,
        "Infosys":          0.0612,
        "Bajaj Holdings":   0.0501,
        "Alphabet Inc":     0.0489,
        "Microsoft Corp":   0.0423,
        "Coal India":       0.0380,
        "ITC Ltd":          0.0340,
        "Power Grid":       0.0310,
        "Maruti Suzuki":    0.0290,
        "Others":           0.3861,
    },
    120503: {
        "HDFC Bank":        0.0920,
        "Infosys":          0.0780,
        "Reliance Ind":     0.0650,
        "TCS":              0.0580,
        "ICICI Bank":       0.0520,
        "Maruti Suzuki":    0.0310,
        "L&T":              0.0290,
        "Axis Bank":        0.0260,
        "Sun Pharma":       0.0240,
        "Others":           0.3450,
    },
}
# ---------------------------------------------------------------------------
# Sample funds for Phase 4 optimiser demo
# ---------------------------------------------------------------------------
DEMO_FUNDS = [
    FundStats(119598, "Parag Parikh Flexi Cap",         0.14, 0.17),
    FundStats(120503, "Mirae Asset Large Cap",           0.12, 0.15),
    FundStats(120505, "Axis Small Cap",                 0.16, 0.22),
    FundStats(120465, "HDFC Mid-Cap Opportunities",     0.15, 0.20),
    FundStats(119364, "ICICI Pru Balanced Advantage",   0.10, 0.10),
    FundStats(119551, "Kotak Gilt Fund",                0.07, 0.05),
]


def divider(char="─", width=65):
    print(char * width)


def section_header(title: str):
    divider("═")
    print(f"  {title}")
    divider("═")


def run_demo():
    print()
    section_header("AI FINANCIAL ADVISORY TOOL  —  Phase 2 + 3 + 4 Demo")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 2: Client onboarding, risk profiling, goal planning
    # ──────────────────────────────────────────────────────────────────

    # 1. Init DB
    print("\n[1/5] Initialising database …")
    init_db()
    print(f"      DB path: {DATABASE_PATH}")

    # 2. Create client
    print("\n[2/5] Creating demo client …")
    existing = get_client_by_email(DEMO_CLIENT["email"])
    if existing:
        delete_client(existing.id)
        print("      (Previous demo client cleared)")

    client = create_client(**DEMO_CLIENT)
    print(f"      Created: {client.name}  |  Age: {client.age}  |"
          f"  Income: ₹{client.annual_income:,.0f} p.a.  |"
          f"  Dependants: {client.dependants}")

    # 3. Risk questionnaire
    print("\n[3/5] Running risk questionnaire …")
    for q in QUESTIONNAIRE:
        idx = DEMO_RESPONSES[q["id"]]
        chosen = q["options"][idx]["text"]
        print(f"      Q{q['id']:02d}: {chosen[:65]}")

    profile = compute_risk_profile(
        responses=DEMO_RESPONSES,
        age=client.age,
        annual_income=client.annual_income,
        dependants=client.dependants,
    )
    update_client_risk_profile(client.id, profile.category.value, profile.adjusted_score)

    print()
    divider()
    print(describe_profile(profile))
    divider()

    # 4. Goal planning
    print("\n[4/5] Planning goals …")
    plans = plan_all_goals(
        goals=DEMO_GOALS,
        risk_profile=profile.category.value,
        monthly_income=client.monthly_income,
    )

    total_sip = sum(p.adjusted_sip for p in plans)

    for plan in plans:
        years_to_goal = plan.input.years_to_goal
        target_year   = date.today().year + years_to_goal
        add_goal(
            client_id=client.id,
            goal_name=plan.input.name,
            goal_type=plan.input.goal_type.value,
            target_amount=plan.future_value,
            target_year=target_year,
            current_savings=plan.input.existing_investment,
            monthly_sip=plan.adjusted_sip,
            priority=1,
        )
        print()
        print(format_goal_plan(plan))
        divider()

    print(f"\n  Combined Monthly SIP Needed : ₹{total_sip:,.0f}")
    print(f"  As % of Monthly Income      : {total_sip / client.monthly_income * 100:.1f}%")

    # 5. Fund recommendations
    print("\n[5/5] Generating fund recommendations …")
    recommendations = recommend_all_goals(
        plans=plans,
        risk_profile=profile.category.value,
        db_path=DATABASE_PATH,
    )

    for rec in recommendations:
        print()
        section_header(f"RECOMMENDATION  ›  {rec.goal_name.upper()}")
        print(format_recommendation(rec))

    # 6. Portfolio snapshot
    print()
    section_header("SAMPLE PORTFOLIO SNAPSHOT")
    add_holding(
        client_id=client.id,
        scheme_code=119598,
        scheme_name="Parag Parikh Flexi Cap Fund - Direct Growth",
        units=1200.0,
        avg_nav=55.00,
        invested_amount=660_000,
        current_value=750_000,
    )
    add_holding(
        client_id=client.id,
        scheme_code=120503,
        scheme_name="Mirae Asset Large Cap Fund - Direct Growth",
        units=800.0,
        avg_nav=75.00,
        invested_amount=600_000,
        current_value=640_000,
    )

    summary = get_portfolio_summary(client.id)
    print(f"  Holdings        : {summary['num_holdings']}")
    print(f"  Total Invested  : ₹{summary['total_invested']:>14,.0f}")
    print(f"  Current Value   : ₹{summary['total_current']:>14,.0f}")
    print(f"  Absolute Gain   : ₹{summary['absolute_gain']:>14,.0f}")
    print(f"  Gain %          : {summary['gain_percentage']:.2f}%")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 3: Performance metrics, overlap, sector allocation
    # ──────────────────────────────────────────────────────────────────

    section_header("PHASE 3  —  PERFORMANCE METRICS")

    print()
    try:
        portfolio_perf = analyse_portfolio(client.id)
        print(format_performance(portfolio_perf))
    except Exception as exc:
        # Fallback: manual CAGR + Sharpe if NAV history not populated
        print(f"  (Full XIRR analysis skipped — NAV history needed: {exc})")
        print()
        holdings_list = summary.get("holdings", [])
        for h in holdings_list:
            cagr = compute_cagr(
                invested=h["invested_amount"],
                current=h["current_value"],
                years=3.0,
            )
            sharpe = compute_sharpe(
                annual_return=cagr,
                annual_volatility=0.17,
            )
            print(f"  {h['scheme_name'][:50]}")
            print(f"    CAGR (3yr)  : {cagr:.2%}")
            print(f"    Sharpe      : {sharpe:.2f}  (vol assumed 17%)")
            print()

    section_header("PHASE 3  —  OVERLAP ANALYSIS")

    overlap_matrix = compute_overlap_matrix(list(DEMO_FUND_HOLDINGS.keys()))
    print()
    print(format_overlap_matrix(overlap_matrix))

    section_header("PHASE 3  —  SECTOR ALLOCATION")

    try:
        sector_alloc = analyse_portfolio_sectors(client.id)
        print()
        print(format_sector_allocation(sector_alloc))
    except Exception as exc:
        print(f"  (Sector analysis skipped — holdings data needed: {exc})")
        print()


    # ──────────────────────────────────────────────────────────────────
    # PHASE 4: Optimiser + Claude AI advisor
    # ──────────────────────────────────────────────────────────────────

    section_header("PHASE 4  —  PORTFOLIO OPTIMISER")

    print("\n  Running Max Sharpe optimisation …")
    constraints = OptimiserConstraints(
        min_funds=3,
        max_funds=5,
        min_weight=0.05,
        max_weight=0.40,
    )
    opt_result = optimise_max_sharpe(DEMO_FUNDS, constraints=constraints)
    print()
    print(opt_result.summary())

    print()
    print("  Running Min Variance optimisation …")
    opt_minvar = optimise_min_variance(DEMO_FUNDS, constraints=constraints)
    print()
    print(opt_minvar.summary())

    section_header("PHASE 4  —  CLAUDE OPTIMISATION EXPLAINER")

    goal_names = [g.name for g in DEMO_GOALS]
    explanation = explain_portfolio_optimisation(
        opt_result,
        risk_profile=profile.category.value,
        goal_names=goal_names,
    )
    print()
    print(explanation)

    section_header("PHASE 4  —  CLAUDE ADVISORY NARRATIVE (streaming)")

    client_data = {
        "name":           client.name,
        "age":            client.age,
        "annual_income":  client.annual_income,
        "monthly_income": client.monthly_income,
        "dependants":     client.dependants,
        "risk_profile":   profile.category.value,
        "risk_score":     profile.adjusted_score,
    }

    goals_data = [
        {
            "name":          plan.input.name,
            "goal_type":     plan.input.goal_type.value,
            "target_amount": plan.input.target_amount_today,
            "future_value":  plan.future_value,
            "years_to_goal": plan.input.years_to_goal,
            "adjusted_sip":  plan.adjusted_sip,
        }
        for plan in plans
    ]

    print()
    for chunk in stream_advisory_narrative(
        client_data, goals_data, summary, opt_result
    ):
        print(chunk, end="", flush=True)
    print()

    divider("═")
    print("\n  Phases 2 + 3 + 4 complete. All engines operational.\n")
    print("  Next → Phase 5: Streamlit Advisor UI\n")
    divider("═")


if __name__ == "__main__":
    run_demo()
