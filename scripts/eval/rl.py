#!/usr/bin/env python3
"""Evaluation wrapper: stateless RL PCB tool calls for one agent.

    python3 /tmp/eval/rl.py <project_dir> <tool_name> '<json args>'

Uses a private RLPCB_HOME per project (symlinked shared databases) so parallel agents don't interfere, opens the
project, runs one tool, prints JSON. EVAL_ALLOWED restricts which tools may be called (the experimental condition).
"""
import json
import os
import sys

proj, tool = sys.argv[1], sys.argv[2]
args = json.loads(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else {}
home = os.path.join(proj, ".home")
os.makedirs(home, exist_ok=True)
for f in ("library_index.db", "knowledge.db", "corpus"):
    src, dst = os.path.join(os.environ.get("RLPCB_SHARED_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), f), os.path.join(home, f)
    if os.path.exists(src) and not os.path.exists(dst):
        os.symlink(src, dst)
os.environ["RLPCB_HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
allowed = set(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowed_" + os.environ.get("EVAL_COND", "A") + ".txt")).read().split())
log = os.path.join(proj, "calls.log")
with open(log, "a") as f:
    f.write(json.dumps({"tool": tool, "args": args}) + "\n")
if tool not in allowed:
    print(json.dumps({"error": f"Tool '{tool}' is not available in this session. Available: {sorted(allowed)}"}))
    sys.exit(0)
from rlpcb.agent.tools import Session, run_tool  # noqa: E402

s = Session()
pro = os.path.join(proj, "board", "board.kicad_pro")
if not os.path.exists(pro):
    run_tool(s, "create_project", {"folder": proj, "name": "board"})
else:
    run_tool(s, "open_project", {"path": pro})
r = run_tool(s, tool, args)
out = json.dumps(r, indent=1, ensure_ascii=False, default=str)
if len(out) > 14000:
    out = out[:14000] + "\n... [truncated]"
print(out)
