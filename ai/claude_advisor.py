"""
ai/claude_advisor.py
---------------------
Phase 4 — Claude AI Advisor Integration.

Provides three main capabilities:

1. stream_advisory_narrative()
   Full streaming advisory report for a client. Takes the complete client
   context (profile, goals, plans, portfolio, optimiser result) and streams
   a professional, personalised narrative using Claude.

2. parse_optimiser_constraints()
   Natural-language constraint parsing via Claude.
   e.g. "no more than 25% in any single fund, at least 4 funds" →
   OptimiserConstraints(max_weight=0.25, min_funds=4, ...)

3. explain_portfolio_optimisation()
   Plain-language explanation of why the optimiser picked certain funds,
   tailored to the client's risk profile and goals.

Design decisions
----------------
- Uses claude-sonnet-4-20250514 throughout
- Streaming via anthropic.Anthropic().messages.stream() context manager
- All prompts are self-contained (stateless) — no session memory required
- Returns plain text; formatting (markdown) left to the Streamlit UI layer
- ANTHROPIC_API_KEY read from environment via python-dotenv
- All monetary amounts formatted in Indian number system (lakhs / crores)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from typing import Generator, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Lazy import so the module loads even without anthropic installed ──────────

def _get_anthropic_client():
    """Return an Anthropic client, raising a clear error if not installed."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file."
            )
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        raise ImportError(
            "anthropic package not installed. "
            "Run: pip install anthropic --break-system-packages"
        )


# ── Formatting helpers ────────────────────────────────────────────────────────

def _inr(amount: float) -> str:
    """Format a float as Indian Rupee with lakh/crore suffixes."""
    if amount >= 1e7:
        return f"₹{amount / 1e7:.2f} Cr"
    elif amount >= 1e5:
        return f"₹{amount / 1e5:.2f} L"
    else:
        return f"₹{amount:,.0f}"


def _build_client_context_block(client_data: dict) -> str:
    """
    Build a structured text block describing the client.
    client_data keys: name, age, annual_income, monthly_income, dependants,
                      risk_profile, risk_score
    """
    return f"""
CLIENT PROFILE
==============
Name              : {client_data.get('name', 'N/A')}
Age               : {client_data.get('age', 'N/A')} years
Annual Income     : {_inr(client_data.get('annual_income', 0))}
Monthly Income    : {_inr(client_data.get('monthly_income', 0))}
Dependants        : {client_data.get('dependants', 0)}
Risk Profile      : {client_data.get('risk_profile', 'Moderate')}
Risk Score        : {client_data.get('risk_score', 0)}/100
""".strip()


def _build_goals_block(goals: list[dict]) -> str:
    """
    goals: list of dicts with keys:
      name, goal_type, target_amount, years_to_goal, monthly_sip,
      future_value, adjusted_sip
    """
    if not goals:
        return "No goals defined."
    lines = ["FINANCIAL GOALS", "=============="]
    for i, g in enumerate(goals, 1):
        lines.append(
            f"{i}. {g.get('name', 'Goal')} ({g.get('goal_type', '')})\n"
            f"   Target (today)  : {_inr(g.get('target_amount', 0))}\n"
            f"   Future Value    : {_inr(g.get('future_value', 0))}\n"
            f"   Time Horizon    : {g.get('years_to_goal', 0)} years\n"
            f"   Monthly SIP     : {_inr(g.get('adjusted_sip', 0))}"
        )
    return "\n".join(lines)


def _build_portfolio_block(portfolio: dict) -> str:
    """
    portfolio keys: num_holdings, total_invested, total_current,
                    absolute_gain, gain_percentage, holdings (list of dicts)
    """
    if not portfolio or not portfolio.get("num_holdings"):
        return "Portfolio: No holdings yet."
    lines = [
        "CURRENT PORTFOLIO",
        "=================",
        f"Holdings        : {portfolio['num_holdings']}",
        f"Total Invested  : {_inr(portfolio['total_invested'])}",
        f"Current Value   : {_inr(portfolio['total_current'])}",
        f"Gain / Loss     : {_inr(portfolio['absolute_gain'])} "
        f"({portfolio['gain_percentage']:.1f}%)",
    ]
    holdings = portfolio.get("holdings", [])
    if holdings:
        lines.append("")
        lines.append("Holdings detail:")
        for h in holdings:
            lines.append(
                f"  • {h.get('scheme_name', 'Unknown')[:50]} — "
                f"Invested {_inr(h.get('invested_amount', 0))}, "
                f"Current {_inr(h.get('current_value', 0))}"
            )
    return "\n".join(lines)


def _build_optimiser_block(opt_result) -> str:
    """
    opt_result: OptimiserResult or dict with same fields.
    """
    if opt_result is None:
        return "Optimiser: Not run."
    if hasattr(opt_result, "summary"):
        return f"OPTIMISER RESULT\n================\n{opt_result.summary()}"
    # dict fallback
    return f"OPTIMISER RESULT\n================\n{json.dumps(opt_result, indent=2)}"


