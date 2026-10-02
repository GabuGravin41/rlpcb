"""Copilot core: how much the AI may do, proposals the engineer reviews, a journal with undo, and an honest record of
what was checked.

This file is kept identical in RL PCB (rlpcb/agent/copilot.py) and RL CAD (rlcad/agent/copilot.py). Each tool supplies
an adapter (which files make up the design, how to summarise a change, which checks to run); the mechanics here are
shared, so an engineer meets the same modes, proposals and undo in KiCad and in FreeCAD.

Modes (per scope; the strictest scope touched by a change wins)
  teach    the AI explains only; it does not suggest changes unless asked
  advise   the AI gives guidelines and reviews; every design write is refused and returned as advice
  propose  writes run on a copy of the design; the engineer sees the diff and the check results, then accepts or
           rejects (the reason is kept, so the AI learns what this engineer wants)
  do       writes apply directly; each one is journalled with a snapshot, so it can be undone

Scopes name parts of a design: "block:power", "board:routing", "part:frame", "sheet:mcu.kicad_sch" … A setting for
"board" covers "board:routing" unless "board:routing" has its own setting.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import time
import uuid
from typing import Callable, Dict, Iterable, List, Optional

MODES = ("teach", "advise", "propose", "do")
MODE_HELP = {
    "teach": "explain and answer questions; no design changes",
    "advise": "guidelines and reviews; the engineer makes every change",
    "propose": "the AI prepares changes on a copy; the engineer accepts or rejects each one",
    "do": "the AI changes the design directly; every change is journalled and can be undone",
}
_RANK = {m: i for i, m in enumerate(MODES)}


def _now() -> float:
    return round(time.time(), 3)


def _sha(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Copilot:
    """State lives in `<state_dir>`: settings.json, journal.jsonl, snapshots/, proposals/."""

    def __init__(self, root: str, state_dir: str, include: Iterable[str] = ("*",),
                 exclude: Iterable[str] = (), default_mode: str = "propose"):
        self.root = os.path.abspath(root)
        self.state_dir = os.path.abspath(state_dir)
        self.include = list(include)
        self.exclude = list(exclude) + [os.path.relpath(self.state_dir, self.root).replace(os.sep, "/") + "/*"]
        self.default_mode = default_mode

    # ------------------------------------------------------------------ settings
    def _p(self, *a) -> str:
        return os.path.join(self.state_dir, *a)

    def settings(self) -> Dict:
        try:
            with open(self._p("settings.json"), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d.setdefault("mode", self.default_mode)
        d.setdefault("scopes", {})
        return d

    def _save_settings(self, d: Dict):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self._p("settings.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)

    def set_mode(self, mode: str, scope: str = "", note: str = "") -> Dict:
        if mode not in MODES and mode != "inherit":
            raise ValueError(f"mode must be one of {', '.join(MODES)} (or 'inherit' to clear a scope)")
        d = self.settings()
        if scope:
            if mode == "inherit":
                d["scopes"].pop(scope, None)
            else:
                d["scopes"][scope] = mode
        else:
            if mode == "inherit":
                raise ValueError("the default mode cannot be 'inherit'")
            d["mode"] = mode
        if note:
            d.setdefault("notes", {})[scope or "*"] = note
        self._save_settings(d)
        self.log("engineer", "set_mode", {"mode": mode, "scope": scope or "*", "note": note}, summary=f"mode {mode} "
                 f"for {scope or 'the whole design'}")
        return d

    def mode_for(self, scopes: Iterable[str]) -> Dict:
        """Strictest mode over the scopes a change touches (most specific setting per scope)."""
        d = self.settings()
        sc = d["scopes"]
        worst, why = None, ""
        for s in list(scopes) or [""]:
            m, src = d["mode"], "default"
            parts = s.split(":") if s else []
            for k in range(len(parts), 0, -1):
                key = ":".join(parts[:k])
                if key in sc:
                    m, src = sc[key], key
                    break
            if worst is None or _RANK[m] < _RANK[worst]:
                worst, why = m, src
        return {"mode": worst, "from": why}

    # ------------------------------------------------------------------ files
    def _wanted(self, rel: str) -> bool:
        rel = rel.replace(os.sep, "/")
        if any(fnmatch.fnmatch(rel, e) or rel.startswith(e.rstrip("*")) and e.endswith("/*") for e in self.exclude):
            return False
        return any(fnmatch.fnmatch(rel, i) for i in self.include)

    def files(self, root: Optional[str] = None) -> Dict[str, str]:
        """{relative path: sha1} of the design files under root."""
        root = root or self.root
        out = {}
        if not os.path.isdir(root):
            return out
        for dp, dns, fns in os.walk(root):
            reld = os.path.relpath(dp, root).replace(os.sep, "/")
            dns[:] = [d for d in dns if self._wanted_dir(("" if reld == "." else reld + "/") + d)]
            for fn in fns:
                rel = (fn if reld == "." else f"{reld}/{fn}")
                if self._wanted(rel):
                    try:
                        out[rel] = _sha(os.path.join(dp, fn))
                    except OSError:
                        pass
        return out

    def _wanted_dir(self, rel: str) -> bool:
        return not any(fnmatch.fnmatch(rel + "/x", e) or fnmatch.fnmatch(rel, e.rstrip("/*")) for e in self.exclude)

    @staticmethod
    def diff(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, List[str]]:
        return {"added": sorted(set(after) - set(before)),
                "removed": sorted(set(before) - set(after)),
                "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k])}

    def _copy_tree(self, src: str, dst: str, rels: Iterable[str]):
        for rel in rels:
            s, d = os.path.join(src, rel), os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)

    # ------------------------------------------------------------------ snapshots / journal
    def snapshot(self, rels: Iterable[str], label: str = "") -> str:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        d = self._p("snapshots", sid)
        os.makedirs(d, exist_ok=True)
        present = [r for r in rels if os.path.exists(os.path.join(self.root, r))]
        self._copy_tree(self.root, d, present)
        with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"label": label, "files": present, "absent": [r for r in rels if r not in present],
                       "t": _now()}, f)
        return sid

    def log(self, actor: str, action: str, args: Optional[Dict] = None, summary: str = "", **extra) -> Dict:
        os.makedirs(self.state_dir, exist_ok=True)
        e = {"id": uuid.uuid4().hex[:10], "t": _now(), "actor": actor, "action": action, "args": args or {},
             "summary": summary, **extra}
        with open(self._p("journal.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(e, default=str) + "\n")
        return e

    def journal(self, limit: int = 30, action: str = "") -> List[Dict]:
        try:
            with open(self._p("journal.jsonl"), encoding="utf-8") as f:
                rows = [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []
        if action:
            rows = [r for r in rows if r["action"] == action]
        return rows[-limit:]

    def undo(self, entry_id: str = "", force: bool = False) -> Dict:
        """Restore the files of a journalled change (default: the most recent undoable one)."""
        rows = [r for r in self.journal(10000) if r.get("snapshot") and not r.get("undone")]
        if entry_id:
            rows = [r for r in rows if r["id"] == entry_id]
        if not rows:
            raise ValueError("nothing to undo" if not entry_id else f"no undoable change {entry_id}")
        e = rows[-1]
        now = self.files()
        drift = [r for r, h in (e.get("after") or {}).items() if now.get(r) != h]
        if drift and not force:
            raise ValueError(f"these files changed after that step: {drift[:6]}; undo the later changes first, or "
                             "pass force=true to restore anyway")
        d = self._p("snapshots", e["snapshot"])
        with open(os.path.join(d, "_meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self._copy_tree(d, self.root, meta["files"])
        for rel in meta.get("absent", []):                    # files the change created
            p = os.path.join(self.root, rel)
            if os.path.exists(p):
                os.remove(p)
        self._mark(e["id"], undone=True)
        self.log("engineer", "undo", {"entry": e["id"]}, summary=f"undid: {e.get('summary', e['action'])}")
        return {"undone": e["id"], "action": e["action"], "restored": meta["files"], "removed": meta.get("absent", [])}

    def _mark(self, entry_id: str, **kv):
        p = self._p("journal.jsonl")
        rows = self.journal(100000)
        for r in rows:
            if r["id"] == entry_id:
                r.update(kv)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")

    # ------------------------------------------------------------------ applying a change (do mode)
    def apply(self, actor: str, action: str, args: Dict, run: Callable[[], Dict], scopes: List[str],
              summarize: Optional[Callable[[str, str, Dict], Dict]] = None) -> Dict:
        """Run a write directly, with a snapshot of every design file for undo."""
        before = self.files()
        sid = self.snapshot(list(before), label=action)
        res = run()
        after = self.files()
        ch = self.diff(before, after)
        if not any(ch.values()):
            shutil.rmtree(self._p("snapshots", sid), ignore_errors=True)
            return {"result": res, "changes": ch}
        # record which files did not exist before, so undo removes them
        meta_p = self._p("snapshots", sid, "_meta.json")
        with open(meta_p, encoding="utf-8") as f:
            meta = json.load(f)
        meta["files"] = [r for r in meta["files"] if r in set(ch["changed"]) | set(ch["removed"])]
        meta["absent"] = ch["added"]
        with open(meta_p, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        summ = summarize(self._p("snapshots", sid), self.root, ch) if summarize else {}
        e = self.log(actor, action, args, summary=summ.get("text", ""), scopes=scopes, snapshot=sid, changes=ch,
                     after={r: after[r] for r in ch["added"] + ch["changed"]}, detail=summ)
        return {"result": res, "changes": ch, "journal_id": e["id"], "undo": {"tool": "undo", "args": {"id": e["id"]}},
                "summary": summ}

    # ------------------------------------------------------------------ proposals (propose mode)
    def sandbox(self) -> (str, str):
        pid = time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:5]
        work = self._p("proposals", pid, "work")
        os.makedirs(work, exist_ok=True)
        self._copy_tree(self.root, work, self.files())
        return pid, work

    def propose(self, actor: str, action: str, args: Dict, run_in: Callable[[str], Dict], scopes: List[str],
                summarize: Optional[Callable[[str, str, Dict], Dict]] = None, rationale: str = "",
                live_replay: Optional[Dict] = None) -> Dict:
        """Run a write on a copy of the design and record the result as a proposal."""
        pid, work = self.sandbox()
        base = self.files()
        res = run_in(work)
        after = self.files(work)
        ch = self.diff(base, after)
        summ = summarize(self.root, work, ch) if summarize else {}
        prop = {"id": pid, "t": _now(), "status": "pending", "actor": actor, "action": action, "args": args,
                "scopes": scopes, "rationale": rationale, "changes": ch, "base": {r: base.get(r) for r in
                                                                                  ch["changed"] + ch["removed"]},
                "summary": summ, "result": res, "live_replay": live_replay}
        with open(self._p("proposals", pid, "proposal.json"), "w", encoding="utf-8") as f:
            json.dump(prop, f, indent=1, default=str)
        self.log(actor, "propose", {"proposal": pid, "action": action}, summary=summ.get("text", ""), proposal=pid)
        if not any(ch.values()):
            prop["note"] = "the change produced no file differences"
        return prop

    def proposals(self, status: str = "") -> List[Dict]:
        d = self._p("proposals")
        out = []
        if not os.path.isdir(d):
            return out
        for pid in sorted(os.listdir(d)):
            try:
                with open(os.path.join(d, pid, "proposal.json"), encoding="utf-8") as f:
                    p = json.load(f)
            except (OSError, ValueError):
                continue
            if not status or p["status"] == status:
                out.append(p)
        return out

    def proposal(self, pid: str) -> Dict:
        try:
            with open(self._p("proposals", pid, "proposal.json"), encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            raise ValueError(f"no proposal {pid}; pending: {[p['id'] for p in self.proposals('pending')]}")

    def _save_proposal(self, p: Dict):
        with open(self._p("proposals", p["id"], "proposal.json"), "w", encoding="utf-8") as f:
            json.dump(p, f, indent=1, default=str)

    def work_dir(self, pid: str) -> str:
        return self._p("proposals", pid, "work")

    def accept(self, pid: str, note: str = "", force: bool = False,
               replay: Optional[Callable[[Dict], Optional[Dict]]] = None) -> Dict:
        p = self.proposal(pid)
        if p["status"] != "pending":
            raise ValueError(f"proposal {pid} is already {p['status']}")
        now = self.files()
        drift = [r for r, h in p["base"].items() if now.get(r) != h]
        if drift and not force:
            raise ValueError(f"the design changed since this proposal was made ({drift[:6]}); reject it and ask for a "
                             "fresh one, or accept with force=true to overwrite those files")
        replayed = replay(p) if (replay and p.get("live_replay")) else None
        ch = p["changes"]
        work = self.work_dir(pid)
        rels = ch["added"] + ch["changed"] + ch["removed"]
        sid = self.snapshot(rels, label=f"accept {pid}")
        if replayed is None:
            self._copy_tree(work, self.root, ch["added"] + ch["changed"])
            for rel in ch["removed"]:
                q = os.path.join(self.root, rel)
                if os.path.exists(q):
                    os.remove(q)
        after = self.files()
        p.update(status="accepted", decided=_now(), note=note, applied_live=bool(replayed))
        self._save_proposal(p)
        e = self.log("engineer", "accept", {"proposal": pid, "action": p["action"]}, summary=p["summary"].get("text", ""),
                     proposal=pid, snapshot=sid, changes=ch, note=note,
                     after={r: after.get(r) for r in ch["added"] + ch["changed"]})
        return {"accepted": pid, "files": rels, "journal_id": e["id"], "applied_live": bool(replayed),
                "undo": {"tool": "undo", "args": {"id": e["id"]}}}

    def reject(self, pid: str, reason: str = "") -> Dict:
        p = self.proposal(pid)
        if p["status"] != "pending":
            raise ValueError(f"proposal {pid} is already {p['status']}")
        p.update(status="rejected", decided=_now(), note=reason)
        self._save_proposal(p)
        shutil.rmtree(self.work_dir(pid), ignore_errors=True)
        self.log("engineer", "reject", {"proposal": pid, "action": p["action"]}, summary=reason, proposal=pid)
        return {"rejected": pid, "reason": reason}

    def feedback(self, limit: int = 8) -> List[Dict]:
        """Recent decisions on proposals, with the engineer's reasons (so the AI adapts to this engineer)."""
        out = [{"proposal": p["id"], "action": p["action"], "status": p["status"], "reason": p.get("note", ""),
                "summary": (p.get("summary") or {}).get("text", "")}
               for p in self.proposals() if p["status"] in ("accepted", "rejected")]
        return out[-limit:]

    def status(self) -> Dict:
        d = self.settings()
        return {"mode": d["mode"], "mode_meaning": MODE_HELP[d["mode"]], "scopes": d["scopes"],
                "notes": d.get("notes", {}),
                "pending_proposals": [{"id": p["id"], "action": p["action"], "summary": p["summary"].get("text", ""),
                                       "checks": p["summary"].get("checks")} for p in self.proposals("pending")],
                "recent_feedback": self.feedback(),
                "recent_changes": [{"id": r["id"], "actor": r["actor"], "action": r["action"], "summary": r["summary"],
                                    "undone": r.get("undone", False)} for r in self.journal(8)]}


def gate_message(mode: str, src: str, tool: str, args: Dict, scopes: List[str]) -> Dict:
    """What a write returns when the mode does not allow it."""
    scope_txt = ", ".join(scopes) or "the design"
    if mode == "teach":
        how = ("You are in teach mode here: explain the idea, the reasoning and the trade-offs. Do not describe the "
               "edit as instructions unless the engineer asks.")
    else:
        how = ("You are in advise mode here: tell the engineer exactly what to change and why (values, locations, "
               "order of steps), and what to check afterwards. The engineer makes the change.")
    return {"blocked_by_mode": mode, "mode_set_on": src, "scopes": scopes, "would_have_called": {"tool": tool, "args": args},
            "message": f"Not applied: {scope_txt} is in '{mode}' mode ({MODE_HELP[mode]}). {how}",
            "engineer_can": "change the mode with copilot_mode (e.g. mode='propose' for this scope)"}
