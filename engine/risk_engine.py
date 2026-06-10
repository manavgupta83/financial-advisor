"""
engine/risk_engine.py
---------------------
Risk profiling engine for the AI Financial Advisory Tool.

Responsibilities:
  - Define the 10-question SEBI-aligned risk questionnaire
  - Score each response and compute a total risk score
  - Map the score to a risk profile (Conservative / Moderate / Aggressive / Very Aggressive)
  - Factor in age-based and income-based guardrails (SEBI guidelines)
  - Return a structured RiskProfile dataclass used downstream by goal + recommendation engines

Risk profiles:
  Score 0-25  → Conservative
  Score 26-45 → Moderate
  Score 46-65 → Aggressive
  Score 66-80 → Very Aggressive

Age guardrail: investors 55+ are capped at Moderate regardless of questionnaire score.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskCategory(str, Enum):
    CONSERVATIVE    = "Conservative"
    MODERATE        = "Moderate"
    AGGRESSIVE      = "Aggressive"
    VERY_AGGRESSIVE = "Very Aggressive"


# ---------------------------------------------------------------------------
# Questionnaire definition
# ---------------------------------------------------------------------------

QUESTIONNAIRE: list[dict] = [
    {
        "id": 1,
        "question": "What is your primary investment objective?",
        "options": [
            {"text": "Preserve capital — I cannot afford to lose money", "score": 4},
            {"text": "Generate steady income with minimal risk",           "score": 8},
            {"text": "Balanced growth and income",                         "score": 12},
            {"text": "Long-term capital growth",                           "score": 16},
            {"text": "Maximum growth — I can handle high volatility",      "score": 20},
        ],
    },
    {
        "id": 2,
        "question": "How long can you stay invested before needing this money?",
        "options": [
            {"text": "Less than 1 year",    "score": 2},
            {"text": "1–3 years",            "score": 4},
            {"text": "3–5 years",            "score": 6},
            {"text": "5–10 years",           "score": 8},
            {"text": "More than 10 years",   "score": 10},
        ],
    },
    {
        "id": 3,
        "question": "If your portfolio dropped 20% in a month, what would you do?",
        "options": [
            {"text": "Sell everything immediately",                               "score": 2},
            {"text": "Sell some to cut losses",                                   "score": 4},
            {"text": "Do nothing and wait",                                       "score": 6},
            {"text": "Buy a little more at lower prices",                         "score": 8},
            {"text": "Invest significantly more — great buying opportunity",      "score": 10},
        ],
    },
    {
        "id": 4,
        "question": "What percentage of your monthly income do you invest?",
        "options": [
            {"text": "Less than 5%",    "score": 2},
            {"text": "5–10%",           "score": 4},
            {"text": "10–20%",          "score": 6},
            {"text": "20–30%",          "score": 8},
            {"text": "More than 30%",   "score": 10},
        ],
    },
    {
        "id": 5,
        "question": "How stable is your current income source?",
        "options": [
            {"text": "Very unstable — freelance / commission-only",        "score": 2},
            {"text": "Somewhat unstable — contract / seasonal",            "score": 4},
            {"text": "Moderately stable — small business / self-employed", "score": 6},
            {"text": "Stable — salaried employee",                         "score": 8},
            {"text": "Very stable — government / PSU / top MNC",          "score": 10},
        ],
    },
    {
        "id": 6,
        "question": "Do you have an emergency fund covering 6+ months of expenses?",
        "options": [
            {"text": "No emergency fund at all",         "score": 2},
            {"text": "Less than 3 months covered",       "score": 4},
            {"text": "3–6 months covered",               "score": 6},
            {"text": "6–12 months covered",              "score": 8},
            {"text": "More than 12 months covered",      "score": 10},
        ],
    },
    {
        "id": 7,
        "question": "What is your investment experience?",
        "options": [
            {"text": "No experience — first time investor",                   "score": 2},
            {"text": "Some experience — only FDs / PPF / savings",           "score": 4},
            {"text": "Moderate — mutual funds for a few years",               "score": 6},
            {"text": "Good — diversified MF portfolio for 5+ years",         "score": 8},
            {"text": "Extensive — direct stocks, derivatives, global funds",  "score": 10},
        ],
    },
    {
        "id": 8,
        "question": "What best describes your current debt situation?",
        "options": [
            {"text": "Heavy debt — EMIs exceed 50% of income",          "score": 1},
            {"text": "Moderate debt — EMIs 30–50% of income",           "score": 3},
            {"text": "Manageable debt — EMIs 15–30% of income",         "score": 5},
            {"text": "Light debt — home loan only",                     "score": 7},
            {"text": "Debt-free",                                        "score": 10},
        ],
    },
    {
        "id": 9,
        "question": "Which statement best reflects your attitude toward risk and return?",
        "options": [
            {"text": "I prefer guaranteed returns even if low",                    "score": 2},
            {"text": "Slightly higher return is okay if risk is very small",      "score": 4},
            {"text": "I accept moderate fluctuations for moderate gains",         "score": 6},
            {"text": "I accept large swings for potentially high returns",        "score": 8},
            {"text": "I actively seek high-risk high-reward opportunities",       "score": 10},
        ],
    },
    {
        "id": 10,
        "question": "Which best describes your tax planning approach?",
        "options": [
            {"text": "I only use 80C instruments (PPF, NSC, FD)",                  "score": 2},
            {"text": "80C + NPS + basic ELSS",                                    "score": 4},
            {"text": "ELSS, NPS, and some direct equity",                         "score": 6},
            {"text": "Optimise across LTCG, STCG, debt indexation",              "score": 8},
            {"text": "Sophisticated — ESOP planning, HUF, trust structures",     "score": 10},
        ],
    },
]

# Score-to-profile mapping boundaries (inclusive lower bound)
SCORE_BANDS: list[tuple[int, int, RiskCategory]] = [
    (0,  25, RiskCategory.CONSERVATIVE),
    (26, 45, RiskCategory.MODERATE),
    (46, 65, RiskCategory.AGGRESSIVE),
    (66, 80, RiskCategory.VERY_AGGRESSIVE),
]

# Age beyond which profile is capped at Moderate
AGE_GUARDRAIL_THRESHOLD = 55


# ---------------------------------------------------------------------------
# RiskProfile dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskProfile:
    raw_score:          int
    adjusted_score:     int
    category:           RiskCategory
    age_capped:         bool           = False
    responses:          dict[int, int] = field(default_factory=dict)  # q_id → chosen score
    notes:              list[str]      = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine functions
# ---------------------------------------------------------------------------

def get_questionnaire() -> list[dict]:
    """Return the full questionnaire for rendering in UI or CLI."""
    return QUESTIONNAIRE


def score_responses(responses: dict[int, int]) -> int:
    """
    Validate and sum scores from a dict of {question_id: option_index (0-based)}.
    Raises ValueError if any question is missing or option index is out of range.
    """
    total = 0
    for q in QUESTIONNAIRE:
        qid = q["id"]
        if qid not in responses:
            raise ValueError(f"Missing response for question {qid}")
        idx = responses[qid]
        options = q["options"]
        if not (0 <= idx < len(options)):
            raise ValueError(
                f"Invalid option index {idx} for question {qid} "
                f"(valid: 0–{len(options) - 1})"
            )
        total += options[idx]["score"]
    return total


def _score_to_category(score: int) -> RiskCategory:
    for lo, hi, cat in SCORE_BANDS:
        if lo <= score <= hi:
            return cat
    # Score beyond 80 → Very Aggressive
    return RiskCategory.VERY_AGGRESSIVE


def compute_risk_profile(
    responses: dict[int, int],
    age: int,
    annual_income: float,
    dependants: int = 0,
) -> RiskProfile:
    """
    Core function: compute a complete RiskProfile from questionnaire responses
    and demographic inputs.

    Parameters
    ----------
    responses       : dict mapping question_id (1-based) → chosen option index (0-based)
    age             : client's age in years
    annual_income   : annual gross income in INR
    dependants      : number of financial dependants (adjusts score down slightly)

    Returns
    -------
    RiskProfile dataclass
    """
    notes: list[str] = []

    # 1. Score raw responses
    raw_score = score_responses(responses)

    # 2. Dependants adjustment: -2 per dependant beyond 1, max -6
    dep_adjustment = min(max(dependants - 1, 0) * 2, 6)
    adjusted_score = max(raw_score - dep_adjustment, 0)
    if dep_adjustment > 0:
        notes.append(
            f"Score reduced by {dep_adjustment} points due to {dependants} dependants."
        )

    # 3. Income floor guard: very low income → cap at Moderate
    if annual_income < 300_000:  # < ₹3 LPA
        if adjusted_score > 45:
            adjusted_score = 45
            notes.append(
                "Score capped at Moderate band: annual income below ₹3 LPA."
            )

    # 4. Determine category from adjusted score
    category = _score_to_category(adjusted_score)

    # 5. Age guardrail: 55+ → cap at Moderate
    age_capped = False
    if age >= AGE_GUARDRAIL_THRESHOLD and category in (
        RiskCategory.AGGRESSIVE, RiskCategory.VERY_AGGRESSIVE
    ):
        category = RiskCategory.MODERATE
        age_capped = True
        notes.append(
            f"Profile capped at Moderate: client is {age} years old "
            f"(guardrail applies at {AGE_GUARDRAIL_THRESHOLD}+)."
        )

    return RiskProfile(
        raw_score=raw_score,
        adjusted_score=adjusted_score,
        category=category,
        age_capped=age_capped,
        responses=responses,
        notes=notes,
    )


def describe_profile(profile: RiskProfile) -> str:
    """Return a human-readable description of a risk profile."""
    descriptions = {
        RiskCategory.CONSERVATIVE: (
            "You prefer capital preservation over growth. "
            "Recommended allocation: 70–80% debt, 20–30% equity. "
            "Suitable instruments: liquid funds, short-duration debt funds, conservative hybrid funds."
        ),
        RiskCategory.MODERATE: (
            "You seek a balance between stability and growth. "
            "Recommended allocation: 50–60% equity, 40–50% debt. "
            "Suitable instruments: balanced advantage funds, large-cap funds, flexi-cap funds."
        ),
        RiskCategory.AGGRESSIVE: (
            "You are comfortable with market volatility in pursuit of long-term wealth creation. "
            "Recommended allocation: 70–80% equity, 20–30% debt. "
            "Suitable instruments: flexi-cap, mid-cap, multi-cap, international funds."
        ),
        RiskCategory.VERY_AGGRESSIVE: (
            "You actively seek maximum long-term returns and can tolerate significant short-term losses. "
            "Recommended allocation: 85–90% equity, 10–15% debt/alternatives. "
            "Suitable instruments: small-cap, sectoral/thematic, international, momentum funds."
        ),
    }
    lines = [
        f"Risk Profile  : {profile.category.value}",
        f"Raw Score     : {profile.raw_score} / 80",
        f"Adjusted Score: {profile.adjusted_score} / 80",
        "",
        descriptions[profile.category],
    ]
    if profile.notes:
        lines.append("")
        lines.append("Guardrails applied:")
        for note in profile.notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)