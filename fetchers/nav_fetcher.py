# fetchers/nav_fetcher.py
# Fetches live and historical NAV data from mfapi.in and stores it in the database.
# Two main functions:
#   - fetch_and_store_nav(scheme_code): fetches full NAV history for one fund
#   - fetch_all_scheme_codes(): fetches the master list of all MF schemes from AMFI

import requests
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import MFAPI_BASE, AMFI_NAV_URL
from data.database import engine, Fund, NAVHistory, init_db


# ── 1. Fetch full scheme list from AMFI ───────────────────────────────────────
def fetch_all_scheme_codes() -> pd.DataFrame:
    """
    Downloads the AMFI NAV file and extracts scheme codes + names.
    Returns a DataFrame with columns: scheme_code, scheme_name, fund_house, plan_type
    """
    print("Fetching scheme list from AMFI...")
    response = requests.get(AMFI_NAV_URL, timeout=30)
    response.raise_for_status()

    rows = []
    current_fund_house = ""

    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Fund house header lines look like "Aditya Birla Sun Life Mutual Fund"
        if line.endswith("Mutual Fund") or line.endswith("Mutual fund"):
            current_fund_house = line
            continue

        parts = line.split(";")
        if len(parts) < 5:
            continue

        try:
            scheme_code = int(parts[0].strip())
        except ValueError:
            continue

        scheme_name = parts[3].strip()
        plan_type   = "Direct" if "Direct" in scheme_name else "Regular"

        rows.append({
            "scheme_code": scheme_code,
            "scheme_name": scheme_name,
            "fund_house":  current_fund_house,
            "plan_type":   plan_type,
        })

    df = pd.DataFrame(rows)
    print(f"✅ Found {len(df)} schemes from AMFI")
    return df


# ── 2. Store scheme master into funds table ───────────────────────────────────
def store_scheme_master(df: pd.DataFrame):
    """
    Inserts or updates fund records in the funds table.
    Uses INSERT OR IGNORE so re-runs are safe.
    """
    with Session(engine) as session:
        inserted = 0
        for _, row in df.iterrows():
            exists = session.query(Fund).filter_by(
                scheme_code=row["scheme_code"]
            ).first()

            if not exists:
                fund = Fund(
                    scheme_code = row["scheme_code"],
                    scheme_name = row["scheme_name"],
                    fund_house  = row["fund_house"],
                    plan_type   = row["plan_type"],
                )
                session.add(fund)
                inserted += 1

        session.commit()
    print(f"✅ Inserted {inserted} new schemes into funds table")


# ── 3. Fetch NAV history for a single scheme ──────────────────────────────────
def fetch_and_store_nav(scheme_code: int) -> int:
    """
    Fetches complete NAV history for a scheme from mfapi.in
    and stores it in nav_history table.
    Returns number of new records inserted.
    """
    url = f"{MFAPI_BASE}/{scheme_code}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  ⚠️  Failed to fetch scheme {scheme_code}: {e}")
        return 0

    nav_records = data.get("data", [])
    if not nav_records:
        return 0

    rows = []
    for record in nav_records:
        try:
            rows.append({
                "scheme_code": scheme_code,
                "nav_date":    datetime.strptime(record["date"], "%d-%m-%Y").date(),
                "nav":         float(record["nav"]),
            })
        except (ValueError, KeyError):
            continue

    if not rows:
        return 0

    # Bulk insert — skip duplicates cleanly
    with Session(engine) as session:
        stmt = insert(NAVHistory).values(rows).prefix_with("OR IGNORE")
        result = session.execute(stmt)
        session.commit()

    return len(rows)


# ── 4. Fetch NAV for a list of scheme codes ───────────────────────────────────
def fetch_navs_for_schemes(scheme_codes: list[int]):
    """
    Fetches and stores NAV history for a list of scheme codes.
    Prints progress as it goes.
    """
    total = len(scheme_codes)
    for i, code in enumerate(scheme_codes, 1):
        count = fetch_and_store_nav(code)
        print(f"  [{i}/{total}] Scheme {code}: {count} NAV records stored")


# ── 5. Quick test: fetch 5 well-known funds ───────────────────────────────────
TEST_SCHEMES = [
    100033,  # HDFC Top 100 Fund - Direct
    120503,  # Mirae Asset Large Cap Fund - Direct
    122639,  # Parag Parikh Flexi Cap Fund - Direct
    118989,  # Axis Small Cap Fund - Direct
    125354,  # Kotak Emerging Equity Fund - Direct
]

if __name__ == "__main__":
    init_db()

    print("\n── Step 1: Loading scheme master ──")
    df = fetch_all_scheme_codes()
    store_scheme_master(df)

    print("\n── Step 2: Fetching NAV history for 5 test funds ──")
    fetch_navs_for_schemes(TEST_SCHEMES)

    print("\n── Step 3: Verify ──")
    with Session(engine) as session:
        fund_count = session.query(Fund).count()
        nav_count  = session.query(NAVHistory).count()
        print(f"✅ Funds in DB:       {fund_count}")
        print(f"✅ NAV records in DB: {nav_count}")