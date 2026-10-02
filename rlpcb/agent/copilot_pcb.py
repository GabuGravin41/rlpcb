"""RL PCB side of the copilot: which tools change the design, which part of the design each one touches (its scope),
how a change is summarised for the engineer, and what was and was not verified.

run_tool() in tools.py sends every call through `gate()`; read-only tools pass straight through.
"""
from __future__ import annotations

import copy
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .copilot import MODE_HELP, MODES, Copilot, gate_message

INCLUDE = ["docs/*", "datasheets/*", "*.kicad_sch", "*.kicad_pcb", "*.kicad_pro", "*.kicad_dru", "*.kicad_sym", "*.pretty/*", "sym-lib-table",
           "fp-lib-table", ".rlpcb/plan.json", "*.mech.json", "enclosure*.json", "system.json", "*/system.json",
           "*.kicad_mod"]
EXCLUDE = ["fab/*", "*-backups/*", ".rlpcb/backups/*", ".rlpcb/history/*", "*.routed.kicad_pcb", "*.placed.kicad_pcb",
           "_autosave-*", "*.lck", "output/*", "*.kicad_prl"]

# kind: design (changes the design; gated) | decision (engineer's call; gated, never 'do' by itself) |
#       output (exports derived files; allowed) | workspace (library/knowledge caches; allowed) | session
_SCOPE = {
    "create_project": "project", "add_sheet": "schematic", "import_lcsc_part": "library",
    "corpus_import_symbol": "library", "plan_set_info": "plan:requirements", "plan_import_schematic": "plan",
    "place_parts": "schematic", "sync_fields_from_plan": "schematic",
    "setup_netclasses": "board:rules", "add_design_rules": "board:rules", "move_footprints": "board:placement",
    "autoroute": "board:routing", "add_tracks_live": "board:routing", "finish_routing": "board:routing",
    "system_create": "system", "system_add_board": "system", "system_add_harness": "system",
    "system_add_supply": "system", "design_checks": "decisions", "kickoff_apply": "project",
}
_BLOCK_TOOLS = {"plan_add_block": "id", "add_block": "instance", "block_connect": "instance"}
_PLAN_TOOLS = {"plan_add_components", "plan_remove_component", "plan_connect", "plan_disconnect", "plan_no_connect"}
CREATES = {"create_project", "kickoff_apply"}
OUTPUT = {"export_jlcpcb", "export_plan_netlist", "export_fabrication", "mech_export", "run_erc", "run_drc"}
WORKSPACE = {"rebuild_library_index", "ingest_documents", "corpus_ingest", "fetch_datasheet", "open_project"}


def classify(name: str, args: Dict, plan_lookup: Optional[Callable[[str], str]] = None) -> Tuple[str, List[str]]:
    """(kind, scopes) of a tool call."""
    args = args or {}
    if name == "design_checks":
        return ("decision", ["decisions"]) if args.get("acknowledge") else ("read", [])
    if name == "setup_netclasses" and not args.get("apply"):
        return "read", []
    if name in _BLOCK_TOOLS:
        b = str(args.get(_BLOCK_TOOLS[name]) or "")
        return "design", [f"block:{b}" if b else "plan"]
    if name in _PLAN_TOOLS:
        scopes = set()
        refs = []
        if name == "plan_add_components":
            for c in args.get("components") or []:
                scopes.add(f"block:{c['block']}" if c.get("block") else "plan")
        else:
            refs = [str(args.get("ref") or "")] + [str(x).split(".")[0] for x in args.get("pins") or []]
        for r in refs:
            if r and plan_lookup:
                b = plan_lookup(r)
                scopes.add(f"block:{b}" if b else "plan")
        return "design", sorted(scopes) or ["plan"]
    if name in _SCOPE:
        return "design", [_SCOPE[name]]
    if name in OUTPUT:
        return "output", []
    if name in WORKSPACE:
        return "workspace", []
    return "read", []


def copilot_for_dir(project_dir: str) -> Copilot:
    mode = os.environ.get("RLPCB_DEFAULT_MODE", "propose")
    return Copilot(project_dir, os.path.join(project_dir, ".rlpcb", "copilot"), INCLUDE, EXCLUDE, default_mode=mode)


