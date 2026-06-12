"""
ui/pages/06_holdings_upload.py

Statement Upload & Ingestion — Scope Section 1.6

Allows the investor (or advisor on their behalf) to upload MF account statements:
  - CAMS Consolidated Account Statement (PDF or Excel)
  - KFintech Consolidated Account Statement (PDF or Excel)
  - Individual AMC statements (Excel)

The Statement Ingestion Agent parses each file, extracts transaction-level data,
deduplicates across files, and shows a review screen before writing to DB.
XIRR at ISIN level is computed from actual cashflows after confirmation.
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
import sqlite3
from config.settings import DATABASE_PATH
from data.database import init_db
from agents.statement_ingestion_agent import ingest_statements, commit_ingestion
init_db()

st.set_page_config(page_title="Upload Statements", page_icon="📂", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #0D1117; color: #C9D1D9; }
  [data-testid="stSidebarNav"] { display: none !important; }
  section[data-testid="stSidebar"] { background: #0D1117; border-right: 1px solid #21262D; }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
  .block-container { padding: 2rem 2.5rem; }
  .page-title { font-family: 'DM Serif Display', serif; font-size: 1.9rem; color: #E6EDF3; }
  .page-sub { color: #8B949E; font-size: 0.85rem; margin-top: -0.5rem; margin-bottom: 1.5rem; }
  .section-heading { font-family: 'DM Serif Display', serif; font-size: 1.1rem; color: #E6EDF3; margin: 1.5rem 0 0.75rem; padding-bottom: 0.4rem; border-bottom: 1px solid #21262D; }
  .holding-card { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 0.5rem; }
  .holding-name { font-size: 0.9rem; font-weight: 600; color: #E6EDF3; }
  .holding-isin { font-size: 0.72rem; color: #8B949E; font-family: 'JetBrains Mono', monospace; }
  .xirr-positive { color: #3FB950; font-family: 'JetBrains Mono', monospace; }
  .xirr-negative { color: #F85149; font-family: 'JetBrains Mono', monospace; }
  .warn-box { background: #2D2000; border-left: 3px solid #E3B341; border-radius: 6px; padding: 0.6rem 0.9rem; font-size: 0.82rem; color: #E3B341; margin-bottom: 0.5rem; }
  .err-box  { background: #2D0000; border-left: 3px solid #F85149; border-radius: 6px; padding: 0.6rem 0.9rem; font-size: 0.82rem; color: #F85149; margin-bottom: 0.5rem; }
  .wordmark { font-family: 'DM Serif Display', serif; font-size: 1.6rem; color: #E6EDF3; }
  .wordmark span { color: #3FB950; }
  h1,h2,h3 { color: #E6EDF3 !important; }
</style>
""", unsafe_allow_html=True)


def _sidebar():
    with st.sidebar:
        st.markdown('<div class="wordmark">Fin<span>.</span>Advisor</div>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:0.7rem;color:#8B949E;margin-top:-0.2rem;margin-bottom:1rem;">AI-Powered Advisory Platform</p>', unsafe_allow_html=True)
        st.divider()
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            clients = conn.execute("SELECT id, name FROM clients ORDER BY name").fetchall()
            conn.close()
        except Exception:
            clients = []
        if clients:
            names = [r[1] for r in clients]
            ids   = [r[0] for r in clients]
            default = 0
            if st.session_state.get("selected_client_id") in ids:
                default = ids.index(st.session_state["selected_client_id"])
            chosen = st.selectbox("Active Client", names, index=default)
            st.session_state["selected_client_id"] = ids[names.index(chosen)]
        else:
            st.caption("No clients yet.")
        st.divider()
        st.markdown('<p style="font-size:0.7rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem;">Navigation</p>', unsafe_allow_html=True)
        st.page_link("pages/01_Client_Onboarding.py",  label="Client Onboarding",   icon="🧾")
        st.page_link("pages/02_Goal_Planner.py",        label="Goal Planner",         icon="🎯")
        st.page_link("pages/03_Portfolio.py",            label="Portfolio",            icon="📈")
        st.page_link("pages/04_Optimiser.py",            label="Optimiser",            icon="⚙️")
        st.page_link("pages/05_Advisory_Report.py",      label="Advisory Report",      icon="📄")
        st.page_link("pages/06_Holdings_Upload.py",      label="Upload Statements",    icon="📂")
        st.page_link("pages/07_Fund_Discovery.py",       label="Fund Discovery",       icon="🔍")
        st.divider()
        st.markdown('<p style="font-size:0.65rem;color:#30363D;">Phase 5+ — Streamlit UI</p>', unsafe_allow_html=True)

