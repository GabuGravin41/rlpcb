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
            resp = _http(f"{base}/chat/completions", {"model": model, "messages": msgs, "tools": tools},
                         {"authorization": f"Bearer {key}"})
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
