"""
main.py
--------
Entry point for the AI Financial Advisory Tool -- CLI demo runner.

Phase 2 CLI demo:
  - Demonstrates a complete client onboarding flow end-to-end:
      1. Create a sample client
      2. Run the risk questionnaire (auto-answered for demo)
      3. Define four goals (Retirement, Education, Emergency, House)
      4. Plan each goal (SIP + FV)
      5. Generate fund recommendations per goal
      6. Print a full advisory report to stdout

Phase 6 note:
  The full platform is now served via the FastAPI backend:
    PYTHONPATH=/Users/manavgupta/financial_advisor uvicorn api.main:app --reload
  This file remains as a local smoke-test / CLI demo only.
  All engine logic is unchanged.

Run CLI demo:
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


DEMO_RESPONSES = {
    1: 3, 2: 3, 3: 3, 4: 2, 5: 3, 6: 2, 7: 2, 8: 3, 9: 3, 10: 2,
}

DEMO_CLIENT = {
    "name":           "Arjun Mehta",
    "email":          "arjun.mehta@demo.advisor",
    "phone":          "9876543210",
    "age":            35,
    "annual_income":  2_400_000,
    "dependants":     2,
    "pan":            "ARJPM1234H",
}

DEMO_GOALS = [
    GoalInput(goal_type=GoalType.RETIREMENT, name="Retirement Corpus",
              target_amount_today=0, years_to_goal=25, monthly_expense_at_goal=120_000),
    GoalInput(goal_type=GoalType.EDUCATION, name="Daughter's Higher Education",
              target_amount_today=3_000_000, years_to_goal=13, existing_investment=200_000),
    GoalInput(goal_type=GoalType.EMERGENCY, name="Emergency Fund",
              target_amount_today=720_000, years_to_goal=1, inflation_rate=0.0),
    GoalInput(goal_type=GoalType.HOUSE, name="House Down Payment",
              target_amount_today=2_500_000, years_to_goal=5, existing_investment=500_000),
]


def divider(char="-", width=65):
    print(char * width)


def section_header(title: str):
    divider("=")
    print(f"  {title}")
    divider("=")


def run_demo():
    print()
    section_header("AI FINANCIAL ADVISORY TOOL  --  Phase 2 Demo (CLI)")

    print("\n[1/5] Initialising database ...")
    init_db()
    print(f"      DB path: {DATABASE_PATH}")

    print("\n[2/5] Creating demo client ...")
    existing = get_client_by_email(DEMO_CLIENT["email"])
    if existing:
        delete_client(existing.id)
        print("      (Previous demo client cleared)")

    client = create_client(**DEMO_CLIENT)
    print(f"      Created: {client.name}  |  Age: {client.age}  |"
          f"  Income: Rs {client.annual_income:,.0f} p.a.  |"
          f"  Dependants: {client.dependants}")

    print("\n[3/5] Running risk questionnaire ...")
    for q in QUESTIONNAIRE:
        idx = DEMO_RESPONSES[q["id"]]
        chosen = q["options"][idx]["text"]
        print(f"      Q{q['id']:02d}: {chosen[:65]}")

    profile = compute_risk_profile(
        responses=DEMO_RESPONSES, age=client.age,
        annual_income=client.annual_income, dependants=client.dependants,
    )
    update_client_risk_profile(client.id, profile.category.value, profile.adjusted_score)
    print()
    divider()
    print(describe_profile(profile))
    divider()

    print("\n[4/5] Planning goals ...")
    plans = plan_all_goals(goals=DEMO_GOALS, risk_profile=profile.category.value,
                           monthly_income=client.monthly_income)
    total_sip = sum(p.adjusted_sip for p in plans)

    for plan in plans:
        years_to_goal = plan.input.years_to_goal
        target_year = date.today().year + years_to_goal
        add_goal(
            client_id=client.id, goal_name=plan.input.name,
            goal_type=plan.input.goal_type.value, target_amount=plan.future_value,
            target_year=target_year, current_savings=plan.input.existing_investment,
            monthly_sip=plan.adjusted_sip, priority=1,
        )
        print()
        print(format_goal_plan(plan))
        divider()

    print(f"\n  Combined Monthly SIP Needed : Rs {total_sip:,.0f}")
    print(f"  As % of Monthly Income      : {total_sip / client.monthly_income * 100:.1f}%")

    print("\n[5/5] Generating fund recommendations ...")
    recommendations = recommend_all_goals(plans=plans, risk_profile=profile.category.value, db_path=DATABASE_PATH)
    for rec in recommendations:
        print()
        section_header(f"RECOMMENDATION  >  {rec.goal_name.upper()}")
        print(format_recommendation(rec))

    print()
    section_header("SAMPLE PORTFOLIO SNAPSHOT")
    add_holding(client_id=client.id, scheme_code=119598,
                scheme_name="Parag Parikh Flexi Cap Fund - Direct Growth",
                units=1200.0, avg_nav=55.00, invested_amount=660_000, current_value=750_000)
    add_holding(client_id=client.id, scheme_code=120503,
                scheme_name="Mirae Asset Large Cap Fund - Direct Growth",
                units=800.0, avg_nav=75.00, invested_amount=600_000, current_value=640_000)

    summary = get_portfolio_summary(client.id)
    print(f"  Holdings        : {summary['num_holdings']}")
    print(f"  Total Invested  : Rs {summary['total_invested']:>14,.0f}")
    print(f"  Current Value   : Rs {summary['total_current']:>14,.0f}")
    print(f"  Absolute Gain   : Rs {summary['absolute_gain']:>14,.0f}")
    print(f"  Gain %          : {summary['gain_percentage']:.2f}%")

    divider("=")
    print("\n  Phases 1-5 complete. All engines operational.")
    print("  Phase 6 complete: FastAPI backend running.")
    print()
    print("  API server:")
    print("    PYTHONPATH=/Users/manavgupta/financial_advisor uvicorn api.main:app --reload")
    print()
    print("  Streamlit UI (still works):")
    print("    PYTHONPATH=/Users/manavgupta/financial_advisor streamlit run ui/app.py")
    print()
    print("  Next --> Phase 7: React investor app\n")
    divider("=")


if __name__ == "__main__":
    run_demo()
