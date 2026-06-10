"""
engine/goal_engine.py
----------------------
Goal planning engine for the AI Financial Advisory Tool.

Responsibilities:
  - Define standard financial goal types (Retirement, Education, House, Wedding, Emergency, Custom)
  - Calculate the inflation-adjusted future value of a goal
  - Determine required SIP and/or lumpsum contributions to reach the goal
  - Validate goal feasibility against income and timeline constraints
  - Return a structured GoalPlan dataclass used by the recommendation engine

Formulae used:
  FV with inflation  : FV = PV × (1 + inflation_rate)^n
  SIP required       : PMT = FV × r / [(1+r)^n - 1]   where r = monthly return rate
  Lumpsum required   : PV = FV / (1+r)^n               where r = annual return rate
  SEBI limits        : Max SIP cannot exceed 40% of monthly income (guardrail)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
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


# Default inflation and return assumptions (can be overridden per goal)
DEFAULT_INFLATION: dict[GoalType, float] = {
    GoalType.RETIREMENT:  0.06,   # 6% general inflation
    GoalType.EDUCATION:   0.08,   # 8% education inflation
    GoalType.HOUSE:       0.07,   # 7% real-estate inflation
    GoalType.WEDDING:     0.07,
    GoalType.EMERGENCY:   0.00,   # emergency fund: no inflation adjustment (liquid)
    GoalType.TRAVEL:      0.05,
    GoalType.CUSTOM:      0.06,
}

# Conservative expected annual returns by risk profile (post-tax approximation)
EXPECTED_ANNUAL_RETURN: dict[str, float] = {
    "Conservative":    0.07,   # 7%
    "Moderate":        0.10,   # 10%
    "Aggressive":      0.12,   # 12%
    "Very Aggressive": 0.14,   # 14%
}

# Max SIP as fraction of monthly income (soft guardrail)
MAX_SIP_INCOME_FRACTION = 0.40


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GoalInput:
    """Input provided by advisor / client for a single goal."""
    goal_type:          GoalType
    name:               str           # e.g. "Daughter's MBA", "Retirement corpus"
    target_amount_today: float        # target in today's ₹ (e.g. 50,00,000)
    years_to_goal:      int           # years until the goal is needed
    existing_investment: float = 0.0  # already invested lumpsum towards this goal
    inflation_rate:     Optional[float] = None  # override; None → use default
    expected_return:    Optional[float] = None  # override; None → use risk profile default
    is_recurring:       bool = False  # True for retirement (needs 20yr drawdown estimate)
    monthly_expense_at_goal: float = 0.0  # for retirement: expected monthly spend at retirement


@dataclass
class GoalPlan:
    """Computed plan for a single financial goal."""
    input:                GoalInput
    inflation_rate:       float
    expected_annual_return: float

    future_value:         float   # inflation-adjusted target
    monthly_sip_required: float   # SIP needed (no existing investment considered)
    adjusted_sip:         float   # SIP after accounting for existing investment growth
    lumpsum_required:     float   # alternative: invest this much today

    feasibility:          str     # "Feasible" / "Stretch" / "Infeasible"
    feasibility_notes:    list[str] = field(default_factory=list)

    # Retirement-specific
    retirement_corpus:    float = 0.0   # if is_recurring goal


# ---------------------------------------------------------------------------
# Core calculation functions
# ---------------------------------------------------------------------------

def _future_value_inflation(pv: float, inflation: float, years: int) -> float:
    """Inflate a present-value amount by inflation rate over years."""
    return pv * math.pow(1 + inflation, years)


def _sip_for_fv(fv: float, annual_return: float, years: int) -> float:
    """
    Monthly SIP required to accumulate FV in `years` years.
    Uses standard SIP FV formula: FV = PMT × [(1+r)^n - 1] / r × (1+r)
    Rearranged: PMT = FV × r / [(1+r)^n - 1] / (1+r)
    where r = monthly return rate, n = total months.
    """
    if years <= 0:
        return fv  # goal is now — full lumpsum
    r = annual_return / 12
    n = years * 12
    if r == 0:
        return fv / n
    return fv * r / ((math.pow(1 + r, n) - 1) * (1 + r))


def _lumpsum_for_fv(fv: float, annual_return: float, years: int) -> float:
    """Present value (lumpsum today) needed to reach FV in `years`."""
    if years <= 0:
        return fv
    return fv / math.pow(1 + annual_return, years)


def _existing_investment_growth(
    existing: float, annual_return: float, years: int
) -> float:
    """Future value of an existing lumpsum investment."""
    return existing * math.pow(1 + annual_return, years)


def _retirement_corpus(
    monthly_expense: float,
    years_in_retirement: int = 25,
    post_retirement_return: float = 0.06,
    post_retirement_inflation: float = 0.05,
) -> float:
    """
    Estimate retirement corpus required using the real-rate annuity method.
    real_rate = (1 + return) / (1 + inflation) - 1
    corpus = monthly_expense × 12 × [1 - (1+real_rate)^-n] / real_rate
    """
    real_rate = (1 + post_retirement_return) / (1 + post_retirement_inflation) - 1
    if abs(real_rate) < 1e-9:
        return monthly_expense * 12 * years_in_retirement
    annual_expense = monthly_expense * 12
    corpus = annual_expense * (1 - math.pow(1 + real_rate, -years_in_retirement)) / real_rate
    return corpus


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

    Parameters
    ----------
    goal_input      : GoalInput describing what the client wants
    risk_profile    : one of "Conservative" / "Moderate" / "Aggressive" / "Very Aggressive"
    monthly_income  : client's monthly gross income in INR

    Returns
    -------
    GoalPlan with all computed figures and feasibility assessment
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

    # 2. Compute future value (inflation-adjusted target)
    if goal_input.goal_type == GoalType.RETIREMENT and goal_input.monthly_expense_at_goal > 0:
        # For retirement: inflate monthly expense, then compute corpus
        inflated_monthly = _future_value_inflation(
            goal_input.monthly_expense_at_goal, inflation, years
        )
        retirement_corpus = _retirement_corpus(inflated_monthly)
        future_value = retirement_corpus
        notes.append(
            f"Retirement corpus based on ₹{goal_input.monthly_expense_at_goal:,.0f}/month "
            f"(today), inflated to ₹{inflated_monthly:,.0f}/month at retirement."
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
            f"Existing investment of ₹{goal_input.existing_investment:,.0f} "
            f"grows to ₹{existing_fv:,.0f} — covers "
            f"{existing_fv / future_value * 100:.1f}% of goal."
        )

    # 4. Compute SIP and lumpsum
    raw_sip       = _sip_for_fv(future_value, expected_return, years)
    adjusted_sip  = _sip_for_fv(residual_fv, expected_return, years)
    lumpsum       = _lumpsum_for_fv(residual_fv, expected_return, years)

    # 5. Feasibility check
    max_affordable_sip = monthly_income * MAX_SIP_INCOME_FRACTION
    if adjusted_sip <= max_affordable_sip * 0.25:
        feasibility = "Feasible"
    elif adjusted_sip <= max_affordable_sip:
        feasibility = "Stretch"
        notes.append(
            f"SIP required is ₹{adjusted_sip:,.0f}/month — "
            f"{adjusted_sip / monthly_income * 100:.1f}% of income. Consider extending timeline."
        )
    else:
        feasibility = "Infeasible"
        notes.append(
            f"SIP of ₹{adjusted_sip:,.0f}/month exceeds {MAX_SIP_INCOME_FRACTION*100:.0f}% "
            f"income cap (₹{max_affordable_sip:,.0f}). Goal needs revision."
        )

    # 6. Short timeline warning
    if years < 3 and goal_input.goal_type not in (GoalType.EMERGENCY,):
        notes.append(
            f"Goal is only {years} year(s) away — equity exposure should be limited. "
            f"Consider debt/hybrid funds."
        )

    return GoalPlan(
        input=goal_input,
        inflation_rate=inflation,
        expected_annual_return=expected_return,
        future_value=future_value,
        monthly_sip_required=raw_sip,
        adjusted_sip=adjusted_sip,
        lumpsum_required=lumpsum,
        feasibility=feasibility,
        feasibility_notes=notes,
        retirement_corpus=future_value if goal_input.goal_type == GoalType.RETIREMENT else 0.0,
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
        # Mark all non-emergency plans as needing review
        for plan in plans:
            if plan.input.goal_type != GoalType.EMERGENCY:
                plan.feasibility_notes.append(
                    f"⚠ Combined SIP across all goals = ₹{total_sip:,.0f}/month "
                    f"(exceeds {MAX_SIP_INCOME_FRACTION*100:.0f}% income limit of ₹{max_sip:,.0f}). "
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
        f"  Target Today         : ₹{g.target_amount_today:>15,.0f}",
        f"  Inflation-Adj Target : ₹{plan.future_value:>15,.0f}  "
        f"(@ {plan.inflation_rate*100:.1f}% p.a.)",
        f"  Expected Return      : {plan.expected_annual_return*100:.1f}% p.a.",
        "",
        f"  Monthly SIP Required : ₹{plan.adjusted_sip:>12,.0f}/month",
        f"  OR Lumpsum Today     : ₹{plan.lumpsum_required:>12,.0f}",
        "",
        f"  Feasibility          : {plan.feasibility}",
    ]
    if plan.feasibility_notes:
        lines.append("  Notes:")
        for note in plan.feasibility_notes:
            lines.append(f"    → {note}")
    return "\n".join(lines)# engine/__init__.py