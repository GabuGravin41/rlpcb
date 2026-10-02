#!/usr/bin/env bash
# RL PCB installer for Linux/macOS.  Usage: ./install.sh [--seed-corpus]
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
[ -x "$REPO/.venv/bin/python" ] || "$PY" -m venv "$REPO/.venv"
VPY="$REPO/.venv/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r "$REPO/requirements.txt"
"$VPY" -m pip install -q -e "$REPO"
mkdir -p "$HOME/.rlpcb"
printf '{"python": "%s", "repo": "%s", "port": 8765}\n' "$VPY" "$REPO" > "$HOME/.rlpcb/launcher.json"
mkdir -p "$HOME/.rlpcb/corpus"
[ -f "$HOME/.rlpcb/corpus/corpus.db" ] || cp "$REPO/seed/corpus.db" "$HOME/.rlpcb/corpus/corpus.db" 2>/dev/null || true
(cd "$REPO" && "$VPY" -m rlpcb index)

if [ "$(uname)" = "Darwin" ]; then DOCS="$HOME/Documents/KiCad"; CLAUDE="$HOME/Library/Application Support/Claude"; else DOCS="$HOME/.local/share/kicad"; CLAUDE="$HOME/.config/Claude"; fi
for v in 10.0 9.0 8.0 7.0; do
  base="$DOCS/$v"; [ -d "$base" ] || continue
  if [ "${v%%.*}" -ge 9 ]; then
    mkdir -p "$base/plugins/org.rlpcb.copilot"
    cp "$REPO"/kicad_plugin/ipc/* "$REPO/kicad_plugin/launcher_common.py" "$base/plugins/org.rlpcb.copilot/"
    echo "kicad-python>=0.3" > "$base/plugins/org.rlpcb.copilot/requirements.txt"
  fi
  mkdir -p "$base/scripting/plugins/rlpcb_copilot"
  cp "$REPO"/kicad_plugin/action/* "$REPO/kicad_plugin/launcher_common.py" "$base/scripting/plugins/rlpcb_copilot/"
  echo "Installed KiCad $v plugins"
done

if [ -d "$CLAUDE" ]; then
  "$VPY" - "$CLAUDE/claude_desktop_config.json" "$VPY" "$REPO" <<'EOF'
import json, os, sys
path, vpy, repo = sys.argv[1:4]
cfg = {}
if os.path.exists(path):
    cfg = json.load(open(path)) if open(path).read().strip() else {}
cfg.setdefault("mcpServers", {})["rlpcb"] = {"command": vpy, "args": ["-m", "rlpcb.agent.mcp_server"], "env": {"PYTHONPATH": repo}}
json.dump(cfg, open(path, "w"), indent=2)
print("Registered with Claude Desktop:", path)
EOF
fi
if [ "${1:-}" = "--seed-corpus" ]; then (cd "$REPO" && "$VPY" -m rlpcb corpus seed); fi
(cd "$REPO" && "$VPY" -m rlpcb doctor) || true
echo "Claude Code users:  claude mcp add rlpcb -- $VPY -m rlpcb.agent.mcp_server"
