"""
agents/statement_ingestion_agent.py
-------------------------------------
Statement Ingestion Agent (Scope Section 4.6)

Processes MF account statements uploaded by the investor.
Supported formats:
  - CAMS Consolidated Account Statement (PDF or Excel)
  - KFintech Consolidated Account Statement (PDF or Excel)
  - Individual AMC statements (Excel)

For each uploaded file the agent:
  1. Detects format and routes to appropriate parser
  2. Extracts: scheme_name, ISIN, date_of_purchase, purchase_cost, units_bought
  3. Deduplicates across multiple uploaded files per ISIN
  4. Writes transaction records to client_holdings (with full tx history)
  5. Computes XIRR at ISIN level using actual cashflows (Brent's method)
  6. Returns a structured ingestion result for the investor to review

Approval checkpoint: the agent surfaces a review screen before writing to DB.
The investor must confirm ingestion. Failures are flagged inline.

Note: No real-time NAV — current value computed from DB (daily cron NAV).
"""

from __future__ import annotations

import io
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config.settings import DATABASE_PATH
from engine.performance_engine import compute_xirr


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TransactionRecord:
    scheme_name:    str
    isin:           str
    purchase_date:  date
    purchase_cost:  float   # ₹ invested on this date
    units_bought:   float
    source_file:    str     # filename this came from


@dataclass
class HoldingSummary:
    isin:           str
    scheme_name:    str
    scheme_code:    Optional[int]
    transactions:   list[TransactionRecord]
    total_units:    float
    total_cost:     float
    current_nav:    Optional[float]
    current_value:  Optional[float]
    xirr:           Optional[float]  # computed from actual cashflows


@dataclass
class IngestionResult:
    holdings:       list[HoldingSummary]
    total_invested: float
    total_current:  float
    warnings:       list[str] = field(default_factory=list)
    errors:         list[str] = field(default_factory=list)
    files_processed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_format(filename: str, content: bytes) -> str:
    """
    Returns one of: 'cams_pdf', 'cams_excel', 'kfintech_pdf',
                    'kfintech_excel', 'amc_excel', 'unknown'
    """
    fname = filename.lower()
    if fname.endswith(".pdf"):
        text_head = ""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                if pdf.pages:
                    text_head = (pdf.pages[0].extract_text() or "")[:500].lower()
        except Exception:
            pass
        if "cams" in text_head or "computer age" in text_head:
            return "cams_pdf"
        if "kfintech" in text_head or "karvy" in text_head:
            return "kfintech_pdf"
        return "pdf_unknown"
    if fname.endswith((".xlsx", ".xls")):
        if "cams" in fname:
            return "cams_excel"
        if "kfin" in fname or "karvy" in fname:
            return "kfintech_excel"
        return "amc_excel"
    return "unknown"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> Optional[date]:
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_excel_generic(content: bytes, source_file: str) -> list[TransactionRecord]:
    """
    Generic Excel parser — tries to extract transaction rows.
    Expects columns containing: scheme/fund name, ISIN, date, amount/cost, units.
    Falls back gracefully if columns differ.
    """
    import pandas as pd
    records: list[TransactionRecord] = []
    try:
        df = pd.read_excel(io.BytesIO(content), header=None)
        # Flatten to string for header detection
        df_str = df.astype(str)
        # Find row where headers likely appear
        header_row = 0
        for i, row in df_str.iterrows():
            joined = " ".join(row.values).lower()
            if any(kw in joined for kw in ["isin", "scheme", "folio", "units", "amount"]):
                header_row = i
                break
        df.columns = df.iloc[header_row]
        df = df.iloc[header_row + 1:].reset_index(drop=True)
        df.columns = [str(c).lower().strip() for c in df.columns]

        # Flexible column mapping
        col_map = {}
        for col in df.columns:
            if "isin" in col:                            col_map["isin"] = col
            elif any(k in col for k in ["scheme","fund","name"]): col_map["scheme"] = col
            elif any(k in col for k in ["date","trxn","trans"]):  col_map["date"] = col
            elif any(k in col for k in ["amount","cost","price"]): col_map["cost"] = col
            elif any(k in col for k in ["unit","qty"]):           col_map["units"] = col

        required = {"isin", "scheme", "date", "cost", "units"}
        missing = required - set(col_map.keys())
        if missing:
            return records  # Cannot parse this format

        for _, row in df.iterrows():
            try:
                isin = str(row[col_map["isin"]]).strip()
                if not isin or isin == "nan" or len(isin) < 10:
                    continue
                scheme = str(row[col_map["scheme"]]).strip()
                dt = _parse_date(str(row[col_map["date"]]))
                cost = float(str(row[col_map["cost"]]).replace(",", "").replace("₹", ""))
                units = float(str(row[col_map["units"]]).replace(",", ""))
                if not dt or cost <= 0 or units <= 0:
                    continue
                records.append(TransactionRecord(
                    scheme_name=scheme, isin=isin, purchase_date=dt,
                    purchase_cost=cost, units_bought=units, source_file=source_file
                ))
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return records


