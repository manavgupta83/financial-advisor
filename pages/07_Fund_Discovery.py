"""
pages/07_Fund_Discovery.py — Streamlit Cloud stub
Delegates to ui/pages/07_fund_discovery.py
"""
import sys, os
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo not in sys.path:
    sys.path.insert(0, repo)
_path = os.path.join(repo, "ui", "pages", "07_fund_discovery.py")
with open(_path) as f:
    exec(compile(f.read(), _path, "exec"), {"__file__": _path, "__name__": "__main__"})
