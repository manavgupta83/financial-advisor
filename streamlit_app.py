"""
streamlit_app.py
-----------------
Root entry point for Streamlit Community Cloud.
"""
import sys, os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Init DB on boot
try:
    from data.database import init_db
    init_db()
except Exception as e:
    import streamlit as st
    st.error(f"DB init failed: {e}")
    st.stop()

# Run ui/app.py in-process
_app_path = os.path.join(REPO_ROOT, "ui", "app.py")
with open(_app_path, "r", encoding="utf-8") as _f:
    exec(compile(_f.read(), _app_path, "exec"), {"__file__": _app_path, "__name__": "__main__"})
