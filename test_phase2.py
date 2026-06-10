"""
test_phase2.py
--------------
End-to-end test for Phase 2: Client Engine.

Tests:
  1. Risk questionnaire scoring + profile computation
  2. Goal planning calculations (SIP, lumpsum, FV)
  3. Recommendation engine (category allocation, DB fund lookup)
  4. Client manager CRUD (create client, add goals, add holdings)

Run with:
  PYTHONPATH=/Users/manavgupta/financial_advisor python test_phase2.py
"""

import sys
import os
import traceback

# Ensure project root is on path
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

PASSED = []
FAILED = []

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def ok(msg: str):
    print(f"  ✓  {msg}")
    PASSED.append(msg)

def fail(msg: str, err: str = ""):
    print(f"  ✗  {msg}")
    if err:
        print(f"     {err}")
    FAILED.append(msg)

# ============================================================
# 1. Risk Engine
# ============================================================
section("1. Risk Engine")

try:
    from engine.risk_engine import (
        QUESTIONNAIRE, score_responses, compute_risk_profile,
        describe_profile, RiskCategory
    )
    ok("Imported risk_engine")

    # Check questionnaire has 10 questions
    assert len(QUESTIONNAIRE) == 10, f"Expected 10 questions, got {len(QUESTIONNAIRE)}"
    ok(f"Questionnaire has {len(QUESTIONNAIRE)} questions")

    # Test: select the highest-score option for each question → Very Aggressive
    max_responses = {q["id"]: len(q["options"]) - 1 for q in QUESTIONNAIRE}
    max_score = score_responses(max_responses)
    ok(f"Max score (all highest options) = {max_score}")

    # Test: select the lowest-score option → Conservative
    min_responses = {q["id"]: 0 for q in QUESTIONNAIRE}
    min_score = score_responses(min_responses)
    ok(f"Min score (all lowest options) = {min_score}")

    # Compute a conservative profile
    conservative = compute_risk_profile(
        responses=min_responses,
        age=30,
        annual_income=600_000,
        dependants=0,
    )
    assert conservative.category == RiskCategory.CONSERVATIVE, \
        f"Expected Conservative, got {conservative.category}"
    ok(f"Conservative profile computed: {conservative.category.value} (score={conservative.raw_score})")

    # Compute a very aggressive profile
    aggressive = compute_risk_profile(
        responses=max_responses,
        age=28,
        annual_income=2_000_000,
        dependants=0,
    )
    assert aggressive.category == RiskCategory.VERY_AGGRESSIVE
    ok(f"Very Aggressive profile computed: {aggressive.category.value} (score={aggressive.raw_score})")

    # Test age guardrail: 58 years old + aggressive score → should cap at Moderate
    capped = compute_risk_profile(
        responses=max_responses,
        age=58,
        annual_income=2_000_000,
        dependants=0,
    )
    assert capped.age_capped is True
    assert capped.category == RiskCategory.MODERATE
    ok(f"Age guardrail applied at 58: capped to {capped.category.value}")

    # Test dependants adjustment
    dep_profile = compute_risk_profile(
        responses=max_responses,
        age=35,
        annual_income=1_500_000,
        dependants=4,
    )
    assert dep_profile.adjusted_score < dep_profile.raw_score
    ok(f"Dependants adjustment: raw={dep_profile.raw_score}, adjusted={dep_profile.adjusted_score}")

    # describe_profile
    desc = describe_profile(conservative)
    assert "Conservative" in desc
    ok("describe_profile() returned valid text")

except Exception as e:
    fail("Risk engine test", traceback.format_exc())


# ============================================================
# 2. Goal Engine
# ============================================================
section("2. Goal Engine")

