# config/settings.py
# Central configuration: paths, constants, and environment variable loader.
# All other modules import from here — never hardcode paths or keys elsewhere.

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths 
BASE_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = BASE_DIR / "data"
DB_PATH    = DATA_DIR / "financial_advisor.db"
DATABASE_PATH = str(DB_PATH)   # alias used by engine + data modules

#  External APIs 
MFAPI_BASE        = "https://api.mfapi.in/mf"
AMFI_NAV_URL      = "https://www.amfiindia.com/spages/NAVAll.txt"
NSE_SCRIP_MASTER  = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# Anthropic 
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

#  Scheduler 
NAV_FETCH_HOUR   = 22   # Fetch fresh NAVs at 10 PM IST daily
NAV_FETCH_MINUTE = 0

# App constants
MAX_HOLDINGS_PER_FUND = 50   # Max stocks we store per fund per month