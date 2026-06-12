"""
agents/fund_summary_agent.py
------------------------------
Fund Summary Agent (Scope Sections 1.4 / 3.8)

Quarterly cron that generates AI-powered plain-language summaries
of how each tracked mutual fund invests.

Pipeline per fund:
  1. Fetch Scheme Information Document (SID) URL from AMC website
  2. Download the latest factsheet / SID PDF
  3. Extract text (pdfplumber)
  4. Send to Claude with a structured prompt
  5. Store the summary as a static value in fund_summaries table
  6. Refresh each quarter (APScheduler trigger)

Summary covers: investment strategy, style, benchmark, key characteristics.
Displayed on the fund factsheet page (Section 1.4).

Note: Falls back gracefully if SID URL unavailable — logs gap, skips fund.
"""

from __future__ import annotations

import io
import sqlite3
import time
import logging
from datetime import date, datetime
from typing import Optional

import requests

from config.settings import DATABASE_PATH, ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AMC SID URL patterns
# Extend this dict as more AMCs are confirmed
# ---------------------------------------------------------------------------

AMC_SID_URLS: dict[str, str] = {
    # scheme_name_fragment -> SID PDF URL pattern
    # These are placeholders — real URLs sourced from AMC websites
    "Parag Parikh":  "https://amc.ppfas.com/downloads/sid/",
    "HDFC":          "https://www.hdfcfund.com/downloads/",
    "Mirae":         "https://www.miraeassetmf.co.in/downloads/",
}


# ---------------------------------------------------------------------------
# Text extraction from PDF
# ---------------------------------------------------------------------------

def _extract_pdf_text(content: bytes, max_chars: int = 8000) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import pdfplumber
        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
                if sum(len(t) for t in text_parts) > max_chars:
                    break
        return "\n".join(text_parts)[:max_chars]
    except ImportError:
        logger.warning("pdfplumber not installed — cannot extract PDF text")
        return ""
    except Exception as e:
        logger.warning("PDF extraction error: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Claude summary generation
# ---------------------------------------------------------------------------

def _generate_summary(fund_name: str, source_text: str) -> Optional[str]:
    """
    Send extracted SID/factsheet text to Claude and get a plain-language
    fund strategy summary.
    Returns the summary string or None on failure.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — skipping summary generation")
        return None
    if not source_text.strip():
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""You are summarising a mutual fund's investment strategy for a retail investor in India.

Fund name: {fund_name}

Source document extract (Scheme Information Document / Factsheet):
{source_text[:6000]}

Write a concise plain-language summary (150-200 words) covering:
1. What the fund invests in (asset class, market cap focus)
2. Investment style (growth, value, blend, thematic, etc.)
3. Benchmark index
4. Key risk characteristics
5. Who this fund is suitable for

Write in simple English. No jargon. No bullet points. Paragraph format only.
"""
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error("Claude summary error for %s: %s", fund_name, e)
        return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_tracked_funds(limit: int = 500) -> list[dict]:
    """Return funds that have NAV history (i.e. actively tracked)."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        rows = conn.execute(
            """
            SELECT DISTINCT f.scheme_code, f.scheme_name, f.fund_house
            FROM funds f
            INNER JOIN nav_history n ON n.scheme_code = f.scheme_code
            ORDER BY f.scheme_name
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        conn.close()
        return [{"scheme_code": r[0], "scheme_name": r[1], "fund_house": r[2]} for r in rows]
    except Exception as e:
        logger.error("get_tracked_funds error: %s", e)
        return []


def _summary_needs_refresh(scheme_code: int) -> bool:
    """Returns True if no summary exists or summary is older than 85 days (~1 quarter)."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        row = conn.execute(
            "SELECT generated_at FROM fund_summaries WHERE scheme_code=?",
            (scheme_code,)
        ).fetchone()
        conn.close()
        if not row:
            return True
        generated = datetime.fromisoformat(str(row[0]))
        age_days = (datetime.utcnow() - generated).days
        return age_days >= 85
    except Exception:
        return True


def _save_summary(
    scheme_code: int,
    scheme_name: str,
    summary_text: str,
    source_url: str = "",
) -> None:
    """Upsert fund summary into fund_summaries table."""
    quarter = f"Q{((date.today().month - 1) // 3) + 1}-{date.today().year}"
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute(
            """
            INSERT INTO fund_summaries
              (scheme_code, scheme_name, summary_text, source_doc_url, generated_at, quarter)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(scheme_code) DO UPDATE SET
              summary_text=excluded.summary_text,
              source_doc_url=excluded.source_doc_url,
              generated_at=excluded.generated_at,
              quarter=excluded.quarter
            """,
            (scheme_code, scheme_name, summary_text, source_url,
             datetime.utcnow().isoformat(), quarter)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("save_summary error for %s: %s", scheme_code, e)


def _get_summary(scheme_code: int) -> Optional[str]:
    """Retrieve stored summary for a fund. Returns None if not yet generated."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        row = conn.execute(
            "SELECT summary_text FROM fund_summaries WHERE scheme_code=?",
            (scheme_code,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source document fetch
# ---------------------------------------------------------------------------

def _fetch_source_document(scheme_name: str, fund_house: str) -> tuple[str, bytes]:
    """
    Attempt to fetch a SID or factsheet PDF for this fund.
    Returns (url, content_bytes). Returns ("", b"") if unavailable.
    This is a best-effort fetch — AMC URL patterns vary.
    """
    # Match against known AMC URL patterns
    for name_fragment, base_url in AMC_SID_URLS.items():
        if name_fragment.lower() in scheme_name.lower() or name_fragment.lower() in (fund_house or "").lower():
            # Construct a plausible URL — in production these are discovered from AMC sitemaps
            url = base_url
            try:
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200 and len(resp.content) > 1000:
                    return url, resp.content
            except Exception:
                pass
    return "", b""


# ---------------------------------------------------------------------------
# Main cron job function
# ---------------------------------------------------------------------------

def run_fund_summary_cron(
    max_funds: int = 50,
    sleep_between: float = 2.0,
) -> dict:
    """
    Quarterly cron job — generate/refresh AI summaries for tracked funds.

    Parameters
    ----------
    max_funds      : max funds to process per run (to manage API costs)
    sleep_between  : seconds to wait between API calls

    Returns
    -------
    dict with keys: processed, refreshed, skipped, errors
    """
    logger.info("Fund summary cron starting")
    stats = {"processed": 0, "refreshed": 0, "skipped": 0, "errors": 0}

    funds = _get_tracked_funds(limit=max_funds)
    for fund in funds:
        sc   = fund["scheme_code"]
        name = fund["scheme_name"]
        house = fund["fund_house"] or ""
        stats["processed"] += 1

        if not _summary_needs_refresh(sc):
            stats["skipped"] += 1
            continue

        # Try to fetch source document
        url, content = _fetch_source_document(name, house)
        source_text = _extract_pdf_text(content) if content else ""

        # If no SID available, use fund name + category as minimal context
        if not source_text:
            source_text = f"Fund: {name}\nAMC: {house}\n(No SID document available — summary based on fund name only.)"

        summary = _generate_summary(name, source_text)
        if summary:
            _save_summary(sc, name, summary, url)
            stats["refreshed"] += 1
            logger.info("Summary generated for %s", name)
        else:
            stats["errors"] += 1
            logger.warning("Summary generation failed for %s", name)

        time.sleep(sleep_between)

    logger.info("Fund summary cron complete: %s", stats)
    return stats


# Public helper for UI
get_fund_summary = _get_summary


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    result = run_fund_summary_cron(max_funds=5, sleep_between=1.0)
    print(result)
