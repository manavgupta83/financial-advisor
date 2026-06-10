"""
ai/sector_llm.py
-----------------
Phase 4 — LLM Sector Classification Fallback.

When a stock/security in a fund's holdings cannot be mapped to a sector via
the local sector_map table (populated in Phase 1 from AMFI/NSE data),
this module calls Claude to infer the most likely SEBI sector classification.

Capabilities
------------
1. classify_single()
   Classify one security by name (and optionally ISIN).

2. classify_batch()
   Classify a list of securities in a single API call (cost-efficient).
   Returns a dict {isin_or_name: sector_label}.

3. enrich_holdings_with_sectors()
   Takes a list of holding dicts (from holdings_fetcher), checks the local
   DB first, and calls the LLM only for misses. Updates the sector_map table.

SEBI sector labels used (consistent with Phase 3 sector_engine.py)
-------------------------------------------------------------------
Financial Services, Information Technology, Consumer Goods, Automobiles,
Pharma & Healthcare, Energy & Power, Metals & Mining, Infrastructure,
Real Estate, Telecom, Chemicals, FMCG, Media & Entertainment,
Agriculture, Services, Sovereign / Government, International / Foreign,
Other

Design decisions
----------------
- Batch calls with up to 50 securities per request to minimise API cost
- Response parsed as JSON; falls back to "Other" on parse failure
- Results cached in memory (same process) to avoid duplicate calls
- DB write is optional — pass db_path=None to skip persistence
- Uses claude-sonnet-4-20250514 (cheap, fast, accurate for classification)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

SEBI_SECTORS = [
    "Financial Services",
    "Information Technology",
    "Consumer Goods",
    "Automobiles",
    "Pharma & Healthcare",
    "Energy & Power",
    "Metals & Mining",
    "Infrastructure",
    "Real Estate",
    "Telecom",
    "Chemicals",
    "FMCG",
    "Media & Entertainment",
    "Agriculture",
    "Services",
    "Sovereign / Government",
    "International / Foreign",
    "Other",
]

SECTOR_LABEL_SET = set(SEBI_SECTORS)
BATCH_SIZE = 50   # max securities per Claude call

# In-process cache: {isin_or_name_key: sector_label}
_sector_cache: dict[str, str] = {}


# ── Anthropic client ──────────────────────────────────────────────────────────

def _get_anthropic_client():
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


# ── Prompt templates ──────────────────────────────────────────────────────────

CLASSIFY_SYSTEM_PROMPT = f"""\
You are a financial data specialist who classifies Indian stock market
securities into SEBI-approved sector categories.

You MUST use ONLY the following sector labels (exact spelling):
{json.dumps(SEBI_SECTORS, indent=2)}

Rules:
- Foreign / overseas securities → "International / Foreign"
- Government securities, T-bills, G-Secs → "Sovereign / Government"
- If genuinely unclear → "Other"
- Return ONLY valid JSON. No explanation, no markdown fences.
"""

CLASSIFY_BATCH_USER_TEMPLATE = """\
Classify each security below into one of the allowed sectors.

Input securities (as a JSON list of objects with "key", "name", "isin"):
{securities_json}

Return a JSON object where each key matches the "key" field from input,
and the value is the sector label string.

Example format:
{{"key1": "Information Technology", "key2": "Financial Services"}}
"""


# ── Core classification logic ─────────────────────────────────────────────────

def _make_key(name: str, isin: Optional[str]) -> str:
    """Stable cache key for a security."""
    return (isin or "").strip().upper() or name.strip().upper()


def _normalise_sector(raw: str) -> str:
    """Map Claude's response to a known sector; fallback to 'Other'."""
    raw = raw.strip()
    if raw in SECTOR_LABEL_SET:
        return raw
    # Fuzzy normalisation for common variations
    raw_lower = raw.lower()
    for label in SEBI_SECTORS:
        if label.lower() in raw_lower or raw_lower in label.lower():
            return label
    logger.warning("Unknown sector label '%s'; mapping to 'Other'", raw)
    return "Other"