# ── 1. Streaming advisory narrative ──────────────────────────────────────────

ADVISORY_SYSTEM_PROMPT = """\
You are a senior SEBI-registered Mutual Fund Distributor and Certified Financial
Planner (CFP) based in India. You prepare concise, personalised financial
advisory reports for clients.

Your reports:
- Are written in clear, professional but warm English
- Use Indian financial terminology (SIP, corpus, lakh, crore, CAGR, XIRR)
- Quote all amounts in ₹ with lakh/crore suffixes where appropriate
- Are grounded in the data provided — never invent numbers
- Include a brief risk disclaimer at the end (SEBI compliance)
- Are structured with clear section headings

Current financial context for India (2025):
- Repo rate: ~6.5%; risk-free rate ~6.5%
- Long-term equity CAGR assumption: 12% (large cap), 14% (flexi/small cap)
- Inflation: ~5-6% general, ~8% education
"""

ADVISORY_USER_TEMPLATE = """\
Please write a complete financial advisory report for the following client.

{client_block}

{goals_block}

{portfolio_block}

{optimiser_block}

The report should cover:
1. Executive Summary (2-3 sentences personalised to the client)
2. Risk Profile Assessment — explain what {risk_profile} means for this client
3. Goal Analysis — review each goal, feasibility, and SIP adequacy
4. Portfolio Review — comment on current holdings, gains, and gaps
5. Recommended Optimised Allocation — explain the optimiser's suggested weights
   in plain language, and why each fund suits this client's profile
6. Action Plan — numbered list of 5-7 concrete next steps
7. Risk Disclaimer (standard SEBI-style, 3-4 lines)

Be concise but complete. Write for a financially literate but non-expert reader.
"""


def stream_advisory_narrative(
    client_data: dict,
    goals: list[dict],
    portfolio: dict,
    opt_result=None,
) -> Generator[str, None, None]:
    """
    Stream a full advisory narrative for a client.

    Parameters
    ----------
    client_data : dict
        Keys: name, age, annual_income, monthly_income, dependants,
              risk_profile, risk_score
    goals : list[dict]
        Each dict: name, goal_type, target_amount, years_to_goal,
                   future_value, adjusted_sip
    portfolio : dict
        Keys: num_holdings, total_invested, total_current,
              absolute_gain, gain_percentage, holdings
    opt_result : OptimiserResult or None
        Output from optimiser_engine; None if optimiser not run

    Yields
    ------
    str : text chunks from the Claude API stream
    """
    client_block  = _build_client_context_block(client_data)
    goals_block   = _build_goals_block(goals)
    portfolio_block = _build_portfolio_block(portfolio)
    optimiser_block = _build_optimiser_block(opt_result)

    user_prompt = ADVISORY_USER_TEMPLATE.format(
        client_block=client_block,
        goals_block=goals_block,
        portfolio_block=portfolio_block,
        optimiser_block=optimiser_block,
        risk_profile=client_data.get("risk_profile", "Moderate"),
    )

    client = _get_anthropic_client()

    try:
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=ADVISORY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text_chunk in stream.text_stream:
                yield text_chunk
    except Exception as exc:
        logger.error("Claude API streaming failed: %s", exc)
        yield f"\n[Advisory generation failed: {exc}]"


def get_advisory_narrative(
    client_data: dict,
    goals: list[dict],
    portfolio: dict,
    opt_result=None,
) -> str:
    """
    Non-streaming wrapper. Returns the full advisory as a single string.
    Useful for CLI demos and tests.
    """
    return "".join(
        stream_advisory_narrative(client_data, goals, portfolio, opt_result)
    )


# ── 2. Natural-language constraint parser ─────────────────────────────────────

CONSTRAINT_SYSTEM_PROMPT = """\
You are a financial portfolio constraint parser. Your ONLY job is to extract
numerical constraints from natural-language text and return them as JSON.

Always return a valid JSON object with these exact keys (all optional — omit
keys that are not mentioned):
  min_funds       : int    (minimum number of funds)
  max_funds       : int    (maximum number of funds)
  min_weight      : float  (minimum weight per fund as a decimal, e.g. 0.05)
  max_weight      : float  (maximum weight per fund as a decimal, e.g. 0.40)
  risk_free_rate  : float  (risk-free rate as decimal, e.g. 0.065)

Rules:
- Convert percentages to decimals: "25%" → 0.25
- Interpret "at least N funds" as min_funds=N
- Interpret "no more than N funds" as max_funds=N
- Return ONLY the JSON object. No explanation, no markdown fences.
"""

CONSTRAINT_USER_TEMPLATE = """\
Extract portfolio constraints from this text:

"{user_text}"

Return only the JSON object.
"""


