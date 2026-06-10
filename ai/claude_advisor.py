"""
ai/claude_advisor.py
---------------------
Phase 4 — Claude AI Advisor Integration.

Provides three main capabilities:

1. stream_advisory_narrative()
   Full streaming advisory report for a client. Accepts either:
     - A single client_context dict (Phase 5 UI call pattern)
     - Four separate args: client_data, goals, portfolio, opt_result
       (original Phase 4 / CLI call pattern)

2. parse_optimiser_constraints()
   Natural-language constraint parsing via Claude.

3. explain_portfolio_optimisation()
   Plain-language streaming explanation of the optimiser result.
   Phase 5 fix: now a generator (yields str chunks) and accepts the
   kwargs pattern used by ui/pages/04_optimiser.py.

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
                "ANTHROPIC_API_KEY not set. Add it to your .env file or Streamlit Secrets."
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
        return f"\u20b9{amount / 1e7:.2f} Cr"
    elif amount >= 1e5:
        return f"\u20b9{amount / 1e5:.2f} L"
    else:
        return f"\u20b9{amount:,.0f}"


def _build_client_context_block(client_data: dict) -> str:
    return f"""
CLIENT PROFILE
==============
Name              : {client_data.get('name', 'N/A')}
Age               : {client_data.get('age', 'N/A')} years
Annual Income     : {_inr(client_data.get('annual_income', 0))}
Monthly Income    : {_inr(client_data.get('monthly_income', client_data.get('annual_income', 0) / 12))}
Dependants        : {client_data.get('dependants', 0)}
Risk Profile      : {client_data.get('risk_profile', 'Moderate')}
Risk Score        : {client_data.get('risk_score', 0)}/100
""".strip()


def _build_goals_block(goals: list[dict]) -> str:
    if not goals:
        return "No goals defined."
    lines = ["FINANCIAL GOALS", "=============="]
    for i, g in enumerate(goals, 1):
        lines.append(
            f"{i}. {g.get('name', g.get('goal_name', 'Goal'))} ({g.get('type', g.get('goal_type', ''))})\n"
            f"   Target          : {_inr(g.get('target_amount', g.get('target', 0)))}\n"
            f"   Future Value    : {_inr(g.get('future_value', g.get('target_amount', 0)))}\n"
            f"   Time Horizon    : {g.get('years_to_goal', 0)} years\n"
            f"   Monthly SIP     : {_inr(g.get('adjusted_sip', g.get('monthly_sip', 0)))}"
        )
    return "\n".join(lines)


def _build_portfolio_block(portfolio: dict) -> str:
    if not portfolio or not portfolio.get("num_holdings"):
        return "Portfolio: No holdings yet."
    lines = [
        "CURRENT PORTFOLIO",
        "=================",
        f"Holdings        : {portfolio['num_holdings']}",
        f"Total Invested  : {_inr(portfolio['total_invested'])}",
        f"Current Value   : {_inr(portfolio['total_current'])}",
        f"Gain / Loss     : {_inr(portfolio['absolute_gain'])} "
        f"({portfolio.get('gain_pct', portfolio.get('gain_percentage', 0)):.1f}%)",
    ]
    holdings = portfolio.get("holdings", [])
    if holdings:
        lines.append("")
        lines.append("Holdings detail:")
        for h in holdings:
            lines.append(
                f"  \u2022 {h.get('name', h.get('scheme_name', 'Unknown'))[:50]} \u2014 "
                f"Invested {_inr(h.get('invested', h.get('invested_amount', 0)))}, "
                f"Current {_inr(h.get('current', h.get('current_value', 0)))}"
            )
    return "\n".join(lines)


def _build_optimiser_block(opt_result) -> str:
    if opt_result is None:
        return "Optimiser: Not run."
    if hasattr(opt_result, "summary"):
        return f"OPTIMISER RESULT\n================\n{opt_result.summary()}"
    return f"OPTIMISER RESULT\n================\n{json.dumps(opt_result, indent=2)}"


# ── 1. Streaming advisory narrative ──────────────────────────────────────────

ADVISORY_SYSTEM_PROMPT = """\
You are a senior SEBI-registered Mutual Fund Distributor and Certified Financial
Planner (CFP) based in India. You prepare concise, personalised financial
advisory reports for clients.