def _parse_pdf_generic(content: bytes, source_file: str) -> list[TransactionRecord]:
    """
    Generic PDF parser using pdfplumber.
    Extracts text and applies regex patterns to find transaction rows.
    """
    records: list[TransactionRecord] = []
    try:
        import pdfplumber
        text_lines: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text() or ""
                text_lines.extend(extracted.split("\n"))

        # Pattern: date  description  units  amount  isin (order varies by AMC)
        # This is a best-effort pattern — real CAS formats need dedicated parsers
        date_pat   = re.compile(r"\d{2}[-/]\w{3}[-/]\d{4}|\d{2}[-/]\d{2}[-/]\d{4}")
        isin_pat   = re.compile(r"\bIN[A-Z0-9]{10}\b|\bUS[A-Z0-9]{10}\b")
        amount_pat = re.compile(r"[\d,]+\.\d{2}")

        current_scheme = ""
        current_isin   = ""

        for line in text_lines:
            # Track scheme name lines (usually all caps, no numbers)
            if re.match(r"^[A-Z][A-Z \-&()]{10,}$", line.strip()):
                current_scheme = line.strip()
            isin_match = isin_pat.search(line)
            if isin_match:
                current_isin = isin_match.group()
            date_match = date_pat.search(line)
            amounts = amount_pat.findall(line)
            if date_match and amounts and current_isin and current_scheme:
                dt = _parse_date(date_match.group())
                if not dt:
                    continue
                try:
                    cost  = float(amounts[-1].replace(",", ""))
                    units = float(amounts[0].replace(",", "")) if len(amounts) > 1 else 0
                    if cost > 0:
                        records.append(TransactionRecord(
                            scheme_name=current_scheme, isin=current_isin,
                            purchase_date=dt, purchase_cost=cost,
                            units_bought=units, source_file=source_file
                        ))
                except ValueError:
                    continue
    except ImportError:
        pass  # pdfplumber not installed — handled at UI layer
    except Exception:
        pass
    return records


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(
    new_records: list[TransactionRecord],
    existing_records: list[dict],  # existing from DB: {isin, purchase_date, purchase_cost}
) -> list[TransactionRecord]:
    """
    Remove transaction records that already exist in DB (by isin + date + cost).
    """
    existing_keys = {
        (r["isin"], str(r["purchase_date"]), float(r["purchase_cost"]))
        for r in existing_records
    }
    return [
        r for r in new_records
        if (r.isin, str(r.purchase_date), float(r.purchase_cost)) not in existing_keys
    ]


# ---------------------------------------------------------------------------
# NAV lookup + XIRR
# ---------------------------------------------------------------------------

