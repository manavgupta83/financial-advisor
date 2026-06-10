# config/settings.py
# Central configuration: paths, constants, and environment variable loader.
# All other modules import from here — never hardcode paths or keys elsewhere.

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
# On Streamlit Cloud /mount/src/<repo>/data/ is read-only at deploy time.
# We write the DB to /tmp so it's always writable (ephemeral but fine for demo).
# Locally the FINANCIAL_ADVISOR_DB env var can override to a persistent path.
BASE_DIR = Path(__file__).resolve().parent.parent

_default_db = Path("/tmp/financial_advisor.db")
DB_PATH = Path(os.getenv("FINANCIAL_ADVISOR_DB", str(_default_db)))
DATABASE_PATH = str(DB_PATH)   # alias used by engine + data modules

# ── External APIs ─────────────────────────────────────────────────────────────
MFAPI_BASE       = "https://api.mfapi.in/mf"
AMFI_NAV_URL     = "https://www.amfiindia.com/spages/NAVAll.txt"
NSE_SCRIP_MASTER = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# ── Anthropic ─────────────────────────────────────────────────────────────────
# On Streamlit Cloud set this via App Settings > Secrets.
# Locally it comes from .env.
try:
    import streamlit as st
    ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-20250514"

# ── Scheduler ─────────────────────────────────────────────────────────────────
NAV_FETCH_HOUR   = 22   # Fetch fresh NAVs at 10 PM IST daily
NAV_FETCH_MINUTE = 0

# ── App constants ─────────────────────────────────────────────────────────────
MAX_HOLDINGS_PER_FUND = 50   # Max stocks we store per fund per month
