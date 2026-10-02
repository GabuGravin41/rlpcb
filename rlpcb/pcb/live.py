"""Live control of a running KiCad (9+) through the official IPC API (kicad-python / kipy).

Enable in KiCad: Preferences → Plugins → "Enable KiCad API". Works on the PCB
editor today; schematic calls are probed at runtime and used when the installed
KiCad exposes them.

Everything here is optional: if kipy is not installed or KiCad is not running,
functions raise LiveUnavailable with a human-readable reason and the copilot
falls back to file-based editing.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional


class LiveUnavailable(RuntimeError):
    pass


_CHOSEN: Optional[str] = None


def _socket_candidates() -> List[str]:
    """Every KiCad API socket we can find. Each running KiCad process opens its own socket: the first one gets
    api.sock, later ones api-<pid>.sock. If you opened the PCB editor as a separate program (or run two KiCads),
    the board may live behind a socket other than the default."""
    import glob
    import os
    from tempfile import gettempdir
    out = []
    env = os.environ.get("KICAD_API_SOCKET")
    if env:
        out.append(env)
    dirs = [os.path.join(gettempdir(), "kicad"), "/tmp/kicad",
            os.path.expanduser("~/.var/app/org.kicad.KiCad/cache/tmp/kicad")]
    for d in dirs:
        files = sorted(glob.glob(os.path.join(d, "api*.sock")), key=lambda f: (os.path.basename(f) != "api.sock", f))
        for f in files:
            url = "ipc://" + f
            if url not in out:
                out.append(url)
    return out


def _connect(path: Optional[str]):
    from kipy import KiCad
    k = KiCad(socket_path=path, timeout_ms=4000) if path else KiCad(timeout_ms=4000)
    k.ping()
    return k


def _kicad(want_board: bool = False):
    """Connect to KiCad. With want_board, prefer the KiCad process that has a PCB editor open."""
    global _CHOSEN
    try:
        import kipy  # noqa: F401
    except ImportError as e:
        raise LiveUnavailable("kicad-python (kipy) is not installed: pip install kicad-python") from e
    tried, first_ok, errors = [], None, []
    order = ([_CHOSEN] if _CHOSEN else []) + [None] + _socket_candidates()
    for path in order:
        if path in tried:
            continue
        tried.append(path)
        try:
            k = _connect(path)
        except Exception as e:  # noqa
            errors.append(f"{path or 'default'}: {type(e).__name__}")
            continue
        if not want_board:
            _CHOSEN = path
            return k
        first_ok = first_ok or k
        try:
            k.get_board()
            _CHOSEN = path
            return k
        except Exception as e:  # noqa
            errors.append(f"{path or 'default'}: connected, but no board ({str(e)[:80]})")
    if first_ok is not None:
        return first_ok
    raise LiveUnavailable(
        "Cannot reach KiCad's API. Open the PCB editor and enable Preferences → Plugins → 'Enable KiCad API', then "
        "restart KiCad. Tried: " + "; ".join(errors))


def _board():
    k = _kicad(want_board=True)
    try:
        return k, k.get_board()
    except Exception as e:  # noqa
        raise LiveUnavailable(
            "Reached KiCad, but none of its API sockets has a board open. If you started the PCB editor on its own "
            "(not from the project window), close it and open the board from the KiCad project window, or restart "
            f"KiCad so only one instance runs ({e})") from e


def status() -> Dict:
    try:
        k = _kicad(want_board=True)
    except LiveUnavailable as e:
        return {"connected": False, "reason": str(e), "sockets_found": _socket_candidates()}
    info = {"connected": True, "socket": _CHOSEN or "default", "sockets_found": _socket_candidates()}
    try:
        info["kicad_version"] = str(k.get_version())
    except Exception:
        pass
    try:
        b = k.get_board()
        info["board"] = b.name
        info["copper_layers"] = b.get_copper_layer_count()
    except Exception as e:  # noqa
        info["board"] = None
        msg = str(e)
        if "no handler" in msg or "GetOpenDocuments" in msg:
            msg = ("Connected to a KiCad process that has no PCB editor. If a board is open, it is probably in a "
                   "second KiCad process whose API socket wasn't found (see sockets_found). Open the board from the "
                   "KiCad project window of a single KiCad instance.")
        info["board_error"] = msg
    info["schematic_api"] = _schematic_available(k)
    return info


def _schematic_available(k) -> bool:
    try:
        from kipy.proto.common.types.base_types_pb2 import DocumentType
        docs = k.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
        return len(docs) > 0
    except Exception:
        return False


def _schematic():
    k = _kicad()
    try:
        from kipy.proto.common.types.base_types_pb2 import DocumentType
        from kipy.schematic import Schematic
        docs = k.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
        if not docs:
            raise LiveUnavailable("No schematic open (or this KiCad version has no schematic API yet)")
        return Schematic(k._client, docs[0])
    except LiveUnavailable:
        raise
    except Exception as e:  # noqa
        raise LiveUnavailable(f"Schematic API not available in this KiCad version ({e})") from e


def _ref(fp) -> str:
    try:
        return fp.reference_field.text.value
    except Exception:
        return "?"


def footprints() -> List[Dict]:
    _, b = _board()
    out = []
    for fp in b.get_footprints():
        p = fp.position
        out.append({"ref": _ref(fp), "x_mm": p.x / 1e6, "y_mm": p.y / 1e6,
                    "rotation": fp.orientation.degrees, "locked": fp.locked})
    return out


def select(refs: Iterable[str], editor: str = "pcb") -> Dict:
    """Highlight components in the open editor so the user can find them."""
    refs = set(refs)
    if editor == "schematic":
        sch = _schematic()
        items = [s for s in sch.get_symbols() if getattr(getattr(s, "reference_field", None), "text", None) is not None
                 and s.reference_field.text.value in refs]
        sch.clear_selection()
        if items:
            sch.add_to_selection(items)
        return {"selected": len(items)}
    _, b = _board()
    items = [fp for fp in b.get_footprints() if _ref(fp) in refs]
    b.clear_selection()
    if items:
        b.add_to_selection(items)
    return {"selected": [_ref(i) for i in items], "missing": sorted(refs - {_ref(i) for i in items})}


def move_footprints(moves: List[Dict]) -> Dict:
    """moves: [{ref, x_mm, y_mm, rotation?, side?('top'|'bottom')}] — one undoable commit."""
    from kipy.geometry import Angle, Vector2

    _, b = _board()
    by_ref = {_ref(fp): fp for fp in b.get_footprints()}
    changed, missing, locked = [], [], []
    commit = b.begin_commit()
    try:
        to_update = []
        flip = []
        for m in moves:
            fp = by_ref.get(m["ref"])
            if fp is None:
                missing.append(m["ref"])
                continue
            if fp.locked:
                locked.append(m["ref"])
                continue
            fp.position = Vector2.from_xy_mm(float(m["x_mm"]), float(m["y_mm"]))
            if m.get("rotation") is not None:
                fp.orientation = Angle.from_degrees(float(m["rotation"]))
            to_update.append(fp)
            side = m.get("side")
            if side:
                from kipy.util.board_layer import layer_from_canonical_name
                on_top = fp.layer == layer_from_canonical_name("F.Cu")
                if (side == "bottom") == on_top:
                    flip.append(fp)
            changed.append(m["ref"])
        if to_update:
            b.update_items(to_update)
        if flip:
            b.flip_items(flip)
        b.push_commit(commit, "RL PCB: place footprints")
    except Exception:
        b.drop_commit(commit)
        raise
    return {"moved": changed, "missing": missing, "locked_skipped": locked,
            "note": "One undo step in KiCad (Ctrl+Z) reverts all of these moves."}


def add_tracks(segments: List[Dict]) -> Dict:
    """segments: [{net, layer:'F.Cu', width_mm, points:[[x,y],...]}] and vias: [{net, x_mm, y_mm, size_mm, drill_mm}]."""
    from kipy.board_types import Net, Track
    from kipy.geometry import Vector2
    from kipy.util.board_layer import layer_from_canonical_name

    _, b = _board()
    nets = {n.name: n for n in b.get_nets()}
    items = []
    for s in segments:
        net = nets.get(s["net"]) or Net(name=s["net"])
        pts = s["points"]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = Track()
            t.start = Vector2.from_xy_mm(x1, y1)
            t.end = Vector2.from_xy_mm(x2, y2)
            t.width = int(float(s.get("width_mm", 0.25)) * 1e6)
            t.layer = layer_from_canonical_name(s.get("layer", "F.Cu"))
            t.net = net
            items.append(t)
    commit = b.begin_commit()
    try:
        created = b.create_items(items)
        b.push_commit(commit, "RL PCB: add tracks")
    except Exception:
        b.drop_commit(commit)
        raise
    return {"created_segments": len(created)}


def add_vias(vias: List[Dict]) -> Dict:
    from kipy.board_types import Net, Via
    from kipy.geometry import Vector2

    _, b = _board()
    nets = {n.name: n for n in b.get_nets()}
    items = []
    for v in vias:
        via = Via()
        via.position = Vector2.from_xy_mm(float(v["x_mm"]), float(v["y_mm"]))
        via.diameter = int(float(v.get("size_mm", 0.6)) * 1e6)
        via.drill_diameter = int(float(v.get("drill_mm", 0.3)) * 1e6)
        via.net = nets.get(v["net"]) or Net(name=v["net"])
        items.append(via)
    commit = b.begin_commit()
    try:
        created = b.create_items(items)
        b.push_commit(commit, "RL PCB: add vias")
    except Exception:
        b.drop_commit(commit)
        raise
    return {"created_vias": len(created)}


def refill_zones() -> Dict:
    _, b = _board()
    b.refill_zones(block=True)
    return {"ok": True}


def save_board() -> Dict:
    _, b = _board()
    b.save()
    return {"saved": b.name}


def board_text() -> str:
    """The live board as .kicad_pcb text (includes unsaved edits)."""
    _, b = _board()
    return b.get_as_string()


def selection() -> Dict:
    """What the user has selected in the PCB editor (footprints, tracks, vias) — lets them ask 'what is this?'."""
    _, b = _board()
    out = {"footprints": [], "tracks": 0, "vias": 0, "other": 0}
    for it in b.get_selection():
        cls = type(it).__name__
        if cls == "FootprintInstance":
            p = it.position
            out["footprints"].append({"ref": _ref(it), "x_mm": p.x / 1e6, "y_mm": p.y / 1e6})
        elif cls in ("Track", "ArcTrack"):
            out["tracks"] += 1
            try:
                out.setdefault("nets", set()).add(it.net.name)
            except Exception:
                pass
        elif cls == "Via":
            out["vias"] += 1
        else:
            out["other"] += 1
    if "nets" in out:
        out["nets"] = sorted(out["nets"])
    return out
