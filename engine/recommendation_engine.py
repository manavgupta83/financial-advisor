"""
engine/recommendation_engine.py
---------------------------------
Fund recommendation engine for the AI Financial Advisory Tool.

Responsibilities:
  - Map a client's risk profile + goal type + time horizon to
    appropriate SEBI fund categories (e.g. "Large Cap Fund", "Short Duration Fund")
  - Assign portfolio allocation weights across those categories
  - Query the local SQLite DB to find actual funds in each category
  - Return a structured Recommendation dataclass for each goal

Recommendation logic:
  - Time horizon < 3 years       → shift towards debt/liquid regardless of profile
  - Time horizon 3-7 years       → hybrid + moderate equity
  - Time horizon > 7 years       → full equity tilt per risk profile
  - Emergency fund goal          → always liquid/ultra-short only
  - Retirement goal (horizon 7+) → add international + index tilt
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from engine.risk_engine import RiskCategory
from engine.goal_engine import GoalType, GoalPlan


# ---------------------------------------------------------------------------
# Fund category allocation matrices
# Category names match SEBI classification nomenclature
# ---------------------------------------------------------------------------

# Structure: risk_profile → horizon_bucket → list of (category, weight%)
ALLOCATION_MATRIX: dict[str, dict[str, list[tuple[str, float]]]] = {

    "Conservative": {
        "short":   [  # < 3 years
            ("Liquid Fund",                  40.0),
            ("Ultra Short Duration Fund",    35.0),
            ("Short Duration Fund",          25.0),
        ],
        "medium":  [  # 3-7 years
            ("Short Duration Fund",          40.0),
            ("Conservative Hybrid Fund",     35.0),
            ("Large Cap Fund",               15.0),
            ("Liquid Fund",                  10.0),
        ],
        "long":    [  # > 7 years
            ("Conservative Hybrid Fund",     40.0),
            ("Large Cap Fund",               30.0),
            ("Short Duration Fund",          20.0),
            ("ELSS Fund",                    10.0),
        ],
    },

    "Moderate": {
        "short":   [
            ("Short Duration Fund",          35.0),
            ("Arbitrage Fund",               30.0),
            ("Conservative Hybrid Fund",     25.0),
            ("Liquid Fund",                  10.0),
        ],
        "medium":  [
            ("Flexi Cap Fund",               35.0),
            ("Balanced Advantage Fund",      30.0),
            ("Short Duration Fund",          20.0),
            ("Large Cap Fund",               15.0),
        ],
        "long":    [
            ("Flexi Cap Fund",               35.0),
            ("Large Cap Fund",               25.0),
            ("ELSS Fund",                    20.0),
            ("Short Duration Fund",          10.0),
            ("International Fund",           10.0),
        ],
    },

    "Aggressive": {
        "short":   [
            ("Balanced Advantage Fund",      40.0),
            ("Arbitrage Fund",               30.0),
            ("Short Duration Fund",          30.0),
        ],
        "medium":  [
            ("Flexi Cap Fund",               35.0),
            ("Mid Cap Fund",                 25.0),
            ("Large Cap Fund",               20.0),
            ("Short Duration Fund",          20.0),
        ],
        "long":    [
            ("Flexi Cap Fund",               30.0),
            ("Mid Cap Fund",                 25.0),
            ("Small Cap Fund",               15.0),
            ("ELSS Fund",                    15.0),
            ("International Fund",           10.0),
            ("Short Duration Fund",           5.0),
        ],
    },

    "Very Aggressive": {
        "short":   [
            ("Balanced Advantage Fund",      45.0),
            ("Flexi Cap Fund",               30.0),
            ("Short Duration Fund",          25.0),
        ],
        "medium":  [
            ("Flexi Cap Fund",               30.0),
            ("Mid Cap Fund",                 30.0),
            ("Small Cap Fund",               20.0),
            ("Short Duration Fund",          20.0),
        ],
        "long":    [
            ("Flexi Cap Fund",               25.0),
            ("Mid Cap Fund",                 25.0),
            ("Small Cap Fund",               20.0),
            ("Sectoral/Thematic Fund",       10.0),
            ("International Fund",           10.0),
            ("ELSS Fund",                    10.0),
        ],
    },
}

# Overrides for specific goal types
GOAL_OVERRIDES: dict[GoalType, dict] = {
    GoalType.EMERGENCY: {
        "force_allocation": [
            ("Liquid Fund",               60.0),
            ("Ultra Short Duration Fund", 40.0),
        ]
    },
    GoalType.RETIREMENT: {
        # For long horizon, tilt to index + NPS-friendly categories
        "long_append": [("Index Fund",  0.0)],  # replace International with Index if NRI check needed
    },
}

# SEBI category to common alternate names (for DB lookup flexibility)
CATEGORY_ALIASES: dict[str, list[str]] = {
    "Flexi Cap Fund":             ["Flexi Cap Fund", "Flexicap Fund", "Multi Cap Fund"],
    "Balanced Advantage Fund":    ["Balanced Advantage Fund", "Dynamic Asset Allocation Fund"],
    "Conservative Hybrid Fund":   ["Conservative Hybrid Fund"],
    "ELSS Fund":                  ["ELSS", "Equity Linked Savings Scheme"],
    "International Fund":         ["International Fund", "Overseas Fund", "Fund of Funds (Overseas)"],
    "Index Fund":                 ["Index Fund", "Nifty 50 Index Fund", "Sensex Index Fund"],
    "Sectoral/Thematic Fund":     ["Sectoral Fund", "Thematic Fund", "Sectoral/Thematic Fund"],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CategoryAllocation:
    category:     str
    weight:       float          # percentage 0-100
    funds:        list[dict]     = field(default_factory=list)  # rows from DB


@dataclass
class Recommendation:
    goal_name:     str
    goal_type:     GoalType
    risk_profile:  str
    horizon_years: int
    horizon_bucket: str          # "short" / "medium" / "long"
    target_sip:    float         # monthly SIP from GoalPlan
    allocations:   list[CategoryAllocation] = field(default_factory=list)
    notes:         list[str]               = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper: horizon bucket
# ---------------------------------------------------------------------------

def _horizon_bucket(years: int) -> str:
    if years < 3:
        return "short"
    elif years <= 7:
        return "medium"
    return "long"


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------

def _fetch_funds_for_category(
    conn: sqlite3.Connection,
    category: str,
    limit: int = 3,
) -> list[dict]:
    """
    Query the funds table for a given SEBI category (with alias fallback).
    Uses Phase 1 schema columns: category, sub_category.
    Returns up to `limit` funds as dicts.
    """
    aliases = CATEGORY_ALIASES.get(category, [category])
    placeholders = ",".join(["?" for _ in aliases])
    cursor = conn.execute(
        f"""
        SELECT scheme_code, scheme_name, fund_house, category, sub_category
        FROM   funds
        WHERE  category     IN ({placeholders})
           OR  sub_category IN ({placeholders})
        LIMIT  ?
        """,
        aliases + aliases + [limit],
    )
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Main recommendation function
# ---------------------------------------------------------------------------

def recommend_for_goal(
    plan: GoalPlan,
    risk_profile: str,
    db_path: str,
) -> Recommendation:
    """
    Build a fund recommendation for a single GoalPlan.

    Parameters
    ----------
    plan         : GoalPlan from goal_engine.plan_goal()
    risk_profile : "Conservative" / "Moderate" / "Aggressive" / "Very Aggressive"
    db_path      : path to the SQLite database file

    Returns
    -------
    Recommendation with category allocations and suggested funds per category
    """
    goal_type   = plan.input.goal_type
    years       = plan.input.years_to_goal
    bucket      = _horizon_bucket(years)
    notes: list[str] = []

    # 1. Start from the allocation matrix
    if goal_type == GoalType.EMERGENCY:
        raw_alloc = GOAL_OVERRIDES[GoalType.EMERGENCY]["force_allocation"]
        notes.append("Emergency fund: overriding to liquid/ultra-short only.")
    else:
        profile_matrix = ALLOCATION_MATRIX.get(risk_profile, ALLOCATION_MATRIX["Moderate"])
        raw_alloc = profile_matrix.get(bucket, profile_matrix["long"])

    # 2. Tax-saving tilt: if ELSS goal, ensure ELSS ≥ 40%
    if goal_type == GoalType.CUSTOM and "ELSS" in plan.input.name.upper():
        raw_alloc = [
            ("ELSS Fund", 60.0),
            ("Large Cap Fund", 25.0),
            ("Short Duration Fund", 15.0),
        ]
        notes.append("ELSS-tagged goal: tilted to 60% ELSS for Section 80C optimisation.")

    # 3. Short-horizon safety override for any goal < 1 year
    if years <= 1 and goal_type != GoalType.EMERGENCY:
        raw_alloc = [
            ("Liquid Fund",               50.0),
            ("Ultra Short Duration Fund", 30.0),
            ("Arbitrage Fund",            20.0),
        ]
        notes.append(
            f"Horizon is {years} year — overridden to capital-preservation allocation."
        )

    # 4. Normalise weights to exactly 100 (handles floating point)
    total_weight = sum(w for _, w in raw_alloc)
    normalised = [(cat, round(w / total_weight * 100, 1)) for cat, w in raw_alloc]

    # 5. Fetch actual funds from DB
    conn = sqlite3.connect(db_path)
    allocations: list[CategoryAllocation] = []
    for cat, weight in normalised:
        funds = _fetch_funds_for_category(conn, cat, limit=3)
        if not funds:
            notes.append(
                f"No funds found in DB for category '{cat}'. "
                f"Add more funds via nav_fetcher to populate this category."
            )
        allocations.append(CategoryAllocation(category=cat, weight=weight, funds=funds))
    conn.close()

    return Recommendation(
        goal_name=plan.input.name,
        goal_type=goal_type,
        risk_profile=risk_profile,
        horizon_years=years,
        horizon_bucket=bucket,
        target_sip=plan.adjusted_sip,
        allocations=allocations,
        notes=notes,
    )


def recommend_all_goals(
    plans: list[GoalPlan],
    risk_profile: str,
    db_path: str,
) -> list[Recommendation]:
    """Generate recommendations for all goals."""
    return [recommend_for_goal(p, risk_profile, db_path) for p in plans]


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def format_recommendation(rec: Recommendation) -> str:
    """Return a human-readable recommendation summary."""
    lines = [
        f"Recommendation: {rec.goal_name} ({rec.goal_type.value})",
        f"  Risk Profile : {rec.risk_profile}",
        f"  Horizon      : {rec.horizon_years} years ({rec.horizon_bucket}-term)",
        f"  Monthly SIP  : ₹{rec.target_sip:,.0f}",
        "",
        "  Allocation:",
    ]
    for alloc in rec.allocations:
        lines.append(f"    {alloc.weight:5.1f}%  {alloc.category}")
        for fund in alloc.funds:
            lines.append(f"             → {fund.get('scheme_name', 'N/A')[:60]}")
        if not alloc.funds:
            lines.append("             → (no funds in DB yet — seed more data)")
    if rec.notes:
        lines.append("")
        lines.append("  Notes:")
        for note in rec.notes:
            lines.append(f"    • {note}")
    return "\n".join(lines)
