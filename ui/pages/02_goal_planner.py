"""
ui/pages/02_goal_planner.py
-----------------------------
Streamlit page: Goal Planner.

Features:
  - Add a new goal (type, name, target, horizon, existing corpus)
  - Calls goal_engine.plan_all_goals() and shows SIP calcs per goal
  - Feasibility gauge: total SIP as % of monthly income (40% cap)
  - Persists each goal to DB via client_manager.add_goal()
  - Summary table of all existing goals

Run via:
  PYTHONPATH=/Users/manavgupta/financial_advisor streamlit run ui/app.py
"""

import sys, os
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))

import streamlit as st
import sqlite3
import plotly.graph_objects as go
from datetime import date

from config.settings import DATABASE_PATH
from data.client_manager import add_goal, get_goals_for_client
from engine.goal_engine import GoalType, GoalInput, plan_all_goals, format_goal_plan

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Goal Planner", page_icon="🎯", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #0D1117; color: #C9D1D9; }
  .block-container { padding: 2rem 2.5rem; }
  section[data-testid="stSidebar"] { background: #0D1117; border-right: 1px solid #21262D; }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
  .page-title { font-family: 'DM Serif Display', serif; font-size: 1.9rem; color: #E6EDF3; }
  .page-sub { color: #8B949E; font-size: 0.85rem; margin-top: -0.5rem; margin-bottom: 1.5rem; }
  .goal-card {
    background: #161B22; border: 1px solid #21262D;
    border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 0.75rem;
    border-left: 4px solid #E3B341;
  }
  .goal-title { font-size: 1rem; font-weight: 600; color: #E6EDF3; }
  .goal-meta { font-size: 0.78rem; color: #8B949E; margin-top: 0.2rem; }
  .sip-value { font-family: 'JetBrains Mono', monospace; font-size: 1.4rem; color: #3FB950; }
  .fv-value { font-family: 'JetBrains Mono', monospace; font-size: 1rem; color: #58A6FF; }
  .section-heading { font-family: 'DM Serif Display', serif; font-size: 1.1rem; color: #E6EDF3; margin: 1.5rem 0 0.75rem; padding-bottom: 0.4rem; border-bottom: 1px solid #21262D; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextInput > div > div, .stNumberInput > div > div { background: #0D1117 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
  .stSelectbox > div > div { background: #0D1117 !important; border-color: #30363D !important; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🎯 Goal Planner")
    st.caption("Define goals and auto-compute SIP requirements.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_client(client_id: int) -> dict:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def feasibility_gauge(sip_pct: float) -> go.Figure:
    """Plotly gauge: SIP as % of monthly income. Green < 30%, Yellow 30-40%, Red > 40%."""
    color = "#3FB950" if sip_pct < 30 else ("#E3B341" if sip_pct < 40 else "#F85149")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=sip_pct,
        number={"suffix": "%", "font": {"color": "#E6EDF3", "family": "JetBrains Mono", "size": 28}},
        title={"text": "SIP as % of Monthly Income", "font": {"color": "#8B949E", "size": 12}},
        gauge={
            "axis": {"range": [0, 80], "tickcolor": "#30363D", "tickfont": {"color": "#8B949E", "size": 10}},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "#161B22",
            "bordercolor": "#21262D",
            "steps": [
                {"range": [0,  30], "color": "#1A7F3722"},
                {"range": [30, 40], "color": "#9E6A0322"},
                {"range": [40, 80], "color": "#67060322"},
            ],
            "threshold": {
                "line": {"color": "#F85149", "width": 2},
                "thickness": 0.7,
                "value": 40,
            },
        }
    ))
    fig.update_layout(
        paper_bgcolor="#161B22",
        plot_bgcolor="#161B22",
        font={"color": "#E6EDF3"},
        height=220,
        margin=dict(l=20, r=20, t=40, b=0),
    )
    return fig


GOAL_TYPE_LABELS = {
    "retirement": "🏖️  Retirement",
    "education":  "🎓  Education",
    "house":      "🏠  House",
    "emergency":  "🛡️  Emergency Fund",
}

GOAL_TYPE_MAP = {
    "🏖️  Retirement":     GoalType.RETIREMENT,
    "🎓  Education":      GoalType.EDUCATION,
    "🏠  House":          GoalType.HOUSE,
    "🛡️  Emergency Fund": GoalType.EMERGENCY,
}

# ── Guard: client must be selected ───────────────────────────────────────────
st.markdown('<div class="page-title">Goal Planner</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Define financial goals and auto-compute SIP requirements with inflation-adjusted projections.</div>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")
if not client_id:
    st.warning("No active client. Please select or create a client in **Client Onboarding** first.")
    st.stop()

client = get_client(client_id)
if not client:
    st.error("Client not found in DB.")
    st.stop()

monthly_income = (client.get("annual_income") or 0) / 12
risk_profile   = client.get("risk_profile") or "Moderate"

st.markdown(
    f"**Active client:** {client['name']}  ·  Risk: **{risk_profile}**  ·  Monthly income: ₹{monthly_income:,.0f}",
)

tab_add, tab_existing = st.tabs(["➕  Add Goal", "📋  All Goals"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Add Goal
# ══════════════════════════════════════════════════════════════════════════════
with tab_add:
    with st.form("goal_form"):
        st.markdown('<div class="section-heading" style="margin-top:0;">Goal Details</div>', unsafe_allow_html=True)

        g1, g2 = st.columns(2)
        with g1:
            goal_type_label = st.selectbox("Goal Type *", list(GOAL_TYPE_MAP.keys()))
            goal_name       = st.text_input("Goal Name *", placeholder="e.g. Daughter's Higher Education")
        with g2:
            years_to_goal   = st.number_input("Years to Goal *", min_value=1, max_value=40, value=10)
            target_today    = st.number_input("Target Amount Today (₹) *", min_value=0, value=3_000_000, step=100_000,
                                              help="Enter the amount in today's money. Inflation adjustment applied automatically.")

        g3, g4, g5 = st.columns(3)
        with g3:
            existing_inv = st.number_input("Existing Investment (₹)", min_value=0, value=0, step=10_000)
        with g4:
            inflation_rate = st.number_input("Inflation Rate (%)", min_value=0.0, max_value=20.0, value=6.0, step=0.5)
        with g5:
            monthly_expense = st.number_input(
                "Monthly Expense at Goal (₹)",
                min_value=0, value=0, step=5_000,
                help="Retirement only: monthly expense in today's money at retirement age.",
            )

        submitted = st.form_submit_button("📊  Compute SIP & Save Goal", type="primary", use_container_width=True)

    if submitted:
        if not goal_name:
            st.error("Goal Name is required.")
            st.stop()

        goal_type_enum = GOAL_TYPE_MAP[goal_type_label]
        inflation = inflation_rate / 100.0

        goal_input = GoalInput(
            goal_type=goal_type_enum,
            name=goal_name,
            target_amount_today=target_today,
            years_to_goal=years_to_goal,
            existing_investment=existing_inv,
            inflation_rate=inflation,
            monthly_expense_at_goal=monthly_expense if monthly_expense > 0 else 0,
        )

        plans = plan_all_goals(
            goals=[goal_input],
            risk_profile=risk_profile,
            monthly_income=monthly_income,
        )
        plan = plans[0]

        # Persist goal
        target_year = date.today().year + years_to_goal
        add_goal(
            client_id=client_id,
            goal_name=goal_name,
            goal_type=goal_type_enum.value,
            target_amount=plan.future_value,
            target_year=target_year,
            current_savings=existing_inv,
            monthly_sip=plan.adjusted_sip,
            priority=1,
        )

        st.success(f"Goal **{goal_name}** saved!")

        # Result display
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.metric("Future Value (inflated)", f"₹{plan.future_value/1e5:.2f}L")
        with r2:
            st.metric("Required SIP", f"₹{plan.monthly_sip_required:,.0f}/mo")
        with r3:
            st.metric("Adjusted SIP (feasibility)", f"₹{plan.adjusted_sip:,.0f}/mo")
        with r4:
            st.metric("Expected Return", f"{plan.expected_annual_return*100:.1f}% p.a.")

        # Feasibility gauge
        existing_goals = get_goals_for_client(client_id)
        total_sip = sum(g.monthly_sip or 0 for g in existing_goals)
        sip_pct = (total_sip / monthly_income * 100) if monthly_income > 0 else 0

        fg1, fg2 = st.columns([1, 2])
        with fg1:
            st.plotly_chart(feasibility_gauge(sip_pct), use_container_width=True)
        with fg2:
            st.markdown(f"""
            <div style="background:#161B22;border:1px solid #21262D;border-radius:10px;padding:1.25rem;margin-top:0.5rem;">
              <div style="font-size:0.7rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem;">SIP Feasibility</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:1.4rem;color:#E6EDF3;">
                ₹{total_sip:,.0f}<span style="font-size:0.85rem;color:#8B949E;">/mo total</span>
              </div>
              <div style="font-size:0.82rem;color:#8B949E;margin-top:0.5rem;">
                {sip_pct:.1f}% of ₹{monthly_income:,.0f} monthly income<br>
                <span style="color:{'#3FB950' if sip_pct<30 else '#E3B341' if sip_pct<40 else '#F85149'};">
                {'✅ Comfortable' if sip_pct < 30 else '⚠️ Stretching' if sip_pct < 40 else '🔴 Exceeds 40% cap — consider revising goals'}
                </span>
              </div>
            </div>
            """, unsafe_allow_html=True)

        # Full plan detail
        with st.expander("📋 Full goal plan detail"):
            st.code(format_goal_plan(plan), language=None)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Existing Goals
# ══════════════════════════════════════════════════════════════════════════════
with tab_existing:
    goals = get_goals_for_client(client_id)
    if not goals:
        st.info("No goals defined yet. Use **Add Goal** to create one.")
    else:
        total_sip = sum(g.monthly_sip or 0 for g in goals)
        sip_pct   = (total_sip / monthly_income * 100) if monthly_income > 0 else 0

        # Feasibility gauge at top
        gc1, gc2, gc3 = st.columns([1, 1, 1])
        with gc1:
            st.plotly_chart(feasibility_gauge(sip_pct), use_container_width=True)
        with gc2:
            st.metric("Total Monthly SIP", f"₹{total_sip:,.0f}")
            st.metric("% of Income", f"{sip_pct:.1f}%")
        with gc3:
            total_target = sum(g.target_amount or 0 for g in goals)
            st.metric("Goals Count", len(goals))
            st.metric("Total Future Value", f"₹{total_target/1e5:.1f}L")

        st.markdown('<div class="section-heading">Goal Breakdown</div>', unsafe_allow_html=True)

        for goal in goals:
            gtype  = goal.goal_type or "goal"
            gname  = goal.goal_name or "—"
            target = goal.target_amount or 0
            sip    = goal.monthly_sip or 0
            yr     = goal.target_year or "—"
            savings= goal.current_savings or 0
            icon   = {"retirement":"🏖️","education":"🎓","house":"🏠","emergency":"🛡️"}.get(gtype.lower(), "🎯")

            st.markdown(f"""
            <div class="goal-card">
              <div class="goal-title">{icon} {gname}</div>
              <div class="goal-meta">{gtype.title()} · Target year: {yr} · Existing corpus: ₹{savings:,.0f}</div>
              <div style="display:flex;gap:2rem;margin-top:0.75rem;">
                <div>
                  <div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.08em;">Monthly SIP</div>
                  <div class="sip-value">₹{sip:,.0f}</div>
                </div>
                <div>
                  <div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.08em;">Future Value</div>
                  <div class="fv-value">₹{target/1e5:.2f}L</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
