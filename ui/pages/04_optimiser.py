"""
ui/pages/04_optimiser.py

Phase 5 fix: explain_portfolio_optimisation() is now a streaming generator.
Updated the streaming loop accordingly. No other logic changes.
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
import sqlite3
import plotly.graph_objects as go

from config.settings import DATABASE_PATH
from data.database import init_db
from engine.optimiser_engine import FundStats, OptimiserConstraints, optimise_portfolio, efficient_frontier
from ai.claude_advisor import parse_optimiser_constraints, explain_portfolio_optimisation
init_db()

st.set_page_config(page_title="Portfolio Optimiser", page_icon="\u2699\ufe0f", layout="wide")

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
  .constraint-box { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.25rem; margin-bottom: 1rem; }
  .constraint-box pre { color: #3FB950; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; margin: 0; }
  .alloc-row { display: flex; align-items: center; gap: 1rem; padding: 0.6rem 0; border-bottom: 1px solid #21262D; }
  .alloc-name { flex: 1; font-size: 0.88rem; color: #E6EDF3; }
  .alloc-bar-bg { flex: 2; background: #21262D; border-radius: 4px; height: 8px; }
  .alloc-bar { background: #3FB950; border-radius: 4px; height: 8px; }
  .alloc-pct { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #3FB950; min-width: 50px; text-align: right; }
  .claude-stream { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.5rem; margin-top: 1rem; font-size: 0.9rem; line-height: 1.7; white-space: pre-wrap; }
  .info-note { background: #161B22; border-left: 3px solid #E3B341; border-radius: 6px; padding: 0.75rem 1rem; font-size: 0.8rem; color: #8B949E; margin-bottom: 1rem; }
  .wordmark { font-family: 'DM Serif Display', serif; font-size: 1.6rem; color: #E6EDF3; }
  .wordmark span { color: #3FB950; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextArea > div > div { background: #161B22 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
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


def dark_chart(fig, height=350):
    fig.update_layout(paper_bgcolor="#161B22", plot_bgcolor="#161B22",
                      font={"color": "#C9D1D9", "family": "Inter"}, height=height,
                      margin=dict(l=10,r=10,t=40,b=10), legend=dict(bgcolor="#161B22",bordercolor="#21262D"))
    fig.update_xaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    fig.update_yaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    return fig


st.markdown('<div class="page-title">Portfolio Optimiser</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Type constraints in plain English. Claude parses them, then CVXPY finds the optimal allocation.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client selected.")
    st.stop()

holdings = get_holdings(client_id)
if len(holdings) < 2:
    st.info("Add at least 2 holdings in **Portfolio** before running the optimiser.")
    st.stop()

st.markdown('<div class="section-heading">Step 1 \u2014 Constraints</div>', unsafe_allow_html=True)
nl_constraints = st.text_area("Your constraints", value="",
    placeholder="e.g. No single fund more than 40%. Keep at least 3 funds. Minimum 5% per fund.",
    height=80, label_visibility="collapsed")
objective = st.radio("Optimisation objective", ["Maximise Sharpe Ratio", "Minimise Variance"], horizontal=True)
obj_key   = "max_sharpe" if "Sharpe" in objective else "min_variance"

if st.button("\U0001f50d  Parse Constraints with Claude", use_container_width=True):
    if not nl_constraints.strip():
        st.warning("Please enter constraints first.")
    else:
        with st.spinner("Sending to Claude\u2026"):
            try:
                parsed = parse_optimiser_constraints(nl_constraints)
                st.session_state["parsed_constraints"] = {
                    "min_funds": parsed.min_funds, "max_funds": parsed.max_funds,
                    "min_weight": parsed.min_weight, "max_weight": parsed.max_weight,
                    "risk_free_rate": parsed.risk_free_rate}
                st.success("Constraints parsed!")
            except Exception as e:
                st.error(f"Claude parse error: {e}")

if "parsed_constraints" in st.session_state:
    pc = st.session_state["parsed_constraints"]
    st.markdown(f"""<div class="constraint-box"><pre>min_funds : {pc['min_funds']}\nmax_funds : {pc['max_funds']}\nmin_weight: {pc['min_weight']*100:.0f}%\nmax_weight: {pc['max_weight']*100:.0f}%\nrisk_free : {pc['risk_free_rate']*100:.1f}%</pre></div>""", unsafe_allow_html=True)

st.markdown('<div class="section-heading">Step 2 \u2014 Run Optimiser</div>', unsafe_allow_html=True)


def build_fund_stats(holdings):
    stats = []
    for h in holdings:
        inv = h["invested_amount"] or 1
        cur = h["current_value"]  or inv
        er  = max((cur/inv)**(1/3.0)-1, 0.05)
        stats.append(FundStats(scheme_code=h["scheme_code"],
            scheme_name=h["scheme_name"] or str(h["scheme_code"]),
            expected_return=round(er,4), volatility=0.15,
            sharpe_ratio=round((er-0.065)/0.15,2)))
    return stats


fund_stats = build_fund_stats(holdings)
st.markdown('<div class="info-note">\u26a0\ufe0f Volatility fixed at 15% per fund (estimated). Returns derived from invested vs current values.</div>', unsafe_allow_html=True)

if st.button("\u26a1  Run Optimiser", type="primary", use_container_width=True):
    pc = st.session_state.get("parsed_constraints", {})
    constraints = OptimiserConstraints(
        min_funds=pc.get("min_funds",3), max_funds=pc.get("max_funds",len(holdings)),
        min_weight=pc.get("min_weight",0.05), max_weight=pc.get("max_weight",0.40),
        risk_free_rate=pc.get("risk_free_rate",0.065))
    n = len(fund_stats)
    corr = [[1.0 if i==j else 0.3 for j in range(n)] for i in range(n)]
    with st.spinner("Running CVXPY optimiser\u2026"):
        try:
            result = optimise_portfolio(funds=fund_stats, correlation_matrix=corr, constraints=constraints, objective=obj_key)
            st.session_state["opt_result"] = {
                "weights": result.weights, "fund_names": [f.scheme_name for f in fund_stats],
                "sharpe": result.portfolio_sharpe, "return": result.portfolio_return,
                "volatility": result.portfolio_volatility, "objective": obj_key}
            st.session_state["fund_stats_for_explain"] = [{"name":f.scheme_name,"return":f.expected_return,"vol":f.volatility} for f in fund_stats]
            st.session_state["constraints_for_explain"] = pc
            st.success("Optimisation complete!")
        except Exception as e:
            st.error(f"Optimiser error: {e}")
    with st.spinner("Computing efficient frontier\u2026"):
        try:
            st.session_state["ef_points"] = efficient_frontier(funds=fund_stats, correlation_matrix=corr, constraints=constraints, n_points=30)
        except Exception:
            st.session_state["ef_points"] = None

if "opt_result" in st.session_state:
    res = st.session_state["opt_result"]
    st.markdown('<div class="section-heading">Step 3 \u2014 Optimised Portfolio</div>', unsafe_allow_html=True)
    rm1, rm2, rm3 = st.columns(3)
    rm1.metric("Portfolio Return",     f"{res['return']*100:.2f}%")
    rm2.metric("Portfolio Volatility", f"{res['volatility']*100:.2f}%")
    rm3.metric("Sharpe Ratio",         f"{res['sharpe']:.2f}")
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**Allocation Weights**")
        for name, w in sorted(zip(res["fund_names"],res["weights"]), key=lambda x:x[1], reverse=True):
            pct   = w*100
            short = name[:35]+"\u2026" if len(name)>38 else name
            st.markdown(f"""<div class="alloc-row"><div class="alloc-name">{short}</div><div class="alloc-bar-bg"><div class="alloc-bar" style="width:{pct:.1f}%"></div></div><div class="alloc-pct">{pct:.1f}%</div></div>""", unsafe_allow_html=True)
    with oc2:
        sp = sorted(zip(res["fund_names"],res["weights"]), key=lambda x:x[1], reverse=True)
        fig_bar = go.Figure(go.Bar(x=[p[0][:25]+"\u2026" if len(p[0])>28 else p[0] for p in sp],
            y=[p[1]*100 for p in sp], marker_color="#3FB950",
            text=[f"{p[1]*100:.1f}%" for p in sp], textposition="outside"))
        fig_bar.update_layout(title="Fund Weights (%)", yaxis_title="%", xaxis_tickangle=-20)
        st.plotly_chart(dark_chart(fig_bar, 320), use_container_width=True)
    ef_points = st.session_state.get("ef_points")
    if ef_points:
        st.markdown('<div class="section-heading">Efficient Frontier</div>', unsafe_allow_html=True)
        fig_ef = go.Figure()
        fig_ef.add_trace(go.Scatter(x=[p["volatility"]*100 for p in ef_points], y=[p["return"]*100 for p in ef_points],
            mode="lines+markers", line=dict(color="#3FB950",width=2), name="Efficient Frontier"))
        fig_ef.add_trace(go.Scatter(x=[res["volatility"]*100], y=[res["return"]*100], mode="markers",
            marker=dict(color="#F85149",size=12,symbol="star"), name="Optimal"))
        fig_ef.update_layout(title="Risk\u2013Return Frontier", xaxis_title="Volatility (%)", yaxis_title="Return (%)")
        st.plotly_chart(dark_chart(fig_ef, 380), use_container_width=True)

    st.markdown('<div class="section-heading">Step 4 \u2014 AI Explanation</div>', unsafe_allow_html=True)
    if st.button("\U0001f916  Explain with Claude", use_container_width=True):
        placeholder = st.empty()
        full_text = ""
        try:
            placeholder.markdown('<div class="claude-stream">Generating\u2026</div>', unsafe_allow_html=True)
            # explain_portfolio_optimisation is now a streaming generator (Phase 5 fix)
            weights_dict = dict(zip(res["fund_names"], res["weights"]))
            for chunk in explain_portfolio_optimisation(
                optimised_weights=weights_dict,
                portfolio_metrics={"return": res["return"], "volatility": res["volatility"], "sharpe": res["sharpe"]},
                fund_stats=st.session_state.get("fund_stats_for_explain", []),
                constraints=st.session_state.get("constraints_for_explain", {}),
                objective=res["objective"],
            ):
                full_text += chunk
                placeholder.markdown(f'<div class="claude-stream">{full_text}</div>', unsafe_allow_html=True)
        except Exception as e:
            placeholder.error(f"Streaming error: {e}")
