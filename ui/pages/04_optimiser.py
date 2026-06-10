"""
ui/pages/04_optimiser.py
--------------------------
Streamlit page: Portfolio Optimiser.

Features:
  1. Natural-language constraint input → parsed by LLM (ai/claude_advisor.py)
  2. Select optimisation objective: Max Sharpe or Min Variance
  3. Run optimiser (engine/optimiser_engine.py) against current holdings
  4. Display optimised weights as bar chart + allocation table
  5. Efficient frontier scatter (optimiser_engine.efficient_frontier)
  6. Stream Claude's explanation of the optimisation result

Run via:
  PYTHONPATH=/Users/manavgupta/financial_advisor streamlit run ui/app.py
"""

import sys, os
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

import streamlit as st
import sqlite3
import plotly.graph_objects as go

from config.settings import DATABASE_PATH
from engine.optimiser_engine import (
    FundStats, OptimiserConstraints,
    optimise_portfolio, efficient_frontier,
)
from ai.claude_advisor import (
    parse_optimiser_constraints,
    explain_portfolio_optimisation,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Portfolio Optimiser", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #0D1117; color: #C9D1D9; }
  .block-container { padding: 2rem 2.5rem; }
  section[data-testid="stSidebar"] { background: #0D1117; border-right: 1px solid #21262D; }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
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
  .claude-stream { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.5rem; margin-top: 1rem; font-size: 0.9rem; line-height: 1.7; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextArea > div > div { background: #161B22 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Portfolio Optimiser")
    st.caption("Max-Sharpe or Min-Variance with natural-language constraints.")


def get_holdings(client_id: int) -> list[dict]:
    """Return holdings with scheme_name (from funds table) and computed current_value."""
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


def dark_chart(fig: go.Figure, height: int = 350) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="#161B22", plot_bgcolor="#161B22",
        font={"color": "#C9D1D9", "family": "Inter"},
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(bgcolor="#161B22", bordercolor="#21262D"),
    )
    fig.update_xaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    fig.update_yaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    return fig


# ── Guard ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="page-title">Portfolio Optimiser</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Type your constraints in plain English. Claude parses them, then the CVXPY solver finds the optimal allocation.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client selected.")
    st.stop()

holdings = get_holdings(client_id)
if len(holdings) < 2:
    st.info("Add at least 2 holdings in **Portfolio** before running the optimiser.")
    st.stop()


# ── Step 1: Constraints ────────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Step 1 — Constraints</div>', unsafe_allow_html=True)

st.markdown("""
<p style='color:#8B949E;font-size:0.85rem;'>
Describe any constraints in plain English. Examples:<br>
<em>"No single fund more than 35%. At least 3 funds. Min 5% per fund."</em><br>
<em>"Max 40% in any one fund, keep at least 4 funds, limit min allocation to 8%."</em>
</p>
""", unsafe_allow_html=True)

nl_constraints = st.text_area(
    "Your constraints",
    value="No single fund should exceed 40%. Keep at least 3 funds. Minimum 5% per fund.",
    height=80,
    label_visibility="collapsed",
)

objective = st.radio(
    "Optimisation objective",
    ["Maximise Sharpe Ratio", "Minimise Variance"],
    horizontal=True,
)
obj_key = "max_sharpe" if "Sharpe" in objective else "min_variance"

parse_btn = st.button("🔍  Parse Constraints with Claude", use_container_width=True)

parsed_constraints: OptimiserConstraints | None = None

if parse_btn:
    with st.spinner("Sending to Claude…"):
        try:
            parsed_constraints = parse_optimiser_constraints(nl_constraints)
            st.session_state["parsed_constraints"] = {
                "min_funds":     parsed_constraints.min_funds,
                "max_funds":     parsed_constraints.max_funds,
                "min_weight":    parsed_constraints.min_weight,
                "max_weight":    parsed_constraints.max_weight,
                "risk_free_rate":parsed_constraints.risk_free_rate,
            }
            st.success("Constraints parsed!")
        except Exception as e:
            st.error(f"Claude parse error: {e}")

# Show parsed constraints if available
if "parsed_constraints" in st.session_state:
    pc = st.session_state["parsed_constraints"]
    st.markdown(f"""
    <div class="constraint-box">
      <div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.5rem;">Parsed Constraints</div>
      <pre>min_funds    : {pc['min_funds']}
max_funds    : {pc['max_funds']}
min_weight   : {pc['min_weight']*100:.0f}%
max_weight   : {pc['max_weight']*100:.0f}%
risk_free    : {pc['risk_free_rate']*100:.1f}%</pre>
    </div>
    """, unsafe_allow_html=True)


# ── Step 2: Run Optimiser ──────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Step 2 — Run Optimiser</div>', unsafe_allow_html=True)

# Build FundStats from holdings
# Use simple estimates: expected_return from (current-invested)/invested / 3yr, volatility=15%, correlation=0
import math

def build_fund_stats(holdings: list[dict]) -> list[FundStats]:
    stats = []
    for h in holdings:
        invested = h["invested_amount"] or 1
        current  = h["current_value"]  or invested
        years    = 3.0
        er       = max((current / invested) ** (1 / years) - 1, 0.05)
        stats.append(FundStats(
            scheme_code=h["scheme_code"],
            scheme_name=h["scheme_name"] or str(h["scheme_code"]),
            expected_return=round(er, 4),
            volatility=0.15,
            sharpe_ratio=round((er - 0.065) / 0.15, 2),
        ))
    return stats

fund_stats = build_fund_stats(holdings)

run_btn = st.button("⚡  Run Optimiser", type="primary", use_container_width=True)

if run_btn:
    # Build constraints (use parsed if available, else defaults)
    pc = st.session_state.get("parsed_constraints", {})
    constraints = OptimiserConstraints(
        min_funds      = pc.get("min_funds", 3),
        max_funds      = pc.get("max_funds", len(holdings)),
        min_weight     = pc.get("min_weight", 0.05),
        max_weight     = pc.get("max_weight", 0.40),
        risk_free_rate = pc.get("risk_free_rate", 0.065),
    )

    # Correlation matrix (identity for now — no history)
    n = len(fund_stats)
    corr_matrix = [[1.0 if i == j else 0.3 for j in range(n)] for i in range(n)]

    with st.spinner("Running CVXPY optimiser…"):
        try:
            result = optimise_portfolio(
                funds=fund_stats,
                correlation_matrix=corr_matrix,
                constraints=constraints,
                objective=obj_key,
            )
            st.session_state["opt_result"] = {
                "weights":     result.weights,
                "fund_names":  [f.scheme_name for f in fund_stats],
                "sharpe":      result.portfolio_sharpe,
                "return":      result.portfolio_return,
                "volatility":  result.portfolio_volatility,
                "objective":   obj_key,
            }
            st.session_state["fund_stats_for_explain"] = [
                {"name": f.scheme_name, "return": f.expected_return, "vol": f.volatility}
                for f in fund_stats
            ]
            st.session_state["constraints_for_explain"] = pc
            st.success("Optimisation complete!")
        except Exception as e:
            st.error(f"Optimiser error: {e}")

    # Efficient frontier
    with st.spinner("Computing efficient frontier…"):
        try:
            ef_points = efficient_frontier(
                funds=fund_stats,
                correlation_matrix=corr_matrix,
                constraints=constraints,
                n_points=30,
            )
            st.session_state["ef_points"] = ef_points
        except Exception:
            st.session_state["ef_points"] = None


# ── Step 3: Results ────────────────────────────────────────────────────────────
if "opt_result" in st.session_state:
    res = st.session_state["opt_result"]

    st.markdown('<div class="section-heading">Step 3 — Optimised Portfolio</div>', unsafe_allow_html=True)

    rm1, rm2, rm3 = st.columns(3)
    with rm1:
        st.metric("Portfolio Return", f"{res['return']*100:.2f}%")
    with rm2:
        st.metric("Portfolio Volatility", f"{res['volatility']*100:.2f}%")
    with rm3:
        st.metric("Sharpe Ratio", f"{res['sharpe']:.2f}")

    # Allocation visual
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**Allocation Weights**")
        names   = res["fund_names"]
        weights = res["weights"]
        for name, w in sorted(zip(names, weights), key=lambda x: x[1], reverse=True):
            pct  = w * 100
            short = name[:35] + "…" if len(name) > 38 else name
            st.markdown(f"""
            <div class="alloc-row">
              <div class="alloc-name">{short}</div>
              <div class="alloc-bar-bg"><div class="alloc-bar" style="width:{pct:.1f}%"></div></div>
              <div class="alloc-pct">{pct:.1f}%</div>
            </div>""", unsafe_allow_html=True)

    with oc2:
        # Bar chart
        sorted_pairs = sorted(zip(names, weights), key=lambda x: x[1], reverse=True)
        snames = [p[0][:25] + "…" if len(p[0]) > 28 else p[0] for p in sorted_pairs]
        sweights = [p[1] * 100 for p in sorted_pairs]

        fig_bar = go.Figure(go.Bar(
            x=snames, y=sweights,
            marker_color="#3FB950",
            text=[f"{w:.1f}%" for w in sweights],
            textposition="outside",
        ))
        fig_bar.update_layout(title="Fund Weights (%)", yaxis_title="%", xaxis_tickangle=-20)
        st.plotly_chart(dark_chart(fig_bar, 320), use_container_width=True)

    # Efficient frontier
    ef_points = st.session_state.get("ef_points")
    if ef_points:
        st.markdown('<div class="section-heading">Efficient Frontier</div>', unsafe_allow_html=True)
        ef_vols = [p["volatility"] * 100 for p in ef_points]
        ef_rets = [p["return"] * 100      for p in ef_points]
        ef_sharpes = [p.get("sharpe", 0) for p in ef_points]

        fig_ef = go.Figure()
        fig_ef.add_trace(go.Scatter(
            x=ef_vols, y=ef_rets,
            mode="lines+markers",
            marker=dict(color=ef_sharpes, colorscale="Viridis", size=6, showscale=True,
                        colorbar=dict(title="Sharpe", tickfont=dict(color="#8B949E"), titlefont=dict(color="#8B949E"))),
            line=dict(color="#3FB950", width=2),
            name="Efficient Frontier",
            hovertemplate="Vol: %{x:.1f}%<br>Return: %{y:.1f}%<extra></extra>",
        ))
        # Mark optimal point
        opt_vol = res["volatility"] * 100
        opt_ret = res["return"] * 100
        fig_ef.add_trace(go.Scatter(
            x=[opt_vol], y=[opt_ret],
            mode="markers",
            marker=dict(color="#F85149", size=12, symbol="star"),
            name="Optimal Portfolio",
        ))
        fig_ef.update_layout(
            title="Risk–Return Efficient Frontier",
            xaxis_title="Volatility (%)",
            yaxis_title="Expected Return (%)",
        )
        st.plotly_chart(dark_chart(fig_ef, 380), use_container_width=True)

    # ── Step 4: Claude explanation ─────────────────────────────────────────────
    st.markdown('<div class="section-heading">Step 4 — AI Explanation</div>', unsafe_allow_html=True)

    explain_btn = st.button("🤖  Explain this optimisation with Claude", use_container_width=True)

    if explain_btn:
        fund_stats_info = st.session_state.get("fund_stats_for_explain", [])
        constraints_info = st.session_state.get("constraints_for_explain", {})

        weights_info = dict(zip(res["fund_names"], res["weights"]))

        stream_placeholder = st.empty()
        full_text = ""

        try:
            stream_placeholder.markdown('<div class="claude-stream">Generating explanation…</div>', unsafe_allow_html=True)
            for chunk in explain_portfolio_optimisation(
                optimised_weights=weights_info,
                portfolio_metrics={
                    "return": res["return"],
                    "volatility": res["volatility"],
                    "sharpe": res["sharpe"],
                },
                fund_stats=fund_stats_info,
                constraints=constraints_info,
                objective=res["objective"],
            ):
                full_text += chunk
                stream_placeholder.markdown(
                    f'<div class="claude-stream">{full_text}</div>',
                    unsafe_allow_html=True,
                )
        except Exception as e:
            stream_placeholder.error(f"Claude streaming error: {e}")