_sidebar()

st.markdown('<div class="page-title">Upload Statements</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Upload CAMS / KFintech CAS or individual AMC statements. We extract your holdings and compute XIRR on actual cashflows.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client. Please select one in **Client Onboarding**.")
    st.stop()

st.info(
    "**Supported formats:** CAMS CAS (PDF/Excel) · KFintech CAS (PDF/Excel) · Individual AMC statements (Excel)  \n"
    "**Note:** The freshness and validity of uploaded statements is your responsibility. "
    "NAV used for current value is from our daily database feed — not real-time.",
    icon="ℹ️"
)

st.markdown('<div class="section-heading">Step 1 — Upload Files</div>', unsafe_allow_html=True)
uploaded_files = st.file_uploader(
    "Upload one or more statement files",
    type=["pdf", "xlsx", "xls"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files and st.button("🔍  Parse Statements", type="primary", use_container_width=True):
    with st.spinner("Parsing statements…"):
        file_tuples = [(f.name, f.read()) for f in uploaded_files]
        result = ingest_statements(file_tuples, client_id)
        st.session_state["ingestion_result"] = result

if "ingestion_result" in st.session_state:
    result = st.session_state["ingestion_result"]

    st.markdown('<div class="section-heading">Step 2 — Review Extraction</div>', unsafe_allow_html=True)

    if result.errors:
        for err in result.errors:
            st.markdown(f'<div class="err-box">❌ {err}</div>', unsafe_allow_html=True)

    if result.warnings:
        for warn in result.warnings:
            st.markdown(f'<div class="warn-box">⚠️ {warn}</div>', unsafe_allow_html=True)

    if result.files_processed:
        st.success(f"Parsed {len(result.files_processed)} file(s): {', '.join(result.files_processed)}")

    if not result.holdings:
        st.warning("No holdings extracted. Check file format or try a different statement.")
    else:
        r1, r2, r3 = st.columns(3)
        r1.metric("Holdings found",   len(result.holdings))
        r2.metric("Total invested",   f"₹{result.total_invested/1e5:.2f}L")
        r3.metric("Current value",    f"₹{result.total_current/1e5:.2f}L" if result.total_current else "—")

        st.markdown('<div class="section-heading">Holdings extracted</div>', unsafe_allow_html=True)
        for h in result.holdings:
            xirr_str = ""
            if h.xirr is not None:
                xirr_pct = h.xirr * 100
                cls = "xirr-positive" if xirr_pct >= 0 else "xirr-negative"
                xirr_str = f'<span class="{cls}">{xirr_pct:.2f}% XIRR</span>'
            st.markdown(
                f'<div class="holding-card">'
                f'<div class="holding-name">{h.scheme_name}</div>'
                f'<div class="holding-isin">{h.isin}</div>'
                f'<div style="display:flex;gap:2rem;margin-top:0.6rem;font-size:0.82rem;color:#8B949E;">'
                f'<span>Units: <b style="color:#E6EDF3">{h.total_units:,.3f}</b></span>'
                f'<span>Cost: <b style="color:#E6EDF3">₹{h.total_cost:,.0f}</b></span>'
                f'<span>Current: <b style="color:#E6EDF3">{"₹"+f"{h.current_value:,.0f}" if h.current_value else "NAV unavailable"}</b></span>'
                f'<span>{xirr_str}</span>'
                f'</div>'
                f'<div style="font-size:0.72rem;color:#555;margin-top:0.3rem;">{len(h.transactions)} transaction(s) · {len(set(tx.source_file for tx in h.transactions))} source file(s)</div>'
                f'</div>',
                unsafe_allow_html=True
            )

        st.markdown('<div class="section-heading">Step 3 — Confirm &amp; Save</div>', unsafe_allow_html=True)
        st.warning(
            "Review the extracted holdings above carefully. "
            "Once confirmed, these will be saved to your portfolio. "
            "This action cannot be undone automatically — contact your advisor to correct errors."
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅  Confirm &amp; Save to Portfolio", type="primary", use_container_width=True):
                rows = commit_ingestion(result, client_id)
                st.success(f"Saved {rows} transaction records to your portfolio.")
                del st.session_state["ingestion_result"]
                st.rerun()
        with col2:
            if st.button("❌  Discard", use_container_width=True):
                del st.session_state["ingestion_result"]
                st.rerun()
