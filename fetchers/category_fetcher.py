"""
fetchers/category_fetcher.py
-----------------------------
One-time script to populate category and sub_category in the funds table
by parsing SEBI-standard category names from scheme names.

AMFI scheme names follow predictable patterns:
  "Parag Parikh Flexi Cap Fund - Direct Growth"  -> Flexi Cap Fund
  "Axis Small Cap Fund - Direct Growth"           -> Small Cap Fund
  "HDFC Liquid Fund - Direct Growth"              -> Liquid Fund
  etc.

This script:
  1. Reads all funds with NULL category from the DB
  2. Matches scheme_name against known SEBI category keywords
  3. Updates category and sub_category in the funds table

Run once after the AMFI scheme master is loaded:
  PYTHONPATH=/Users/manavgupta/financial_advisor \
  FINANCIAL_ADVISOR_DB=/Users/manavgupta/financial_advisor/data/financial_advisor.db \
  python fetchers/category_fetcher.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE_PATH


# ---------------------------------------------------------------------------
# SEBI category keyword map
# Order matters -- more specific patterns first
# (scheme_name substring, category, sub_category)
# ---------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, str, str]] = [
    # Equity
    ("Large & Mid Cap",      "Large & Mid Cap Fund",      "Large & Mid Cap Fund"),
    ("Large and Mid Cap",    "Large & Mid Cap Fund",      "Large & Mid Cap Fund"),
    ("Multi Cap",            "Multi Cap Fund",            "Multi Cap Fund"),
    ("Flexi Cap",            "Flexi Cap Fund",            "Flexi Cap Fund"),
    ("Large Cap",            "Large Cap Fund",            "Large Cap Fund"),
    ("Mid Cap",              "Mid Cap Fund",              "Mid Cap Fund"),
    ("Small Cap",            "Small Cap Fund",            "Small Cap Fund"),
    ("Micro Cap",            "Small Cap Fund",            "Micro Cap Fund"),
    ("Dividend Yield",       "Dividend Yield Fund",       "Dividend Yield Fund"),
    ("Value Fund",           "Value Fund",                "Value Fund"),
    ("Contra Fund",          "Contra Fund",               "Contra Fund"),
    ("Focused Fund",         "Focused Fund",              "Focused Fund"),
    ("Sectoral",             "Sectoral/Thematic Fund",    "Sectoral Fund"),
    ("Thematic",             "Sectoral/Thematic Fund",    "Thematic Fund"),
    ("ELSS",                 "ELSS Fund",                 "ELSS Fund"),
    ("Tax Saver",            "ELSS Fund",                 "ELSS Fund"),
    ("Tax Saving",           "ELSS Fund",                 "ELSS Fund"),
    ("International",        "International Fund",        "International Fund"),
    ("Global",               "International Fund",        "International Fund"),
    ("Overseas",             "International Fund",        "International Fund"),
    ("ESG",                  "Sectoral/Thematic Fund",    "ESG Fund"),
    ("Infrastructure",       "Sectoral/Thematic Fund",    "Infrastructure Fund"),
    ("Banking",              "Sectoral/Thematic Fund",    "Banking Fund"),
    ("Technology",           "Sectoral/Thematic Fund",    "Technology Fund"),
    ("Pharma",               "Sectoral/Thematic Fund",    "Pharma Fund"),
    ("Healthcare",           "Sectoral/Thematic Fund",    "Healthcare Fund"),
    ("Consumption",          "Sectoral/Thematic Fund",    "Consumption Fund"),
    ("Manufacturing",        "Sectoral/Thematic Fund",    "Manufacturing Fund"),
    ("Energy",               "Sectoral/Thematic Fund",    "Energy Fund"),
    ("PSU",                  "Sectoral/Thematic Fund",    "PSU Fund"),
    ("Quant",                "Sectoral/Thematic Fund",    "Quant Fund"),
    # Hybrid
    ("Aggressive Hybrid",    "Aggressive Hybrid Fund",    "Aggressive Hybrid Fund"),
    ("Conservative Hybrid",  "Conservative Hybrid Fund",  "Conservative Hybrid Fund"),
    ("Balanced Advantage",   "Balanced Advantage Fund",   "Balanced Advantage Fund"),
    ("Dynamic Asset",        "Balanced Advantage Fund",   "Dynamic Asset Allocation"),
    ("Multi Asset",          "Multi Asset Allocation Fund","Multi Asset Allocation"),
    ("Equity Savings",       "Equity Savings Fund",       "Equity Savings Fund"),
    ("Arbitrage",            "Arbitrage Fund",            "Arbitrage Fund"),
    ("Hybrid",               "Aggressive Hybrid Fund",    "Hybrid Fund"),
    # Debt
    ("Overnight",            "Overnight Fund",            "Overnight Fund"),
    ("Liquid",               "Liquid Fund",               "Liquid Fund"),
    ("Ultra Short Duration", "Ultra Short Duration Fund", "Ultra Short Duration Fund"),
    ("Ultra Short Term",     "Ultra Short Duration Fund", "Ultra Short Duration Fund"),
    ("Low Duration",         "Low Duration Fund",         "Low Duration Fund"),
    ("Money Market",         "Money Market Fund",         "Money Market Fund"),
    ("Short Duration",       "Short Duration Fund",       "Short Duration Fund"),
    ("Short Term",           "Short Duration Fund",       "Short Term Fund"),
    ("Medium Duration",      "Medium Duration Fund",      "Medium Duration Fund"),
    ("Medium to Long",       "Medium to Long Duration Fund", "Medium to Long Duration Fund"),
    ("Long Duration",        "Long Duration Fund",        "Long Duration Fund"),
    ("Dynamic Bond",         "Dynamic Bond Fund",         "Dynamic Bond Fund"),
    ("Corporate Bond",       "Corporate Bond Fund",       "Corporate Bond Fund"),
    ("Credit Risk",          "Credit Risk Fund",          "Credit Risk Fund"),
    ("Banking & PSU",        "Banking and PSU Fund",      "Banking and PSU Fund"),
    ("Banking and PSU",      "Banking and PSU Fund",      "Banking and PSU Fund"),
    ("Gilt",                 "Gilt Fund",                 "Gilt Fund"),
    ("Floater",              "Floater Fund",              "Floater Fund"),
    ("Fixed Maturity",       "Fixed Maturity Plan",       "Fixed Maturity Plan"),
    ("FMP",                  "Fixed Maturity Plan",       "Fixed Maturity Plan"),
    # Index / ETF / FOF
    ("Index Fund",           "Index Fund",                "Index Fund"),
    ("ETF",                  "ETF",                       "ETF"),
    ("Exchange Traded",      "ETF",                       "ETF"),
    ("Fund of Fund",         "Fund of Funds",             "Fund of Funds"),
    ("Fund of Funds",        "Fund of Funds",             "Fund of Funds"),
    ("FOF",                  "Fund of Funds",             "Fund of Funds"),
    # Debt broad fallback
    ("Debt",                 "Short Duration Fund",       "Debt Fund"),
    ("Income",               "Medium Duration Fund",      "Income Fund"),
    ("Bond",                 "Corporate Bond Fund",       "Bond Fund"),
]


def classify_scheme(scheme_name: str) -> tuple[str, str]:
    """Return (category, sub_category) for a scheme name, or ('', '') if unmatched."""
    name_upper = scheme_name.upper()
    for keyword, category, sub_category in CATEGORY_RULES:
        if keyword.upper() in name_upper:
            return category, sub_category
    return "", ""


def populate_categories(dry_run: bool = False) -> dict:
    """Populate category and sub_category for all funds with NULL/empty category."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT scheme_code, scheme_name FROM funds "
            "WHERE category IS NULL OR category = ''"
        ).fetchall()

    total = len(rows)
    updated = 0
    unmatched = 0
    unmatched_examples = []

    updates = []
    for row in rows:
        category, sub_category = classify_scheme(row["scheme_name"])
        if category:
            updates.append((category, sub_category, row["scheme_code"]))
            updated += 1
        else:
            unmatched += 1
            if len(unmatched_examples) < 10:
                unmatched_examples.append(row["scheme_name"])

    if not dry_run and updates:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.executemany(
                "UPDATE funds SET category = ?, sub_category = ? WHERE scheme_code = ?",
                updates,
            )

    return {
        "total_funds": total,
        "updated": updated,
        "unmatched": unmatched,
        "unmatched_examples": unmatched_examples,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    print("Populating fund categories from scheme names...")
    result = populate_categories(dry_run=False)
    print(f"Total funds processed : {result['total_funds']}")
    print(f"Categories populated  : {result['updated']}")
    print(f"Unmatched (no category): {result['unmatched']}")
    if result["unmatched_examples"]:
        print("\nUnmatched examples (first 10):")
        for name in result["unmatched_examples"]:
            print(f"  {name}")
    print("\nDone. Run GET /funds/screen to verify.")