def copilot_for(session, proposal_id: str = "") -> Copilot:
    """The copilot for the open project, or for whichever project holds `proposal_id` (proposals for new projects and
    system folders live in those folders)."""
    if proposal_id:
        root = _registry().get(proposal_id)
        if root and (not session.project or os.path.abspath(root) != os.path.abspath(session.project_dir)):
            return copilot_for_dir(root)
    session.need_project()
    return copilot_for_dir(session.project_dir)


def _registry_path() -> str:
    from ..config import data_dir
    return os.path.join(data_dir(), "proposal_index.json")


def _registry() -> Dict[str, str]:
    import json
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def register_proposal(pid: str, root: str):
    import json
    d = _registry()
    d[pid] = os.path.abspath(root)
    os.makedirs(os.path.dirname(_registry_path()), exist_ok=True)
    with open(_registry_path(), "w", encoding="utf-8") as f:
        json.dump(d, f)


def external_pending(session) -> List[Dict]:
    """Pending proposals that live outside the open project (new projects, system folders)."""
    out = []
    here = os.path.abspath(session.project_dir) if session.project else None
    for pid, root in _registry().items():
        if root == here:
            continue
        try:
            pr = copilot_for_dir(root).proposal(pid)
        except Exception:  # noqa
            continue
        if pr["status"] == "pending":
            out.append(dict(pr, root=root))
    return out


# ------------------------------------------------------------------------------------------- summaries
def summarize(before_root: str, after_root: str, ch: Dict) -> Dict:
    """Engineer-readable description of a change between two copies of a project."""
    lines, detail = [], {}
    for rel in ch["changed"] + ch["added"]:
        a, b = os.path.join(before_root, rel), os.path.join(after_root, rel)
        try:
            if rel.endswith("plan.json"):
                d = _plan_diff(a if os.path.exists(a) else None, b)
                detail["plan"] = d
                lines += d["lines"]
            elif rel.endswith(".kicad_pcb"):
                d = _board_diff(a if os.path.exists(a) else None, b)
                detail[rel] = d
                lines += [f"{rel}: {x}" for x in d["lines"]]
            elif rel.endswith(".kicad_sch"):
                d = _sch_diff(a if os.path.exists(a) else None, b)
                lines += [f"{rel}: {x}" for x in d]
            else:
                lines.append(f"{'new' if rel in ch['added'] else 'changed'}: {rel}")
        except Exception as e:  # noqa
            lines.append(f"changed: {rel} (could not summarise: {e})")
    for rel in ch["removed"]:
        lines.append(f"removed: {rel}")
    return {"text": "; ".join(lines[:12]) + (f"; … {len(lines) - 12} more" if len(lines) > 12 else ""),
            "lines": lines, "detail": detail}


def _plan_diff(a: Optional[str], b: str) -> Dict:
    from ..design.plan import DesignPlan
    pa = DesignPlan.load(os.path.dirname(os.path.dirname(a))) if a else DesignPlan(name="")
    pb = DesignPlan.load(os.path.dirname(os.path.dirname(b)))
    ca, cb = {c.ref: c for c in pa.components}, {c.ref: c for c in pb.components}
    na, nb = {n.name: set(n.nodes) for n in pa.nets}, {n.name: set(n.nodes) for n in pb.nets}
    added = [f"{r} {cb[r].value} ({cb[r].role or cb[r].lib_id})" for r in cb if r not in ca]
    removed = [r for r in ca if r not in cb]
    changed = [f"{r}: {ca[r].value}→{cb[r].value}" if ca[r].value != cb[r].value else f"{r}: footprint → {cb[r].footprint}"
               for r in cb if r in ca and (ca[r].value != cb[r].value or ca[r].footprint != cb[r].footprint)]
    nets_new = [n for n in nb if n not in na]
    nets_gone = [n for n in na if n not in nb]
    nets_mod = [f"{n} (+{len(nb[n] - na[n])}/−{len(na[n] - nb[n])} pins)" for n in nb if n in na and nb[n] != na[n]]
    blocks = [b_.title for b_ in pb.blocks if b_.id not in {x.id for x in pa.blocks}]
    dec = pb.decisions[len(pa.decisions):]
    req = {k: v for k, v in pb.requirements.items() if pa.requirements.get(k) != v}
    lines = []
    if blocks:
        lines.append("blocks added: " + ", ".join(blocks))
    if added:
        lines.append(f"{len(added)} parts added: " + ", ".join(added[:8]) + (" …" if len(added) > 8 else ""))
    if removed:
        lines.append("parts removed: " + ", ".join(removed))
    if changed:
        lines.append("parts changed: " + ", ".join(changed[:8]))
    if nets_new:
        lines.append(f"{len(nets_new)} nets added: " + ", ".join(nets_new[:10]))
    if nets_mod:
        lines.append("nets changed: " + ", ".join(nets_mod[:8]))
    if nets_gone:
        lines.append("nets removed: " + ", ".join(nets_gone))
    if req:
        lines.append("requirements: " + ", ".join(f"{k}={v}" for k, v in req.items()))
    if dec:
        lines.append("decisions: " + " | ".join(dec))
    return {"lines": lines or ["plan unchanged in substance"], "parts_added": [a_.split()[0] for a_ in added],
            "parts_removed": removed, "nets_added": nets_new, "nets_changed": nets_mod}