def parse_optimiser_constraints(user_text: str) -> "OptimiserConstraints":
    """
    Parse natural-language constraint instructions into an OptimiserConstraints
    object via Claude.

    Parameters
    ----------
    user_text : str
        e.g. "I want at least 4 funds, max 25% in any single fund"

    Returns
    -------
    OptimiserConstraints with extracted values; defaults used for missing keys
    """
    # Import here to avoid circular dependency in tests
    from engine.optimiser_engine import OptimiserConstraints

    client = _get_anthropic_client()
    prompt = CONSTRAINT_USER_TEMPLATE.format(user_text=user_text)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=CONSTRAINT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip any accidental markdown fences
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)

        return OptimiserConstraints(
            min_funds=int(parsed.get("min_funds", 3)),
            max_funds=int(parsed.get("max_funds", 6)),
            min_weight=float(parsed.get("min_weight", 0.05)),
            max_weight=float(parsed.get("max_weight", 0.40)),
            risk_free_rate=float(parsed.get("risk_free_rate", 0.065)),
        )

    except json.JSONDecodeError as exc:
        logger.error("Failed to parse constraints JSON: %s | raw=%s", exc, raw)
        return OptimiserConstraints()
    except Exception as exc:
        logger.error("Constraint parsing failed: %s", exc)
        return OptimiserConstraints()


# ── 3. Portfolio optimisation explainer ───────────────────────────────────────

EXPLAIN_SYSTEM_PROMPT = """\
You are a financial advisor explaining a portfolio optimisation result to a
client in plain, jargon-free language. Be warm, clear, and specific.
Keep the explanation under 300 words.
"""

EXPLAIN_USER_TEMPLATE = """\
The portfolio optimiser recommended the following allocation for a client with
a {risk_profile} risk profile and these goals: {goal_names}.

Optimiser result:
{optimiser_summary}

Explain:
1. Why this mix was chosen (in terms of risk vs. return trade-off)
2. The role of each significant fund (>5% weight) in the portfolio
3. How this allocation suits the client's risk profile and goals
4. One or two things the client should watch out for

Write directly to the client, starting with "For your portfolio, the optimiser..."
"""


def explain_portfolio_optimisation(
    opt_result,
    risk_profile: str,
    goal_names: list[str],
) -> str:
    """
    Generate a plain-language explanation of the optimiser's output.

    Parameters
    ----------
    opt_result : OptimiserResult
    risk_profile : str   e.g. "Aggressive"
    goal_names : list[str]   e.g. ["Retirement", "Education"]

    Returns
    -------
    str — explanation text (non-streaming)
    """
    if opt_result is None:
        return "No optimiser result to explain."

    summary = (
        opt_result.summary()
        if hasattr(opt_result, "summary")
        else str(opt_result)
    )

    prompt = EXPLAIN_USER_TEMPLATE.format(
        risk_profile=risk_profile,
        goal_names=", ".join(goal_names) if goal_names else "general wealth creation",
        optimiser_summary=summary,
    )

    client = _get_anthropic_client()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=EXPLAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Optimisation explanation failed: %s", exc)
        return f"[Explanation unavailable: {exc}]"


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from engine.optimiser_engine import (
        FundStats, OptimiserConstraints, optimise_max_sharpe,
    )

    # Sample data matching the Phase 2 demo client
    sample_client = {
        "name": "Arjun Mehta",
        "age": 35,
        "annual_income": 2_400_000,
        "monthly_income": 200_000,
        "dependants": 2,
        "risk_profile": "Aggressive",
        "risk_score": 72,
    }

    sample_goals = [
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

    sample_portfolio = {
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

    sample_funds = [
        FundStats(100001, "Parag Parikh Flexi Cap",        0.14, 0.17),
        FundStats(100002, "Mirae Asset Large Cap",          0.12, 0.15),
        FundStats(100003, "Axis Small Cap",                0.16, 0.22),
        FundStats(100004, "HDFC Mid-Cap Opportunities",    0.15, 0.20),
        FundStats(100005, "ICICI Pru Balanced Advantage",  0.10, 0.10),
    ]

    opt = optimise_max_sharpe(sample_funds)
    print("\n─── OPTIMISER RESULT ───")
    print(opt.summary())

    print("\n─── CONSTRAINT PARSER TEST ───")
    test_text = "I want at least 4 funds, no single fund should exceed 30%"
    constraints = parse_optimiser_constraints(test_text)
    print(f"  Parsed: min_funds={constraints.min_funds}, "
          f"max_funds={constraints.max_funds}, "
          f"max_weight={constraints.max_weight:.0%}")

    print("\n─── OPTIMISATION EXPLAINER ───")
    explanation = explain_portfolio_optimisation(
        opt, "Aggressive", ["Retirement", "Education"]
    )
    print(explanation)

    print("\n─── STREAMING ADVISORY NARRATIVE ───")
    for chunk in stream_advisory_narrative(
        sample_client, sample_goals, sample_portfolio, opt
    ):
        print(chunk, end="", flush=True)
    print()
