"""
fetchers/scheduler.py
-----------------------
APScheduler cron setup for all background data pipelines.

Jobs configured:
  - NAV pipeline      : daily at 22:00 IST (16:30 UTC) — fetches latest NAV for all tracked funds
  - Holdings pipeline : 1st of each month at 01:00 UTC — fetches AMC Excel disclosures
  - Fund summaries    : quarterly (1st Jan, Apr, Jul, Oct at 02:00 UTC) — AI fund summaries

Usage:
  from fetchers.scheduler import start_scheduler
  scheduler = start_scheduler()   # call once at app startup

Or run standalone:
  PYTHONPATH=/path/to/repo python fetchers/scheduler.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

def _run_nav_cron():
    """Daily NAV fetch for all funds that have existing nav_history records."""
    try:
        import sqlite3
        from config.settings import DATABASE_PATH
        from fetchers.nav_fetcher import fetch_and_store_nav

        conn = sqlite3.connect(DATABASE_PATH)
        scheme_codes = [
            r[0] for r in
            conn.execute("SELECT DISTINCT scheme_code FROM nav_history").fetchall()
        ]
        conn.close()

        logger.info("NAV cron: fetching %d funds", len(scheme_codes))
        for sc in scheme_codes:
            try:
                count = fetch_and_store_nav(sc)
                logger.debug("  scheme %d: %d records", sc, count)
            except Exception as e:
                logger.warning("  scheme %d failed: %s", sc, e)
        logger.info("NAV cron complete")
    except Exception as e:
        logger.error("NAV cron error: %s", e)


def _run_holdings_cron():
    """Monthly holdings fetch for all tracked AMCs."""
    try:
        from fetchers.holdings_fetcher import fetch_and_store_holdings
        logger.info("Holdings cron starting")
        fetch_and_store_holdings()
        logger.info("Holdings cron complete")
    except Exception as e:
        logger.error("Holdings cron error: %s", e)


def _run_fund_summary_cron():
    """Quarterly fund summary generation via Claude."""
    try:
        from agents.fund_summary_agent import run_fund_summary_cron
        logger.info("Fund summary cron starting")
        result = run_fund_summary_cron(max_funds=100, sleep_between=2.0)
        logger.info("Fund summary cron complete: %s", result)
    except Exception as e:
        logger.error("Fund summary cron error: %s", e)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def start_scheduler() -> BackgroundScheduler:
    """
    Configure and start the background scheduler.
    Returns the running scheduler instance.
    Call scheduler.shutdown() on app teardown.
    """
    scheduler = BackgroundScheduler(timezone="UTC")

    # 1. NAV pipeline — daily at 16:30 UTC (22:00 IST)
    scheduler.add_job(
        _run_nav_cron,
        trigger=CronTrigger(hour=16, minute=30),
        id="nav_daily",
        name="Daily NAV fetch",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 hour grace if missed
    )

    # 2. Holdings pipeline — 1st of each month at 01:00 UTC
    scheduler.add_job(
        _run_holdings_cron,
        trigger=CronTrigger(day=1, hour=1, minute=0),
        id="holdings_monthly",
        name="Monthly holdings fetch",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # 3. Fund summary pipeline — quarterly (Jan/Apr/Jul/Oct, 1st at 02:00 UTC)
    scheduler.add_job(
        _run_fund_summary_cron,
        trigger=CronTrigger(month="1,4,7,10", day=1, hour=2, minute=0),
        id="fund_summaries_quarterly",
        name="Quarterly fund summary generation",
        replace_existing=True,
        misfire_grace_time=86400,  # 24 hour grace
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Jobs: NAV daily, Holdings monthly, Fund summaries quarterly."
    )
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    print("Starting scheduler in foreground (Ctrl+C to stop)...")
    sched = start_scheduler()
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.shutdown()
        print("Scheduler stopped.")