def _board_diff(a: Optional[str], b: str) -> Dict:
    from ..pcb.board import Board
    from ..pcb.review import layout_metrics
    bb = Board(b)
    ba = Board(a) if a else None
    lines = []
    moved = []
    if ba:
        fa = {f.ref: f for f in ba.footprints}
        for f in bb.footprints:
            o = fa.get(f.ref)
            if o and (abs(o.x - f.x) > 0.01 or abs(o.y - f.y) > 0.01 or o.angle != f.angle or o.layer != f.layer):
                moved.append(f"{f.ref} ({o.x:.1f},{o.y:.1f})→({f.x:.1f},{f.y:.1f})"
                             + (f" {o.angle:g}°→{f.angle:g}°" if o.angle != f.angle else "")
                             + (" flipped" if o.layer != f.layer else ""))
        if moved:
            lines.append(f"{len(moved)} footprints moved: " + ", ".join(moved[:8]) + (" …" if len(moved) > 8 else ""))
    ma, mb = (layout_metrics(ba) if ba else None), layout_metrics(bb)
    if ma:
        dt = mb["track_length_mm"] - ma["track_length_mm"]
        dv = mb["vias"] - ma["vias"]
        if abs(dt) > 0.05 or dv:
            lines.append(f"copper: {dt:+.1f} mm of track, {dv:+d} vias (now {mb['track_length_mm']:.0f} mm, "
                         f"{mb['vias']} vias)")
        du = mb["unrouted"] - ma["unrouted"]
        if du:
            lines.append(f"unrouted connections {ma['unrouted']} → {mb['unrouted']}")
        dr = mb["ratsnest_mm"] - ma["ratsnest_mm"]
        if moved and abs(dr) > 0.5:
            lines.append(f"ratsnest length {ma['ratsnest_mm']:.0f} → {mb['ratsnest_mm']:.0f} mm "
                         f"({'shorter' if dr < 0 else 'longer'}: {'better' if dr < 0 else 'worse'} placement)")
    return {"lines": lines or ["board changed (no placement or copper difference found)"], "moved": moved,
            "metrics_before": ma, "metrics_after": mb}


def _sch_diff(a: Optional[str], b: str) -> List[str]:
    def syms(p):
        if not p:
            return {}
        txt = open(p, encoding="utf-8", errors="replace").read()
        return dict(re.findall(r'\(property "Reference" "([^"]+)"[^)]*\)[\s\S]{0,400}?\(property "Value" "([^"]*)"', txt))
    sa, sb = syms(a), syms(b)
    add = [r for r in sb if r not in sa and not r.startswith("#")]
    rem = [r for r in sa if r not in sb and not r.startswith("#")]
    out = []
    if add:
        out.append(f"{len(add)} symbols placed: " + ", ".join(sorted(add)[:12]))
    if rem:
        out.append("symbols removed: " + ", ".join(sorted(rem)[:12]))
    return out or ["schematic edited"]


