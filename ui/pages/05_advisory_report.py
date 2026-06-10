"""
ui/pages/05_advisory_report.py

Phase 5 fix: stream_advisory_narrative() now accepts the single
client_context dict pattern used here. No other logic changes.
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
import sqlite3
from datetime import date

from config.settings import DATABASE_PATH
from data.database import init_db
from data.client_manager import get_goals_for_client
from engine.performance_engine import compute_cagr, compute_sharpe_ratio, simulate_sip_cashflows, compute_xirr
from ai.claude_advisor import stream_advisory_narrative
init_db()

st.set_page_config(page_title="Advisory Report", page_icon="\U0001f4c4", layout="wide")

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
  .report-container { background: #161B22; border: 1px solid #21262D; border-radius: 12px; padding: 2rem 2.5rem; margin-top: 1.5rem; line-height: 1.8; }
  .report-container h1 { font-family: 'DM Serif Display',serif !important; color: #E6EDF3 !important; font-size: 1.6rem; border-bottom: 1px solid #21262D; padding-bottom: 0.5rem; }
  .report-container h2 { font-size: 1.2rem; color: #58A6FF !important; }
  .report-container h3 { font-size: 1rem; color: #3FB950 !important; }
  .report-container p, .report-container ul, .report-container ol { color: #C9D1D9; font-size: 0.9rem; }
  .context-card { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 1rem; }
  .context-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; color: #8B949E; margin-bottom: 0.25rem; }
  .context-value { font-size: 0.9rem; color: #E6EDF3; font-weight: 500; }
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
        st.page_link("pages/01_Client_Onboarding.py", label="Client Onboarding", icon="\U0001f9fe")
        st.page_link("pages/02_Goal_Planner.py",      label="Goal Planner",       icon="\U0001f3af")
        st.page_link("pages/03_Portfolio.py",          label="Portfolio",          icon="\U0001f4c8")
        st.page_link("pages/04_Optimiser.py",          label="Optimiser",          icon="\u2699\ufe0f")
        st.page_link("pages/05_Advisory_Report.py",    label="Advisory Report",    icon="\U0001f4c4")
        st.divider()
        st.markdown('<p style="font-size:0.65rem;color:#30363D;">Phase 5 \u2014 Streamlit UI</p>', unsafe_allow_html=True)

_sidebar()


def get_client(client_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_holdings(client_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT h.*, COALESCE(f.scheme_name,'Scheme '||h.scheme_code) AS scheme_name,
                   (h.units*h.avg_nav) AS current_value
            FROM client_holdings h LEFT JOIN funds f ON f.scheme_code=h.scheme_code
            WHERE h.client_id=?
        """, (client_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def build_context(client, goals, holdings):
    """Assemble the client_context dict for stream_advisory_narrative()."""
    inv  = sum(h.get("invested_amount", 0) for h in holdings)
    cur  = sum(h.get("current_value",   0) for h in holdings)
    cagr = compute_cagr(inv, cur, years=3.0) if inv > 0 else 0.0
    xirr = None
    try:
        xirr = compute_xirr(simulate_sip_cashflows(inv, months=36, final_value=cur))
    except Exception:
        pass
    sharpe = compute_sharpe_ratio(cagr, risk_free_rate=0.065, volatility=0.15)
    gain   = cur - inv
    return {
        "client": {
            "name":           client.get("name"),
            "age":            client.get("age"),
            "annual_income":  client.get("annual_income"),
            "monthly_income": (client.get("annual_income") or 0) / 12,
            "dependants":     client.get("dependants"),
            "risk_profile":   client.get("risk_profile"),
            "risk_score":     client.get("risk_score"),
        },
        "goals": [
            {
                "name":        g.goal_name,
                "type":        g.goal_type,
                "target":      g.target_amount,
                "target_year": g.target_year,
                "monthly_sip": g.monthly_sip,
            }
            for g in goals
        ],
        "portfolio": {
            "num_holdings":  len(holdings),
            "total_invested": inv,
            "total_current":  cur,
            "absolute_gain":  gain,
            "gain_pct":       (gain / inv * 100) if inv > 0 else 0,
        },
        "performance": {"cagr": cagr, "xirr": xirr, "sharpe": sharpe},
        "holdings": [
            {
                "name":     h.get("scheme_name"),
                "invested": h.get("invested_amount"),
                "current":  h.get("current_value"),
            }
            for h in holdings
        ],
        "report_date": date.today().isoformat(),
    }


st.markdown('<div class="page-title">Advisory Report</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Claude generates a personalised financial advisory narrative \u2014 streamed live.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client. Go to **Client Onboarding** first.")
    st.stop()

client   = get_client(client_id)
goals    = get_goals_for_client(client_id)
holdings = get_holdings(client_id)
if not client:
    st.error("Client not found.")
    st.stop()

st.markdown('<div class="section-heading">Report Context</div>', unsafe_allow_html=True)
cc1, cc2, cc3, cc4 = st.columns(4)
cc1.markdown(f'<div class="context-card"><div class="context-label">Client</div><div class="context-value">{client["name"]}</div></div>', unsafe_allow_html=True)
cc2.markdown(f'<div class="context-card"><div class="context-label">Risk Profile</div><div class="context-value">{client.get("risk_profile", "\u2014")}</div></div>', unsafe_allow_html=True)
cc3.markdown(f'<div class="context-card"><div class="context-label">Goals</div><div class="context-value">{len(goals)} defined</div></div>', unsafe_allow_html=True)
cc4.markdown(f'<div class="context-card"><div class="context-label">Holdings</div><div class="context-value">{len(holdings)} funds</div></div>', unsafe_allow_html=True)

with st.expander("\u2699\ufe0f Customise report (optional)"):
    include_sections = st.multiselect("Sections to include",
        ["Executive Summary","Risk Profile Analysis","Goal Review","Portfolio Health",
         "Fund Recommendations","Tax Planning","Action Items"],
        default=["Executive Summary","Risk Profile Analysis","Goal Review",
                 "Portfolio Health","Fund Recommendations","Action Items"])

report_ph   = st.empty()
download_ph = st.empty()

if st.button("\U0001f4c4  Generate Advisory Report", type="primary", use_container_width=True):
    context = build_context(client, goals, holdings)
    context["requested_sections"] = include_sections
    full_report = ""
    report_ph.markdown('<div class="report-container"><em style="color:#8B949E;">Generating\u2026</em></div>', unsafe_allow_html=True)
    try:
        # stream_advisory_narrative accepts client_context= keyword (Phase 5 fix)
        for chunk in stream_advisory_narrative(client_context=context):
            full_report += chunk
            report_ph.markdown(f'<div class="report-container">{full_report}</div>', unsafe_allow_html=True)
        st.session_state["last_report"] = full_report
        st.session_state["last_report_client"] = client["name"]
    except Exception as e:
        report_ph.error(f"Streaming error: {e}")
elif "last_report" in st.session_state:
    st.caption(f"\U0001f4c4 Last report for **{st.session_state.get('last_report_client', '\u2014')}**. Click Generate to refresh.")
    report_ph.markdown(f'<div class="report-container">{st.session_state["last_report"]}</div>', unsafe_allow_html=True)

if "last_report" in st.session_state:
    name_safe = (st.session_state.get("last_report_client") or "report").replace(" ", "_")
    download_ph.download_button(
        label="\u2b07\ufe0f  Download as Markdown",
        data=st.session_state["last_report"],
        file_name=f"advisory_{name_safe}_{date.today().isoformat()}.md",
        mime="text/markdown",
        use_container_width=True,
    )
