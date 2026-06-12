"""
ui/pages/07_fund_discovery.py

Fund Discovery — Scope Sections 1.4 / 2.7

Read-only fund screener and factsheet reference tool.
Features:
  - Search across 14,000+ funds with filters
  - Fund factsheet: NAV chart, top holdings, sector breakdown
  - AI-generated fund summary (from fund_summaries table)
  - Side-by-side comparison of up to 3 funds
  - Portfolio overlap indicator per fund
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
from agents.fund_summary_agent import get_fund_summary
init_db()

st.set_page_config(page_title="Fund Discovery", page_icon="🔍", layout="wide")

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
  .fund-card { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 0.5rem; cursor: pointer; }
  .fund-name { font-size: 0.9rem; font-weight: 600; color: #E6EDF3; }
  .fund-meta { font-size: 0.75rem; color: #8B949E; margin-top: 0.2rem; }
  .summary-box { background: #161B22; border-left: 3px solid #3FB950; border-radius: 0 8px 8px 0; padding: 1rem 1.25rem; margin: 0.75rem 0; font-size: 0.88rem; line-height: 1.7; color: #C9D1D9; }
  .overlap-pill { display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }
  .overlap-low    { background: #1a4731; color: #3FB950; }
  .overlap-medium { background: #4a2a00; color: #E3B341; }
  .overlap-high   { background: #5A1A08; color: #F85149; }
  .wordmark { font-family: 'DM Serif Display', serif; font-size: 1.6rem; color: #E6EDF3; }
  .wordmark span { color: #3FB950; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextInput > div > div { background: #0D1117 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
  .stSelectbox > div > div { background: #0D1117 !important; border-color: #30363D !important; }
  .stMultiSelect > div { background: #0D1117 !important; border-color: #30363D !important; }
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


def dark_chart(fig, height=300):
    fig.update_layout(
        paper_bgcolor="#161B22", plot_bgcolor="#161B22",
        font={"color": "#C9D1D9", "family": "Inter"}, height=height,
        margin=dict(l=10,r=10,t=30,b=10),
        legend=dict(bgcolor="#161B22", bordercolor="#21262D")
    )
    fig.update_xaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    fig.update_yaxes(gridcolor="#21262D", zerolinecolor="#21262D")
    return fig


def get_client_scheme_codes(client_id) -> list[int]:
    """Get the scheme codes already in the active client's portfolio."""
    if not client_id:
        return []
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        rows = conn.execute(
            "SELECT DISTINCT scheme_code FROM client_holdings WHERE client_id=?",
            (client_id,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def compute_overlap_with_portfolio(scheme_code: int, client_scheme_codes: list[int]) -> float:
    """Return average pairwise overlap % of this fund with client's existing holdings."""
    if not client_scheme_codes:
        return 0.0
    try:
        from engine.overlap_engine import compute_overlap
        scores = []
        for sc in client_scheme_codes:
            if sc != scheme_code:
                ov = compute_overlap(scheme_code, sc)
                scores.append(ov.overlap_pct)
        return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

st.markdown('<div class="page-title">Fund Discovery</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Search 14,000+ funds · View factsheets · Compare up to 3 funds · See portfolio overlap</div>', unsafe_allow_html=True)
st.caption("Read-only reference tool. Fund selection for your plan goes through the recommendation engine and your advisor.")

client_id = st.session_state.get("selected_client_id")
client_scheme_codes = get_client_scheme_codes(client_id)

tab_search, tab_compare = st.tabs(["🔍  Screener & Factsheet", "⚖️  Compare Funds"])

# ── Tab 1: Screener ──────────────────────────────────────────────────────────
with tab_search:
    st.markdown('<div class="section-heading">Filters</div>', unsafe_allow_html=True)
    f1, f2, f3 = st.columns(3)
    with f1:
        search_q = st.text_input("Search fund name or AMC", placeholder="e.g. Parag Parikh, HDFC")
    with f2:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            categories = [r[0] for r in conn.execute(
                "SELECT DISTINCT category FROM funds WHERE category IS NOT NULL ORDER BY category"
            ).fetchall()]
            conn.close()
        except Exception:
            categories = []
        category_filter = st.selectbox("Category", ["All"] + categories)
    with f3:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            amcs = [r[0] for r in conn.execute(
                "SELECT DISTINCT fund_house FROM funds WHERE fund_house IS NOT NULL ORDER BY fund_house LIMIT 100"
            ).fetchall()]
            conn.close()
        except Exception:
            amcs = []
        amc_filter = st.selectbox("AMC", ["All"] + amcs)

    # Build query
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        query = "SELECT scheme_code, scheme_name, fund_house, category, sub_category FROM funds WHERE 1=1"
        params: list = []
        if search_q:
            query += " AND (scheme_name LIKE ? OR fund_house LIKE ?)"
            params += [f"%{search_q}%", f"%{search_q}%"]
        if category_filter != "All":
            query += " AND category=?"
            params.append(category_filter)
        if amc_filter != "All":
            query += " AND fund_house=?"
            params.append(amc_filter)
        query += " ORDER BY scheme_name LIMIT 50"
        funds = conn.execute(query, params).fetchall()
        conn.close()
    except Exception:
        funds = []

    st.markdown(f'<div class="section-heading">Results ({len(funds)} shown)</div>', unsafe_allow_html=True)

    if not funds:
        st.info("No funds match your filters.")
    else:
        for fund in funds:
            sc, name, house, cat, subcat = fund

            # Portfolio overlap indicator
            overlap_pct = compute_overlap_with_portfolio(sc, client_scheme_codes)
            if overlap_pct > 0:
                if overlap_pct >= 40:
                    pill = f'<span class="overlap-pill overlap-high">{overlap_pct:.0f}% overlap</span>'
                elif overlap_pct >= 20:
                    pill = f'<span class="overlap-pill overlap-medium">{overlap_pct:.0f}% overlap</span>'
                else:
                    pill = f'<span class="overlap-pill overlap-low">{overlap_pct:.0f}% overlap</span>'
            else:
                pill = ""

            with st.expander(f"{name}{'' if not pill else '  '}" ):
                st.markdown(
                    f'<div class="fund-meta">{house or ""} · {cat or ""} · {subcat or ""} · Scheme code: {sc}{pill}</div>',
                    unsafe_allow_html=True
                )

                exp_col1, exp_col2 = st.columns(2)

                with exp_col1:
                    # NAV history chart
                    try:
                        conn = sqlite3.connect(DATABASE_PATH)
                        nav_rows = conn.execute(
                            "SELECT nav_date, nav FROM nav_history WHERE scheme_code=? ORDER BY nav_date ASC",
                            (sc,)
                        ).fetchall()
                        conn.close()
                        if nav_rows:
                            dates = [r[0] for r in nav_rows]
                            navs  = [r[1] for r in nav_rows]
                            fig = go.Figure(go.Scatter(
                                x=dates, y=navs, mode="lines",
                                line=dict(color="#3FB950", width=1.5),
                                fill="tozeroy", fillcolor="rgba(63,185,80,0.08)"
                            ))
                            fig.update_layout(title="NAV History", xaxis_title="Date", yaxis_title="NAV (₹)")
                            st.plotly_chart(dark_chart(fig, 260), use_container_width=True)
                        else:
                            st.caption("No NAV history. Run nav_fetcher for this fund.")
                    except Exception as e:
                        st.caption(f"NAV chart error: {e}")

                with exp_col2:
                    # Top holdings
                    try:
                        conn = sqlite3.connect(DATABASE_PATH)
                        holdings_rows = conn.execute(
                            """
                            SELECT stock_name, weight_pct FROM fund_holdings
                            WHERE scheme_code=?
                            ORDER BY holding_date DESC, weight_pct DESC
                            LIMIT 10
                            """,
                            (sc,)
                        ).fetchall()
                        conn.close()
                        if holdings_rows:
                            st.markdown("**Top holdings**")
                            for stock, w in holdings_rows:
                                st.markdown(
                                    f'<div style="display:flex;justify-content:space-between;font-size:0.82rem;'
                                    f'padding:3px 0;border-bottom:1px solid #21262D;">'
                                    f'<span style="color:#C9D1D9">{stock or "—"}</span>'
                                    f'<span style="color:#3FB950;font-family:JetBrains Mono,monospace">{(w or 0):.2f}%</span></div>',
                                    unsafe_allow_html=True
                                )
                        else:
                            st.caption("No holdings data. Run holdings_fetcher for this fund.")
                    except Exception as e:
                        st.caption(f"Holdings error: {e}")

                # AI fund summary
                summary = get_fund_summary(sc)
                if summary:
                    st.markdown(f'<div class="summary-box"><b>AI Fund Summary</b><br>{summary}</div>', unsafe_allow_html=True)
                else:
                    st.caption("AI summary not yet generated. Run the fund summary cron to populate.")

                # Add to compare
                if st.button(f"Add to comparison", key=f"cmp_{sc}"):
                    compare_list = st.session_state.get("compare_list", [])
                    if sc not in compare_list and len(compare_list) < 3:
                        compare_list.append(sc)
                        st.session_state["compare_list"] = compare_list
                        st.success(f"Added to comparison ({len(compare_list)}/3)")
                    elif sc in compare_list:
                        st.info("Already in comparison.")
                    else:
                        st.warning("Comparison is full (max 3 funds). Remove one first.")


# ── Tab 2: Compare ───────────────────────────────────────────────────────────
with tab_compare:
    compare_list = st.session_state.get("compare_list", [])
    if not compare_list:
        st.info("Add up to 3 funds from the Screener tab to compare them here.")
    else:
        # Clear button
        if st.button("🗑  Clear comparison"):
            st.session_state["compare_list"] = []
            st.rerun()

        try:
            conn = sqlite3.connect(DATABASE_PATH)
            funds_info = {}
            for sc in compare_list:
                row = conn.execute(
                    "SELECT scheme_code, scheme_name, fund_house, category, sub_category FROM funds WHERE scheme_code=?",
                    (sc,)
                ).fetchone()
                if row:
                    funds_info[sc] = {
                        "scheme_code": row[0], "scheme_name": row[1],
                        "fund_house": row[2], "category": row[3], "sub_category": row[4]
                    }
            conn.close()
        except Exception:
            funds_info = {}

        if funds_info:
            cols = st.columns(len(funds_info))
            for i, (sc, info) in enumerate(funds_info.items()):
                with cols[i]:
                    st.markdown(f"**{info['scheme_name']}**")
                    st.caption(f"{info['fund_house']} · {info['category']}")

                    # Latest NAV + basic stats
                    try:
                        conn = sqlite3.connect(DATABASE_PATH)
                        nav_row = conn.execute(
                            "SELECT nav, nav_date FROM nav_history WHERE scheme_code=? ORDER BY nav_date DESC LIMIT 1",
                            (sc,)
                        ).fetchone()
                        # 1yr return approximation
                        old_row = conn.execute(
                            "SELECT nav FROM nav_history WHERE scheme_code=? AND nav_date <= date('now','-1 year') ORDER BY nav_date DESC LIMIT 1",
                            (sc,)
                        ).fetchone()
                        conn.close()

                        if nav_row:
                            st.metric("Latest NAV", f"₹{nav_row[0]:.2f}", help=f"As of {nav_row[1]}")
                        if nav_row and old_row and old_row[0] > 0:
                            ret_1yr = (nav_row[0] - old_row[0]) / old_row[0] * 100
                            st.metric("1yr Return", f"{ret_1yr:.1f}%")
                    except Exception:
                        st.caption("NAV data unavailable")

                    # Overlap with portfolio
                    ov = compute_overlap_with_portfolio(sc, client_scheme_codes)
                    if ov > 0:
                        st.metric("Portfolio overlap", f"{ov:.1f}%")

                    # AI summary
                    summary = get_fund_summary(sc)
                    if summary:
                        st.markdown(f'<div class="summary-box" style="font-size:0.82rem">{summary[:300]}…</div>', unsafe_allow_html=True)