# ------------------------------------------------------------------------------------------- assurance
STATIC_GAPS = [
    "EMC: no field simulation; layout advice uses rules of thumb (return paths, loop area, pair matching)",
    "Signal integrity: impedance and timing are not simulated; trace widths come from the stackup calculator only",
    "Thermal: no thermal simulation; dissipation figures come from the calculators",
    "Firmware: pin assignments are checked against the MCU's pin functions, not against your firmware",
    "Component data: ratings and pin functions are only as good as the symbol library and the fields on each part",
]


def findings_of(session) -> List[Dict]:
    """Plan + board check findings for a session (cheap; used for before/after deltas)."""
    from ..design.checks import board_checks
    from .tools import _split_acked, t_plan_review
    plan = session.plan()
    out: List[Dict] = []
    if plan.components:
        rv = t_plan_review(session)               # includes the plan checks
        out += [{"severity": "error", "rule": "plan", "message": str(m), "refs": []} for m in rv.get("errors", [])]
        out += [{"severity": "warning", "rule": "plan", "message": str(m), "refs": []} for m in rv.get("warnings", [])]
    if session.project and os.path.exists(session.pcb_path):
        try:
            out += board_checks(session.board(), plan, session.pins_of)
        except Exception:  # noqa
            pass
    out, _ = _split_acked(plan, out)
    return [f for f in out if f["severity"] in ("error", "warning")]


def check_delta(before: List[Dict], after: List[Dict]) -> Dict:
    key = lambda f: (f["severity"], f["rule"], f["message"])
    kb, ka = {key(f) for f in before}, {key(f) for f in after}
    new = [f for f in after if key(f) not in kb]
    fixed = [f for f in before if key(f) not in ka]
    return {"errors_before": sum(f["severity"] == "error" for f in before),
            "errors_after": sum(f["severity"] == "error" for f in after),
            "warnings_before": sum(f["severity"] == "warning" for f in before),
            "warnings_after": sum(f["severity"] == "warning" for f in after),
            "new_findings": [f"{f['severity']}: {f['message']}" for f in new][:10],
            "resolved_findings": [f"{f['severity']}: {f['message']}" for f in fixed][:10]}


def unverified(session) -> List[str]:
    """What the checks cannot vouch for in this project, item by item."""
    out: List[str] = []
    try:
        plan = session.plan()
    except Exception:  # noqa
        return out
    nosrc = [c.ref for c in plan.components if not c.dnp and not any(
        k.lower() in ("datasheet", "lcsc", "mpn", "manufacturer_part", "mfr part") for k in c.fields)
        and not re.match(r"^(R|C|L|FB|TP|H|MH|J)\d", c.ref)]
    if nosrc:
        out.append(f"{len(nosrc)} active parts have no datasheet/MPN/LCSC field, so their ratings are unverified: "
                   + ", ".join(nosrc[:12]))
    nofp = [c.ref for c in plan.components if not c.footprint]
    if nofp:
        out.append(f"{len(nofp)} parts have no footprint chosen: " + ", ".join(nofp[:12]))
    nopins = sorted({c.lib_id for c in plan.components if not session.pins_of(c.lib_id)})
    if nopins:
        out.append("symbols not found in the libraries, so their pins could not be checked: " + ", ".join(nopins[:8]))
    pw = [n.name for n in plan.nets if n.net_class == "power" and n.current_a is None]
    if pw:
        out.append("power nets without a current, so track widths and part ratings are not checked against load: "
                   + ", ".join(pw[:10]))
    return out


def assurance(session, delta: Optional[Dict] = None, ran: Optional[List[str]] = None) -> Dict:
    return {"checks_run": ran or ["plan review", "design checks (plan + board heuristics)"],
            "result": delta, "not_verified": unverified(session) + STATIC_GAPS}


# ------------------------------------------------------------------------------------------- the gate
def _clone(session, project_dir: str):
    s2 = copy.copy(session)
    s2.project = os.path.join(project_dir, os.path.basename(session.project)) if session.project else None
    s2._sym_cache = {}
    s2.settings = dict(session.settings)
    return s2


def _live_to_file(name: str, args: Dict) -> Tuple[Dict, Optional[Dict]]:
    """Proposals edit files: switch live-API tools to their file form; keep the original call to replay live."""
    a = dict(args or {})
    if name == "move_footprints":
        replay = {"tool": name, "args": dict(a, method="live")}
        a["method"] = "file"
        return a, replay
    return a, None


