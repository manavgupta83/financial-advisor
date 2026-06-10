"""
ui/app.py
----------
Home dashboard for the AI Financial Advisory Tool.

Displays:
  - Client selector (sidebar, persists across pages via st.session_state)
  - Summary cards: risk profile, total invested, current value, gain %
  - Quick links to all advisory pages

Run:
  PYTHONPATH=/Users/manavgupta/financial_advisor streamlit run ui/app.py
"""

import sys
import os

# Ensure repo root is on path (works locally via PYTHONPATH and on Cloud).
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
# Fallback: also honour the legacy PYTHONPATH env var used locally.
_pythonpath = os.environ.get("PYTHONPATH", "")
if _pythonpath and _pythonpath not in sys.path:
    sys.path.insert(0, _pythonpath)

import streamlit as st
import sqlite3
from config.settings import DATABASE_PATH
from data.database import init_db

# ── Ensure DB + tables exist before any query ────────────────────────────────
init_db()

# ── Page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="FinAdvisor — Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  section[data-testid="stSidebar"] {
    background: #0D1117;
    border-right: 1px solid #21262D;
  }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
  section[data-testid="stSidebar"] .stSelectbox label { color: #8B949E !important; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; }

  .main { background: #0D1117; }
  .block-container { padding: 2rem 2.5rem; }

  .metric-card {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
  }
  .metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--accent, #3FB950);
  }
  .metric-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #8B949E;
    margin-bottom: 0.4rem;
  }
  .metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.6rem;
    font-weight: 500;
    color: #E6EDF3;
    line-height: 1.1;
  }
  .metric-sub { font-size: 0.75rem; color: #8B949E; margin-top: 0.3rem; }
  .metric-positive { color: #3FB950; }
  .metric-negative { color: #F85149; }

  .nav-card {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .nav-card:hover { border-color: #3FB950; background: #1C2128; }
  .nav-card-icon { font-size: 1.5rem; margin-bottom: 0.5rem; }
  .nav-card-title { font-size: 0.95rem; font-weight: 600; color: #E6EDF3; }
  .nav-card-desc { font-size: 0.78rem; color: #8B949E; margin-top: 0.2rem; line-height: 1.4; }

  .section-heading {
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    color: #E6EDF3;
    margin: 1.5rem 0 0.75rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid #21262D;
  }

  .risk-badge {
    display: inline-block;
    padding: 0.2rem 0.75rem;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .risk-conservative   { background: #0D419D22; color: #58A6FF; border: 1px solid #1F6FEB44; }
  .risk-moderate       { background: #1A7F3722; color: #3FB950; border: 1px solid #238636aa; }
  .risk-aggressive     { background: #9E6A0322; color: #E3B341; border: 1px solid #BB800944; }
  .risk-very-aggressive { background: #67060322; color: #F85149; border: 1px solid #F8514944; }

  .wordmark {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #E6EDF3;
    letter-spacing: -0.01em;
  }
  .wordmark span { color: #3FB950; }

  h1, h2, h3 { color: #E6EDF3 !important; }
  p, li { color: #C9D1D9; }

  .stSelectbox > div > div { background: #161B22 !important; border-color: #21262D !important; color: #E6EDF3 !important; }
  div[data-testid="metric-container"] { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1rem; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_all_clients():
    """Return list of (id, name, email) tuples from DB."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.execute("SELECT id, name, email FROM clients ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def get_client_detail(client_id: int):
    """Return full client row as dict."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_portfolio_quick(client_id: int):
    """Fast portfolio totals."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        row = conn.execute("""
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(invested_amount), 0)   AS inv,
                   COALESCE(SUM(units * avg_nav), 0)   AS cur
            FROM client_holdings WHERE client_id=?
        """, (client_id,)).fetchone()
        conn.close()
        if row:
            return {"n": row[0], "invested": row[1], "current": row[2]}
    except Exception:
        pass
    return {"n": 0, "invested": 0.0, "current": 0.0}


def get_goals_quick(client_id: int):
    """Return goal rows for client."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM client_goals WHERE client_id=?", (client_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def risk_badge_html(profile: str) -> str:
    cls_map = {
        "Conservative": "risk-conservative",
        "Moderate": "risk-moderate",
        "Aggressive": "risk-aggressive",
        "Very Aggressive": "risk-very-aggressive",
    }
    cls = cls_map.get(profile, "risk-moderate")
    return f'<span class="risk-badge {cls}">{profile}</span>'


# ── Sidebar: Client Selector ─────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="wordmark">Fin<span>.</span>Advisor</div>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:0.72rem;color:#8B949E;margin-top:-0.3rem;margin-bottom:1.5rem;">AI-Powered Advisory Platform</p>', unsafe_allow_html=True)

    clients = get_all_clients()
    if clients:
        client_options = {f"{name} ({email})": cid for cid, name, email in clients}
        labels = list(client_options.keys())

        default_idx = 0
        if "selected_client_id" in st.session_state:
            for i, (cid, *_) in enumerate(clients):
                if cid == st.session_state["selected_client_id"]:
                    default_idx = i
                    break

        chosen_label = st.selectbox("Active Client", labels, index=default_idx)
        selected_id = client_options[chosen_label]
        st.session_state["selected_client_id"] = selected_id
        st.session_state["selected_client_label"] = chosen_label
    else:
        st.warning("No clients yet. Start with **Client Onboarding**.")
        st.session_state["selected_client_id"] = None

    st.markdown("---")
    st.markdown('<p style="font-size:0.7rem;color:#8B949E;text-transform:uppercase;letter-spacing:0.08em;">Navigation</p>', unsafe_allow_html=True)
    pages = [
        ("🧾", "Client Onboarding"),
        ("🎯", "Goal Planner"),
        ("📈", "Portfolio"),
        ("⚙️", "Optimiser"),
        ("📄", "Advisory Report"),
    ]
    for icon, label in pages:
        st.markdown(f"{icon} {label}")

    st.markdown("---")
    st.markdown('<p style="font-size:0.65rem;color:#30363D;">Phase 5 — Streamlit UI</p>', unsafe_allow_html=True)


# ── Main Dashboard ────────────────────────────────────────────────────────────

st.markdown('<div class="wordmark">Dashboard</div>', unsafe_allow_html=True)
st.markdown('<p style="color:#8B949E;margin-top:-0.3rem;margin-bottom:1.5rem;">Select a client in the sidebar, then navigate to any tool.</p>', unsafe_allow_html=True)

client_id = st.session_state.get("selected_client_id")

if not client_id:
    st.info("👈  No clients in the database yet. Go to **Client Onboarding** to create one.")
    st.stop()

client    = get_client_detail(client_id)
portfolio = get_portfolio_quick(client_id)
goals     = get_goals_quick(client_id)

# ── Client Header ─────────────────────────────────────────────────────────────
col_name, col_risk = st.columns([3, 1])
with col_name:
    st.markdown(f"### {client.get('name', '—')}")
    st.markdown(
        f"<p style='color:#8B949E;font-size:0.82rem;margin-top:-0.8rem;'>"
        f"{client.get('email','—')} · ₹{client.get('annual_income',0):,.0f} p.a. · Age {client.get('age','—')}"
        f"</p>", unsafe_allow_html=True
    )
with col_risk:
    rp = client.get("risk_profile", client.get("risk_label", "—"))
    st.markdown(f"<div style='padding-top:0.6rem;'>{risk_badge_html(rp)}</div>", unsafe_allow_html=True)

# ── Summary Metric Cards ──────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Portfolio at a Glance</div>', unsafe_allow_html=True)

invested  = portfolio["invested"]
current   = portfolio["current"]
gain      = current - invested
gain_pct  = (gain / invested * 100) if invested > 0 else 0.0
total_sip = sum(g.get("monthly_sip", 0) or 0 for g in goals)

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown(f"""
    <div class="metric-card" style="--accent:#3FB950">
      <div class="metric-label">Holdings</div>
      <div class="metric-value">{portfolio['n']}</div>
      <div class="metric-sub">active funds</div>
    </div>""", unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card" style="--accent:#58A6FF">
      <div class="metric-label">Total Invested</div>
      <div class="metric-value">&#8377;{invested/1e5:.2f}L</div>
      <div class="metric-sub">cost basis</div>
    </div>""", unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card" style="--accent:#58A6FF">
      <div class="metric-label">Current Value</div>
      <div class="metric-value">&#8377;{current/1e5:.2f}L</div>
      <div class="metric-sub">mark-to-market</div>
    </div>""", unsafe_allow_html=True)

with c4:
    gain_cls  = "metric-positive" if gain >= 0 else "metric-negative"
    gain_sign = "+" if gain >= 0 else ""
    gain_acc  = "#3FB950" if gain >= 0 else "#F85149"
    st.markdown(f"""
    <div class="metric-card" style="--accent:{gain_acc}">
      <div class="metric-label">Unrealised Gain</div>
      <div class="metric-value {gain_cls}">{gain_sign}&#8377;{abs(gain)/1e5:.2f}L</div>
      <div class="metric-sub {gain_cls}">{gain_sign}{gain_pct:.1f}%</div>
    </div>""", unsafe_allow_html=True)

with c5:
    st.markdown(f"""
    <div class="metric-card" style="--accent:#E3B341">
      <div class="metric-label">Monthly SIP</div>
      <div class="metric-value">&#8377;{total_sip/1e3:.1f}K</div>
      <div class="metric-sub">across {len(goals)} goal(s)</div>
    </div>""", unsafe_allow_html=True)

# ── Goals Summary ─────────────────────────────────────────────────────────────
if goals:
    st.markdown('<div class="section-heading">Goals</div>', unsafe_allow_html=True)
    cols = st.columns(min(len(goals), 4))
    for i, goal in enumerate(goals[:4]):
        with cols[i % 4]:
            target = goal.get("target_amount", 0) or 0
            sip    = goal.get("monthly_sip", 0) or 0
            yr     = goal.get("target_year", "—")
            st.markdown(f"""
            <div class="metric-card" style="--accent:#E3B341;padding:1rem 1.25rem;">
              <div class="metric-label">{goal.get('goal_type','Goal').upper()}</div>
              <div style="font-size:0.88rem;font-weight:600;color:#E6EDF3;margin-bottom:0.3rem;">{goal.get('goal_name','—')}</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:1rem;color:#E3B341;">&#8377;{target/1e5:.1f}L</div>
              <div class="metric-sub">SIP &#8377;{sip:,.0f}/mo &middot; Target {yr}</div>
            </div>""", unsafe_allow_html=True)

# ── Quick Nav ─────────────────────────────────────────────────────────────────
st.markdown('<div class="section-heading">Tools</div>', unsafe_allow_html=True)

nav_items = [
    ("🧾", "Client Onboarding",  "Collect KYC, run the 10-question risk questionnaire, store risk profile."),
    ("🎯", "Goal Planner",        "Define retirement, education, emergency and house goals. Auto-compute SIP."),
    ("📈", "Portfolio Analytics", "XIRR, CAGR, Sharpe ratio, sector heatmap, fund overlap matrix."),
    ("⚙️", "Portfolio Optimiser", "Type constraints in plain English. Run max-Sharpe / min-variance."),
    ("📄", "Advisory Report",     "Stream a full AI-generated advisory narrative for the active client."),
]
nav_cols = st.columns(5)
for col, (icon, title, desc) in zip(nav_cols, nav_items):
    with col:
        st.markdown(f"""
        <div class="nav-card">
          <div class="nav-card-icon">{icon}</div>
          <div class="nav-card-title">{title}</div>
          <div class="nav-card-desc">{desc}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
