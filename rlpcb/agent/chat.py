"""Built-in agent loop (for the chat panel inside KiCad).

Backends:
  * anthropic — Claude via the Messages API (needs an API key; separate from a Claude Pro subscription).
                Model "auto" picks the newest Sonnet available to the key. Web search is enabled server-side.
  * openai    — any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter, vLLM...) with tool calling.

(With only a Claude Pro/Max subscription, use Claude Desktop + the RL PCB MCP server instead — same tools.)
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, Iterator, List, Optional

from ..config import data_dir, load_settings, save_settings
from .prompt import SYSTEM_PROMPT
from .tools import TOOLS, Session, run_tool, to_json

ANTHROPIC_URL = "https://api.anthropic.com/v1"


def _http(url: str, payload: Optional[dict], headers: Dict[str, str], timeout: int = 600) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:800]}")


def anthropic_key() -> Optional[str]:
    return os.environ.get("ANTHROPIC_API_KEY") or load_settings().get("anthropic_api_key")


def pick_model(key: str, wanted: str) -> str:
    if wanted and wanted != "auto":
        return wanted
    cache = load_settings().get("_auto_model")
    if cache and time.time() - cache.get("t", 0) < 86400:
        return cache["id"]
    try:
        d = _http(f"{ANTHROPIC_URL}/models?limit=100", None, {"x-api-key": key, "anthropic-version": "2023-06-01"}, 30)
        ids = [m["id"] for m in d.get("data", [])]
        pref = [i for i in ids if "sonnet" in i] or [i for i in ids if "opus" in i] or ids
        model = pref[0]  # API lists newest first
        save_settings({"_auto_model": {"id": model, "t": time.time()}})
        return model
    except Exception:
        return "claude-sonnet-4-5"


def _tool_defs_anthropic():
    return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in TOOLS]


def _tool_result_content(res: dict) -> list:
    images = res.pop("image_paths", None) if isinstance(res, dict) else None
    content = [{"type": "text", "text": to_json(res, 40000)}]
    for p in images or []:
        if p.lower().endswith(".png") and os.path.exists(p):
            with open(p, "rb") as f:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                             "data": base64.b64encode(f.read()).decode()}})
    return content


class Conversation:
    def __init__(self, session: Optional[Session] = None, conv_id: Optional[str] = None):
        self.session = session or Session()
        if conv_id and not re.fullmatch(r"[\w-]{1,64}", conv_id):
            raise ValueError("bad conversation id")
        self.id = conv_id or time.strftime("%Y%m%d-%H%M%S")
        self.messages: List[dict] = []
        self.path = os.path.join(data_dir(), "conversations", f"{self.id}.json")
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.messages = json.load(f).get("messages", [])

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        slim = []
        for m in self.messages:  # don't persist base64 images
            if isinstance(m.get("content"), list):
                c = []
                for blk in m["content"]:
                    if blk.get("type") == "tool_result" and isinstance(blk.get("content"), list):
                        blk = dict(blk, content=[x for x in blk["content"] if x.get("type") != "image"])
                    c.append(blk)
                m = dict(m, content=c)
            slim.append(m)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"id": self.id, "messages": slim, "project": self.session.project}, f)

    # ---------------------------------------------------------------- run
    def send(self, text: str, emit: Callable[[dict], None], context: Optional[str] = None) -> None:
        s = load_settings()
        provider = s.get("provider", "anthropic")
        user = text if not context else f"{text}\n\n[KiCad context]\n{context}"
        self.messages.append({"role": "user", "content": user})
        try:
            if provider == "openai":
                self._run_openai(emit, s)
            elif provider == "anthropic" and anthropic_key():
                self._run_anthropic(emit, s)
            elif provider == "local" or not anthropic_key():
                self._run_local(emit, text)
            else:
                self._run_anthropic(emit, s)
        except Exception as e:  # noqa
            emit({"type": "error", "text": str(e)})
        finally:
            self.save()
            emit({"type": "done"})

    def _system(self) -> str:
        proj = self.session.project or "none (ask the user or use find_projects)"
        return SYSTEM_PROMPT + f"\n\nActive KiCad project: {proj}\nToday: {time.strftime('%Y-%m-%d')}"

    def _run_anthropic(self, emit, s):
        key = anthropic_key()
        if not key:
            raise RuntimeError("No Anthropic API key. Set it in the panel's settings (⚙) or the ANTHROPIC_API_KEY "
                               "environment variable — or use Claude Desktop with the RL PCB MCP server (works with Pro).")
        model = pick_model(key, s.get("model", "auto"))
        tools = _tool_defs_anthropic()
        if s.get("web_search", True):
            tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 5})
        tools[-1]["cache_control"] = {"type": "ephemeral"}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        for step in range(int(s.get("max_steps", 40))):
            payload = {"model": model, "max_tokens": int(s.get("max_tokens", 8000)),
                       "system": [{"type": "text", "text": self._system(), "cache_control": {"type": "ephemeral"}}],
                       "tools": tools, "messages": self._trimmed()}
            emit({"type": "status", "text": f"thinking… ({model})"})
            resp = _http(f"{ANTHROPIC_URL}/messages", payload, headers)
            content = resp.get("content", [])
            if resp.get("stop_reason") == "max_tokens":
                # a truncated turn may contain a half-written tool call: drop tool calls, keep the text
                content = [b for b in content if b.get("type") == "text"] or [{"type": "text", "text": "(reply truncated)"}]
                self.messages.append({"role": "assistant", "content": content})
                for blk in content:
                    emit({"type": "text", "text": blk["text"]})
                emit({"type": "error", "text": "The reply hit max_tokens; ask me to continue (or raise max_tokens in settings)."})
                break
            self.messages.append({"role": "assistant", "content": content})
            results = []
            for blk in content:
                if blk.get("type") == "text" and blk.get("text"):
                    emit({"type": "text", "text": blk["text"]})
                elif blk.get("type") == "tool_use":
                    emit({"type": "tool", "name": blk["name"], "input": blk.get("input", {})})
                    res = run_tool(self.session, blk["name"], blk.get("input") or {})
                    emit({"type": "tool_result", "name": blk["name"], "summary": _summ(res),
                          "images": [p for p in (res.get("image_paths") or [])]})
                    results.append({"type": "tool_result", "tool_use_id": blk["id"], "content": _tool_result_content(res),
                                    **({"is_error": True} if "error" in res else {})})
                elif blk.get("type") == "server_tool_use":
                    emit({"type": "tool", "name": blk.get("name", "web_search"), "input": blk.get("input", {})})
            if results:  # every tool_use must be answered, whatever the stop reason
                self.messages.append({"role": "user", "content": results})
                continue
            if resp.get("stop_reason") == "pause_turn":
                continue
            break

    def _trimmed(self, keep: int = 60) -> List[dict]:
        msgs = self.messages[-keep:]
        # never start with a dangling tool_result
        while msgs and msgs[0]["role"] == "user" and isinstance(msgs[0]["content"], list) and \
                any(b.get("type") == "tool_result" for b in msgs[0]["content"]):
            msgs = msgs[1:]
        return msgs

    def _run_openai(self, emit, s):
        base = s.get("openai_base_url", "http://localhost:11434/v1").rstrip("/")
        key = s.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "none"
        model = s.get("openai_model") or s.get("model") or "qwen2.5:14b"
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                 for t in TOOLS]
        msgs = [{"role": "system", "content": self._system()}]
        for m in self.messages:
            if isinstance(m["content"], str):
                msgs.append({"role": m["role"], "content": m["content"]})
            elif m.get("_openai"):
                msgs.append(m["_openai"])
        for step in range(int(s.get("max_steps", 40))):
            emit({"type": "status", "text": f"thinking… ({model})"})
            try:
                resp = _http(f"{base}/chat/completions", {"model": model, "messages": msgs, "tools": tools},
                             {"authorization": f"Bearer {key}"})
            except Exception as e:
                raise RuntimeError(
                    f"AI endpoint connection failed ({base}): {e}\n\n"
                    f"• If using Ollama or LM Studio, verify that the local server is running.\n"
                    f"• If using Grok or OpenAI, check that your API key and base URL are correct.\n"
                    f"• You can switch to Local Assistant mode anytime in Settings (⚙)."
                )
            msg = resp["choices"][0]["message"]
            msgs.append(msg)
            if msg.get("content"):
                emit({"type": "text", "text": msg["content"]})
            calls = msg.get("tool_calls") or []
            if not calls:
                self.messages.append({"role": "assistant", "content": msg.get("content") or ""})
                break
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                emit({"type": "tool", "name": name, "input": args})
                res = run_tool(self.session, name, args)
                res.pop("image_paths", None)
                emit({"type": "tool_result", "name": name, "summary": _summ(res)})
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": to_json(res, 30000)})

    def _run_local(self, emit: Callable[[dict], None], text: str) -> None:
        """Local intelligence execution without external API keys."""
        tl = text.lower().strip()
        tool_name = None
        tool_args = {}

        if "review layout" in tl or "review the board" in tl or "layout" in tl:
            tool_name = "review_layout"
            emit({"type": "status", "text": "Analyzing PCB layout..."})
        elif "ghost wire" in tl or "check the schematic" in tl or "drawing" in tl:
            tool_name = "check_schematic"
            emit({"type": "status", "text": "Scanning schematic drawing..."})
        elif "verify" in tl:
            tool_name = "verify_schematic"
            emit({"type": "status", "text": "Verifying drawing vs plan..."})
        elif "what's verified" in tl or "assurance" in tl:
            tool_name = "assurance_report"
            emit({"type": "status", "text": "Compiling assurance report..."})
        elif "board status" in tl or "board overview" in tl or "status" in tl:
            tool_name = "board_overview"
            emit({"type": "status", "text": "Reading board overview..."})
        elif "drc" in tl:
            tool_name = "run_drc"
            emit({"type": "status", "text": "Running DRC..."})
        elif "wiring guide" in tl:
            tool_name = "wiring_guide"
            emit({"type": "status", "text": "Generating wiring sequence..."})
        elif "show schematic" in tl or "render schematic" in tl:
            tool_name = "render_schematic"
            emit({"type": "status", "text": "Rendering schematic sheets..."})
        elif "new design" in tl or "kickoff" in tl:
            tool_name = "kickoff"
            tool_args = {"idea": text}
            emit({"type": "status", "text": "Generating design architecture..."})
        elif "calculate" in tl:
            tool_name = "calculate"
            tool_args = {"name": "trace_width", "params": {"current_a": 3.0}}
            emit({"type": "status", "text": "Running calculator..."})

        if tool_name:
            emit({"type": "tool", "name": tool_name, "input": tool_args})
            res = run_tool(self.session, tool_name, tool_args)
            images = [p for p in (res.get("image_paths") or [])]
            emit({"type": "tool_result", "name": tool_name, "summary": _summ(res), "images": images})
            formatted = self._format_local_result(tool_name, res, text)
            self.messages.append({"role": "assistant", "content": [{"type": "text", "text": formatted}]})
            emit({"type": "text", "text": formatted})
        else:
            resp = self._local_conversational_response(text)
            self.messages.append({"role": "assistant", "content": [{"type": "text", "text": resp}]})
            emit({"type": "text", "text": resp})

    def _format_local_result(self, tool_name: str, res: dict, query: str) -> str:
        if "error" in res:
            return f"**Error executing `{tool_name}`:** {res['error']}"

        if tool_name == "review_layout":
            pts = res.get("points", [])
            md = f"### ⌗ PCB Layout Engineering Review\n\nEvaluated layout against senior layout guidelines. Found **{len(pts)} findings**:\n\n"
            md += "| Category | Severity | Finding | Physical Rationale & Suggestion |\n|---|---|---|---|\n"
            for p in pts:
                cat = p.get("category", "layout")
                lvl = p.get("level", "info")
                msg = p.get("message", "").replace("\n", " ")
                why = p.get("why", "").replace("\n", " ")
                sug = p.get("suggestion", "")
                rec = f"{why} *Action: {sug}*" if sug else why
                md += f"| **{cat}** | `{lvl}` | {msg} | {rec} |\n"
            md += "\n---\n*✨ Verified by RL PCB Live Board Analysis.*"
            return md

        if tool_name == "check_schematic":
            probs = res.get("issues", [])
            counts = res.get("counts", {})
            md = "### 👻 Schematic Drawing Audit\n\n"
            if not probs:
                md += f"✅ **Zero ghost wires or drawing defects found!**\n- Nets checked: {counts.get('nets', 0)}\n- Components checked: {counts.get('components', 0)}\n- All pins and junctions are cleanly connected.\n"
            else:
                md += f"Found **{len(probs)} drawing issues**:\n\n"
                for pr in probs:
                    at = pr.get("at_mm") or pr.get("at", [0, 0])
                    md += f"- **{pr.get('kind', 'Issue')}**: {pr.get('message', '')} at `({at[0]:.2f}, {at[1]:.2f}) mm` on sheet `{pr.get('sheet', '/')}`\n"
            return md

        if tool_name == "verify_schematic":
            pct = res.get("progress_percent", 0)
            done = res.get("connections_done", 0)
            tot = res.get("connections_planned", 0)
            miss = res.get("missing_connections", [])
            md = f"### ✔ Schematic vs. Plan Verification ({pct}% Complete)\n\n"
            md += f"- **Connections verified:** {done} / {tot}\n"
            md += f"- **Nets complete:** {res.get('nets_complete', 0)} / {res.get('nets_total', 0)}\n"
            md += f"- **Shorts / unplanned nets:** {len(res.get('shorts', []))}\n\n"
            if miss:
                md += "#### Next Connections Needed:\n"
                for m in miss[:10]:
                    md += f"- Wire `{m.get('from', '')}` to `{m.get('to', '')}` (Net: `{m.get('net', '')}`)\n"
            return md

        if tool_name == "board_overview":
            sz = res.get("size_mm", [0, 0])
            r = res.get("routing", {})
            md = f"### ▦ Board Overview & Routing Status\n\n"
            md += f"- **Board Dimensions:** {sz[0]} × {sz[1]} mm ({res.get('thickness_mm', 1.6)} mm thick)\n"
            md += f"- **Layer Stack:** {len(res.get('copper_layers', []))} copper layers ({', '.join(res.get('copper_layers', []))})\n"
            md += f"- **Components / Footprints:** {res.get('footprints', 0)} total ({res.get('top_side', 0)} top, {res.get('bottom_side', 0)} bottom)\n"
            md += f"- **Routing Progress:** ~{r.get('percent_routed_approx', 0)}% routed (~{r.get('unrouted_connections_approx', 0)} connections remaining)\n"
            md += f"- **Tracks & Vias:** {res.get('tracks', 0)} track segments, {res.get('vias', 0)} vias\n"
            md += f"- **Copper Zones:** {res.get('zones', 0)} zones ({', '.join(res.get('zone_nets', []))})\n"
            return md

        if tool_name == "assurance_report":
            v = res.get("result", {}).get("findings", [])
            nv = res.get("not_verified", [])
            md = "### ✓? Engineering Assurance Report\n\n"
            if v:
                md += "#### Automated Check Findings:\n"
                for f in v:
                    md += f"- `[{f.get('severity', 'info')}]` **{f.get('rule', '')}**: {f.get('message', '')}\n"
            if nv:
                md += "\n#### Not Verified by Static Checks (Requires Inspection):\n"
                for item in nv:
                    md += f"- ⚠️ {item}\n"
            return md

        if tool_name == "run_drc":
            v = res.get("violations", [])
            md = f"### ⚠ KiCad Design Rule Check (DRC)\n\nFound **{len(v)} DRC violations**.\n\n"
            if not v:
                md += "✅ **0 DRC Errors!** Clearance, track widths, and keepouts pass.\n"
            else:
                for item in v[:12]:
                    md += f"- `{item.get('type', 'DRC')}`: {item.get('message', '')}\n"
            return md

        if tool_name == "wiring_guide":
            steps = res.get("steps", [])
            md = f"### 🧭 Step-by-Step Wiring Sequence\n\nComputed optimal shortest wiring sequence ({len(steps)} steps):\n\n"
            for s in steps[:12]:
                md += f"{s.get('step', '')}. Connect **{s.get('from', '')}** to **{s.get('to', '')}** (Net `{s.get('net', '')}`)\n"
            return md

        if tool_name == "render_schematic":
            return "### 🖼 Schematic Sheets Rendered\n\nRendered visual sheets displayed below."

        return f"### Result for `{tool_name}`\n\n```json\n{to_json(res, 2000)}\n```"

    def _local_conversational_response(self, text: str) -> str:
        # Check for specific component references like U1, C12, J2
        match = re.search(r"\b([A-Z]+[0-9]+)\b", text)
        if match:
            comp = match.group(1)
            r = run_tool(self.session, "locate", {"reference": comp})
            exp = run_tool(self.session, "explain_component", {"ref": comp})
            if not r.get("error"):
                return (f"### Component: {comp}\n\n"
                        f"- **Value:** `{r.get('value', 'N/A')}`\n"
                        f"- **Footprint:** `{r.get('footprint', 'N/A')}`\n"
                        f"- **Coordinates:** `({r.get('pos', [0, 0])[0]:.2f}, {r.get('pos', [0, 0])[1]:.2f}) mm` on sheet `{r.get('sheet', '/')}`\n"
                        f"- **Role:** {exp.get('role', 'Circuit component')}\n\n"
                        f"{exp.get('explanation', '')}\n\n"
                        f"---\n*💡 Running in Local Direct Intelligence Mode.*")

        proj = self.session.project or "No active KiCad project"
        return (f"### RL PCB Local Copilot\n\n"
                f"**Active Project:** `{proj}`\n\n"
                f"I am running natively in **Local Direct Intelligence Mode** (zero API key required). You can click any quick action above or ask me to:\n\n"
                f"- **`Review layout`**: 16-point expert layout review (placement, return paths, decoupling, skew)\n"
                f"- **`Ghost wires`**: Scan for floating wires, near-misses, and unconnected pins\n"
                f"- **`Verify wiring`**: Check hand-drawn schematic against planned connections\n"
                f"- **`Board status`**: Inspect board size, copper stackup, track counts, and unrouted ratsnest\n"
                f"- **`Run DRC`**: Check design rule clearances and violations\n"
                f"- **`Locate <Ref>`**: Find and highlight any part on the schematic or PCB (e.g. `locate U3`)\n\n"
                f"---\n"
                f"✨ *Tip: For full conversational AI pair-programming, you can also ask your Antigravity assistant directly in chat!*")



def _summ(res: dict) -> str:
    if "error" in res:
        return "error: " + str(res["error"])[:200]
    keys = list(res.keys())[:6]
    return ", ".join(keys)


def list_conversations() -> List[dict]:
    d = os.path.join(data_dir(), "conversations")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True)[:50]:
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                j = json.load(fh)
            first = next((m["content"] for m in j["messages"] if m["role"] == "user" and isinstance(m["content"], str)), "")
            out.append({"id": j["id"], "title": first[:60], "project": j.get("project")})
        except Exception:
            continue
    return out