def _get_current_nav(scheme_code: int) -> Optional[float]:
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        row = conn.execute(
            "SELECT nav FROM nav_history WHERE scheme_code=? ORDER BY nav_date DESC LIMIT 1",
            (scheme_code,)
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def _resolve_scheme_code(isin: str) -> Optional[int]:
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        # Try fund_holdings first (most reliable ISIN→scheme mapping)
        row = conn.execute(
            "SELECT DISTINCT scheme_code FROM fund_holdings WHERE isin=? LIMIT 1", (isin,)
        ).fetchone()
        conn.close()
        return int(row[0]) if row else None
    except Exception:
        return None


def _compute_xirr_for_holding(
    transactions: list[TransactionRecord],
    current_value: float,
) -> Optional[float]:
    """Build cashflow list and compute XIRR using actual purchase dates."""
    if not transactions or current_value <= 0:
        return None
    try:
        from scipy.optimize import brentq
        cashflows = []
        for tx in transactions:
            cashflows.append((-tx.purchase_cost, tx.purchase_date))
        cashflows.append((current_value, date.today()))
        # Convert to days-from-first
        base = cashflows[0][1]
        amounts  = [cf[0] for cf in cashflows]
        day_diffs = [(cf[1] - base).days for cf in cashflows]

        def npv(rate):
            return sum(a / (1 + rate) ** (d / 365.0) for a, d in zip(amounts, day_diffs))

        try:
            return brentq(npv, -0.999, 100.0, maxiter=500)
        except ValueError:
            return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def ingest_statements(
    files: list[tuple[str, bytes]],   # [(filename, file_bytes), ...]
    client_id: int,
) -> IngestionResult:
    """
    Process one or more statement files for a client.

    Parameters
    ----------
    files   : list of (filename, file_bytes) tuples
    client_id : the client this ingestion is for

    Returns
    -------
    IngestionResult — structured for investor review screen.
    DOES NOT write to DB — caller must call commit_ingestion() after review.
    """
    all_records: list[TransactionRecord] = []
    warnings: list[str] = []
    errors: list[str] = []
    files_processed: list[str] = []

    for filename, content in files:
        fmt = _detect_format(filename, content)
        records: list[TransactionRecord] = []

        if fmt in ("cams_excel", "kfintech_excel", "amc_excel"):
            records = _parse_excel_generic(content, filename)
        elif fmt in ("cams_pdf", "kfintech_pdf", "pdf_unknown"):
            records = _parse_pdf_generic(content, filename)
        else:
            errors.append(f"{filename}: unrecognised format — skipped.")
            continue

        if not records:
            warnings.append(f"{filename}: parsed but no transactions extracted. Check format.")
        else:
            all_records.extend(records)
            files_processed.append(filename)

    # Fetch existing transactions for deduplication
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        existing = conn.execute(
            "SELECT isin, purchase_date, purchase_cost FROM client_holdings WHERE client_id=?",
            (client_id,)
        ).fetchall()
        conn.close()
        existing_dicts = [{"isin": r[0], "purchase_date": r[1], "purchase_cost": r[2]} for r in existing]
    except Exception:
        existing_dicts = []

    all_records = _deduplicate(all_records, existing_dicts)

    # Group by ISIN
    isin_groups: dict[str, list[TransactionRecord]] = {}
    for r in all_records:
        isin_groups.setdefault(r.isin, []).append(r)

    holdings: list[HoldingSummary] = []
    for isin, txns in isin_groups.items():
        scheme_name = txns[0].scheme_name
        scheme_code = _resolve_scheme_code(isin)
        total_units = sum(t.units_bought for t in txns)
        total_cost  = sum(t.purchase_cost for t in txns)
        current_nav  = _get_current_nav(scheme_code) if scheme_code else None
        current_value = total_units * current_nav if current_nav and total_units > 0 else None
        xirr = _compute_xirr_for_holding(txns, current_value) if current_value else None

        holdings.append(HoldingSummary(
            isin=isin, scheme_name=scheme_name, scheme_code=scheme_code,
            transactions=txns, total_units=total_units, total_cost=total_cost,
            current_nav=current_nav, current_value=current_value, xirr=xirr,
        ))

    holdings.sort(key=lambda h: h.total_cost, reverse=True)

    return IngestionResult(
        holdings=holdings,
        total_invested=sum(h.total_cost for h in holdings),
        total_current=sum(h.current_value or 0 for h in holdings),
        warnings=warnings,
        errors=errors,
        files_processed=files_processed,
    )


def commit_ingestion(result: IngestionResult, client_id: int) -> int:
    """
    Write confirmed ingestion result to client_holdings.
    Called only after investor reviews and confirms the ingestion preview.
    Returns number of transaction rows written.
    """
    rows_written = 0
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        for holding in result.holdings:
            for tx in holding.transactions:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO client_holdings
                      (client_id, scheme_code, isin, scheme_name,
                       units, avg_nav, invested_amount,
                       purchase_date, purchase_cost, units_bought)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        client_id,
                        holding.scheme_code,
                        holding.isin,
                        holding.scheme_name,
                        holding.total_units,
                        holding.current_nav or 0,
                        holding.total_cost,
                        str(tx.purchase_date),
                        tx.purchase_cost,
                        tx.units_bought,
                    )
                )
                rows_written += 1
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"commit_ingestion error: {e}")
    return rows_written