Your reports:
- Are written in clear, professional but warm English
- Use Indian financial terminology (SIP, corpus, lakh, crore, CAGR, XIRR)
- Quote all amounts in \u20b9 with lakh/crore suffixes where appropriate
- Are grounded in the data provided \u2014 never invent numbers
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
2. Risk Profile Assessment \u2014 explain what {risk_profile} means for this client
3. Goal Analysis \u2014 review each goal, feasibility, and SIP adequacy
4. Portfolio Review \u2014 comment on current holdings, gains, and gaps
5. Recommended Optimised Allocation \u2014 explain the optimiser's suggested weights
   in plain language, and why each fund suits this client's profile
6. Action Plan \u2014 numbered list of 5-7 concrete next steps
7. Risk Disclaimer (standard SEBI-style, 3-4 lines)

Be concise but complete. Write for a financially literate but non-expert reader.
"""


def stream_advisory_narrative(
    client_data: dict = None,
    goals: list = None,
    portfolio: dict = None,
    opt_result=None,
    # Phase 5 UI call pattern: single bundled dict
    client_context: dict = None,
) -> Generator[str, None, None]:
    """
    Stream a full advisory narrative for a client.

    Two supported call patterns:

    Pattern A (Phase 5 UI):
        stream_advisory_narrative(client_context={
            'client': {...},
            'goals': [...],
            'portfolio': {...},
            'performance': {...},
            'holdings': [...],
            'report_date': '...',
            'requested_sections': [...],
        })

    Pattern B (original / CLI):
        stream_advisory_narrative(client_data, goals, portfolio, opt_result)

    Yields str chunks from the Claude API stream.
    """
    # --- Unpack Pattern A ---
    if client_context is not None:
        client_data = client_context.get("client", {})
        raw_goals   = client_context.get("goals", [])
        # Goals from Pattern A are dicts with keys: name, type, target,
        # target_year, monthly_sip.  Normalise to the standard format.
        goals = [
            {
                "name":          g.get("name") or g.get("goal_name", "Goal"),
                "goal_type":     g.get("type") or g.get("goal_type", ""),
                "target_amount": g.get("target") or g.get("target_amount", 0),
                "future_value":  g.get("target") or g.get("target_amount", 0),
                "years_to_goal": 0,
                "adjusted_sip":  g.get("monthly_sip", 0),
            }
            for g in raw_goals
        ]
        raw_portfolio  = client_context.get("portfolio", {})
        raw_holdings   = client_context.get("holdings", [])
        # Merge portfolio totals with holdings detail list
        portfolio = {
            **raw_portfolio,
            "holdings": [
                {"name": h.get("name"), "invested": h.get("invested", 0), "current": h.get("current", 0)}
                for h in raw_holdings
            ],
        }
        opt_result = None  # Not passed through Pattern A

    # --- Fallback defaults ---
    if client_data is None:
        client_data = {}
    if goals is None:
        goals = []
    if portfolio is None:
        portfolio = {}

    client_block    = _build_client_context_block(client_data)
    goals_block     = _build_goals_block(goals)
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
    """Non-streaming wrapper. Returns the full advisory as a single string."""
    return "".join(
        stream_advisory_narrative(client_data, goals, portfolio, opt_result)
    )


# ── 2. Natural-language constraint parser ─────────────────────────────────────

CONSTRAINT_SYSTEM_PROMPT = """\
You are a financial portfolio constraint parser. Your ONLY job is to extract
numerical constraints from natural-language text and return them as JSON.

Always return a valid JSON object with these exact keys (all optional \u2014 omit
keys that are not mentioned):
  min_funds       : int    (minimum number of funds)
  max_funds       : int    (maximum number of funds)
  min_weight      : float  (minimum weight per fund as a decimal, e.g. 0.05)
  max_weight      : float  (maximum weight per fund as a decimal, e.g. 0.40)
  risk_free_rate  : float  (risk-free rate as decimal, e.g. 0.065)

Rules:
- Convert percentages to decimals: "25%" \u2192 0.25
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
    """
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
        logger.error("Failed to parse constraints JSON: %s", exc)
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
A portfolio optimiser produced the following allocation.

Optimiser metrics:
  Expected Return : {ret:.2%}
  Volatility      : {vol:.2%}
  Sharpe Ratio    : {sharpe:.2f}
  Objective       : {objective}

Fund weights:
{weights_lines}

Fund statistics:
{fund_stats_lines}

Explain:
1. Why this mix was chosen (risk vs. return trade-off)
2. The role of each significant fund (>5% weight) in the portfolio
3. One or two things the client should watch out for

Write directly to the client, starting with "For your portfolio, the optimiser..."
"""


