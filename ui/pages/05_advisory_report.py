"""
ui/pages/05_advisory_report.py
--------------------------------
Streamlit page: AI Advisory Report.

Streams a full advisory narrative for the active client using
ai/claude_advisor.stream_advisory_narrative().

Inputs assembled:
  - Client KYC from DB
  - Risk profile (category + score)
  - All goals from DB
  - Holdings + portfolio summary
  - Performance metrics (CAGR, XIRR, Sharpe)
  - Sector allocation summary

Output:
  - Streaming markdown report rendered live in the browser
  - Download button after stream completes

Run via:
  PYTHONPATH=/Users/manavgupta/financial_advisor streamlit run ui/app.py
"""

import sys, os
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

import streamlit as st
import sqlite3
from datetime import date

from config.settings import DATABASE_PATH
from data.client_manager import get_goals_for_client
from engine.performance_engine import compute_cagr, compute_sharpe_ratio, simulate_sip_cashflows, compute_xirr
from ai.claude_advisor import stream_advisory_narrative

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Advisory Report", page_icon="📄", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #0D1117; color: #C9D1D9; }
  .block-container { padding: 2rem 2.5rem; }
  section[data-testid="stSidebar"] { background: #0D1117; border-right: 1px solid #21262D; }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
  .page-title { font-family: 'DM Serif Display', serif; font-size: 1.9rem; color: #E6EDF3; }
  .page-sub { color: #8B949E; font-size: 0.85rem; margin-top: -0.5rem; margin-bottom: 1.5rem; }
  .section-heading { font-family: 'DM Serif Display', serif; font-size: 1.1rem; color: #E6EDF3; margin: 1.5rem 0 0.75rem; padding-bottom: 0.4rem; border-bottom: 1px solid #21262D; }

  /* Report container */
  .report-container {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 12px;
    padding: 2rem 2.5rem;
    margin-top: 1.5rem;
    line-height: 1.8;
  }
  .report-container h1, .report-container h2, .report-container h3 {
    font-family: 'DM Serif Display', serif !important;
    color: #E6EDF3 !important;
    margin-top: 1.5rem;
  }
  .report-container h1 { font-size: 1.6rem; border-bottom: 1px solid #21262D; padding-bottom: 0.5rem; }
  .report-container h2 { font-size: 1.2rem; color: #58A6FF !important; }
  .report-container h3 { font-size: 1rem; color: #3FB950 !important; }
  .report-container p  { color: #C9D1D9; font-size: 0.9rem; }
  .report-container ul, .report-container ol { color: #C9D1D9; font-size: 0.9rem; }
  .report-container strong { color: #E6EDF3; }
  .report-container table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
  .report-container th { background: #21262D; color: #E6EDF3; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; }
  .report-container td { padding: 0.4rem 0.75rem; border-bottom: 1px solid #21262D; font-size: 0.88rem; color: #C9D1D9; }

  /* Context card */
  .context-card {
    background: #161B22; border: 1px solid #21262D;
    border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 1rem;
  }
  .context-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; color: #8B949E; margin-bottom: 0.25rem; }
  .context-value { font-size: 0.9rem; color: #E6EDF3; font-weight: 500; }
  h1,h2,h3 { color: #E6EDF3 !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 📄 Advisory Report")
    st.caption("Stream a full AI-generated financial plan for the active client.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_client(client_id: int) -> dict:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_holdings(client_id: int) -> list[dict]:
    """Return holdings with scheme_name and computed current_value."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT h.*,
               COALESCE(f.scheme_name, 'Scheme ' || h.scheme_code) AS scheme_name,
               (h.units * h.avg_nav) AS current_value
        FROM client_holdings h
        LEFT JOIN funds f ON f.scheme_code = h.scheme_code
        WHERE h.client_id = ?
    """, (client_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_report_context(client: dict, goals: list, holdings: list) -> dict:
    """Assemble structured context dict for claude_advisor."""
    total_invested = sum(h.get("invested_amount", 0) for h in holdings)
    total_current  = sum(h.get("current_value",   0) for h in holdings)

    cagr = 0.0
    xirr = None
    if total_invested > 0:
        cagr = compute_cagr(total_invested, total_current, years=3.0)
        try:
            cfs = simulate_sip_cashflows(total_invested, months=36, final_value=total_current)
            xirr = compute_xirr(cfs)
        except Exception:
            pass

    sharpe = compute_sharpe_ratio(cagr, risk_free_rate=0.065, volatility=0.15)
    gain   = total_current - total_invested
    gain_pct = (gain / total_invested * 100) if total_invested > 0 else 0.0

    return {
        "client": {
            "name":          client.get("name"),
            "age":           client.get("age"),
            "annual_income": client.get("annual_income"),
            "dependants":    client.get("dependants"),
            "risk_profile":  client.get("risk_profile"),
            "risk_score":    client.get("risk_score"),
        },
        "goals": [
            {
                "name":         g.goal_name,
                "type":         g.goal_type,
                "target":       g.target_amount,
                "target_year":  g.target_year,
                "monthly_sip":  g.monthly_sip,
            }
            for g in goals
        ],
        "portfolio": {
            "num_holdings": len(holdings),
            "total_invested": total_invested,
            "total_current":  total_current,
            "absolute_gain":  gain,
            "gain_pct":       gain_pct,
        },
        "performance": {
            "cagr":   cagr,
            "xirr":   xirr,
            "sharpe": sharpe,
        },
        "holdings": [
            {
                "name":      h.get("scheme_name"),
                "invested":  h.get("invested_amount"),
                "current":   h.get("current_value"),
            }
            for h in holdings
        ],
        "report_date": date.today().isoformat(),
    }


# ── Guard ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="page-title">Advisory Report</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Claude generates a personalised financial advisory narrative — streamed live — covering risk profile, goals, portfolio health, and recommendations.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client selected. Please choose one in **Client Onboarding**.")
    st.stop()

client   = get_client(client_id)
goals    = get_goals_for_client(client_id)
holdings = get_holdings(client_id)

if not client:
    st.error("Client not found.")
    st.stop()


# ── Context snapshot ──────────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Report Context</div>', unsafe_allow_html=True)

cc1, cc2, cc3, cc4 = st.columns(4)
with cc1:
    st.markdown(f'<div class="context-card"><div class="context-label">Client</div><div class="context-value">{client["name"]}</div></div>', unsafe_allow_html=True)
with cc2:
    rp = client.get("risk_profile", "—")
    st.markdown(f'<div class="context-card"><div class="context-label">Risk Profile</div><div class="context-value">{rp}</div></div>', unsafe_allow_html=True)
with cc3:
    st.markdown(f'<div class="context-card"><div class="context-label">Goals</div><div class="context-value">{len(goals)} defined</div></div>', unsafe_allow_html=True)
with cc4:
    st.markdown(f'<div class="context-card"><div class="context-label">Holdings</div><div class="context-value">{len(holdings)} funds</div></div>', unsafe_allow_html=True)


# ── Report options ────────────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Report Options</div>', unsafe_allow_html=True)

with st.expander("⚙️ Customise report focus (optional)"):
    extra_instructions = st.text_area(
        "Additional instructions for Claude",
        placeholder="e.g. Focus on tax-saving strategies. Include NPS recommendations. Be concise.",
        height=80,
    )
    include_sections = st.multiselect(
        "Sections to include",
        ["Executive Summary", "Risk Profile Analysis", "Goal Review", "Portfolio Health",
         "Fund Recommendations", "Tax Planning", "Action Items"],
        default=["Executive Summary", "Risk Profile Analysis", "Goal Review", "Portfolio Health",
                 "Fund Recommendations", "Action Items"],
    )

report_placeholder = st.empty()
download_placeholder = st.empty()

generate_btn = st.button("📄  Generate Advisory Report", type="primary", use_container_width=True)

if generate_btn:
    context = build_report_context(client, goals, holdings)

    # Add customisation to context
    context["extra_instructions"] = st.session_state.get("extra_instructions", "")
    context["requested_sections"] = include_sections

    full_report = ""
    report_placeholder.markdown(
        '<div class="report-container"><em style="color:#8B949E;">Generating report…</em></div>',
        unsafe_allow_html=True
    )

    try:
        for chunk in stream_advisory_narrative(client_context=context):
            full_report += chunk
            report_placeholder.markdown(
                f'<div class="report-container">{full_report}</div>',
                unsafe_allow_html=True,
            )

        st.session_state["last_report"] = full_report
        st.session_state["last_report_client"] = client["name"]

    except Exception as e:
        report_placeholder.error(f"Streaming error: {e}")


# ── Show last report if available and not re-generating ───────────────────────
elif "last_report" in st.session_state and not generate_btn:
    st.caption(f"📄 Showing last report for **{st.session_state.get('last_report_client', '—')}**. Click **Generate** to refresh.")
    report_placeholder.markdown(
        f'<div class="report-container">{st.session_state["last_report"]}</div>',
        unsafe_allow_html=True,
    )


# ── Download ──────────────────────────────────────────────────────────────────
if "last_report" in st.session_state:
    client_name_safe = (st.session_state.get("last_report_client") or "report").replace(" ", "_")
    download_placeholder.download_button(
        label="⬇️  Download Report as Markdown",
        data=st.session_state["last_report"],
        file_name=f"advisory_report_{client_name_safe}_{date.today().isoformat()}.md",
        mime="text/markdown",
        use_container_width=True,
    )