def classify_batch_via_llm(
    securities: list[dict],   # each: {"name": str, "isin": str | None}
) -> dict[str, str]:
    """
    Classify a batch of securities via a single Claude API call.

    Parameters
    ----------
    securities : list of dicts
        Each dict must have at least a "name" key; "isin" is optional.

    Returns
    -------
    dict mapping the security's cache key to its sector label.
    """
    if not securities:
        return {}

    client = _get_anthropic_client()

    # Build the input list with stable keys
    items = []
    key_to_cache_key = {}
    for i, sec in enumerate(securities):
        cache_key = _make_key(sec["name"], sec.get("isin"))
        row_key = f"s{i}"
        items.append({
            "key": row_key,
            "name": sec["name"],
            "isin": sec.get("isin") or "",
        })
        key_to_cache_key[row_key] = cache_key

    prompt = CLASSIFY_BATCH_USER_TEMPLATE.format(
        securities_json=json.dumps(items, ensure_ascii=False, indent=2)
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=CLASSIFY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()

        # Strip accidental markdown fences
        raw_text = re.sub(r"```(?:json)?", "", raw_text).strip().rstrip("`").strip()
        parsed: dict[str, str] = json.loads(raw_text)

        result: dict[str, str] = {}
        for row_key, raw_sector in parsed.items():
            cache_key = key_to_cache_key.get(row_key)
            if cache_key:
                sector = _normalise_sector(raw_sector)
                result[cache_key] = sector
                _sector_cache[cache_key] = sector

        return result

    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse sector classification JSON: %s | raw=%s",
            exc, raw_text[:200]
        )
        # Fallback: mark everything as "Other"
        return {key_to_cache_key[item["key"]]: "Other" for item in items}
    except Exception as exc:
        logger.error("Sector LLM call failed: %s", exc)
        return {key_to_cache_key[item["key"]]: "Other" for item in items}


def classify_single(name: str, isin: Optional[str] = None) -> str:
    """
    Classify a single security. Checks in-memory cache first.

    Parameters
    ----------
    name : str    Security / company name
    isin : str | None

    Returns
    -------
    str — sector label
    """
    cache_key = _make_key(name, isin)
    if cache_key in _sector_cache:
        return _sector_cache[cache_key]

    result = classify_batch_via_llm([{"name": name, "isin": isin}])
    return result.get(cache_key, "Other")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _fetch_known_sectors(db_path: str, isins: list[str]) -> dict[str, str]:
    """
    Query the sector_map table for a list of ISINs.
    Returns {isin: sector_name}.
    """
    if not isins or not db_path:
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            placeholders = ",".join("?" for _ in isins)
            rows = conn.execute(
                f"SELECT isin, sector_name FROM sector_map WHERE isin IN ({placeholders})",
                isins,
            ).fetchall()
            return {row[0]: row[1] for row in rows}
    except sqlite3.Error as exc:
        logger.error("DB sector lookup failed: %s", exc)
        return {}


def _upsert_sectors(db_path: str, sector_map: dict[str, str]) -> None:
    """
    Upsert {isin_or_name: sector} into the sector_map table.
    Uses isin as the primary identifier; uses name as fallback.
    """
    if not sector_map or not db_path:
        return
    try:
        with sqlite3.connect(db_path) as conn:
            for isin_or_name, sector in sector_map.items():
                # Only upsert rows that look like valid ISINs (12 chars)
                if len(isin_or_name) == 12 and isin_or_name[:2].isalpha():
                    conn.execute(
                        """
                        INSERT INTO sector_map (isin, sector_name)
                        VALUES (?, ?)
                        ON CONFLICT(isin) DO UPDATE SET sector_name=excluded.sector_name
                        """,
                        (isin_or_name, sector),
                    )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error("DB sector upsert failed: %s", exc)


# ── Public high-level function ────────────────────────────────────────────────

