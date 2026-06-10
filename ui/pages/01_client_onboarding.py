"""
ui/pages/01_client_onboarding.py
----------------------------------
Streamlit page: Client Onboarding + Risk Profiling.
"""

import sys, os
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
from data.client_manager import (
    create_client, get_client_by_email,
    update_client_risk_profile, delete_client,
)
from engine.risk_engine import QUESTIONNAIRE, compute_risk_profile, describe_profile
from config.settings import DATABASE_PATH
from data.database import init_db
init_db()

st.set_page_config(page_title="Client Onboarding", page_icon="🧾", layout="wide")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; background: #0D1117; color: #C9D1D9; }
  .block-container { padding: 2rem 2.5rem; }
  section[data-testid="stSidebar"] { background: #0D1117; border-right: 1px solid #21262D; }
  section[data-testid="stSidebar"] * { color: #C9D1D9 !important; }
  .page-title { font-family: 'DM Serif Display', serif; font-size: 1.9rem; color: #E6EDF3; }
  .page-sub { color: #8B949E; font-size: 0.85rem; margin-top: -0.5rem; margin-bottom: 1.5rem; }
  .form-section { background: #161B22; border: 1px solid #21262D; border-radius: 10px; padding: 1.5rem 1.75rem; margin-bottom: 1.25rem; }
  .form-section-title { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #3FB950; margin-bottom: 1rem; }
  .q-number { font-size: 0.65rem; color: #8B949E; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; }
  .q-text { font-size: 0.92rem; color: #E6EDF3; margin-top: 0.2rem; margin-bottom: 0.75rem; }
  .profile-card { background: #161B22; border: 1px solid #238636; border-radius: 12px; padding: 2rem; margin-top: 1.5rem; border-top: 4px solid #3FB950; }
  .profile-title { font-family: 'DM Serif Display', serif; font-size: 1.5rem; color: #E6EDF3; }
  h1,h2,h3 { color: #E6EDF3 !important; }
  .stTextInput > div > div, .stNumberInput > div > div { background: #0D1117 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
  .stSelectbox > div > div { background: #0D1117 !important; border-color: #30363D !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🧾 Client Onboarding")
    st.caption("Create a new client and assess their risk profile.")

st.markdown('<div class="page-title">Client Onboarding</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Complete KYC details and the 10-question SEBI-aligned risk questionnaire.</div>', unsafe_allow_html=True)

tab_new, tab_view = st.tabs(["➕  New Client", "📋  Existing Clients"])

with tab_new:
    with st.form("onboarding_form"):
        st.markdown('<div class="form-section-title">KYC Details</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            name  = st.text_input("Full Name *", placeholder="Arjun Mehta")
            email = st.text_input("Email *",     placeholder="arjun@example.com")
        with c2:
            phone = st.text_input("Phone",   placeholder="9876543210")
            pan   = st.text_input("PAN",     placeholder="ARJPM1234H")
        with c3:
            age           = st.number_input("Age *",              min_value=18, max_value=90, value=35)
            annual_income = st.number_input("Annual Income (₹) *", min_value=0,  value=1_200_000, step=100_000)
        c4, _ = st.columns([1, 2])
        with c4:
            dependants = st.number_input("Dependants", min_value=0, max_value=10, value=1)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="form-section-title">Risk Questionnaire — 10 Questions</div>', unsafe_allow_html=True)
        st.caption("Select the option that best describes your situation.")

        responses: dict[int, int] = {}
        for q in QUESTIONNAIRE:
            st.markdown(f'<div class="q-number">Question {q["id"]}</div><div class="q-text">{q["question"]}</div>', unsafe_allow_html=True)
            options_text = [opt["text"] for opt in q["options"]]
            chosen = st.radio(label=f"q_{q['id']}", options=options_text, index=0,
                              label_visibility="collapsed", key=f"q_{q['id']}", horizontal=False)
            responses[q["id"]] = options_text.index(chosen)
            st.markdown("<br>", unsafe_allow_html=True)

        submitted = st.form_submit_button("✅  Save Client & Compute Risk Profile", type="primary", use_container_width=True)

    if submitted:
        if not name or not email:
            st.error("Name and Email are required.")
            st.stop()
        existing = get_client_by_email(email)
        if existing:
            st.warning(f"Client with email **{email}** already exists (ID {existing.id}). Updating risk profile.")
            profile = compute_risk_profile(responses=responses, age=age, annual_income=annual_income, dependants=dependants)
            update_client_risk_profile(existing.id, profile.category.value, profile.adjusted_score)
            client = existing
        else:
            client = create_client(name=name, email=email, phone=phone, age=age, annual_income=annual_income, dependants=dependants, pan=pan)
            profile = compute_risk_profile(responses=responses, age=age, annual_income=annual_income, dependants=dependants)
            update_client_risk_profile(client.id, profile.category.value, profile.adjusted_score)

        st.session_state["selected_client_id"] = client.id
        st.success(f"Client **{client.name}** saved  ·  ID: {client.id}")

        color_map = {"Conservative":"#58A6FF","Moderate":"#3FB950","Aggressive":"#E3B341","Very Aggressive":"#F85149"}
        accent = color_map.get(profile.category.value, "#3FB950")
        st.markdown(f"""
        <div class="profile-card" style="border-top-color:{accent};">
          <div class="profile-title" style="color:{accent};">{profile.category.value}</div>
          <p style="color:#8B949E;margin:0.4rem 0 1rem;font-size:0.85rem;">Raw score: {profile.raw_score} · Adjusted score: {profile.adjusted_score}</p>
          <p style="color:#C9D1D9;white-space:pre-line;font-size:0.9rem;">{describe_profile(profile)}</p>
        </div>""", unsafe_allow_html=True)
        st.info("➡️  Head to **Goal Planner** to define this client's financial goals.")

with tab_view:
    import sqlite3
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, name, email, age, annual_income, risk_profile, risk_score FROM clients ORDER BY name").fetchall()
        conn.close()
    except Exception:
        rows = []

    if not rows:
        st.info("No clients in the database yet.")
    else:
        for row in rows:
            rp = row["risk_profile"] or "—"
            color_map = {"Conservative":"#58A6FF","Moderate":"#3FB950","Aggressive":"#E3B341","Very Aggressive":"#F85149"}
            accent = color_map.get(rp, "#8B949E")
            income = row["annual_income"] or 0
            with st.expander(f"**{row['name']}**  ·  {row['email']}"):
                cc1, cc2, cc3, cc4 = st.columns(4)
                cc1.metric("Age", row["age"])
                cc2.metric("Annual Income", f"₹{income/1e5:.1f}L")
                cc3.metric("Risk Profile", rp)
                cc4.metric("Risk Score", row["risk_score"] or 0)
                if st.button("Select as Active Client", key=f"sel_{row['id']}"):
                    st.session_state["selected_client_id"] = row["id"]
                    st.success(f"Active client set to **{row['name']}**")