try:
    from engine.goal_engine import (
        GoalType, GoalInput, plan_goal, plan_all_goals, format_goal_plan
    )
    ok("Imported goal_engine")

    # Test 1: Simple education goal
    education_goal = GoalInput(
        goal_type=GoalType.EDUCATION,
        name="Son's Engineering Degree",
        target_amount_today=2_500_000,   # ₹25 lakhs today
        years_to_goal=12,
    )
    plan = plan_goal(education_goal, risk_profile="Moderate", monthly_income=100_000)
    assert plan.future_value > 2_500_000, "FV should exceed today's amount after inflation"
    assert plan.adjusted_sip > 0
    assert plan.lumpsum_required > 0
    ok(f"Education goal: FV=₹{plan.future_value:,.0f}, SIP=₹{plan.adjusted_sip:,.0f}/mo")

    # Test 2: Retirement goal with monthly expense
    retirement_goal = GoalInput(
        goal_type=GoalType.RETIREMENT,
        name="Retirement",
        target_amount_today=0,
        years_to_goal=25,
        monthly_expense_at_goal=80_000,  # ₹80k/month in today's money
    )
    ret_plan = plan_goal(retirement_goal, risk_profile="Aggressive", monthly_income=200_000)
    assert ret_plan.retirement_corpus > 0
    ok(f"Retirement goal: corpus=₹{ret_plan.retirement_corpus:,.0f}, SIP=₹{ret_plan.adjusted_sip:,.0f}/mo")

    # Test 3: Emergency fund goal (no inflation)
    emergency_goal = GoalInput(
        goal_type=GoalType.EMERGENCY,
        name="Emergency Fund",
        target_amount_today=600_000,    # ₹6 lakhs
        years_to_goal=1,
        inflation_rate=0.0,
    )
    emg_plan = plan_goal(emergency_goal, risk_profile="Conservative", monthly_income=100_000)
    # FV should equal target (0% inflation)
    assert abs(emg_plan.future_value - 600_000) < 1, \
        f"Emergency FV mismatch: {emg_plan.future_value}"
    ok(f"Emergency fund: FV=₹{emg_plan.future_value:,.0f} (no inflation applied)")

    # Test 4: Existing investment reduces required SIP
    goal_with_existing = GoalInput(
        goal_type=GoalType.HOUSE,
        name="Down Payment for House",
        target_amount_today=2_000_000,
        years_to_goal=5,
        existing_investment=500_000,
    )
    plan_with = plan_goal(goal_with_existing, risk_profile="Moderate", monthly_income=100_000)
    goal_without = GoalInput(
        goal_type=GoalType.HOUSE,
        name="Down Payment for House",
        target_amount_today=2_000_000,
        years_to_goal=5,
    )
    plan_without = plan_goal(goal_without, risk_profile="Moderate", monthly_income=100_000)
    assert plan_with.adjusted_sip < plan_without.adjusted_sip
    ok(f"Existing investment reduces SIP: ₹{plan_without.adjusted_sip:,.0f} → ₹{plan_with.adjusted_sip:,.0f}")

    # Test 5: plan_all_goals
    all_plans = plan_all_goals(
        [education_goal, retirement_goal, emergency_goal],
        risk_profile="Moderate",
        monthly_income=200_000,
    )
    assert len(all_plans) == 3
    ok(f"plan_all_goals() returned {len(all_plans)} plans")

    # Test 6: format output
    formatted = format_goal_plan(plan)
    assert "₹" in formatted
    ok("format_goal_plan() returned formatted string")

    # Test 7: infeasible goal (SIP exceeds 40% income)
    huge_goal = GoalInput(
        goal_type=GoalType.HOUSE,
        name="Luxury Villa",
        target_amount_today=50_000_000,
        years_to_goal=3,
    )
    huge_plan = plan_goal(huge_goal, risk_profile="Aggressive", monthly_income=100_000)
    assert huge_plan.feasibility == "Infeasible"
    ok(f"Infeasibility detected correctly: {huge_plan.feasibility}")

except Exception as e:
    fail("Goal engine test", traceback.format_exc())


# ============================================================
# 3. Recommendation Engine
# ============================================================
section("3. Recommendation Engine")

try:
    from engine.recommendation_engine import (
        recommend_for_goal, recommend_all_goals,
        format_recommendation, ALLOCATION_MATRIX
    )
    from engine.goal_engine import GoalInput, GoalType, plan_goal
    from config.settings import DATABASE_PATH
    ok("Imported recommendation_engine")

    # Verify allocation matrix covers all profiles and buckets
    for profile in ["Conservative", "Moderate", "Aggressive", "Very Aggressive"]:
        for bucket in ["short", "medium", "long"]:
            allocs = ALLOCATION_MATRIX[profile][bucket]
            total = sum(w for _, w in allocs)
            assert abs(total - 100) < 0.1, f"{profile}/{bucket} weights don't sum to 100: {total}"
    ok("Allocation matrix validated (all weights sum to 100)")

    # Build a sample plan and recommend
    goal = GoalInput(
        goal_type=GoalType.EDUCATION,
        name="MBA Abroad",
        target_amount_today=5_000_000,
        years_to_goal=8,
    )
    plan = plan_goal(goal, risk_profile="Aggressive", monthly_income=200_000)
    rec = recommend_for_goal(plan, risk_profile="Aggressive", db_path=DATABASE_PATH)

    assert rec.goal_name == "MBA Abroad"
    assert len(rec.allocations) > 0
    total_weight = sum(a.weight for a in rec.allocations)
    assert abs(total_weight - 100) < 0.5, f"Allocation weights don't sum to 100: {total_weight}"
    ok(f"Recommendation generated: {len(rec.allocations)} categories, weights sum={total_weight:.1f}%")

    # Emergency fund override check
    emg_goal = GoalInput(
        goal_type=GoalType.EMERGENCY,
        name="Emergency Fund",
        target_amount_today=600_000,
        years_to_goal=1,
    )
    emg_plan = plan_goal(emg_goal, risk_profile="Very Aggressive", monthly_income=200_000)
    emg_rec = recommend_for_goal(emg_plan, risk_profile="Very Aggressive", db_path=DATABASE_PATH)
    cats = [a.category for a in emg_rec.allocations]
    assert "Liquid Fund" in cats, f"Emergency override failed; got: {cats}"
    ok(f"Emergency goal override works: {cats}")

    # Format output
    fmt = format_recommendation(rec)
    assert rec.goal_name in fmt
    ok("format_recommendation() returned valid output")

    # Print a sample recommendation for visual inspection
    print()
    print(fmt)

