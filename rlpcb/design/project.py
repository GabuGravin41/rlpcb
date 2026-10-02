"""Create and discover KiCad projects."""
from __future__ import annotations

import json
import os
import uuid
from typing import List, Optional

from ..kicad import cli


def find_projects(root: str, max_depth: int = 6, limit: int = 200) -> List[dict]:
    out = []
    root = os.path.abspath(os.path.expanduser(root))
    base_depth = root.rstrip(os.sep).count(os.sep)
    for d, dirs, files in os.walk(root):
        if d.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__", "backups")]
        for f in files:
            if f.endswith(".kicad_pro"):
                p = os.path.join(d, f)
                name = f[:-len(".kicad_pro")]
                out.append({"project": p, "name": name,
                            "has_schematic": os.path.exists(os.path.join(d, name + ".kicad_sch")),
                            "has_board": os.path.exists(os.path.join(d, name + ".kicad_pcb")),
                            "has_plan": os.path.exists(os.path.join(d, ".rlpcb", "plan.json")),
                            "modified": os.path.getmtime(p)})
                if len(out) >= limit:
                    return out
    return sorted(out, key=lambda r: -r["modified"])


def create_project(folder: str, name: str, paper: str = "A4", title: str = "", kicad_major: Optional[int] = None) -> dict:
    folder = os.path.abspath(os.path.expanduser(folder))
    pdir = os.path.join(folder, name)
    os.makedirs(pdir, exist_ok=True)
    pro = os.path.join(pdir, name + ".kicad_pro")
    sch = os.path.join(pdir, name + ".kicad_sch")
    if os.path.exists(pro) or os.path.exists(sch):
        return {"error": f"A project already exists at {pdir}"}
    major = kicad_major or cli.major() or 9
    version = 20230121 if major <= 7 else 20231120
    root_uuid = str(uuid.uuid4())
    with open(pro, "w", encoding="utf-8") as f:
        json.dump({"meta": {"filename": name + ".kicad_pro", "version": 1},
                   "sheets": [[root_uuid, "Root"]],
                   "text_variables": {}}, f, indent=2)
    uu = f'"{root_uuid}"' if version >= 20231120 else root_uuid
    gen = '(generator "eeschema")\n\t(generator_version "8.0")' if version >= 20231120 else "(generator eeschema)"
    from ..kicad.sexpr import quote
    tb = f'\n\t(title_block\n\t\t(title {quote(title or name)})\n\t)' if title or name else ""
    with open(sch, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'(kicad_sch\n\t(version {version})\n\t{gen}\n\t(uuid {uu})\n\t(paper {quote(paper)}){tb}\n\t(lib_symbols)\n'
                f'\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n)\n')
    return {"project": pro, "schematic": sch, "folder": pdir, "format_version": version,
            "next": "Open the .kicad_pro in KiCad. The PCB file is created by KiCad the first time you open the PCB editor."}


def add_sheet(root_sch: str, name: str, filename: str = "", width: float = 50.8, height: float = 35.56) -> dict:
    """Add a hierarchical sheet (sheet symbol in the root + a new child .kicad_sch). Returns paths.

    Sheet pins are left to the user (or added via hierarchical labels inside the child and 'Sync sheet pins').
    """
    import re as _re
    from ..design.sch_writer import SchematicPlacer, backup, lock_file_for, new_uuid
    from ..kicad.schematic import Hierarchy
    from ..kicad.sexpr import QStr, dump, parse, quote

    h = Hierarchy(root_sch)
    root = h.root
    folder = os.path.dirname(root.path)
    base = _re.sub(r"[^A-Za-z0-9_\-]+", "_", filename or name).strip("_").lower() or "sheet"
    fname = base if base.endswith(".kicad_sch") else base + ".kicad_sch"
    child = os.path.join(folder, fname)
    if os.path.exists(child):
        return {"error": f"{fname} already exists"}
    if any(sh.name == name for sh in root.sheets):
        return {"error": f"A sheet named '{name}' already exists"}
    v8 = root.version >= 20231120
    child_uuid = str(uuid.uuid4())
    uu = f'"{child_uuid}"' if v8 else child_uuid
    gen = '(generator "eeschema")\n\t(generator_version "8.0")' if v8 else "(generator eeschema)"
    with open(child, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'(kicad_sch\n\t(version {root.version or 20231120})\n\t{gen}\n\t(uuid {uu})\n\t(paper "A4")\n'
                f'\t(title_block\n\t\t(title {quote(name)})\n\t)\n\t(lib_symbols)\n)\n')
    # place the sheet symbol in a free spot of the root sheet
    class _Src:
        def get(self, lib_id):
            return None, None
    placer = SchematicPlacer(root.path, _Src(), root.path)
    x, y = placer.free_spot(width + 10, height + 10)
    x, y = round(x - width / 2, 2), round(y - height / 2, 2)
    su = new_uuid()
    pages = [int(p) for p in _re.findall(r'\(page "(\d+)"\)', root.text)] or [1]
    page = str(max(pages) + 1)
    hide_eff = lambda just: ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left", just]]  # noqa: E731
    node = ["sheet", ["at", x, y], ["size", width, height],
            *([["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"]] if v8 else []),
            ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
            ["uuid", QStr(su) if v8 else su],
            ["property", QStr("Sheetname"), QStr(name), ["at", x, round(y - 0.7, 2), 0], hide_eff("bottom")],
            ["property", QStr("Sheetfile"), QStr(fname), ["at", x, round(y + height + 0.6, 2), 0], hide_eff("top")],
            ["instances", ["project", QStr(h.project_name), ["path", QStr(f"/{root.uuid}"), ["page", QStr(page)]]]]]
    text = root.text
    si = root.root.child("sheet_instances")
    anchor = si.start if si is not None else root.root.end - 1
    lock = lock_file_for(root.path)
    bk = backup(root.path)
    text = text[:anchor] + dump(node, 1) + "\n\t" + text[anchor:]
    parse(text)
    with open(root.path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    res = {"sheet": name, "file": child, "page": page, "at_mm": [x, y], "backup": bk,
           "next": "Place this block's parts with place_parts(sheet_file=...). Connect the sheet to the rest of the "
                   "design with hierarchical labels inside it (Ctrl+H) and matching sheet pins on the sheet symbol "
                   "(right-click the sheet → Sync Sheet Pins), or with global labels."}
    if lock:
        res["warning"] = "The root schematic is open in KiCad: close it without saving and reopen to see the new sheet."
    return res