def explain_portfolio_optimisation(
    # Pattern A: kwargs from ui/pages/04_optimiser.py
    optimised_weights: dict = None,
    portfolio_metrics: dict = None,
    fund_stats: list = None,
    constraints: dict = None,
    objective: str = None,
    # Pattern B: original positional args
    opt_result=None,
    risk_profile: str = None,
    goal_names: list = None,
) -> Generator[str, None, None]:
    """
    Generate a plain-language streaming explanation of the optimiser's output.

    Two call patterns:

    Pattern A (Phase 5 UI — page 04):
        for chunk in explain_portfolio_optimisation(
            optimised_weights={...},
            portfolio_metrics={"return":...,"volatility":...,"sharpe":...},
            fund_stats=[{"name":...,"return":...,"vol":...},...],
            constraints={...},
            objective="max_sharpe",
        ):
            ...

    Pattern B (original):
        text = explain_portfolio_optimisation(opt_result, risk_profile, goal_names)
    """
    # --- Build prompt from Pattern A ---
    if optimised_weights is not None:
        metrics = portfolio_metrics or {}
        ret     = metrics.get("return", 0.0)
        vol     = metrics.get("volatility", 0.0)
        sharpe  = metrics.get("sharpe", 0.0)
        obj_str = objective or "max_sharpe"

        weights_lines = "\n".join(
            f"  {name}: {w*100:.1f}%"
            for name, w in sorted(optimised_weights.items(), key=lambda x: x[1], reverse=True)
        )
        fs_lines = "\n".join(
            f"  {f.get('name','?')}: return={f.get('return',0):.1%}, vol={f.get('vol',0):.1%}"
            for f in (fund_stats or [])
        )
        prompt = EXPLAIN_USER_TEMPLATE.format(
            ret=ret, vol=vol, sharpe=sharpe, objective=obj_str,
            weights_lines=weights_lines,
            fund_stats_lines=fs_lines if fs_lines else "  (not available)",
        )

    # --- Build prompt from Pattern B ---
    elif opt_result is not None:
        summary = (
            opt_result.summary() if hasattr(opt_result, "summary") else str(opt_result)
        )
        prompt = (
            f"Explain this portfolio optimisation result in plain language.\n\n"
            f"Risk profile: {risk_profile or 'Moderate'}\n"
            f"Goals: {', '.join(goal_names) if goal_names else 'general wealth creation'}\n\n"
            f"{summary}\n\n"
            f"Start with: 'For your portfolio, the optimiser...'"
        )
    else:
        yield "No optimiser result to explain."
        return

    client = _get_anthropic_client()

    try:
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=EXPLAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text_chunk in stream.text_stream:
                yield text_chunk
    except Exception as exc:
        logger.error("Optimisation explanation failed: %s", exc)
        yield f"[Explanation unavailable: {exc}]"


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from engine.optimiser_engine import (
        FundStats, OptimiserConstraints, optimise_max_sharpe,
    )

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
    ]

    sample_portfolio = {
        "num_holdings": 2,
        "total_invested": 1_260_000,
        "total_current": 1_390_000,
        "absolute_gain": 130_000,
        "gain_percentage": 10.32,
        "holdings": [
            {"scheme_name": "Parag Parikh Flexi Cap", "invested_amount": 660_000, "current_value": 750_000},
        ],
    }

    sample_funds = [
        FundStats(100001, "Parag Parikh Flexi Cap", 0.14, 0.17),
        FundStats(100002, "Mirae Asset Large Cap",  0.12, 0.15),
        FundStats(100003, "Axis Small Cap",          0.16, 0.22),
    ]

    opt = optimise_max_sharpe(sample_funds)
    print("\n\u2500\u2500\u2500 STREAMING ADVISORY NARRATIVE \u2500\u2500\u2500")
    for chunk in stream_advisory_narrative(sample_client, sample_goals, sample_portfolio, opt):
        print(chunk, end="", flush=True)
    print()

    print("\n\u2500\u2500\u2500 EXPLAIN (Pattern A) \u2500\u2500\u2500")
    for chunk in explain_portfolio_optimisation(
        optimised_weights={"Parag Parikh Flexi Cap": 0.5, "Mirae Asset Large Cap": 0.3, "Axis Small Cap": 0.2},
        portfolio_metrics={"return": 0.13, "volatility": 0.16, "sharpe": 1.2},
        fund_stats=[{"name": "Parag Parikh", "return": 0.14, "vol": 0.17}],
        objective="max_sharpe",
    ):
        print(chunk, end="", flush=True)
    print()
