"""
ui/pages/03_portfolio.py
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
import sqlite3
import plotly.graph_objects as go
import plotly.express as px

from config.settings import DATABASE_PATH
from data.database import init_db
from data.client_manager import add_holding
from engine.performance_engine import compute_cagr, compute_sharpe_ratio, simulate_sip_cashflows, compute_xirr
from engine.overlap_engine import compute_overlap_matrix
from engine.sector_engine import compute_portfolio_sector_allocation
init_db()

st.set_page_config(page_title="Portfolio Analytics", page_icon="📈", layout="wide")

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
  .section-heading { font-family: 'DM Serif Display', serif; font-size: 1.1rem; color: #E6EDF3; margin: 1.75rem 0 0.75rem; padding-bottom: 0.4rem; border-bottom: 1px solid #21262D; }
  .metric-strip { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.1rem 1.25rem; }
  .metric-strip .label { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em; color: #8B949E; margin-bottom: 0.3rem; }
  .metric-strip .value { font-family: 'JetBrains Mono', monospace; font-size: 1.35rem; color: #E6EDF3; }
  .positive { color: #3FB950 !important; } .negative { color: #F85149 !important; }
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
        st.page_link("pages/01_Client_Onboarding.py", label="Client Onboarding", icon="🧾")
        st.page_link("pages/02_Goal_Planner.py",      label="Goal Planner",       icon="🎯")
        st.page_link("pages/03_Portfolio.py",          label="Portfolio",          icon="📈")
        st.page_link("pages/04_Optimiser.py",          label="Optimiser",          icon="⚙️")
        st.page_link("pages/05_Advisory_Report.py",    label="Advisory Report",    icon="📄")
        st.divider()
        st.markdown('<p style="font-size:0.65rem;color:#30363D;">Phase 5 — Streamlit UI</p>', unsafe_allow_html=True)

_sidebar()


def get_holdings(client_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT h.*, COALESCE(f.scheme_name, 'Scheme ' || h.scheme_code) AS scheme_name,
                   (h.units * h.avg_nav) AS current_value
            FROM client_holdings h LEFT JOIN funds f ON f.scheme_code = h.scheme_code
            WHERE h.client_id = ?
        """, (client_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def dark_chart(fig, height=320):
    fig.update_layout(paper_bgcolor="#161B22", plot_bgcolor="#161B22",
                      font={"color": "#C9D1D9", "family": "Inter"}, height=height,
                      margin=dict(l=10,r=10,t=30,b=10), legend=dict(bgcolor="#161B22",bordercolor="#21262D"))
    fig.update_xaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    fig.update_yaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    return fig


st.markdown('<div class="page-title">Portfolio Analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Holdings, performance metrics, sector exposure and fund overlap.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client. Please select one in **Client Onboarding**.")
    st.stop()

holdings       = get_holdings(client_id)
invested_total = sum(h["invested_amount"] for h in holdings)
current_total  = sum(h["current_value"]   for h in holdings)
gain_total     = current_total - invested_total
gain_pct_total = (gain_total / invested_total * 100) if invested_total > 0 else 0.0

s1, s2, s3, s4, s5 = st.columns(5)
for col, label, val, cls in [
    (s1, "Holdings",       str(len(holdings)),             ""),
    (s2, "Total Invested", f"₹{invested_total/1e5:.2f}L",  ""),
    (s3, "Current Value",  f"₹{current_total/1e5:.2f}L",   ""),
    (s4, "Absolute Gain",  f"₹{gain_total/1e5:.2f}L",      "positive" if gain_total>=0 else "negative"),
    (s5, "Gain %",         f"{gain_pct_total:.2f}%",        "positive" if gain_pct_total>=0 else "negative"),
]:
    with col:
        st.markdown(f'<div class="metric-strip"><div class="label">{label}</div><div class="value {cls}">{val}</div></div>', unsafe_allow_html=True)

st.markdown('<div class="section-heading">Holdings</div>', unsafe_allow_html=True)
if not holdings:
    st.info("No holdings yet. Add one below.")
else:
    import pandas as pd
    df = pd.DataFrame(holdings)
    df["gain"]     = df["current_value"] - df["invested_amount"]
    df["gain_pct"] = (df["gain"] / df["invested_amount"] * 100).round(2)
    disp = df[["scheme_name","units","avg_nav","invested_amount","current_value","gain","gain_pct"]].copy()
    disp.columns = ["Fund","Units","Avg NAV","Invested (₹)","Current (₹)","Gain (₹)","Gain %"]
    for c in ["Invested (₹)","Current (₹)","Gain (₹)"]: disp[c] = disp[c].apply(lambda x: f"₹{x:,.0f}")
    disp["Gain %"]   = disp["Gain %"].apply(lambda x: f"{x:.2f}%")
    disp["Avg NAV"]  = disp["Avg NAV"].apply(lambda x: f"₹{x:,.2f}")
    disp["Units"]    = disp["Units"].apply(lambda x: f"{x:,.2f}")
    st.dataframe(disp, use_container_width=True, hide_index=True)

if holdings:
    st.markdown('<div class="section-heading">Performance Metrics</div>', unsafe_allow_html=True)
    cagr = compute_cagr(invested_total, current_total, years=3.0)
    try:
        cfs      = simulate_sip_cashflows(invested_total, months=36, final_value=current_total)
        xirr_val = compute_xirr(cfs)
    except Exception:
        xirr_val = None
    sharpe = compute_sharpe_ratio(cagr, risk_free_rate=0.065, volatility=0.15)
    pm1, pm2, pm3, pm4 = st.columns(4)
    with pm1:
        cls = "positive" if cagr >= 0 else "negative"
        st.markdown(f'<div class="metric-strip"><div class="label">CAGR (est.)</div><div class="value {cls}">{cagr*100:.2f}%</div></div>', unsafe_allow_html=True)
    with pm2:
        if xirr_val is not None:
            cls = "positive" if xirr_val >= 0 else "negative"
            st.markdown(f'<div class="metric-strip"><div class="label">XIRR (sim. SIP)</div><div class="value {cls}">{xirr_val*100:.2f}%</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="metric-strip"><div class="label">XIRR</div><div class="value">—</div></div>', unsafe_allow_html=True)
    with pm3:
        cls = "positive" if sharpe >= 1 else ("" if sharpe >= 0 else "negative")
        st.markdown(f'<div class="metric-strip"><div class="label">Sharpe Ratio</div><div class="value {cls}">{sharpe:.2f}</div></div>', unsafe_allow_html=True)
    with pm4:
        cls = "positive" if gain_total >= 0 else "negative"
        st.markdown(f'<div class="metric-strip"><div class="label">Absolute Gain</div><div class="value {cls}">₹{gain_total/1e5:.2f}L</div></div>', unsafe_allow_html=True)
    st.caption("ℹ️ XIRR uses simulated equal-monthly SIP cashflows. CAGR assumes 3-year horizon.")

st.markdown('<div class="section-heading">Sector Allocation</div>', unsafe_allow_html=True)
scheme_codes = [h["scheme_code"] for h in holdings if h.get("scheme_code")]
weights_map  = {h["scheme_code"]: h["invested_amount"] / (invested_total or 1) for h in holdings if h.get("scheme_code")}
if scheme_codes:
    try:
        sector_alloc = compute_portfolio_sector_allocation(scheme_codes=scheme_codes, portfolio_weights=weights_map, db_path=DATABASE_PATH)
        if sector_alloc:
            sectors  = sorted(sector_alloc.items(), key=lambda x: x[1], reverse=True)
            s_labels = [s[0] for s in sectors]
            s_vals   = [round(s[1]*100,2) for s in sectors]
            sa1, sa2 = st.columns(2)
            with sa1:
                fig_bar = go.Figure(go.Bar(x=s_vals, y=s_labels, orientation="h",
                    marker_color=["#F85149" if v>40 else "#E3B341" if v>25 else "#3FB950" for v in s_vals],
                    text=[f"{v:.1f}%" for v in s_vals], textposition="outside"))
                fig_bar.update_layout(title="Sector Weights", xaxis_title="%", yaxis_autorange="reversed")
                st.plotly_chart(dark_chart(fig_bar, 380), use_container_width=True)
            with sa2:
                fig_pie = go.Figure(go.Pie(labels=s_labels, values=s_vals, hole=0.45,
                    marker=dict(colors=px.colors.qualitative.Plotly), textinfo="label+percent", textfont_size=10))
                fig_pie.update_layout(title="Sector Distribution", showlegend=False)
                st.plotly_chart(dark_chart(fig_pie, 380), use_container_width=True)
        else:
            st.info("No sector data yet. Run holdings_fetcher to populate.")
    except Exception as e:
        st.warning(f"Sector engine error: {e}")
else:
    st.info("Add holdings with scheme codes to see sector allocation.")

st.markdown('<div class="section-heading">Fund Overlap Matrix</div>', unsafe_allow_html=True)
if len(scheme_codes) >= 2:
    try:
        overlap_matrix = compute_overlap_matrix(scheme_codes=scheme_codes, db_path=DATABASE_PATH)
        if overlap_matrix:
            fund_names  = [next((h["scheme_name"] for h in holdings if h["scheme_code"]==sc), str(sc)) for sc in scheme_codes]
            short_names = [n[:25]+"…" if len(n)>28 else n for n in fund_names]
            matrix_vals = [[overlap_matrix.get((sc1,sc2),0.0)*100 for sc2 in scheme_codes] for sc1 in scheme_codes]
            fig_heat = go.Figure(go.Heatmap(z=matrix_vals, x=short_names, y=short_names,
                colorscale=[[0,"#161B22"],[0.2,"#1A7F37"],[0.4,"#9E6A03"],[1.0,"#F85149"]],
                zmin=0, zmax=100, text=[[f"{v:.1f}%" for v in row] for row in matrix_vals],
                texttemplate="%{text}", textfont={"size":11}, showscale=True))
            fig_heat.update_layout(title="Pairwise Overlap (%)", xaxis=dict(tickangle=-30))
            st.plotly_chart(dark_chart(fig_heat, 400), use_container_width=True)
        else:
            st.info("Holdings data not yet populated.")
    except Exception as e:
        st.warning(f"Overlap engine error: {e}")
else:
    st.info("Need at least 2 holdings to compute overlap.")

st.markdown('<div class="section-heading">Add Holding</div>', unsafe_allow_html=True)
with st.expander("➕ Add a new holding manually"):
    with st.form("add_holding_form"):
        h1, h2 = st.columns(2)
        with h1: scheme_code = st.number_input("Scheme Code (AMFI)", min_value=1, value=119598)
        with h2: units = st.number_input("Units", min_value=0.0, value=100.0, step=0.01)
        h3, h4 = st.columns(2)
        with h3: avg_nav = st.number_input("Avg NAV (₹)", min_value=0.0, value=50.0, step=0.01)
        with h4: invested_amount = st.number_input("Amount Invested (₹)", min_value=0, value=50000, step=1000)
        if st.form_submit_button("💾  Save Holding", type="primary", use_container_width=True):
            add_holding(client_id=client_id, scheme_code=scheme_code, units=units, avg_nav=avg_nav, invested_amount=invested_amount)
            st.success(f"Holding (scheme {scheme_code}) added.")
            st.rerun()