def enrich_holdings_with_sectors(
    holdings: list[dict],
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    Given a list of holding dicts (from holdings_fetcher or fund_holdings table),
    ensure each holding has a 'sector' key populated.

    Strategy:
    1. Check in-memory cache
    2. Check DB sector_map (if db_path provided)
    3. Call LLM for remaining unknowns (in batches of BATCH_SIZE)
    4. Persist new mappings back to DB

    Parameters
    ----------
    holdings : list of dicts
        Each dict must have: 'stock_name' (str), 'isin' (str, optional).
        May already have 'sector' (str) — those are skipped.

    db_path : str | None
        Path to the SQLite database. If None, DB lookup/write is skipped.

    Returns
    -------
    list of dicts — same as input but with 'sector' populated on every row.
    """
    if not holdings:
        return holdings

    enriched = [dict(h) for h in holdings]   # shallow copy

    # --- Step 1: Identify unknowns ------------------------------------------
    unknowns: list[tuple[int, dict]] = []    # (index, holding)
    isins_to_fetch: list[str] = []

    for idx, h in enumerate(enriched):
        if h.get("sector"):
            continue  # Already classified
        isin = (h.get("isin") or "").strip().upper()
        name = h.get("stock_name", "").strip()
        cache_key = _make_key(name, isin)
        if cache_key in _sector_cache:
            h["sector"] = _sector_cache[cache_key]
        else:
            unknowns.append((idx, h))
            if isin:
                isins_to_fetch.append(isin)

    if not unknowns:
        return enriched

    # --- Step 2: DB lookup --------------------------------------------------
    db_sectors: dict[str, str] = {}
    if db_path and isins_to_fetch:
        db_sectors = _fetch_known_sectors(db_path, isins_to_fetch)
        for isin, sector in db_sectors.items():
            _sector_cache[isin] = sector

    # Apply DB results
    still_unknown: list[tuple[int, dict]] = []
    for idx, h in unknowns:
        isin = (h.get("isin") or "").strip().upper()
        if isin and isin in db_sectors:
            h["sector"] = db_sectors[isin]
        else:
            still_unknown.append((idx, h))

    if not still_unknown:
        return enriched

    # --- Step 3: LLM batch classification -----------------------------------
    new_mappings: dict[str, str] = {}

    for batch_start in range(0, len(still_unknown), BATCH_SIZE):
        batch = still_unknown[batch_start: batch_start + BATCH_SIZE]
        securities = [
            {"name": h.get("stock_name", ""), "isin": h.get("isin")}
            for _, h in batch
        ]
        batch_result = classify_batch_via_llm(securities)

        for (idx, h), sec in zip(batch, securities):
            cache_key = _make_key(sec["name"], sec["isin"])
            sector = batch_result.get(cache_key, "Other")
            h["sector"] = sector
            new_mappings[cache_key] = sector

    # --- Step 4: Persist to DB ----------------------------------------------
    if db_path and new_mappings:
        _upsert_sectors(db_path, new_mappings)

    return enriched


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n── SINGLE CLASSIFY ──")
    tests = [
        ("Infosys Limited", "INE009A01021"),
        ("HDFC Bank Ltd", "INE040A01034"),
        ("Alphabet Inc Class A", "US02079K3059"),
        ("7.38% GOI 2027", None),
        ("Reliance Industries Ltd", "INE002A01018"),
    ]
    for name, isin in tests:
        sector = classify_single(name, isin)
        print(f"  {name[:40]:<40}  →  {sector}")

    print("\n── BATCH CLASSIFY (from holdings) ──")
    sample_holdings = [
        {"stock_name": "TCS",               "isin": "INE467B01029"},
        {"stock_name": "Bajaj Finance",     "isin": "INE296A01024"},
        {"stock_name": "Asian Paints",      "isin": "INE021A01026"},
        {"stock_name": "Coal India",        "isin": "INE522F01014"},
        {"stock_name": "Zomato Ltd",        "isin": "INE758T01015"},
        {"stock_name": "Microsoft Corp",    "isin": "US5949181045"},
        {"stock_name": "91-Day T-Bill",     "isin": None},
    ]

    enriched = enrich_holdings_with_sectors(sample_holdings, db_path=None)
    for h in enriched:
        print(f"  {h['stock_name']:<30}  →  {h.get('sector', 'N/A')}")
