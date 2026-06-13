"""
engine/goal_engine.py
----------------------
Goal planning engine for the AI Financial Advisory Tool.

Responsibilities:
  - Define standard financial goal types
  - Calculate the inflation-adjusted future value of a goal
  - Determine required SIP and/or lumpsum contributions to reach the goal
  - Validate goal feasibility against income and timeline constraints
  - Return a structured GoalPlan dataclass used by the recommendation engine

Formulae used:
  FV with inflation  : FV = PV x (1 + inflation_rate)^n
  SIP required       : PMT = FV x r / [(1+r)^n - 1]   where r = monthly return rate
  Lumpsum required   : PV = FV / (1+r)^n               where r = annual return rate
  SEBI limits        : Max SIP cannot exceed 40% of monthly income (guardrail)

Rounding:
  All INR monetary outputs (FV, SIP, lumpsum) are rounded to the nearest 500
  via round_to_nearest(). Rounding applied AFTER feasibility check to preserve
  calculation accuracy. Change INR_ROUND_TO to adjust granularity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class GoalType(str, Enum):
    RETIREMENT  = "Retirement"
    EDUCATION   = "Child Education"
    HOUSE       = "House Purchase"
    WEDDING     = "Wedding"
    EMERGENCY   = "Emergency Fund"
    TRAVEL      = "Travel"
    CUSTOM      = "Custom"


DEFAULT_INFLATION: dict[GoalType, float] = {
    GoalType.RETIREMENT:  0.06,
    GoalType.EDUCATION:   0.08,
    GoalType.HOUSE:       0.07,
    GoalType.WEDDING:     0.07,
    GoalType.EMERGENCY:   0.00,
    GoalType.TRAVEL:      0.05,
    GoalType.CUSTOM:      0.06,
}

EXPECTED_ANNUAL_RETURN: dict[str, float] = {
    "Conservative":    0.07,
    "Moderate":        0.10,
    "Aggressive":      0.12,
    "Very Aggressive": 0.14,
}

MAX_SIP_INCOME_FRACTION = 0.40

# Rounding granularity for all INR monetary outputs
INR_ROUND_TO = 500


# ---------------------------------------------------------------------------
# Rounding helper
# ---------------------------------------------------------------------------

def round_to_nearest(value: float, nearest: int = INR_ROUND_TO) -> float:
    """Round a monetary value to the nearest 'nearest' rupees (default 500)."""
    return round(value / nearest) * nearest


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GoalInput:
    """Input provided by advisor / client for a single goal."""
    goal_type:               GoalType
    name:                    str
    target_amount_today:     float
    years_to_goal:           int
    existing_investment:     float = 0.0
    inflation_rate:          Optional[float] = None
    expected_return:         Optional[float] = None
    is_recurring:            bool = False
    monthly_expense_at_goal: float = 0.0


@dataclass
class GoalPlan:
    """Computed plan for a single financial goal. All INR fields rounded to nearest 500."""
    input:                  GoalInput
    inflation_rate:         float
    expected_annual_return: float

    future_value:           float   # inflation-adjusted target (rounded to nearest 500)
    monthly_sip_required:   float   # SIP needed (rounded to nearest 500)
    adjusted_sip:           float   # SIP after existing investment (rounded to nearest 500)
    lumpsum_required:       float   # alternative lumpsum today (rounded to nearest 500)

    feasibility:            str     # "Feasible" / "Stretch" / "Infeasible"
    feasibility_notes:      list[str] = field(default_factory=list)

    retirement_corpus:      float = 0.0


# ---------------------------------------------------------------------------
# Core calculation functions
# ---------------------------------------------------------------------------

def _future_value_inflation(pv: float, inflation: float, years: int) -> float:
    return pv * math.pow(1 + inflation, years)


def _sip_for_fv(fv: float, annual_return: float, years: int) -> float:
    if years <= 0:
        return fv
    r = annual_return / 12
    n = years * 12
    if r == 0:
        return fv / n
    return fv * r / ((math.pow(1 + r, n) - 1) * (1 + r))


def _lumpsum_for_fv(fv: float, annual_return: float, years: int) -> float:
    if years <= 0:
        return fv
    return fv / math.pow(1 + annual_return, years)


def _existing_investment_growth(existing: float, annual_return: float, years: int) -> float:
    return existing * math.pow(1 + annual_return, years)


def _retirement_corpus(
    monthly_expense: float,
    years_in_retirement: int = 25,
    post_retirement_return: float = 0.06,
    post_retirement_inflation: float = 0.05,
) -> float:
    real_rate = (1 + post_retirement_return) / (1 + post_retirement_inflation) - 1
    if abs(real_rate) < 1e-9:
        return monthly_expense * 12 * years_in_retirement
    annual_expense = monthly_expense * 12
    return annual_expense * (1 - math.pow(1 + real_rate, -years_in_retirement)) / real_rate


# ---------------------------------------------------------------------------
# Main planning function
# ---------------------------------------------------------------------------

def plan_goal(
    goal_input: GoalInput,
    risk_profile: str,
    monthly_income: float,
) -> GoalPlan:
    """
    Compute a complete GoalPlan for a single goal.
    All INR monetary outputs are rounded to the nearest 500.
    Rounding is applied after the feasibility check to preserve accuracy.
    """
    notes: list[str] = []

    # 1. Resolve rates
    inflation = (
        goal_input.inflation_rate
        if goal_input.inflation_rate is not None
        else DEFAULT_INFLATION.get(goal_input.goal_type, 0.06)
    )
    expected_return = (
        goal_input.expected_return
        if goal_input.expected_return is not None
        else EXPECTED_ANNUAL_RETURN.get(risk_profile, 0.10)
    )
    years = goal_input.years_to_goal

    # 2. Compute future value
    if goal_input.goal_type == GoalType.RETIREMENT and goal_input.monthly_expense_at_goal > 0:
        inflated_monthly = _future_value_inflation(
            goal_input.monthly_expense_at_goal, inflation, years
        )
        future_value = _retirement_corpus(inflated_monthly)
        notes.append(
            f"Retirement corpus based on {goal_input.monthly_expense_at_goal:,.0f}/month "
            f"today, inflated to {inflated_monthly:,.0f}/month at retirement."
        )
    else:
        future_value = _future_value_inflation(goal_input.target_amount_today, inflation, years)

    # 3. Account for existing investment growth
    existing_fv = _existing_investment_growth(
        goal_input.existing_investment, expected_return, years
    )
    residual_fv = max(future_value - existing_fv, 0)

    if goal_input.existing_investment > 0:
        notes.append(
            f"Existing investment of {goal_input.existing_investment:,.0f} "
            f"grows to {existing_fv:,.0f} -- covers "
            f"{existing_fv / future_value * 100:.1f}% of goal."
        )

    # 4. Compute SIP and lumpsum (raw, unrounded -- used for feasibility check)
    raw_sip      = _sip_for_fv(future_value, expected_return, years)
    adjusted_sip = _sip_for_fv(residual_fv, expected_return, years)
    lumpsum      = _lumpsum_for_fv(residual_fv, expected_return, years)

    # 5. Feasibility check (uses raw unrounded values for accuracy)
    max_affordable_sip = monthly_income * MAX_SIP_INCOME_FRACTION
    if adjusted_sip <= max_affordable_sip * 0.25:
        feasibility = "Feasible"
    elif adjusted_sip <= max_affordable_sip:
        feasibility = "Stretch"
        notes.append(
            f"SIP required is {adjusted_sip:,.0f}/month -- "
            f"{adjusted_sip / monthly_income * 100:.1f}% of income. Consider extending timeline."
        )
    else:
        feasibility = "Infeasible"
        notes.append(
            f"SIP of {adjusted_sip:,.0f}/month exceeds {MAX_SIP_INCOME_FRACTION*100:.0f}% "
            f"income cap ({max_affordable_sip:,.0f}). Goal needs revision."
        )

    if years < 3 and goal_input.goal_type not in (GoalType.EMERGENCY,):
        notes.append(
            f"Goal is only {years} year(s) away -- equity exposure should be limited. "
            f"Consider debt/hybrid funds."
        )

    # 6. Round all INR monetary outputs to nearest 500
    return GoalPlan(
        input=goal_input,
        inflation_rate=inflation,
        expected_annual_return=expected_return,
        future_value=round_to_nearest(future_value),
        monthly_sip_required=round_to_nearest(raw_sip),
        adjusted_sip=round_to_nearest(adjusted_sip),
        lumpsum_required=round_to_nearest(lumpsum),
        feasibility=feasibility,
        feasibility_notes=notes,
        retirement_corpus=round_to_nearest(future_value) if goal_input.goal_type == GoalType.RETIREMENT else 0.0,
    )


def plan_all_goals(
    goals: list[GoalInput],
    risk_profile: str,
    monthly_income: float,
) -> list[GoalPlan]:
    """Plan all goals and add a combined SIP feasibility check."""
    plans = [plan_goal(g, risk_profile, monthly_income) for g in goals]

    total_sip = sum(p.adjusted_sip for p in plans)
    max_sip = monthly_income * MAX_SIP_INCOME_FRACTION
    if total_sip > max_sip:
        for plan in plans:
            if plan.input.goal_type != GoalType.EMERGENCY:
                plan.feasibility_notes.append(
                    f"Combined SIP across all goals = {total_sip:,.0f}/month "
                    f"(exceeds {MAX_SIP_INCOME_FRACTION*100:.0f}% income limit of {max_sip:,.0f}). "
                    f"Prioritise goals or increase income allocation."
                )
    return plans


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def format_goal_plan(plan: GoalPlan) -> str:
    """Return a human-readable summary of a GoalPlan."""
    g = plan.input
    lines = [
        f"Goal: {g.name} ({g.goal_type.value})",
        f"  Years to Goal        : {g.years_to_goal}",
        f"  Target Today         : {g.target_amount_today:>15,.0f}",
        f"  Inflation-Adj Target : {plan.future_value:>15,.0f}  "
        f"(@ {plan.inflation_rate*100:.1f}% p.a.)",
        f"  Expected Return      : {plan.expected_annual_return*100:.1f}% p.a.",
        "",
        f"  Monthly SIP Required : {plan.adjusted_sip:>12,.0f}/month",
        f"  OR Lumpsum Today     : {plan.lumpsum_required:>12,.0f}",
        "",
        f"  Feasibility          : {plan.feasibility}",
    ]
    if plan.feasibility_notes:
        lines.append("  Notes:")
        for note in plan.feasibility_notes:
            lines.append(f"    -> {note}")
    return "\n".join(lines)
