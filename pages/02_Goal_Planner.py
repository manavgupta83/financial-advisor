# pages/02_Goal_Planner.py
import sys, os
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
_p = os.path.join(REPO_ROOT, "ui", "pages", "02_goal_planner.py")
with open(_p) as f:
    exec(compile(f.read(), _p, "exec"), {"__file__": _p, "__name__": "__main__"})
