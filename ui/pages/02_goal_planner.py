"""
ui/pages/02_goal_planner.py
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
import sqlite3
import plotly.graph_objects as go
from datetime import date

from config.settings import DATABASE_PATH
from data.database import init_db
from data.client_manager import add_goal, get_goals_for_client
from engine.goal_engine import GoalType, GoalInput, plan_all_goals, format_goal_plan
init_db()

st.set_page_config(page_title="Goal Planner", page_icon="🎯", layout="wide")

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
  .goal-card { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 0.75rem; border-left: 4px solid #E3B341; }
  .goal-title { font-size: 1rem; font-weight: 600; color: #E6EDF3; }
  .goal-meta { font-size: 0.78rem; color: #8B949E; margin-top: 0.2rem; }
  .sip-value { font-family: 'JetBrains Mono', monospace; font-size: 1.4rem; color: #3FB950; }
  .fv-value  { font-family: 'JetBrains Mono', monospace; font-size: 1rem; color: #58A6FF; }
  .section-heading { font-family: 'DM Serif Display', serif; font-size: 1.1rem; color: #E6EDF3; margin: 1.5rem 0 0.75rem; padding-bottom: 0.4rem; border-bottom: 1px solid #21262D; }
  .wordmark { font-family: 'DM Serif Display', serif; font-size: 1.6rem; color: #E6EDF3; }
  .wordmark span { color: #3FB950; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextInput > div > div, .stNumberInput > div > div { background: #0D1117 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
  .stSelectbox > div > div { background: #0D1117 !important; border-color: #30363D !important; }
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


def get_client(client_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def feasibility_gauge(sip_pct):
    color = "#3FB950" if sip_pct < 30 else ("#E3B341" if sip_pct < 40 else "#F85149")
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=sip_pct,
        number={"suffix": "%", "font": {"color": "#E6EDF3", "family": "JetBrains Mono", "size": 28}},
        title={"text": "SIP as % of Monthly Income", "font": {"color": "#8B949E", "size": 12}},
        gauge={"axis": {"range": [0, 80]}, "bar": {"color": color, "thickness": 0.25},
               "bgcolor": "#161B22", "bordercolor": "#21262D",
               "steps": [{"range": [0,30], "color": "#1A7F3722"},{"range": [30,40], "color": "#9E6A0322"},{"range": [40,80], "color": "#67060322"}],
               "threshold": {"line": {"color": "#F85149", "width": 2}, "thickness": 0.7, "value": 40}}
    ))
    fig.update_layout(paper_bgcolor="#161B22", plot_bgcolor="#161B22", font={"color": "#E6EDF3"}, height=220, margin=dict(l=20,r=20,t=40,b=0))
    return fig


GOAL_TYPE_MAP = {
    "🏖️  Retirement":     GoalType.RETIREMENT,
    "🎓  Education":      GoalType.EDUCATION,
    "🏠  House":          GoalType.HOUSE,
    "🛡️  Emergency Fund": GoalType.EMERGENCY,
}

st.markdown('<div class="page-title">Goal Planner</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Define financial goals and auto-compute SIP with inflation-adjusted projections.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client. Go to **Client Onboarding** first.")
    st.stop()

client = get_client(client_id)
if not client:
    st.error("Client not found.")
    st.stop()

monthly_income = (client.get("annual_income") or 0) / 12
risk_profile   = client.get("risk_profile") or "Moderate"
st.markdown(f"**Active client:** {client['name']}  ·  Risk: **{risk_profile}**  ·  Monthly income: ₹{monthly_income:,.0f}")

tab_add, tab_existing = st.tabs(["➕  Add Goal", "📋  All Goals"])

with tab_add:
    with st.form("goal_form"):
        st.markdown('<div class="section-heading" style="margin-top:0;">Goal Details</div>', unsafe_allow_html=True)
        g1, g2 = st.columns(2)
        with g1:
            goal_type_label = st.selectbox("Goal Type *", list(GOAL_TYPE_MAP.keys()))
            goal_name       = st.text_input("Goal Name *", placeholder="e.g. Daughter's Higher Education")
        with g2:
            years_to_goal = st.number_input("Years to Goal *", min_value=1, max_value=40, value=10)
            target_today  = st.number_input("Target Amount Today (₹) *", min_value=0, value=3_000_000, step=100_000)
        g3, g4, g5 = st.columns(3)
        with g3:
            existing_inv = st.number_input("Existing Investment (₹)", min_value=0, value=0, step=10_000)
        with g4:
            inflation_rate = st.number_input("Inflation Rate (%)", min_value=0.0, max_value=20.0, value=6.0, step=0.5)
        with g5:
            monthly_expense = st.number_input("Monthly Expense at Goal (₹)", min_value=0, value=0, step=5_000)
        submitted = st.form_submit_button("📊  Compute SIP & Save Goal", type="primary", use_container_width=True)

    if submitted:
        if not goal_name:
            st.error("Goal Name is required.")
            st.stop()
        goal_input = GoalInput(
            goal_type=GOAL_TYPE_MAP[goal_type_label], name=goal_name,
            target_amount_today=target_today, years_to_goal=years_to_goal,
            existing_investment=existing_inv, inflation_rate=inflation_rate/100.0,
            monthly_expense_at_goal=monthly_expense if monthly_expense > 0 else 0)
        plans = plan_all_goals(goals=[goal_input], risk_profile=risk_profile, monthly_income=monthly_income)
        plan  = plans[0]
        add_goal(client_id=client_id, goal_name=goal_name, goal_type=GOAL_TYPE_MAP[goal_type_label].value,
                 target_amount=plan.future_value, target_year=date.today().year + years_to_goal,
                 current_savings=existing_inv, monthly_sip=plan.adjusted_sip, priority=1)
        st.success(f"Goal **{goal_name}** saved!")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Future Value", f"₹{plan.future_value/1e5:.2f}L")
        r2.metric("Required SIP", f"₹{plan.monthly_sip_required:,.0f}/mo")
        r3.metric("Adjusted SIP", f"₹{plan.adjusted_sip:,.0f}/mo")
        r4.metric("Expected Return", f"{plan.expected_annual_return*100:.1f}% p.a.")
        existing_goals = get_goals_for_client(client_id)
        total_sip = sum(g.monthly_sip or 0 for g in existing_goals)
        sip_pct   = (total_sip / monthly_income * 100) if monthly_income > 0 else 0
        fg1, fg2 = st.columns([1, 2])
        with fg1:
            st.plotly_chart(feasibility_gauge(sip_pct), use_container_width=True)
        with fg2:
            status = '✅ Comfortable' if sip_pct < 30 else ('⚠️ Stretching' if sip_pct < 40 else '🔴 Exceeds 40% cap')
            color  = '#3FB950' if sip_pct < 30 else ('#E3B341' if sip_pct < 40 else '#F85149')
            st.markdown(f"<div style='background:#161B22;border:1px solid #21262D;border-radius:10px;padding:1.25rem;'><div style='font-size:0.7rem;color:#8B949E;text-transform:uppercase;'>SIP Feasibility</div><div style='font-family:JetBrains Mono,monospace;font-size:1.4rem;color:#E6EDF3;'>₹{total_sip:,.0f}/mo</div><div style='font-size:0.82rem;color:#8B949E;margin-top:0.5rem;'>{sip_pct:.1f}% of ₹{monthly_income:,.0f}<br><span style='color:{color};'>{status}</span></div></div>", unsafe_allow_html=True)
        with st.expander("📋 Full goal plan"):
            st.code(format_goal_plan(plan), language=None)

with tab_existing:
    goals = get_goals_for_client(client_id)
    if not goals:
        st.info("No goals yet. Use **Add Goal**.")
    else:
        total_sip = sum(g.monthly_sip or 0 for g in goals)
        sip_pct   = (total_sip / monthly_income * 100) if monthly_income > 0 else 0
        gc1, gc2, gc3 = st.columns([1, 1, 1])
        with gc1: st.plotly_chart(feasibility_gauge(sip_pct), use_container_width=True)
        with gc2:
            st.metric("Total Monthly SIP", f"₹{total_sip:,.0f}")
            st.metric("% of Income", f"{sip_pct:.1f}%")
        with gc3:
            st.metric("Goals Count", len(goals))
            st.metric("Total Future Value", f"₹{sum(g.target_amount or 0 for g in goals)/1e5:.1f}L")
        st.markdown('<div class="section-heading">Goal Breakdown</div>', unsafe_allow_html=True)
        for goal in goals:
            gtype = goal.goal_type or "goal"
            icon  = {"retirement":"🏖️","education":"🎓","house":"🏠","emergency":"🛡️"}.get(gtype.lower(), "🎯")
            st.markdown(f"""<div class="goal-card"><div class="goal-title">{icon} {goal.goal_name or '—'}</div><div class="goal-meta">{gtype.title()} · Target: {goal.target_year or '—'} · Existing: ₹{goal.current_savings or 0:,.0f}</div><div style='display:flex;gap:2rem;margin-top:0.75rem;'><div><div style='font-size:0.65rem;color:#8B949E;text-transform:uppercase;'>Monthly SIP</div><div class='sip-value'>₹{goal.monthly_sip or 0:,.0f}</div></div><div><div style='font-size:0.65rem;color:#8B949E;text-transform:uppercase;'>Future Value</div><div class='fv-value'>₹{(goal.target_amount or 0)/1e5:.2f}L</div></div></div></div>""", unsafe_allow_html=True)