except Exception as e:
    fail("Recommendation engine test", traceback.format_exc())


# ============================================================
# 4. Client Manager CRUD
# ============================================================
section("4. Client Manager CRUD")

try:
    from data.client_manager import (
        create_client, get_client_by_id, get_client_by_email,
        list_clients, update_client_risk_profile, update_client,
        delete_client,
        add_goal, get_goals_for_client, update_goal_sip, deactivate_goal,
        add_holding, get_holdings_for_client, get_portfolio_summary,
        update_holding_current_value,
    )
    ok("Imported client_manager")

    # Create a test client
    test_email = "test_phase2_manav@advisor.test"
    # Clean up any prior test run
    existing = get_client_by_email(test_email)
    if existing:
        delete_client(existing.id)

    client = create_client(
        name="Test Client Phase2",
        email=test_email,
        phone="9876543210",
        age=35,
        annual_income=2_400_000,  # ₹24 LPA
        dependants=2,
        pan="ABCDE1234F",
    )
    assert client.id > 0
    assert client.monthly_income == 200_000.0
    ok(f"Client created: id={client.id}, monthly_income=₹{client.monthly_income:,.0f}")

    # Fetch by ID
    fetched = get_client_by_id(client.id)
    assert fetched is not None and fetched.name == client.name
    ok("get_client_by_id() works")

    # Fetch by email
    fetched_email = get_client_by_email(test_email)
    assert fetched_email is not None
    ok("get_client_by_email() works")

    # List clients
    all_clients = list_clients()
    assert any(c.id == client.id for c in all_clients)
    ok(f"list_clients() returned {len(all_clients)} clients")

    # Update risk profile
    ok_flag = update_client_risk_profile(client.id, "Moderate", 42)
    updated = get_client_by_id(client.id)
    assert updated.risk_profile == "Moderate"
    assert updated.risk_score == 42
    ok("update_client_risk_profile() works")

    # Update client fields
    update_client(client.id, phone="9999999999", age=36)
    updated2 = get_client_by_id(client.id)
    assert updated2.age == 36
    ok("update_client() partial update works")

    # Add a goal
    goal = add_goal(
        client_id=client.id,
        goal_name="Son's College",
        goal_type="Child Education",
        target_amount=3_000_000,
        target_year=2037,
        current_savings=100_000,
        monthly_sip=15_000,
        priority=1,
    )
    assert goal.id > 0
    ok(f"Goal added: id={goal.id}, '{goal.goal_name}'")

    # Get goals
    goals = get_goals_for_client(client.id)
    assert len(goals) >= 1
    ok(f"get_goals_for_client() returned {len(goals)} goals")

    # Update SIP
    update_goal_sip(goal.id, 18_500)
    goals2 = get_goals_for_client(client.id)
    updated_goal = next((g for g in goals2 if g.id == goal.id), None)
    assert updated_goal is not None and updated_goal.monthly_sip == 18_500
    ok("update_goal_sip() works")

    # Deactivate goal
    deactivate_goal(goal.id)
    goals3 = get_goals_for_client(client.id)
    assert not any(g.id == goal.id for g in goals3)
    ok("deactivate_goal() works (soft delete)")

    # Add a holding
    holding = add_holding(
        client_id=client.id,
        scheme_code=119598,
        scheme_name="Parag Parikh Flexi Cap Fund - Direct Growth",
        units=450.321,
        avg_nav=55.23,
        invested_amount=250_000,
        current_value=285_000,
    )
    assert holding.id > 0
    ok(f"Holding added: id={holding.id}, scheme={holding.scheme_code}")

    # Get holdings
    holdings = get_holdings_for_client(client.id)
    assert len(holdings) >= 1
    ok(f"get_holdings_for_client() returned {len(holdings)} holdings")

    # Update current value
    update_holding_current_value(holding.id, 290_000)
    holdings2 = get_holdings_for_client(client.id)
    h = next((x for x in holdings2 if x.id == holding.id), None)
    assert h is not None
    ok("update_holding_current_value() works")

    # Portfolio summary
    summary = get_portfolio_summary(client.id)
    assert summary["num_holdings"] >= 1
    assert summary["total_invested"] > 0
    ok(f"Portfolio summary: invested=₹{summary['total_invested']:,.0f}, "
       f"current=₹{summary['total_current']:,.0f}, gain={summary['gain_percentage']:.1f}%")

    # Cleanup
    delete_client(client.id)
    assert get_client_by_id(client.id) is None
    ok("delete_client() works (with cascade)")

except Exception as e:
    fail("Client manager CRUD test", traceback.format_exc())


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
    print("\n  All tests passed. Phase 2 is solid. ✓")