def gate(session, name: str, args: Dict, fn: Callable[..., Any], actor: str = "ai") -> Dict:
    """Run a tool call under the copilot rules. Returns the tool's result (plus copilot metadata)."""
    plan_lookup = None
    if session.project and name in _PLAN_TOOLS:
        try:
            plan = session.plan()
            plan_lookup = lambda r: (plan.comp(r).block if plan.comp(r) else "")
        except Exception:  # noqa
            pass
    kind, scopes = classify(name, args, plan_lookup)
    if kind not in ("design", "decision"):
        return fn(session, **(args or {}))
    # where does this tool write?
    root = None
    if name.startswith("system_"):
        root = os.path.abspath(os.path.expanduser(args.get("folder", "")))
    elif name in CREATES:
        root = os.path.join(os.path.abspath(os.path.expanduser(args.get("folder", ""))), args.get("name", ""))
    elif session.project:
        root = session.project_dir
    if not root:
        return fn(session, **(args or {}))
    cp = copilot_for_dir(root) if name.startswith("system_") or name in CREATES else copilot_for(session)
    m = cp.mode_for(scopes)
    mode = m["mode"]
    if kind == "decision" and mode == "do" and actor == "ai":
        mode = "propose"                       # accepting a warning is the engineer's decision
    if actor == "engineer":
        mode = "do"                            # the engineer's own edits always apply (journalled, undoable)
    if mode in ("teach", "advise"):
        cp.log(actor, "advice", {"tool": name, "args": args}, summary=f"blocked in {mode} mode", scopes=scopes)
        return gate_message(mode, m["from"], name, args, scopes)
    has_proj = bool(session.project) and root == session.project_dir
    before = findings_of(session) if has_proj else []
    if mode == "propose":
        a2, replay = _live_to_file(name, args)

        def run_in(work):
            if name.startswith("system_"):
                return fn(session, **dict(a2, folder=work))
            if name in CREATES:                        # build the new project in a scratch folder, then move it in
                import shutil
                tmp = work + "_new"
                r = fn(session, **dict(a2, folder=tmp))
                src = os.path.join(tmp, args.get("name", ""))
                if os.path.isdir(src):
                    for item in os.listdir(src):
                        shutil.move(os.path.join(src, item), os.path.join(work, item))
                shutil.rmtree(tmp, ignore_errors=True)
                return r
            s2 = _clone(session, work)
            return fn(s2, **a2)
        saved_project = session.project
        prop = cp.propose(actor, name, args, run_in, scopes, summarize, live_replay=replay)
        register_proposal(prop["id"], root)
        if session.project != saved_project:           # a creating tool switched the session to the scratch copy
            session.project = saved_project
            from ..config import save_settings
            save_settings({"active_project": saved_project})
        if name in CREATES:
            prop["next_after_accept"] = "open_project " + os.path.join(root, args.get("name", "") + ".kicad_pro")
        if has_proj:
            s2 = _clone(session, cp.work_dir(prop["id"]))
            prop["summary"]["checks"] = check_delta(before, findings_of(s2))
            prop["assurance"] = assurance(s2, prop["summary"]["checks"])
            cp._save_proposal(prop)
        res = prop.get("result")
        return {"proposal": prop["id"], "mode": "propose", "scopes": scopes, "summary": prop["summary"]["text"],
                "changes": prop["changes"], "checks": prop["summary"].get("checks"),
                "assurance": prop.get("assurance"), "tool_result": res,
                "next": "show the engineer the summary and checks; when they agree call proposal_accept(id), "
                        "otherwise proposal_reject(id, reason). Do not accept on your own judgement."}
    # do
    out = cp.apply(actor, name, args, lambda: fn(session, **(args or {})), scopes, summarize)
    res = out["result"] if isinstance(out["result"], dict) else {"result": out["result"]}
    res = dict(res)
    if any(out["changes"].values()):
        res["copilot"] = {"mode": "do", "journal_id": out.get("journal_id"), "summary": out["summary"].get("text"),
                          "undo": out.get("undo")}
        if has_proj:
            res["copilot"]["checks"] = check_delta(before, findings_of(session))
            res["copilot"]["assurance"] = assurance(session, res["copilot"]["checks"])
    return res
