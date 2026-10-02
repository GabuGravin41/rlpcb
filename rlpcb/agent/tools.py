"""RL PCB tool registry — one definition shared by the MCP server and the built-in chat agent.

Each tool has a name, a description written for the model, a JSON schema and a
handler. Handlers return JSON-serialisable dicts; image-producing tools return
{"image_path": ...} which the transports turn into real images.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..config import load_settings, save_settings


@dataclass
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    fn: Callable[..., Any]
    writes: bool = False  # modifies user files


def S(props: Dict[str, dict], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def p(t: str, d: str, **kw) -> dict:
    x = {"type": t, "description": d}
    x.update(kw)
    return x


STR, INT, NUM, BOOL = "string", "integer", "number", "boolean"


# =============================================================================== session
class Session:
    """Holds the active project and lazily-created indexes."""

    def __init__(self):
        self.settings = load_settings()
        self.project: Optional[str] = self.settings.get("active_project")
        self._index = None
        self._kb = None
        self._corpus = None
        self._sym_cache: Dict[str, list] = {}

    # --------------------------------------------------------------- resources
    @property
    def index(self):
        if self._index is None:
            from ..library.index import LibraryIndex
            self._index = LibraryIndex(project_dir=self.project_dir)
            if self._index.stats()["symbols"] == 0:
                self._index.build()
        return self._index

    @property
    def kb(self):
        if self._kb is None:
            from ..knowledge.kb import KnowledgeBase
            self._kb = KnowledgeBase()
            self._kb.ensure_builtin()
        return self._kb

    @property
    def corpus(self):
        if self._corpus is None:
            from ..corpus.corpus import Corpus
            self._corpus = Corpus()
        return self._corpus

    # --------------------------------------------------------------- project
    @property
    def project_dir(self) -> Optional[str]:
        return os.path.dirname(self.project) if self.project else None

    @property
    def project_name(self) -> Optional[str]:
        return os.path.splitext(os.path.basename(self.project))[0] if self.project else None

    def need_project(self):
        if not self.project:
            raise UserError("No project is open. Use open_project (or find_projects to locate one) first.")
        return self.project

    @property
    def sch_path(self) -> str:
        self.need_project()
        return os.path.join(self.project_dir, self.project_name + ".kicad_sch")

    @property
    def pcb_path(self) -> str:
        self.need_project()
        return os.path.join(self.project_dir, self.project_name + ".kicad_pcb")

    def hierarchy(self):
        from ..kicad.schematic import Hierarchy
        if not os.path.exists(self.sch_path):
            raise UserError(f"Schematic not found: {self.sch_path}")
        return Hierarchy(self.sch_path)

    def board(self):
        from ..pcb.board import Board
        if not os.path.exists(self.pcb_path):
            raise UserError("This project has no .kicad_pcb yet. Open the PCB editor once in KiCad and run "
                            "Tools → Update PCB from Schematic (F8).")
        return Board(self.pcb_path)

    def plan(self):
        from ..design.plan import DesignPlan
        self.need_project()
        return DesignPlan.load_or_new(self.project_dir, self.project_name or "design")

    def save_plan(self, plan):
        return plan.save(self.project_dir)

    def pins_of(self, lib_id: str) -> List[dict]:
        if lib_id in self._sym_cache:
            return self._sym_cache[lib_id]
        pins: List[dict] = []
        s = self.index.get_symbol(lib_id)
        if s:
            pins = s.get("pins", [])
        elif self.project:
            try:
                for f in self.hierarchy().files:
                    if lib_id in f.lib_symbols:
                        pins = [pp.to_dict() for pp in f.lib_symbols[lib_id].pins]
                        break
            except Exception:
                pass
        self._sym_cache[lib_id] = pins
        return pins


class UserError(Exception):
    pass


# =============================================================================== helpers
def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _crop_png(png: str, margin: int = 20) -> str:
    """Trim the white page around a render, so the board fills the image."""
    try:
        from PIL import Image, ImageChops
        im = Image.open(png).convert("RGB")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        box = ImageChops.difference(im, bg).point(lambda v: 255 if v > 12 else 0).getbbox()
        if box:
            x0, y0, x1, y1 = box
            im.crop((max(0, x0 - margin), max(0, y0 - margin), min(im.width, x1 + margin),
                     min(im.height, y1 + margin))).save(png)
    except Exception:
        pass
    return png


def _render_svg_to_png(svg: str, width: int = 2000) -> str:
    """SVG → PNG (cropped to the drawing). Tries cairosvg, then PyMuPDF (self-contained on Windows), else returns
    the SVG path."""
    png = _render_svg_raw(svg, width)
    return _crop_png(png) if png.endswith(".png") else png


def _render_svg_raw(svg: str, width: int = 2000) -> str:
    png = os.path.splitext(svg)[0] + ".png"
    try:
        import cairosvg
        cairosvg.svg2png(url=svg, write_to=png, output_width=width, background_color="white")
        return png
    except Exception:
        pass
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # PyMuPDF
        doc = fitz.open(svg)
        page = doc[0]
        zoom = width / max(page.rect.width, 1)
        pdfbytes = doc.convert_to_pdf()
        pdf = fitz.open("pdf", pdfbytes)
        pix = pdf[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(png)
        return png
    except Exception:
        return svg


def _render_pdf_pages(pdf: str, width: int = 2000, max_pages: int = 3) -> List[str]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    out = []
    doc = fitz.open(pdf)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        zoom = width / max(page.rect.width, 1)
        png = f"{os.path.splitext(pdf)[0]}_{i + 1}.png"
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(png)
        out.append(png)
    return out


# =============================================================================== tools
TOOLS: List[Tool] = []


def tool(name: str, description: str, schema: Dict[str, Any], writes: bool = False):
    def deco(fn):
        TOOLS.append(Tool(name, description, schema, fn, writes))
        return fn
    return deco


# ------------------------------------------------------------------------------- environment / project
@tool("kicad_environment", "Report the KiCad installation RL PCB found (version, kicad-cli, libraries, config dirs), "
      "library index size, knowledge base and corpus size, and whether the live KiCad API is reachable.", S({}))
def t_env(s: Session):
    from ..kicad import cli
    from ..kicad.paths import environment_report
    from ..pcb import live
    rep = environment_report()
    rep["kicad_cli_version"] = cli.version()
    rep["library_index"] = s.index.stats()
    rep["knowledge_docs"] = len(s.kb.list_docs())
    rep["corpus"] = s.corpus.stats()
    rep["live_api"] = live.status()
    rep["active_project"] = s.project
    return rep


@tool("find_projects", "Find KiCad projects (*.kicad_pro) under a folder. Defaults to the user's Documents folder.",
      S({"folder": p(STR, "Folder to search (e.g. C:/Users/me/Documents/KiCad)")}))
def t_find_projects(s: Session, folder: str = ""):
    from ..design.project import find_projects
    folder = folder or os.path.join(os.path.expanduser("~"), "Documents")
    return {"projects": find_projects(folder)}


@tool("open_project", "Make a KiCad project the active one (path to .kicad_pro, .kicad_sch or its folder). "
      "Returns an overview: sheets, parts, nets, board status, and design-plan status.",
      S({"path": p(STR, "Path to the .kicad_pro / .kicad_sch or the project folder")}, ["path"]))
def t_open_project(s: Session, path: str):
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        pros = [f for f in os.listdir(path) if f.endswith(".kicad_pro")]
        if not pros:
            raise UserError(f"No .kicad_pro in {path}")
        path = os.path.join(path, pros[0])
    if path.endswith(".kicad_sch") or path.endswith(".kicad_pcb"):
        path = os.path.splitext(path)[0] + ".kicad_pro"
    if not os.path.exists(path):
        raise UserError(f"Not found: {path}")
    s.project = path
    s._index = None
    s._sym_cache = {}
    save_settings({"active_project": path})
    try:
        s.index.build()  # picks up the project's own sym-lib-table / fp-lib-table (unchanged files are skipped)
    except Exception:
        pass
    return t_overview(s)


@tool("project_overview", "Summarise the active project: sheets, component counts by type, nets, board state, plan progress.", S({}))
def t_overview(s: Session):
    s.need_project()
    out: Dict[str, Any] = {"project": s.project}
    if os.path.exists(s.sch_path):
        from collections import Counter
        from ..kicad.connectivity import Connectivity
        h = s.hierarchy()
        comps = h.components()
        conn = Connectivity(h)
        kinds = Counter(re.match(r"[A-Za-z#]+", r).group(0) if re.match(r"[A-Za-z#]+", r) else "?" for r in comps)
        issues = conn.issues_dicts("warning")
        out["schematic"] = {"sheets": [i.name_path for i in h.instances], "components": len(comps),
                            "by_prefix": dict(kinds.most_common()), "nets": len(conn.nets),
                            "drawing_problems": len([i for i in issues if i["severity"] == "error"]),
                            "warnings": len([i for i in issues if i["severity"] == "warning"]),
                            "file_format": h.root.version, "load_errors": h.errors}
    else:
        out["schematic"] = None
    if os.path.exists(s.pcb_path):
        try:
            out["board"] = {k: v for k, v in s.board().overview().items() if k not in ("stackup",)}
        except Exception as e:  # noqa
            out["board"] = {"error": str(e)}
    plan = s.plan()
    out["plan"] = {"exists": bool(plan.components), "components": len(plan.components), "nets": len(plan.nets),
                   "blocks": [b.id for b in plan.blocks]}
    return out


@tool("create_project", "Create a new, empty KiCad project (project + schematic) in a folder and make it active.",
      S({"folder": p(STR, "Parent folder"), "name": p(STR, "Project name (no spaces preferred)"),
         "paper": p(STR, "Sheet size: A4, A3, A2...", default="A4"), "title": p(STR, "Title block title")},
        ["folder", "name"]), writes=True)
def t_create_project(s: Session, folder: str, name: str, paper: str = "A4", title: str = ""):
    from ..design.project import create_project
    r = create_project(folder, name, paper, title)
    if "project" in r:
        s.project = r["project"]
        save_settings({"active_project": s.project})
    return r


@tool("add_sheet", "Add a hierarchical sheet (e.g. one per plan block: 'Power', 'MCU', 'USB') to the root schematic and "
      "create its .kicad_sch file. Then place that block's parts with place_parts(sheet_file=...). Large designs "
      "stay readable when each functional block has its own sheet.",
      S({"name": p(STR, "Sheet name shown in KiCad"), "filename": p(STR, "Optional file name (without path)")}, ["name"]),
      writes=True)
def t_add_sheet(s: Session, name: str, filename: str = ""):
    from ..design.project import add_sheet
    return add_sheet(s.sch_path, name, filename)


# ------------------------------------------------------------------------------- libraries
@tool("search_symbols", "Search KiCad symbol libraries (stock + project + user). Use part numbers ('TPS54331', 'STM32G431'), "
      "functions ('buck 3A 24V', 'CAN transceiver', 'USB-C receptacle') or generic parts ('resistor'). Returns lib_ids "
      "to use in the plan. Always search before proposing a symbol — never invent lib_ids.",
      S({"query": p(STR, "Search text"), "limit": p(INT, "Max results", default=12),
         "library": p(STR, "Restrict to one library nickname, e.g. 'Device' or 'Regulator_Switching'"),
         "ref_prefix": p(STR, "Filter by reference prefix, e.g. 'U', 'Q', 'J'"),
         "min_pins": p(INT, "Minimum pin count"), "max_pins": p(INT, "Maximum pin count")}, ["query"]))
def t_search_symbols(s: Session, query: str, limit: int = 12, library: str = None, ref_prefix: str = None,
                     min_pins: int = None, max_pins: int = None):
    res = s.index.search_symbols(query, limit, library, ref_prefix, min_pins, max_pins)
    if not res:
        cs = s.corpus.find_symbol(query, 5)
        return {"results": [], "note": "Nothing in the installed libraries.",
                "found_in_open_source_designs": cs,
                "options": "Use corpus_import_symbol to borrow one of these, download from the manufacturer / SnapEDA / "
                           "Ultra Librarian / LCSC (easyeda2kicad), or create it in the Symbol Editor."}
    return {"results": res}


@tool("get_symbol", "Full details of a library symbol: description, datasheet, footprint filters, units and every pin "
      "(number, name, electrical type). Use this before writing connections.",
      S({"lib_id": p(STR, "e.g. 'Regulator_Switching:TPS54331D'")}, ["lib_id"]))
def t_get_symbol(s: Session, lib_id: str):
    r = s.index.get_symbol(lib_id)
    if not r:
        raise UserError(f"Symbol {lib_id} not found. Use search_symbols.")
    return r


@tool("search_footprints", "Search footprint libraries by package ('SOIC-8', 'QFN-32 5x5', '0603', 'TO-220', 'USB-C'), "
      "optionally by exact pad count, pitch (mm) or mount type (smd/tht).",
      S({"query": p(STR, "Search text"), "pad_count": p(INT, "Exact pad count"), "pitch": p(NUM, "Pad pitch in mm"),
         "mount": p(STR, "smd | tht | mixed"), "library": p(STR, "Footprint library nickname"),
         "limit": p(INT, "Max results", default=12)}))
def t_search_fp(s: Session, query: str = "", pad_count: int = None, pitch: float = None, mount: str = None,
                library: str = None, limit: int = 12):
    return {"results": s.index.search_footprints(query, limit, library, pad_count, mount, pitch)}


@tool("footprints_for_symbol", "List footprints compatible with a symbol (its default + footprint-filter matches with a "
      "matching pad count).", S({"lib_id": p(STR, "Symbol lib_id")}, ["lib_id"]))
def t_fp_for_sym(s: Session, lib_id: str):
    return {"footprints": s.index.footprints_for_symbol(lib_id)}


@tool("import_lcsc_part", "Import a part from LCSC/JLCPCB (EasyEDA library) by its LCSC number (e.g. 'C2040'): symbol, "
      "footprint and 3D model are converted to KiCad into <project>/lcsc/ and registered in the project's library "
      "tables, then indexed. Ideal for JLCPCB assembly (the LCSC field is filled). Needs internet + easyeda2kicad.",
      S({"lcsc_id": p(STR, "LCSC part number, e.g. C2040")}, ["lcsc_id"]), writes=True)
def t_lcsc(s: Session, lcsc_id: str):
    import subprocess
    import sys as _sys
    s.need_project()
    lcsc_id = lcsc_id.strip().upper()
    if not re.fullmatch(r"C\d{2,9}", lcsc_id):
        raise UserError("LCSC numbers look like C2040")
    out_dir = os.path.join(s.project_dir, "lcsc")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, "lcsc")
    before = set()
    sym_path = base + ".kicad_sym"
    if os.path.exists(sym_path):
        from ..kicad.symbols import SymbolLibrary
        before = set(SymbolLibrary(sym_path, "lcsc").symbols)
    r = subprocess.run([_sys.executable, "-m", "easyeda2kicad", "--full", "--lcsc_id", lcsc_id, "--output", base, "--overwrite"],
                       capture_output=True, text=True, timeout=180)
    if not os.path.exists(sym_path):
        raise UserError("easyeda2kicad failed: " + (r.stderr or r.stdout)[-600:] +
                        " (install it with: pip install easyeda2kicad, and check the internet connection)")
    _ensure_lib_table(s.project_dir, "sym-lib-table", "lcsc", "${KIPRJMOD}/lcsc/lcsc.kicad_sym", "LCSC/EasyEDA imports")
    _ensure_lib_table(s.project_dir, "fp-lib-table", "lcsc", "${KIPRJMOD}/lcsc/lcsc.pretty", "LCSC/EasyEDA imports")
    s.index.build(extra_symbol_files=[sym_path], extra_fp_dirs=[base + ".pretty"], force=True)
    from ..kicad.symbols import SymbolLibrary
    lib = SymbolLibrary(sym_path, "lcsc")
    new = sorted(set(lib.symbols) - before) or sorted(lib.symbols)[-1:]
    out = []
    for n in new:
        sym = lib.symbols[n]
        out.append({"lib_id": f"lcsc:{n}", "footprint": sym.properties.get("Footprint", ""),
                    "pins": len({p.number for p in sym.pins}), "LCSC": lcsc_id})
    return {"imported": out, "note": "Use these lib_ids in the plan and add fields {'LCSC': '%s'} so the JLCPCB BOM "
                                     "is complete. Check the footprint against the datasheet's land pattern." % lcsc_id}


def _ensure_lib_table(project_dir, table, name, uri, descr):
    path = os.path.join(project_dir, table)
    head = "sym_lib_table" if table.startswith("sym") else "fp_lib_table"
    entry = f'  (lib (name "{name}")(type "KiCad")(uri "{uri}")(options "")(descr "{descr}"))\n'
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            t = f.read()
        if f'(name "{name}")' in t:
            return
        t = t.rstrip().rstrip(")") + "\n" + entry + ")\n"
    else:
        t = f"({head}\n  (version 7)\n{entry})\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(t)


@tool("rebuild_library_index", "Re-scan symbol/footprint libraries (after installing new libraries or adding project libraries).",
      S({"force": p(BOOL, "Re-index everything, not only changed files", default=False)}))
def t_rebuild(s: Session, force: bool = False):
    return {"stats": s.index.build(force=force), "totals": s.index.stats()}


# ------------------------------------------------------------------------------- schematic reading
@tool("list_components", "List components in the active schematic (reference, value, symbol, footprint, sheet). "
      "Filter with a regex on reference/value/lib_id.",
      S({"filter": p(STR, "Regex, e.g. '^U' or 'LM358|TL07'"), "sheet": p(STR, "Sheet path fragment")}))
def t_list_components(s: Session, filter: str = "", sheet: str = ""):
    comps = s.hierarchy().components()
    rows = []
    rx = re.compile(filter, re.I) if filter else None
    for ref, c in sorted(comps.items(), key=lambda kv: _nat(kv[0])):
        if sheet and sheet not in c["sheet"]:
            continue
        if rx and not (rx.search(ref) or rx.search(c["value"]) or rx.search(c["lib_id"])):
            continue
        rows.append({"ref": ref, "value": c["value"], "lib_id": c["lib_id"], "footprint": c["footprint"], "sheet": c["sheet"],
                     **({"dnp": True} if c["dnp"] else {})})
    return {"count": len(rows), "components": rows[:600]}


@tool("component_connections", "Show what every pin of a component is connected to in the drawn schematic.",
      S({"ref": p(STR, "Reference, e.g. U3")}, ["ref"]))
def t_comp_conn(s: Session, ref: str):
    from ..kicad.connectivity import Connectivity
    c = Connectivity(s.hierarchy())
    rows = c.component_connections(ref)
    if not rows:
        raise UserError(f"{ref} not found in the schematic")
    return {"ref": ref, "pins": rows}


@tool("find_nets", "Find nets by name (regex) and list the pins on each.",
      S({"pattern": p(STR, "Regex on net names, e.g. 'USB|D\\+' or '^/Power/'")}, ["pattern"]))
def t_find_nets(s: Session, pattern: str):
    from ..kicad.connectivity import Connectivity
    c = Connectivity(s.hierarchy())
    rx = re.compile(pattern, re.I)
    nets = [n.to_dict(200) for name, n in sorted(c.nets.items()) if rx.search(name)]
    return {"count": len(nets), "nets": nets[:80]}


@tool("check_schematic", "Geometric check of the drawn schematic: floating 'ghost' wires, wire ends that miss pins "
      "(near-misses), T-joins without junctions, labels not attached, unconnected pins, shorted power nets, "
      "no-connect misuse. Run after the user draws.",
      S({"min_severity": p(STR, "error | warning | info", default="warning"), "sheet": p(STR, "Only this sheet path")}))
def t_check(s: Session, min_severity: str = "warning", sheet: str = ""):
    from collections import Counter
    from ..kicad.connectivity import Connectivity
    c = Connectivity(s.hierarchy())
    iss = [i for i in c.issues_dicts(min_severity) if not sheet or sheet in i.get("sheet", "")]
    return {"counts": dict(Counter(i["kind"] for i in iss)), "issues": iss[:150],
            "note": "Coordinates are in mm on the named sheet (KiCad status bar shows the cursor position)."}


@tool("run_erc", "Run KiCad's own Electrical Rules Check via kicad-cli (KiCad 8+) and summarise the violations.", S({}))
def t_erc(s: Session):
    from ..kicad import cli
    return cli.erc(s.sch_path)


@tool("render_schematic", "Render the schematic to PNG so you can look at it. Give focus='U3' (or 'U3,C5,R2') to get a "
      "zoomed crop around those parts with red highlight boxes — use this to 'pull up' a section of a big design and explain it.",
      S({"sheet": p(STR, "Sheet name fragment; empty = root/first sheets"),
         "focus": p(STR, "Comma-separated references to zoom to and highlight"),
         "margin_mm": p(NUM, "Extra margin around the focus parts", default=25)}))
def t_render_sch(s: Session, sheet: str = "", focus: str = "", margin_mm: float = 25):
    from ..kicad import cli
    if focus:
        refs = [r.strip() for r in focus.split(",") if r.strip()]
        h = s.hierarchy()
        boxes, sheet_name = [], None
        for inst, sym, ref, unit in h.iter_symbols():
            if ref in refs:
                name = inst.name_path.strip("/").split("/")[-1] if inst.name_path != "/" else ""
                if sheet_name is None:
                    sheet_name = name
                if name == sheet_name:
                    boxes.append(inst.sch.symbol_bbox(sym))
        if not boxes:
            raise UserError(f"None of {refs} found in the schematic")
        png = _render_focus(cli.export_sch_pdf(s.sch_path), refs, boxes, margin_mm)
        return {"image_paths": [png], "sheet": sheet_name or "/", "parts_highlighted": refs}
    files = cli.export_sch_svg(s.sch_path)
    if sheet:
        files = [f for f in files if sheet.lower() in os.path.basename(f).lower()] or files
    pngs = [_render_svg_to_png(f) for f in files[:3]]
    if pngs and not pngs[0].endswith(".png"):
        try:  # no SVG rasteriser: go through PDF with PyMuPDF
            pngs = _render_pdf_pages(cli.export_sch_pdf(s.sch_path))
        except Exception:
            pass
    return {"image_paths": pngs, "sheets_rendered": [os.path.basename(f) for f in files]}


def _svg_for_sheet(files: List[str], project: str, sheet_name: Optional[str]) -> str:
    if not sheet_name:
        for f in files:
            if os.path.basename(f) == f"{project}.svg":
                return f
        return files[0]
    want = f"{project}-{sheet_name}".lower().replace(" ", "_")
    for f in files:
        b = os.path.splitext(os.path.basename(f))[0].lower().replace(" ", "_")
        if b == want or b.endswith("-" + sheet_name.lower().replace(" ", "_")):
            return f
    return files[0]


def _render_focus(pdf_path: str, refs: List[str], boxes, margin_mm: float, width: int = 1600) -> str:
    """Crop the schematic PDF page that shows ``refs`` around the given mm boxes, outlining each in red."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(pdf_path)
    best, best_hits = 0, -1
    for i, pg in enumerate(doc):
        hits = sum(1 for r in refs if pg.search_for(r))
        if hits > best_hits:
            best, best_hits = i, hits
    page = doc[best]
    k = 72.0 / 25.4  # PDF points per mm; KiCad plots the sheet 1:1 from the top-left corner
    for (x0, y0, x1, y1) in boxes:
        page.draw_rect(fitz.Rect((x0 - 2) * k, (y0 - 3) * k, (x1 + 2) * k, (y1 + 3) * k), color=(0.85, 0.1, 0.1), width=1.2)
    X0 = min(b[0] for b in boxes) - margin_mm
    Y0 = min(b[1] for b in boxes) - margin_mm
    X1 = max(b[2] for b in boxes) + margin_mm
    Y1 = max(b[3] for b in boxes) + margin_mm
    clip = fitz.Rect(max(0, X0 * k), max(0, Y0 * k), min(page.rect.width, X1 * k), min(page.rect.height, Y1 * k))
    zoom = width / max(clip.width, 1)
    out = os.path.splitext(pdf_path)[0] + "_focus.png"
    page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False).save(out)
    return out


@tool("locate", "Where is a component or pin on the schematic (sheet + mm coordinates) and on the board. Also selects/"
      "highlights it in KiCad when the live API is enabled.",
      S({"target": p(STR, "'U3' or 'U3.7' or 'U3.VIN'")}, ["target"]))
def t_locate(s: Session, target: str):
    ref, _, pin = target.partition(".")
    h = s.hierarchy()
    out: Dict[str, Any] = {"target": target, "schematic": []}
    for inst, sym, r, unit in h.iter_symbols():
        if r != ref:
            continue
        row = {"sheet": inst.name_path, "unit": unit, "symbol_at_mm": [sym.x, sym.y]}
        if pin:
            for pp, x, y in inst.sch.pin_positions(sym, unit):
                if pp.number == pin or pp.name.lower() == pin.lower():
                    row["pin"] = {"number": pp.number, "name": pp.name, "at_mm": [x, y]}
        out["schematic"].append(row)
    if os.path.exists(s.pcb_path):
        b = s.board()
        f = b.fp(ref)
        if f:
            out["board"] = f.to_dict()
    try:
        from ..pcb import live
        out["highlighted_in_pcb"] = live.select([ref])
    except Exception as e:  # noqa
        out["highlight"] = f"not available ({str(e)[:80]})"
    out["tip"] = "In the schematic editor press Ctrl+F and type the reference to jump to it."
    return out


# ------------------------------------------------------------------------------- design plan
@tool("plan_show", "Show the current design plan: requirements, blocks, components, nets, decisions.",
      S({"block": p(STR, "Only this block")}))
def t_plan_show(s: Session, block: str = ""):
    plan = s.plan()
    d = plan.summary()
    if block:
        refs = {c.ref for c in plan.components if c.block == block}
        d["components"] = [c for c in d["components"] if c["ref"] in refs]
        d["nets"] = [n for n in d["nets"] if any(x.split(".")[0] in refs for x in n["nodes"])]
    return d


@tool("plan_set_info", "Set plan name/description, merge requirement key/values (input voltage, currents, environment, "
      "standards, budget, fab), and/or log a design decision with its rationale.",
      S({"name": p(STR, "Design name"), "description": p(STR, "What the board does"),
         "requirements": p("object", "Key → value, e.g. {'input': '24 V ±20% industrial', 'ambient': '0–60 °C'}"),
         "decision": p(STR, "A decision and why, e.g. 'Use 4 layers: USB 2.0 + dense QFN'")}), writes=True)
def t_plan_info(s: Session, name: str = None, description: str = None, requirements: dict = None, decision: str = None):
    s.need_project()
    plan = s.plan()
    if name:
        plan.name = name
    if description:
        plan.description = description
    if requirements:
        plan.requirements.update({k: str(v) for k, v in requirements.items()})
    if decision:
        plan.decisions.append(decision)
    s.save_plan(plan)
    return {"ok": True, "requirements": plan.requirements, "decisions": plan.decisions[-5:]}


@tool("plan_add_block", "Add or update a functional block (e.g. 'psu_24v_to_5v', 'mcu', 'usb', 'motor_driver_x').",
      S({"id": p(STR, "Short id"), "title": p(STR, "Human title"), "purpose": p(STR, "What it does"),
         "layout_notes": p(STR, "Placement/routing rules for this block"),
         "reference_design": p(STR, "Datasheet section / app note / corpus design this block follows")}, ["id", "title"]),
      writes=True)
def t_plan_block(s: Session, id: str, title: str, purpose: str = "", layout_notes: str = "", reference_design: str = ""):
    from ..design.plan import PlanBlock
    s.need_project()
    plan = s.plan()
    b = next((x for x in plan.blocks if x.id == id), None)
    if b:
        b.title, b.purpose = title, purpose or b.purpose
        b.layout_notes = layout_notes or b.layout_notes
        b.reference_design = reference_design or b.reference_design
    else:
        plan.blocks.append(PlanBlock(id, title, purpose, "", layout_notes, reference_design))
    s.save_plan(plan)
    return {"blocks": [x.id for x in plan.blocks]}


@tool("plan_add_components", "Add components to the plan. Each needs lib_id (from search_symbols); ref is optional "
      "(auto-numbered from the symbol's prefix). Validates that the symbol and footprint exist.",
      S({"components": p("array", "List of components", items=S({
          "ref": p(STR, "Reference, e.g. U1 (optional)"), "lib_id": p(STR, "Symbol lib_id"),
          "value": p(STR, "Value, e.g. 10k, 100n, TPS54331"), "footprint": p(STR, "Footprint lib:name"),
          "block": p(STR, "Block id"), "role": p(STR, "Why this part exists (shown to the user)"),
          "fields": p("object", "Extra fields: MPN, Manufacturer, LCSC, Voltage, Tolerance, Dielectric...")}, ["lib_id"]))},
        ["components"]), writes=True)
def t_plan_add(s: Session, components: List[dict]):
    from ..design.plan import PlanComponent
    s.need_project()
    plan = s.plan()
    taken = set()
    try:
        taken = set(s.hierarchy().components(include_power=False).keys())
    except Exception:
        pass
    added, problems = [], []
    for c in components:
        lib_id = c.get("lib_id", "")
        sym = s.index.get_symbol(lib_id)
        if not sym:
            problems.append(f"{lib_id}: symbol not found — search_symbols first")
            continue
        if sym["lib_id"] != lib_id:
            lib_id = sym["lib_id"]
        fp = c.get("footprint") or sym.get("default_footprint") or ""
        if fp and not s.index.get_footprint(fp):
            problems.append(f"{c.get('ref') or lib_id}: footprint {fp} not found — pick one with footprints_for_symbol")
            fp = c.get("footprint") and "" or fp
        ref = c.get("ref") or plan.next_ref(sym.get("reference_prefix") or "U", taken)
        pc = PlanComponent(ref=ref, lib_id=lib_id, value=c.get("value") or lib_id.split(":")[-1], footprint=fp,
                           block=c.get("block", ""), role=c.get("role", ""), fields=c.get("fields") or {},
                           unit_count=sym.get("units", 1))
        plan.upsert_component(pc)
        added.append({"ref": ref, "lib_id": lib_id, "value": pc.value, "footprint": fp, "units": pc.unit_count})
    s.save_plan(plan)
    from ..design.blocks import BLOCKS
    hints = []
    main_parts = {}
    for b in BLOCKS.values():
        try:
            main_parts.setdefault(b.build().parts[0]["lib_id"], b.id)
        except Exception:
            pass
    for a in added:
        if a["lib_id"] in main_parts and a["lib_id"] not in ("Device:R", "Device:C"):
            hints.append(f"{a['ref']} ({a['lib_id']}): the pre-verified block '{main_parts[a['lib_id']]}' contains this part "
                         "with all its support parts wired correctly — prefer add_block (then plan_remove_component this one)")
    out = {"added": added, "problems": problems, "total_components": len(plan.components)}
    if hints:
        out["hint"] = hints
    return out


@tool("list_blocks", "List the pre-verified circuit blocks (regulators, MCU cores, sensors, USB, LEDs, connectors) with "
      "their parameters and ports. PREFER BLOCKS over placing parts one by one: a block brings its decoupling, "
      "feedback network, crystal loads etc. already correct, and MCU blocks let you connect peripherals by function "
      "(SPI1_SCK, USART1_TX, USB_DP) instead of pin numbers.", S({"category": p(STR, "Optional filter: power, mcu, sensor, memory, interface, io, analog")}))
def t_list_blocks(s: Session, category: str = ""):
    from ..design.blocks import list_blocks
    return {"blocks": [b for b in list_blocks() if not category or b["category"] == category]}


@tool("add_block", "Add a pre-verified circuit block to the plan and connect its ports to nets. Example: "
      "add_block(block='tps5430_buck', instance='buck5v', params={'vin_max': 25.2, 'vout': 5}, "
      "connect={'VIN': 'VBAT', 'VOUT': '+5V'}). GND ports default to net GND. Use the same net name on two blocks to "
      "connect them. Returns the references created, calculated values and the datasheet points to confirm.",
      S({"block": p(STR, "Block id from list_blocks"), "instance": p(STR, "Unique instance name, e.g. buck5v, imu, mcu"),
         "params": p("object", "Block parameters (see list_blocks)"),
         "connect": p("object", "Port → net name, e.g. {'VOUT': '+5V', 'SPI1_SCK': 'IMU_SCK'}")},
        ["block", "instance"]), writes=True)
def t_add_block(s: Session, block: str, instance: str, params: dict = None, connect: dict = None):
    from ..design.blocks import instantiate
    s.need_project()
    plan = s.plan()
    taken = set()
    try:
        taken = set(s.hierarchy().components(include_power=False).keys())
    except Exception:
        pass
    try:
        r = instantiate(plan, s.pins_of, block, instance, params, connect, taken)
    except (KeyError, ValueError, TypeError) as e:
        raise UserError(str(e))
    for c in plan.components:
        if c.block != instance:
            continue
        sym = s.index.get_symbol(c.lib_id)
        if not sym:
            r["problems"].append(f"{c.ref}: symbol {c.lib_id} is not in your libraries")
            continue
        c.unit_count = sym.get("units", 1)
        if not c.footprint:
            c.footprint = sym.get("default_footprint") or ""
        if c.footprint and not s.index.get_footprint(c.footprint):
            r["problems"].append(f"{c.ref}: footprint {c.footprint} is not in your libraries — choose one with "
                                 "footprints_for_symbol")
    s.save_plan(plan)
    return r


@tool("block_connect", "Connect more ports of a block that is already in the plan — e.g. MCU peripherals: "
      "block_connect(instance='mcu', connect={'SPI1_SCK': 'FLASH_SCK', 'USART2_TX': 'DBG_TX', 'PB5': 'LED'}). "
      "Naming a net 'SPI1_SCK' does NOT connect it to the MCU — only a port mapping (here or in add_block) does.",
      S({"instance": p(STR, "Block instance name"), "connect": p("object", "Port → net name")}, ["instance", "connect"]),
      writes=True)
def t_block_connect(s: Session, instance: str, connect: dict):
    from ..design.blocks import connect_ports
    plan = s.plan()
    try:
        r = connect_ports(plan, s.pins_of, instance, connect or {})
    except ValueError as e:
        raise UserError(str(e))
    s.save_plan(plan)
    return r


@tool("plan_remove_component", "Remove a component (and its connections) from the plan.",
      S({"ref": p(STR, "Reference")}, ["ref"]), writes=True)
def t_plan_rm(s: Session, ref: str):
    plan = s.plan()
    plan.remove_component(ref)
    s.save_plan(plan)
    return {"removed": ref}


@tool("plan_connect", "Connect pins into a named net in the plan. Pins as REF.PIN where PIN is a pin number or pin name "
      "('U1.3', 'U1.VIN', 'U2.GND' → all pins named GND, 'U1.PA*' → wildcard). Adds to the net if it exists. "
      "Annotate the net with class (power, ground, signal, high_speed, diff_pair, analog, high_voltage, rf), current, "
      "voltage, impedance and notes — these drive PCB rules later.",
      S({"net": p(STR, "Net name, e.g. +5V, GND, USB_DP, SW_NODE"), "pins": p("array", "Pins", items={"type": STR}),
         "net_class": p(STR, "Class"), "notes": p(STR, "Why / constraints"), "current_a": p(NUM, "Max current"),
         "voltage_v": p(NUM, "Max voltage"), "impedance_ohm": p(NUM, "Target impedance"),
         "diff_partner": p(STR, "Other net of a differential pair")}, ["net", "pins"]), writes=True)
def t_plan_connect(s: Session, net: str, pins: List[str], net_class: str = None, notes: str = None, current_a: float = None,
                   voltage_v: float = None, impedance_ohm: float = None, diff_partner: str = None):
    from ..design.plan import PinResolver
    plan = s.plan()
    res = PinResolver(s.pins_of)
    nodes, errors = [], []
    for spec in pins:
        got, err = res.resolve(plan, spec.strip())
        if err:
            errors.append(err)
        nodes += got
    if not nodes:
        raise UserError("; ".join(errors) or "no pins")
    n, moved = plan.connect(net, nodes, net_class=net_class, notes=notes, current_a=current_a, voltage_v=voltage_v,
                            impedance_ohm=impedance_ohm, diff_partner=diff_partner)
    s.save_plan(plan)
    return {"net": n.name, "nodes": n.nodes, "moved": moved, "errors": errors}


@tool("plan_disconnect", "Remove pins from whatever net they are on in the plan.",
      S({"pins": p("array", "Pins REF.PIN", items={"type": STR})}, ["pins"]), writes=True)
def t_plan_disc(s: Session, pins: List[str]):
    plan = s.plan()
    plan.disconnect(pins)
    s.save_plan(plan)
    return {"ok": True}


@tool("plan_no_connect", "Mark pins as intentionally unconnected in the plan (they get a no-connect flag).",
      S({"pins": p("array", "Pins REF.PIN", items={"type": STR})}, ["pins"]), writes=True)
def t_plan_nc(s: Session, pins: List[str]):
    from ..design.plan import PinResolver
    plan = s.plan()
    res = PinResolver(s.pins_of)
    for spec in pins:
        got, err = res.resolve(plan, spec)
        for g in got:
            if g not in plan.no_connect:
                plan.no_connect.append(g)
    plan.disconnect(plan.no_connect)
    s.save_plan(plan)
    return {"no_connect": plan.no_connect}


@tool("plan_review", "Review the plan before drawing: unconnected power pins, floating inputs, output conflicts, missing "
      "decoupling, footprint/pin-count mismatches, single-pin nets.", S({}))
def t_plan_review(s: Session):
    from ..design.checks import plan_checks
    from ..design.review import review_plan
    plan = s.plan()
    r = review_plan(plan, s.pins_of, s.index.get_footprint)
    for f in plan_checks(plan, s.pins_of, s.index.get_footprint, _board_area(s, plan)):
        r[{"error": "errors", "warning": "warnings", "info": "info"}[f["severity"]]].append(f"[{f['rule']}] {f['message']}")
    r["ready_to_draw"] = not r["errors"]
    r["summary"] = (f"{len(plan.components)} parts, {len(plan.nets)} nets, {len(r['errors'])} errors, "
                    f"{len(r['warnings'])} warnings")
    return r


def _board_area(s: Session, plan) -> Optional[float]:
    """Board area from the .kicad_pcb outline if it exists, else from a 'WxH mm' requirement."""
    try:
        if s.pcb_path and os.path.exists(s.pcb_path):
            b = s.board()
            x0, y0, x1, y1 = b.board_bbox()
            if b.outline and x1 > x0:
                return (x1 - x0) * (y1 - y0)
    except Exception:
        pass
    for v in (plan.requirements or {}).values():
        m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", str(v))
        if m:
            return float(m.group(1)) * float(m.group(2))
    return None


@tool("design_checks", "Engineering checks beyond ERC: capacitor voltage ratings vs rails, inductor/connector current, "
      "missing I2C/open-drain pull-ups, rails fed by several sources (back-feed), board fit; and on the PCB: decoupling "
      "caps far from their pin, crystal distance, tracks too narrow for their current. Returns findings with severity.",
      S({"sides": p(INT, "Board sides available for parts (1 or 2)", default=2),
         "acknowledge": p("array", "Findings the USER has reviewed and accepts: [{'id': '<finding id>', 'reason': '...'}]. "
                                   "Only after the user agreed.", items={"type": "object"})}))
def t_design_checks(s: Session, sides: int = 2, acknowledge: List[dict] = None):
    from ..design.checks import board_checks, plan_checks, summarize
    s.need_project()
    plan = s.plan()
    if acknowledge:
        for a in acknowledge:
            if a.get("id") and a.get("reason"):
                plan.decisions.append(f"ACK {a['id']}: {a['reason']}")
        s.save_plan(plan)
    found = plan_checks(plan, s.pins_of, s.index.get_footprint, _board_area(s, plan), sides)
    board_note = "no board yet (press F8 in KiCad to create it)"
    if s.pcb_path and os.path.exists(s.pcb_path):
        found += board_checks(s.board(), plan, s.pins_of)
        board_note = "board checked"
    found, acked = _split_acked(plan, found)
    order = {"error": 0, "warning": 1, "info": 2}
    found.sort(key=lambda f: order[f["severity"]])
    return {"summary": summarize(found), "board": board_note, "findings": found,
            "acknowledged": acked}


def _split_acked(plan, found):
    acked_ids = {d.split(":", 1)[0][4:].strip() for d in plan.decisions if d.startswith("ACK ")}
    keep, acked = [], []
    for f in found:
        f["id"] = f"{f['rule']}:{'+'.join(sorted(f['refs'])[:6])}"
        (acked if f["id"] in acked_ids else keep).append(f)
    return keep, [f["id"] for f in acked]


@tool("next_step", "What to do next in this project, as ONE concrete action (with the exact tool call when there is one) "
      "plus a checklist of the whole flow. Call it whenever you are unsure what comes next, and after every step.", S({}))
def t_next_step(s: Session):
    return next_step(s)


def next_step(s: Session) -> Dict:
    steps: List[Dict] = []
    action: Optional[Dict] = None

    def step(name, done, detail=""):
        steps.append({"step": name, "done": bool(done), **({"detail": detail} if detail else {})})

    def act(why, tool=None, args=None, user=None):
        nonlocal action
        if action is None:
            action = {"why": why}
            if tool:
                action["tool"] = tool
                action["args"] = args or {}
            if user:
                action["ask_user_to"] = user

    if not s.project:
        return {"stage": "no project", "next_action": {"why": "Nothing is open.", "tool": "find_projects",
                                                       "args": {}, "then": "open_project or create_project"}}
    plan = s.plan()
    step("Requirements recorded", bool(plan.requirements), "input, rails, size, interfaces")
    if not plan.requirements:
        act("Record what the board must do before choosing parts.", "plan_set_info",
            {"requirements": {"input": "…", "rails": "…", "size": "WxH mm", "interfaces": "…"}},
            user="confirm the requirements (input voltage, size, interfaces, currents)")
    step("Parts and nets planned", bool(plan.components), f"{len(plan.components)} parts, {len(plan.nets)} nets")
    if not plan.components:
        act("Build the circuit from pre-verified blocks first; add single parts only for what no block covers.",
            "list_blocks", {})
    rv = t_plan_review(s) if plan.components else {"errors": [], "warnings": []}
    step("Plan review clean", plan.components and not rv["errors"],
         f"{len(rv['errors'])} errors, {len(rv['warnings'])} warnings")
    if plan.components and rv["errors"]:
        act(f"Fix this plan error first: {rv['errors'][0]}", None, None)
    sch_exists = os.path.exists(s.sch_path)
    v = None
    if sch_exists and plan.components:
        from ..design.verify import DesignState
        try:
            v = DesignState(plan, s.hierarchy()).verify()
        except Exception as e:  # noqa
            v = None
            act(f"The schematic could not be read ({e}).")
    not_placed = (v or {}).get("not_placed", [c.ref for c in plan.components])
    step("Symbols placed", plan.components and not not_placed, f"{len(not_placed)} not placed" if not_placed else "")
    if plan.components and not_placed:
        blocks = sorted({c.block for c in plan.components if c.ref in not_placed and c.block})
        args = {"block": blocks[0], "mode": "clipboard"} if blocks else {"refs": not_placed[:30], "mode": "clipboard"}
        act(f"Place the remaining symbols ({len(not_placed)}). Use mode='file' if KiCad's schematic editor is closed.",
            "place_parts", args)
    if v:
        pct = v["progress_percent"]
        step("Schematic wired and verified", pct == 100 and not v["errors"],
             f"{pct} % of {v['connections_planned']} connections, {len(v['errors'])} errors")
        if v["errors"]:
            act(f"Drawing error: {v['errors'][0]['message']}", user="fix it in the schematic, save, then say 'verify'")
        elif v["drawing_problems"]:
            act(f"Drawing problem: {v['drawing_problems'][0]['message']}", user="fix it, save, then say 'verify'")
        elif pct < 100:
            todo = next((n for n in v["nets"] if n["status"] != "complete"), None)
            act(f"{pct} % wired. Next net: {todo['net'] if todo else '?'}", "wiring_guide",
                {"net": "^" + re.escape(todo["net"]) + "$"} if todo else {},
                user="draw the wires listed by wiring_guide, save, then say 'verify'")
    board_exists = os.path.exists(s.pcb_path)
    step("PCB created from schematic (F8)", board_exists)
    if not board_exists:
        act("The board file doesn't exist yet.", user="open the PCB editor and press F8 (Update PCB from Schematic), "
                                                     "draw the board outline on Edge.Cuts, save")
    if board_exists and action is None:
        b = s.board()
        x0, y0, x1, y1 = b.board_bbox()
        has_outline = bool(b.outline)
        step("Board outline drawn", has_outline)
        if not has_outline:
            act("No board outline.", user="draw the outline on Edge.Cuts (or tell me the size and I'll add it)")
        refs = {f.ref for f in b.footprints}
        missing = [c.ref for c in plan.components if c.ref not in refs]
        step("All parts on the board", not missing, f"missing: {', '.join(missing[:10])}" if missing else "")
        if missing:
            act(f"{len(missing)} parts are in the plan but not on the board.", user="press F8 again in the PCB editor")
        off = [f.ref for f in b.footprints if not (x0 <= f.x <= x1 and y0 <= f.y <= y1)]
        step("Parts placed inside the outline", has_outline and not off, f"{len(off)} outside" if off else "")
        if off and has_outline:
            big = [r for r in off if not re.match(r"^(C|R|L|FB|D|LED)\d", r)]
            if big:
                act(f"Place the main parts first ({', '.join(big[:12])}): connectors on edges, then ICs by the plan's "
                    "layout notes.", "move_footprints", {"moves": [{"ref": big[0], "x_mm": "…", "y_mm": "…"}]},
                    user="place the ICs and connectors (or agree positions with me)")
            else:
                act("Put the passives next to the pins they serve.", "placement_suggestions", {},
                    user=None)
        if has_outline and not off:
            sug = placement_suggestions_fn(s)
            step("No courtyard overlaps", not sug["courtyard_overlaps"], ", ".join(sug["courtyard_overlaps"][:5]))
            if sug["courtyard_overlaps"]:
                act(f"Overlapping parts: {sug['courtyard_overlaps'][0]}", "placement_suggestions", {})
        from ..design.checks import board_checks, plan_checks
        dc, _ = _split_acked(plan, [f for f in plan_checks(plan, s.pins_of, s.index.get_footprint, _board_area(s, plan))
                                    + board_checks(b, plan) if f["severity"] != "info"])
        step("Design checks clean", not dc, f"{len(dc)} findings" if dc else "")
        if dc:
            act(f"Design check: {dc[0]['message']}", "design_checks", {},
                user=f"fix it, or accept it with a reason (design_checks acknowledge=[{{'id': '{dc[0]['id']}', "
                     "'reason': '…'}])")
        rs = b.routing_status()
        step("Routed", rs.get("unrouted_connections_approx", 1) == 0, f"≈{rs.get('percent_routed_approx')} %")
        if rs.get("unrouted_connections_approx", 1):
            act("Route critical nets by hand first (power loops, USB, clocks, sensor buses), lock them, then autoroute "
                "the rest.", "autoroute", {"time_limit_min": 5}, user="route the critical nets")
        step("DRC clean", False, "run DRC after routing")
        act("Run DRC and fix what it reports.", "run_drc", {})
    stage = next((st["step"] for st in steps if not st["done"]), "done")
    return {"stage": stage, "next_action": action or {"why": "Everything checks out.", "tool": "export_fabrication",
                                                      "args": {}}, "checklist": steps}


def placement_suggestions_fn(s: Session) -> Dict:
    from ..pcb.assist import placement_suggestions
    return placement_suggestions(s.board(), s.plan())


@tool("system_create", "Start a multi-board system (e.g. a printer: controller, engine, scanner, panel, PSU boards). "
      "Creates <folder>/system.json.", S({"folder": p(STR, "Folder for system.json"), "name": p(STR, "System name")},
                                          ["folder", "name"]), writes=True)
def t_system_create(s: Session, folder: str, name: str):
    from ..design import system
    return system.create(os.path.abspath(folder), name) | {"file": os.path.join(os.path.abspath(folder), system.SYSTEM_FILE)}


@tool("system_add_board", "Add a board (a KiCad project) to a system.",
      S({"folder": p(STR, "System folder"), "name": p(STR, "Short board name, e.g. main, engine, psu"),
         "project": p(STR, "Path to the board's .kicad_pro or its folder (relative to the system folder or absolute)")},
        ["folder", "name", "project"]), writes=True)
def t_system_add_board(s: Session, folder: str, name: str, project: str):
    from ..design import system
    d = system.load(folder)
    d["boards"][name] = project
    system.save(folder, d)
    return {"boards": d["boards"]}


@tool("system_add_harness", "Declare a cable between two boards' connectors. mapping: 'straight' (pin n ↔ pin n), "
      "'reversed', or an explicit {'1': '4', ...}. pin_current_a is the connector's per-pin rating.",
      S({"folder": p(STR, "System folder"), "a_board": p(STR, "Board name"), "a_ref": p(STR, "Connector ref on board a"),
         "b_board": p(STR, "Board name"), "b_ref": p(STR, "Connector ref on board b"),
         "mapping": {"description": "'straight' | 'reversed' | {pin_a: pin_b}"}, "pin_current_a": p(NUM, "Per-pin rating", default=1.0),
         "id": p(STR, "Harness id, e.g. H1"), "cable": p(STR, "Cable description")},
        ["folder", "a_board", "a_ref", "b_board", "b_ref"]), writes=True)
def t_system_add_harness(s: Session, folder: str, a_board: str, a_ref: str, b_board: str, b_ref: str,
                         mapping="straight", pin_current_a: float = 1.0, id: str = "", cable: str = ""):
    from ..design import system
    d = system.load(folder)
    h = {"id": id or f"H{len(d['harnesses']) + 1}", "a": {"board": a_board, "ref": a_ref}, "b": {"board": b_board, "ref": b_ref},
         "mapping": mapping or "straight", "pin_current_a": pin_current_a, "cable": cable}
    d["harnesses"] = [x for x in d["harnesses"] if x.get("id") != h["id"]] + [h]
    system.save(folder, d)
    return {"harness": h}


@tool("system_add_supply", "Declare which board supplies a rail and how much current it can deliver.",
      S({"folder": p(STR, "System folder"), "board": p(STR, "Board name"), "net": p(STR, "Rail net on that board"),
         "capacity_a": p(NUM, "Maximum current"),
         "local_load_a": p(NUM, "Current the supplying board itself draws from this rail (default: the net's current_a)")},
        ["folder", "board", "net", "capacity_a"]), writes=True)
def t_system_add_supply(s: Session, folder: str, board: str, net: str, capacity_a: float, local_load_a: float = None):
    from ..design import system
    d = system.load(folder)
    d["supplies"] = [x for x in d["supplies"] if not (x["board"] == board and x["net"] == net)] + \
        [{"board": board, "net": net, "capacity_a": capacity_a,
          **({"local_load_a": local_load_a} if local_load_a is not None else {})}]
    system.save(folder, d)
    return {"supplies": d["supplies"]}


@tool("system_check", "Check a multi-board system: every harness pin pair (ground/power/voltage/TX-RX/driver conflicts, "
      "open pins, pin-count, per-pin current) and supply capacity across boards. Returns findings and a pin table.",
      S({"folder": p(STR, "System folder")}, ["folder"]))
def t_system_check(s: Session, folder: str):
    from ..design import system
    r = system.check(os.path.abspath(folder), s.pins_of)
    r["pins"] = r["pins"][:200]
    return r


@tool("plan_import_schematic", "Create a plan from the already-drawn schematic (for existing projects), so you can reason "
      "about it, extend it and verify future edits. Overwrites the current plan (history is kept).",
      S({"confirm": p(BOOL, "Must be true", default=False)}, ["confirm"]), writes=True)
def t_plan_import(s: Session, confirm: bool = False):
    if not confirm:
        raise UserError("Pass confirm=true to replace the current plan with one captured from the schematic.")
    from ..design.review import plan_from_schematic
    plan = plan_from_schematic(s.hierarchy())
    s.save_plan(plan)
    return {"components": len(plan.components), "nets": len(plan.nets), "blocks": [b.id for b in plan.blocks]}


@tool("place_parts", "Place planned parts into the schematic — symbols only, never wires. mode='clipboard' (recommended "
      "while the schematic is open in KiCad: user presses Ctrl+V to drop the group) or mode='file' (edits the .kicad_sch; "
      "KiCad must be closed or reverted). Parts are placed near related parts, grid-aligned, with value and footprint set. "
      "labels=true also drops net labels exactly on each pin end (a guaranteed-correct connection) — offer it for big "
      "ICs (MCU/FPGA buses) but default to letting the user wire.",
      S({"refs": p("array", "References to place (default: all unplaced in the block/plan)", items={"type": STR}),
         "block": p(STR, "Place a whole block"), "mode": p(STR, "clipboard | file", default="clipboard"),
         "labels": p(BOOL, "Also add net labels on pin ends", default=False),
         "sheet_file": p(STR, "Target sheet file (default root schematic)")}), writes=True)
def t_place(s: Session, refs: List[str] = None, block: str = "", mode: str = "clipboard", labels: bool = False,
            sheet_file: str = ""):
    from ..design.sch_writer import Placement, SchematicPlacer, SymbolSource
    plan = s.plan()
    placer = SchematicPlacer(os.path.join(s.project_dir, sheet_file) if sheet_file else s.sch_path,
                             SymbolSource(s.index), s.sch_path)
    todo = [c for c in plan.components if (not refs or c.ref in refs) and (not block or c.block == block)]
    already = [c.ref for c in todo if c.ref in placer.existing_refs]
    todo = [c for c in todo if c.ref not in placer.existing_refs]
    if not todo:
        return {"message": "Nothing to place — all selected parts are already in the schematic.", "already_placed": already}
    owner = plan.node_net()
    pin_nets: Dict[str, Dict[str, str]] = {}
    for node, net in owner.items():
        r, pn = node.split(".", 1)
        pin_nets.setdefault(r, {})[pn] = net
    # order: ICs first, then connectors, then passives — passives land near the first IC they connect to
    def prio(c):
        return (0 if re.match(r"^(U|IC)", c.ref) else 2 if re.match(r"^(J|P|CN)", c.ref) else 1, _nat(c.ref))
    todo.sort(key=prio)
    items = [Placement(c.ref, c.lib_id, c.value, c.footprint, 0, 0, fields=c.fields or None,
                       unit=0 if c.unit_count > 1 else 1, dnp=c.dnp) for c in todo]
    # nets that reach parts outside this block (or are rails) must be global labels to join across sheets
    block_of = {c.ref: c.block for c in plan.components}
    global_nets = set()
    for n in plan.nets:
        refs_in = {nd.split(".", 1)[0] for nd in n.nodes}
        if len({block_of.get(r) for r in refs_in}) > 1:
            global_nets.add(n.name)
    res = placer.place(items, mode=mode, labels=labels, pin_nets=pin_nets, global_nets=global_nets)
    if mode == "clipboard" and res.get("clipboard_text"):
        try:
            from ..integrations.clipboard import set_clipboard
            res["clipboard"] = f"copied ({set_clipboard(res['clipboard_text'])})"
            res.pop("clipboard_text")
        except Exception as e:  # noqa
            res["clipboard"] = f"could not access clipboard here ({e}); text included"
    for pl in res.get("placed", []):
        pl.pop("pins", None)
    return res


@tool("wiring_guide", "Step-by-step wiring instructions for the user, per net: shortest wire order (minimum spanning tree "
      "over pin positions), power symbols for rails/ground, labels for far-apart pins, and which steps are already done.",
      S({"block": p(STR, "Only this block"), "net": p(STR, "Regex on net names")}))
def t_wiring(s: Session, block: str = "", net: str = ""):
    from ..design.verify import DesignState
    st = DesignState(s.plan(), s.hierarchy())

    def power_symbol(name):
        r = s.index.db.execute("SELECT lib_id FROM symbols WHERE power=1 AND (name=? OR value=?) ORDER BY lib='power' DESC LIMIT 1",
                               (name, name)).fetchone()
        return r["lib_id"] if r else None
    return st.wiring_guide(block or None, net or None, power_symbol=power_symbol)


@tool("verify_schematic", "Compare the hand-drawn schematic with the plan: progress %, missing connections, shorts between "
      "planned nets, unplanned connections, wrong values/footprints, plus ghost wires and other drawing problems.", S({}))
def t_verify(s: Session):
    from ..design.verify import DesignState
    st = DesignState(s.plan(), s.hierarchy())
    r = st.verify()
    r["nets"] = [n for n in r["nets"] if n["status"] != "complete"][:80] + \
                [{"complete": [n["net"] for n in r["nets"] if n["status"] == "complete"]}]
    return r


@tool("sync_fields_from_plan", "Write the plan's values, footprints and extra fields (MPN, LCSC, voltage…) into the symbols "
      "already drawn in the schematic — e.g. after the user placed parts by hand. The schematic must be closed in KiCad "
      "(or reverted afterwards).", S({"footprints": p(BOOL, "Update footprints", default=True),
                                     "values": p(BOOL, "Update values", default=True),
                                     "extra_fields": p(BOOL, "Add/update MPN, LCSC and other fields", default=True)}), writes=True)
def t_sync(s: Session, footprints: bool = True, values: bool = True, extra_fields: bool = True):
    from ..design.sch_writer import lock_file_for, sync_fields
    fields = tuple(x for x, on in (("Value", values), ("Footprint", footprints)) if on)
    res = sync_fields(s.hierarchy(), s.plan(), fields, extra_fields)
    if lock_file_for(s.sch_path):
        res["warning"] = "The schematic is open in KiCad: close it WITHOUT saving and reopen, or your KiCad session will overwrite these edits."
    return res


@tool("export_jlcpcb", "Create JLCPCB-style assembly files: BOM (Comment, Designator, Footprint, LCSC Part #) from the "
      "schematic and CPL / pick-and-place (Designator, Mid X, Mid Y, Layer, Rotation) from the board.",
      S({"out_dir": p(STR, "Output folder (default <project>/fab/jlcpcb)")}), writes=True)
def t_jlc(s: Session, out_dir: str = ""):
    import csv
    from collections import defaultdict
    out_dir = out_dir or os.path.join(s.project_dir, "fab", "jlcpcb")
    os.makedirs(out_dir, exist_ok=True)
    comps = s.hierarchy().components()
    groups = defaultdict(list)
    missing_lcsc = []
    for ref, c in comps.items():
        if c.get("dnp") or not c.get("in_bom", True):
            continue
        f = c.get("fields", {})
        lcsc = f.get("LCSC") or f.get("LCSC Part") or f.get("LCSC Part #") or f.get("JLCPCB Part #") or ""
        if not lcsc:
            missing_lcsc.append(ref)
        fp = c["footprint"].split(":")[-1]
        groups[(c["value"], fp, lcsc)].append(ref)
    bom = os.path.join(out_dir, f"{s.project_name}_BOM.csv")
    with open(bom, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fp, lcsc), refs in sorted(groups.items(), key=lambda kv: _nat(kv[1][0])):
            w.writerow([val, ",".join(sorted(refs, key=_nat)), fp, lcsc])
    out = {"bom": bom, "bom_lines": len(groups), "parts_without_LCSC_number": sorted(missing_lcsc, key=_nat)[:80]}
    if os.path.exists(s.pcb_path):
        b = s.board()
        cpl = os.path.join(out_dir, f"{s.project_name}_CPL.csv")
        with open(cpl, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
            for f in sorted(b.footprints, key=lambda f: _nat(f.ref)):
                if f.ref.startswith("#") or f.dnp or not f.pads:
                    continue
                w.writerow([f.ref, f"{f.x:.4f}mm", f"{-f.y:.4f}mm", "Top" if f.layer.startswith("F") else "Bottom",
                            f"{f.angle % 360:.0f}"])
        out["cpl"] = cpl
        out["note"] = ("CPL uses footprint origins (Y flipped to JLC's convention). Check rotations in JLC's preview: some "
                       "library footprints need a per-part rotation offset.")
    return out


@tool("export_plan_netlist", "Write the plan as a KiCad netlist (.net) so the PCB can be started (File → Import → Netlist) "
      "even before the schematic drawing is finished.", S({}), writes=True)
def t_plan_netlist(s: Session):
    from ..design.netlist import plan_to_kicad_netlist
    path = os.path.join(s.project_dir, ".rlpcb", "plan.net")
    plan_to_kicad_netlist(s.plan(), path, s.pins_of)
    return {"netlist": path}


# ------------------------------------------------------------------------------- PCB
@tool("board_overview", "PCB summary: size, layers, stackup, footprint counts, tracks/vias/zones, approximate routing progress.", S({}))
def t_board(s: Session):
    return s.board().overview()


@tool("list_footprints", "Footprints on the board with position (mm), rotation, side and size. Regex filter on reference/value.",
      S({"filter": p(STR, "Regex")}))
def t_list_fps(s: Session, filter: str = ""):
    b = s.board()
    rx = re.compile(filter, re.I) if filter else None
    rows = [f.to_dict() for f in b.footprints if not rx or rx.search(f.ref) or rx.search(f.value)]
    return {"count": len(rows), "footprints": sorted(rows, key=lambda r: _nat(r["ref"]))[:500]}


@tool("advise_stackup", "Recommend layer count, layer order and fab class from design characteristics.",
      S({"max_pins_bga": p(INT, "Largest BGA ball count"), "bga_pitch_mm": p(NUM, "Finest BGA pitch"),
         "high_speed": p("array", "Interfaces: USB2 USB3 ETH100 ETH1G PCIE3 PCIE4 DDR3 DDR4 LPDDR4 HDMI MIPI LVDS CAN RS485",
                         items={"type": STR}),
         "power_rails": p(INT, "Number of distinct supply rails"), "max_current_a": p(NUM, "Highest rail current"),
         "board_area_cm2": p(NUM, "Board area"), "component_count": p(INT, "Parts"), "mains_or_hv": p(BOOL, "Mains / >60 V"),
         "rf": p(BOOL, "RF / antennas")}))
def t_stackup(s: Session, **kw):
    from ..pcb.assist import advise_stackup
    return advise_stackup(**kw)


@tool("setup_netclasses", "Derive net classes (Power, HighCurrent, Diff90/100, HighSpeed, HighVoltage, Analog, RF50) from "
      "the plan's net annotations and write them into the .kicad_pro. Set apply=false to preview.",
      S({"apply": p(BOOL, "Write to the project", default=False),
         "overrides": p("object", "Per-class overrides, e.g. {'Power': {'track_width': 0.8}}")}), writes=True)
def t_netclasses(s: Session, apply: bool = False, overrides: dict = None):
    from ..pcb.assist import NETCLASS_DEFAULTS, apply_netclasses, current_class_widths, netclasses_from_plan
    plan = s.plan()
    a = netclasses_from_plan(plan)
    sized = current_class_widths(plan)              # IPC-2221 widths from the plan's currents
    merged = {k: dict(v) for k, v in sized.items()}
    for k, v in (overrides or {}).items():
        merged.setdefault(k, {}).update(v)
    if not apply:
        return {"preview": a, "class_parameters_mm": {k: dict(NETCLASS_DEFAULTS[k], **merged.get(k, {})) for k in a},
                "sized_by_current": sized}
    return apply_netclasses(s.project, a, merged)


@tool("add_design_rules", "Append custom DRC rules to <project>.kicad_dru. Give complete (rule ...) expressions in KiCad "
      "custom-rule syntax; they are syntax-checked first.",
      S({"rules": p("array", "Rule texts", items={"type": STR})}, ["rules"]), writes=True)
def t_rules(s: Session, rules: List[str]):
    from ..pcb.assist import write_custom_rules
    return write_custom_rules(s.project_dir, s.project_name, rules)


@tool("placement_suggestions", "Concrete placement advice for the board: target coordinates for decoupling capacitors "
      "next to the IC pins they serve, functional grouping, connectors to edges, crystals near their IC, courtyard overlaps.", S({}))
def t_place_sugg(s: Session):
    from ..pcb.assist import placement_suggestions
    return placement_suggestions(s.board(), s.plan())


@tool("move_footprints", "Move/rotate footprints. method='live' uses the KiCad API (board open, undoable), 'file' edits the "
      ".kicad_pcb (board must be closed), 'auto' tries live then file.",
      S({"moves": p("array", "Moves", items=S({"ref": p(STR, "Reference"), "x_mm": p(NUM, "X"), "y_mm": p(NUM, "Y"),
                                                 "rotation": p(NUM, "Degrees"), "side": p(STR, "top|bottom")},
                                                ["ref", "x_mm", "y_mm"])),
         "method": p(STR, "auto | live | file", default="auto")}, ["moves"]), writes=True)
def t_move(s: Session, moves: List[dict], method: str = "auto"):
    from ..pcb import live
    from ..pcb.assist import move_footprints_in_file
    if method in ("auto", "live"):
        try:
            return {"method": "live", **live.move_footprints(moves)}
        except live.LiveUnavailable as e:
            if method == "live":
                raise UserError(str(e))
    return {"method": "file", **move_footprints_in_file(s.pcb_path, moves)}


@tool("run_drc", "Run KiCad DRC (kicad-cli, KiCad 8+) incl. schematic parity and unconnected items; summarised by type.",
      S({"refill_zones": p(BOOL, "Refill zones first", default=True)}))
def t_drc(s: Session, refill_zones: bool = True):
    from ..kicad import cli
    return cli.drc(s.pcb_path, True, refill_zones)


@tool("render_pcb", "Render board layers to PNG so you can look at placement/routing.",
      S({"layers": p(STR, "Comma list", default="F.Cu,B.Cu,F.SilkS,Edge.Cuts")}))
def t_render_pcb(s: Session, layers: str = "F.Cu,B.Cu,F.SilkS,Edge.Cuts"):
    from ..kicad import cli
    svg = cli.export_pcb_svg(s.pcb_path, layers)
    return {"image_paths": [_render_svg_to_png(svg, 2000)]}


@tool("autoroute", "Autoroute the board with Freerouting (needs Java 21+). Writes <name>.routed.kicad_pcb — the original "
      "is untouched. Route critical nets by hand first and lock them.",
      S({"max_passes": p(INT, "Router passes (Freerouting 1.x)", default=100),
         "time_limit_min": p(NUM, "Stop and save after this many minutes (Freerouting 2.x)", default=10)}), writes=True)
def t_autoroute(s: Session, max_passes: int = 100, time_limit_min: float = 10):
    from ..pcb.autoroute import autoroute
    return autoroute(s.pcb_path, max_passes, time_limit_min)


@tool("live_status", "Is KiCad's IPC API reachable (KiCad 9+, Preferences → Plugins → Enable API)? Which board is open?", S({}))
def t_live_status(s: Session):
    from ..pcb import live
    return live.status()


@tool("highlight", "Select/highlight parts in the open PCB editor (or schematic when the API supports it) so the user can find them.",
      S({"refs": p("array", "References", items={"type": STR}), "editor": p(STR, "pcb | schematic", default="pcb")}, ["refs"]))
def t_highlight(s: Session, refs: List[str], editor: str = "pcb"):
    from ..pcb import live
    return live.select(refs, editor)


@tool("live_selection", "What is currently selected in the open PCB editor (needs the KiCad API). Use when the user says "
      "'this part', 'these tracks', 'what is this?'.", S({}))
def t_live_sel(s: Session):
    from ..pcb import live
    return live.selection()


@tool("add_tracks_live", "Draw copper tracks in the open PCB editor through the KiCad API (one undo step). Use for simple, "
      "explicitly agreed routes (short power stubs, fan-out); prefer guiding the user for critical routing.",
      S({"segments": p("array", "Tracks", items=S({"net": p(STR, "Net"), "layer": p(STR, "F.Cu/B.Cu/In1.Cu..."),
                                                    "width_mm": p(NUM, "Width"), "points": p("array", "[[x,y],...] mm",
                                                                                              items={"type": "array"})},
                                                   ["net", "points"])),
         "vias": p("array", "Vias", items=S({"net": p(STR, "Net"), "x_mm": p(NUM, "X"), "y_mm": p(NUM, "Y"),
                                              "size_mm": p(NUM, "Diameter"), "drill_mm": p(NUM, "Drill")},
                                             ["net", "x_mm", "y_mm"]))}), writes=True)
def t_tracks(s: Session, segments: List[dict] = None, vias: List[dict] = None):
    from ..pcb import live
    out = {}
    if segments:
        out.update(live.add_tracks(segments))
    if vias:
        out.update(live.add_vias(vias))
    return out


@tool("finish_routing", "Close the connections an autorouter left open, using KiCad's own geometry and DRC: plane "
      "stitching (stub + via to GND/+3V3 planes), a 4-layer grid router with vias, rip-up-and-retry, and negotiated "
      "congestion routing for knots. Reads the autorouted copy if present and writes <name>.finished.kicad_pcb; the "
      "original board is not touched. planes: {'GND': ['In1.Cu','B.Cu'], '+3V3': ['In2.Cu']}.",
      S({"planes": {"type": "object", "description": "Plane net -> layers"},
         "source": p(STR, "Board to finish (default: <name>.routed.kicad_pcb, else the board)")}), writes=True)
def t_finish(s: Session, planes: Dict = None, source: str = ""):
    import shutil
    import subprocess
    import sys
    from ..kicad.paths import kicad_python
    base = os.path.splitext(s.pcb_path)[0]
    src = source or (base + ".routed.kicad_pcb" if os.path.exists(base + ".routed.kicad_pcb") else s.pcb_path)
    out = base + ".finished.kicad_pcb"
    # netclasses live in the .kicad_pro next to the board: give the finished copy the same project settings
    for f in (src, out):
        pro = os.path.splitext(f)[0] + ".kicad_pro"
        if f != s.pcb_path and not os.path.exists(pro):
            shutil.copy(base + ".kicad_pro", pro)
    planes = planes or {"GND": ["In1.Cu", "B.Cu"], "+3V3": ["In2.Cu"]}
    py = kicad_python() or sys.executable
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = [py, "-m", "rlpcb.pcb.finish", src, out, base + ".finish_drc.rpt", "--planes"] + \
        [f"{n}:{','.join(ls)}" for n, ls in planes.items()]
    r = subprocess.run(args, capture_output=True, text=True, timeout=3600, env={**os.environ, "PYTHONPATH": root})
    tail = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "swig/python" not in l)[-4000:]
    return {"finished": out if os.path.exists(out) else None, "log": tail,
            "next": "open the .finished board in KiCad, review, then rename it to the main board or run DRC/export"}


@tool("widen_power_tracks", "Widen the tracks of nets that carry current (the plan's current_a) towards the width "
      "IPC-2221 asks for (10 °C rise), as far as KiCad's DRC allows: each segment keeps the widest width that passes, "
      "or its old width. Writes <name>.widened.kicad_pcb unless in_place=true (board closed in KiCad).",
      S({"nets": p("array", "Nets to widen (default: every net with a current in the plan)", items={"type": STR}),
         "in_place": p(BOOL, "Overwrite the board instead of writing a copy", default=False)}), writes=True)
def t_widen(s: Session, nets: List[str] = None, in_place: bool = False):
    import subprocess
    import sys
    from ..kicad.paths import kicad_python
    from ..pcb.ampacity import width_for
    from ..pcb.board import Board
    plan = s.plan()
    b = Board(s.pcb_path)
    board_nets = {t.net for t in b.tracks}
    targets = {}
    for n in plan.nets:
        if not n.current_a or (nets and n.name not in nets):
            continue
        if n.name.upper() in ("GND", "GNDA", "AGND", "PGND"):
            continue
        full = next((x for x in board_nets if x == n.name or x.split("/")[-1] == n.name), None)
        if not full:
            continue
        w10 = round(width_for(n.current_a, 10) + 0.049, 1)
        ws = sorted({w for w in (w10, round(w10 * 0.8, 1), round(w10 * 0.6, 1), round(w10 * 0.45, 1)) if w >= 0.25},
                    reverse=True)
        if ws and any(t.width < ws[0] - 1e-6 for t in b.tracks if t.net == full):
            targets[full] = ws
    if not targets:
        raise UserError("no net with a current in the plan has tracks on the board (set current_a with plan_set_info)")
    base = os.path.splitext(s.pcb_path)[0]
    out = s.pcb_path if in_place else base + ".widened.kicad_pcb"
    if not in_place:
        import shutil
        shutil.copy(base + ".kicad_pro", base + ".widened.kicad_pro")
    py = kicad_python() or sys.executable
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = [py, "-m", "rlpcb.pcb.widen", s.pcb_path, out, base + ".widen_drc.rpt"] + \
        [f"{k}:{','.join(str(w) for w in v)}" for k, v in targets.items()]
    r = subprocess.run(args, capture_output=True, text=True, timeout=1800, env={**os.environ, "PYTHONPATH": root})
    try:
        res = json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        raise UserError("widening failed: " + (r.stderr or r.stdout)[-1500:])
    res["targets_mm"] = targets
    res["next"] = "review_layout (power points) to see what is still narrow; open the board in KiCad to check"
    return res


@tool("mech_export", "Write <project>/<name>.mech.json: the board's mechanical interface for the product around it "
      "(outline, thickness, mounting holes, connectors with the edge they face and their mate type, part heights per "
      "side, mass). RL CAD reads this file; any MCAD user can too.", S({}), writes=True)
def t_mech_export(s: Session):
    from ..pcb.mech import export_mechanical
    m = export_mechanical(s.pcb_path)
    return {"file": m["path"], "change_notice": m.get("_notice"), "outline_mm": m["outline_mm"], "height_mm": m["height_mm"],
            "mounting_holes": m["mounting_holes"], "connectors": [{k: c[k] for k in ("ref", "mate", "edge", "at_mm", "populated")}
                                                                  for c in m["connectors"]]}


@tool("mech_check", "Check the board against the space each product gives it (<project>/enclosure*.json, written by "
      "RL CAD): outline, mounting pattern, part heights above/below, and connectors that must face a reachable edge. "
      "A board used in several products is checked against each.",
      S({"envelope": p(STR, "Path to one envelope file (default: every <project>/enclosure*.json)")}))
def t_mech_check(s: Session, envelope: str = ""):
    import glob as _glob
    from ..pcb.mech import check_envelope, export_mechanical
    files = [envelope] if envelope else sorted(_glob.glob(os.path.join(s.project_dir, "enclosure*.json")))
    if not files or not os.path.exists(files[0]):
        raise UserError(f"{envelope or os.path.join(s.project_dir, 'enclosure.json')} not found. It is written by RL CAD "
                        "(rlcad integrate <design folder>) for each board slot in the product.")
    m = export_mechanical(s.pcb_path)
    results = []
    for fpath in files:
        with open(fpath, encoding="utf-8") as fh:
            env = json.load(fh)
        r = check_envelope(m, env)
        r["envelope"] = fpath
        r["product"] = env.get("product")
        results.append(r)
    r = dict(results[0])
    if len(results) > 1:
        tot = {}
        for x in results:
            for k, v in x["summary"].items():
                tot[k] = tot.get(k, 0) + v
        r = {"summary": tot, "products": results,
             "findings": [dict(f, product=x["product"]) for x in results for f in x["findings"]]}
    from ..pcb.interface import unseen
    todo = unseen(s.project_dir, "pcb")
    if todo:
        r["mechanical_side_changed"] = todo
        r["next"] = "tell the engineer what the mechanical side changed, then interface_changes(mark_seen=true)"
    return r


@tool("export_fabrication", "Generate a manufacturing package (Gerbers, drill, positions, STEP) into a folder via kicad-cli.",
      S({"out_dir": p(STR, "Output folder (default <project>/fab)")}), writes=True)
def t_fab(s: Session, out_dir: str = ""):
    from ..kicad import cli
    return cli.export_fab(s.pcb_path, out_dir or os.path.join(s.project_dir, "fab"))


# ------------------------------------------------------------------------------- knowledge & calculators
@tool("search_knowledge", "Search the engineering knowledge base: RL PCB's design guides (power, decoupling, high-speed, "
      "stackups, BGA/GPU boards, PLC I/O, motor drives, BMS/UPS, EMC, aerospace, printers, DFM, KiCad workflow) plus any "
      "books/datasheets/app notes the user ingested. Cite what you use.",
      S({"query": p(STR, "Question or keywords"), "limit": p(INT, "Results", default=5),
         "source": p(STR, "builtin | user (default both)")}, ["query"]))
def t_kb(s: Session, query: str, limit: int = 5, source: str = None):
    return {"results": s.kb.search(query, limit, source)}


@tool("read_guide", "Read a knowledge-base document (or one section) in full.",
      S({"name": p(STR, "File or title fragment, e.g. 'stackup' or 'power_decoupling'"), "section": p(STR, "Heading fragment")},
        ["name"]))
def t_read_guide(s: Session, name: str, section: str = None):
    return s.kb.read(name, section)


@tool("fetch_datasheet", "Download a part's datasheet (from the symbol's Datasheet field or a URL) into the knowledge "
      "base, then return the pages about the typical application, layout and pin functions. Afterwards use "
      "search_knowledge(source='datasheet') for anything else in it.",
      S({"lib_id": p(STR, "Symbol whose Datasheet field to use"), "url": p(STR, "Direct PDF URL instead"),
         "focus": p(STR, "What to look for", default="typical application layout guidelines pin description")}))
def t_datasheet(s: Session, lib_id: str = "", url: str = "", focus: str = "typical application layout guidelines pin description"):
    from ..knowledge.datasheets import fetch_and_ingest
    if not url:
        sym = s.index.get_symbol(lib_id) if lib_id else None
        url = (sym or {}).get("datasheet", "")
        if not url or url in ("~", ""):
            raise UserError("No datasheet URL on that symbol — pass url= (manufacturer PDF link).")
    return fetch_and_ingest(s.kb, url, focus, name_hint=(lib_id or "").split(":")[-1])


@tool("list_knowledge", "List the documents in the knowledge base.", S({}))
def t_list_kb(s: Session):
    return {"documents": s.kb.list_docs()}


@tool("ingest_documents", "Add a folder of the user's books, datasheets, app notes (PDF/MD/TXT/HTML) to the knowledge base.",
      S({"folder": p(STR, "Folder path")}, ["folder"]))
def t_ingest(s: Session, folder: str):
    return s.kb.ingest_folder(os.path.expanduser(folder))


@tool("calculate", "Engineering calculators. name ∈ trace_width, trace_resistance, via, microstrip, stripline, differential, "
      "solve_width_for_impedance, critical_length, length_match, clearance, nearest_e, divider, led_resistor, rc_filter, "
      "crystal_load_caps, buck, boost, ldo, mosfet_loss, pdn_target_impedance, cap_resonance, shunt, battery_runtime, "
      "thermal_vias, wavelength. Call with name='help' to get every signature.",
      S({"name": p(STR, "Calculator"), "params": p("object", "Keyword parameters")}, ["name"]))
def t_calc(s: Session, name: str, params: dict = None):
    from ..calc import formulas
    if name == "help":
        return formulas.describe()
    return formulas.run(name, **(params or {}))


# ------------------------------------------------------------------------------- corpus
@tool("reference_designs", "How do real open-source designs wire a part? Search the corpus of ingested KiCad projects by "
      "part number/value/symbol and get, per design, each pin's net and neighbouring parts, plus a consensus across designs.",
      S({"part": p(STR, "Part number or value fragment, e.g. 'TPS5430', 'STM32F4', 'DRV8323', 'USB4105'"),
         "limit": p(INT, "Designs", default=6)}, ["part"]))
def t_refdes(s: Session, part: str, limit: int = 6):
    return s.corpus.part_usage(part, limit)


@tool("corpus_ingest", "Grow the reference corpus: a GitHub repo ('owner/name' or URL), a local folder of KiCad projects, "
      "or 'seed' for the curated list of industrial-grade open hardware (Jetson/Kria carriers, VESC, BMS, MPPT, SDR, PnP...).",
      S({"source": p(STR, "owner/repo, URL, folder path or 'seed'")}, ["source"]))
def t_corpus_ingest(s: Session, source: str):
    from ..corpus.corpus import SEED_REPOS
    if source == "seed":
        return {"results": [s.corpus.ingest_github(r) for r, _ in SEED_REPOS]}
    if os.path.isdir(os.path.expanduser(source)):
        return s.corpus.ingest_folder(os.path.expanduser(source))
    return s.corpus.ingest_github(source)


@tool("corpus_search_github", "Search GitHub for repositories with KiCad designs on a topic (e.g. 'BLDC FOC', 'PLC', "
      "'LiFePO4 BMS', 'FPGA carrier'). Then ingest promising ones.",
      S({"query": p(STR, "Topic"), "limit": p(INT, "Results", default=10)}, ["query"]))
def t_gh(s: Session, query: str, limit: int = 10):
    return {"repos": s.corpus.github_search(query, limit)}


@tool("corpus_projects", "List designs in the reference corpus (or details of one, optionally one part).",
      S({"project": p(STR, "Project name fragment"), "ref": p(STR, "Reference in that project")}))
def t_corpus_projects(s: Session, project: str = "", ref: str = ""):
    if project:
        return s.corpus.design_detail(project, ref or None)
    return {"stats": s.corpus.stats(), "projects": s.corpus.list_projects()}


@tool("corpus_import_symbol", "Copy a symbol embedded in a corpus design into the active project's library "
      "(<project>/<project>.kicad_sym). Find ids with search_symbols (fallback list) or corpus search.",
      S({"symbol_id": p(INT, "Id from the corpus symbol search"), "new_name": p(STR, "Optional new name")}, ["symbol_id"]),
      writes=True)
def t_corpus_sym(s: Session, symbol_id: int, new_name: str = None):
    dest = os.path.join(s.project_dir, s.project_name + ".kicad_sym")
    r = s.corpus.export_symbol(symbol_id, dest, new_name)
    if "symbol" in r:
        _ensure_project_lib(s.project_dir, s.project_name, dest)
        s.index.build(extra_symbol_files=[dest])
        r["lib_id"] = f"{s.project_name}:{r['symbol']}"
    return r


def _ensure_project_lib(project_dir, name, lib_path):
    table = os.path.join(project_dir, "sym-lib-table")
    entry = f'  (lib (name "{name}")(type "KiCad")(uri "${{KIPRJMOD}}/{os.path.basename(lib_path)}")(options "")(descr "RL PCB imported symbols"))\n'
    if os.path.exists(table):
        with open(table, encoding="utf-8") as f:
            t = f.read()
        if f'(name "{name}")' in t:
            return
        t = t.rstrip().rstrip(")") + entry + ")\n"
    else:
        t = "(sym_lib_table\n  (version 7)\n" + entry + ")\n"
    with open(table, "w", encoding="utf-8") as f:
        f.write(t)


# =============================================================================== copilot: modes, proposals, journal
def _cp(s: Session, pid: str = ""):
    from .copilot_pcb import copilot_for
    return copilot_for(s, pid)


@tool("copilot_status", "How the engineer wants to work: the autonomy mode (teach / advise / propose / do) for the whole "
      "design and for each scope, pending proposals, the engineer's recent accept/reject reasons, and recent changes. "
      "Read it at the start of a session and whenever you are about to change something.", S({}))
def t_cp_status(s: Session):
    from .copilot import MODE_HELP
    from .copilot_pcb import external_pending
    if not s.project:
        ext = external_pending(s)
        return {"mode": None, "note": "no project open; the mode is set per project", "modes": MODE_HELP,
                "pending_elsewhere": [{"id": x["id"], "action": x["action"], "root": x["root"],
                                       "summary": x["summary"].get("text", "")} for x in ext]}
    st = _cp(s).status()
    ext = external_pending(s)
    if ext:
        st["pending_elsewhere"] = [{"id": x["id"], "action": x["action"], "root": x["root"],
                                    "summary": x["summary"].get("text", "")} for x in ext]
    st["modes"] = MODE_HELP
    st["scopes_known"] = ["project", "plan", "plan:requirements", "block:<id>", "schematic", "library", "board",
                          "board:placement", "board:routing", "board:rules", "decisions", "system"]
    return st


@tool("copilot_mode", "Set the autonomy mode, for the whole design or one scope (e.g. scope='block:power' mode='do', "
      "scope='board:routing' mode='advise'). Modes: teach (explain only), advise (guidelines; engineer edits), propose "
      "(AI prepares changes on a copy; engineer accepts or rejects), do (AI edits directly; undoable). ONLY call this "
      "when the engineer asks for it. mode='inherit' clears a scope's own setting.",
      S({"mode": p(STR, "teach | advise | propose | do | inherit"), "scope": p(STR, "Scope, empty = whole design"),
         "note": p(STR, "Why (kept with the setting)")}, ["mode"]))
def t_cp_mode(s: Session, mode: str, scope: str = "", note: str = ""):
    cp = _cp(s)
    cp.set_mode(mode, scope, note)
    return cp.status()


@tool("proposals", "List proposals (pending by default) with their summaries and check results.",
      S({"status": p(STR, "pending | accepted | rejected | all", default="pending")}))
def t_proposals(s: Session, status: str = "pending"):
    from .copilot_pcb import external_pending
    ps = _cp(s).proposals("" if status == "all" else status) if s.project else []
    if status in ("pending", "all"):
        ps += external_pending(s)
    return {"proposals": [{"id": x["id"], "status": x["status"], "action": x["action"], "args": x["args"],
                           "summary": x["summary"].get("text", ""), "checks": x["summary"].get("checks"),
                           "reason": x.get("note", "")} for x in ps]}


@tool("proposal_show", "One proposal in full: what changes file by file, the check results before/after, what was not "
      "verified, and (render=true) an image of the proposed board.",
      S({"id": p(STR, "Proposal id"), "render": p(BOOL, "Render the proposed board", default=False)}, ["id"]))
def t_proposal_show(s: Session, id: str, render: bool = False):
    cp = _cp(s, id)
    pr = cp.proposal(id)
    out = {k: pr.get(k) for k in ("id", "status", "action", "args", "scopes", "changes", "summary", "assurance",
                                  "rationale", "note")}
    if render:
        work = cp.work_dir(id)
        pcb = os.path.join(work, os.path.basename(s.pcb_path))
        if os.path.exists(pcb):
            from ..kicad import cli
            try:
                out["image_paths"] = [_render_svg_to_png(cli.export_pcb_svg(pcb, "F.Cu,B.Cu,F.SilkS,Edge.Cuts"), 2000)]
            except Exception as e:  # noqa
                out["render_error"] = str(e)
    return out


@tool("proposal_accept", "Apply a proposal to the design. Call ONLY after the engineer has said yes to this proposal in "
      "the conversation. If the board is open in KiCad, the change is replayed through the live API when possible; "
      "otherwise reload the file in KiCad.",
      S({"id": p(STR, "Proposal id"), "note": p(STR, "Engineer's comment"),
         "force": p(BOOL, "Apply even if the files changed since the proposal", default=False)}, ["id"]))
def t_proposal_accept(s: Session, id: str, note: str = "", force: bool = False):
    def replay(pr):
        rp = pr.get("live_replay") or {}
        if not rp:
            return None
        from ..pcb import live
        try:
            if not live.status().get("connected"):
                return None
        except Exception:  # noqa
            return None
        r = TOOL_MAP[rp["tool"]].fn(s, **rp["args"])
        return r if isinstance(r, dict) and r.get("method") == "live" else None
    cp = _cp(s, id)
    r = cp.accept(id, note, force, replay)
    if pr_next := cp.proposal(id).get("next_after_accept"):
        r["next"] = pr_next
    r["reminder"] = ("if KiCad has the changed file open and the change was not applied live, use File → Revert in "
                     "KiCad to load it")
    return r


@tool("proposal_reject", "Discard a proposal. Pass the engineer's reason: it is kept and shown in copilot_status so "
      "later proposals follow this engineer's preferences.",
      S({"id": p(STR, "Proposal id"), "reason": p(STR, "Why the engineer rejected it")}, ["id"]))
def t_proposal_reject(s: Session, id: str, reason: str = ""):
    return _cp(s, id).reject(id, reason)


@tool("undo", "Undo a change made in 'do' mode or an accepted proposal (default: the most recent one). Refuses if a "
      "later change touched the same files, unless force=true.",
      S({"id": p(STR, "Journal id (from design_journal); empty = most recent"),
         "force": p(BOOL, "Restore even if later changes touched the files", default=False)}))
def t_undo(s: Session, id: str = "", force: bool = False):
    return _cp(s).undo(id, force)


@tool("design_journal", "The design's history: who changed what (AI or engineer), in which mode, with the check results "
      "at the time; proposals and their outcomes; mode changes. Use it to brief a colleague or to find a change to undo.",
      S({"limit": p(INT, "Entries", default=30)}))
def t_journal(s: Session, limit: int = 30):
    rows = _cp(s).journal(limit)
    return {"entries": [{k: r.get(k) for k in ("id", "t", "actor", "action", "summary", "scopes", "proposal", "undone",
                                               "note")} for r in rows]}


@tool("assurance_report", "What the checks have verified in this design and what they cannot vouch for: unsourced part "
      "data, missing footprints, unchecked symbols, power nets without currents, and the limits of the method (no EMC, "
      "SI or thermal simulation). Show it to the engineer before fabrication and whenever you made many changes.", S({}))
def t_assurance(s: Session):
    from .copilot_pcb import assurance, findings_of
    f = findings_of(s)
    return assurance(s, {"errors": sum(x["severity"] == "error" for x in f),
                         "warnings": sum(x["severity"] == "warning" for x in f),
                         "first": [x["message"] for x in f[:5]]})


# =============================================================================== kickoff, teaching, interface notices
@tool("kickoff", "Start a new design from an idea in plain words ('a Wi-Fi soil-moisture sensor on a battery'): the "
      "matching product architecture, its functional blocks with typical parts and what to watch in each, which blocks "
      "RL PCB has pre-verified, the questions whose answers change the design, the pitfalls, the layer count, and a "
      "project structure. Read-only: discuss it with the engineer before kickoff_apply.",
      S({"idea": p(STR, "The product idea in the engineer's words"),
         "archetype": p(STR, "Force an archetype (see 'candidates' / 'known_archetypes')")}, ["idea"]))
def t_kickoff(s: Session, idea: str, archetype: str = ""):
    from ..design.kickoff import brief
    return brief(idea, archetype)


@tool("kickoff_apply", "Create the project agreed in kickoff: KiCad project, one schematic sheet per block group, the "
      "plan's blocks (with their purpose and watch-outs) and requirements, docs/requirements.md (open questions) and "
      "docs/decisions.md, a datasheets folder. Subject to the copilot mode.",
      S({"folder": p(STR, "Parent folder"), "name": p(STR, "Project name"), "archetype": p(STR, "From kickoff"),
         "idea": p(STR, "The idea, kept in the requirements doc"),
         "requirements": p("object", "Answers so far, e.g. {\"input\": \"USB 5 V\"}"),
         "blocks": p("array", "Subset of the archetype's block names (default all)", items={"type": "string"})},
        ["folder", "name", "archetype"]), writes=True)
def t_kickoff_apply(s: Session, folder: str, name: str, archetype: str, idea: str = "", requirements: dict = None,
                    blocks: List[str] = None):
    from ..design.kickoff import apply
    r = apply(folder, name, archetype, requirements, idea, blocks)
    if "project" in r:
        s.project = r["project"]
        save_settings({"active_project": s.project})
    return r


@tool("explain_component", "Teach: what a part does in THIS circuit and why it is there (decoupling, pull-up, divider, "
      "catch diode, CC resistor…), what goes wrong without it, what to check, its connections and its block's purpose. "
      "Roles are read from the plan or inferred from the connections (marked as such).",
      S({"ref": p(STR, "Reference, e.g. C14")}, ["ref"]))
def t_explain_component(s: Session, ref: str):
    from ..design.explain import explain_component
    plan = s.plan()
    rows = None
    if not plan.comp(ref):
        try:
            rows = t_comp_conn(s, ref)["pins"]
        except Exception:  # noqa
            raise UserError(f"{ref} is not in the plan or the schematic")
    out = explain_component(plan, ref, rows, s.pins_of)
    try:
        kb = s.kb.search(f"{out['inferred_role']} {out['value']}", 2)
        out["read_more"] = [{"doc": r.get("source") or r.get("doc"), "section": r.get("section"),
                             "text": (r.get("text") or "")[:400]} for r in kb]
    except Exception:  # noqa
        pass
    return out


@tool("explain_net", "Teach: what a net is (power rail, ground, switch node, fast signal, pair), who is on it, and how "
      "to route it and why.", S({"net": p(STR, "Net name (or regex)")}, ["net"]))
def t_explain_net(s: Session, net: str):
    from ..design.explain import explain_net
    try:
        return explain_net(s.plan(), net)
    except ValueError as e:
        raise UserError(str(e))


@tool("interface_changes", "Change notices between this board and the mechanical design (interface_log.json in the "
      "project): what the mechanical side (RL CAD) changed in the space it gives the board since RL PCB last looked, "
      "and what this board changed in its mech.json. mark_seen=true records that you have reviewed the mechanical "
      "side's notices (after running mech_check).",
      S({"mark_seen": p(BOOL, "Mark the mechanical side's notices as reviewed", default=False),
         "result": p(STR, "What mech_check said, stored with the acknowledgement")}))
def t_interface_changes(s: Session, mark_seen: bool = False, result: str = ""):
    from ..pcb.interface import mark_seen as _mark, read_log, unseen
    d = s.project_dir
    todo = unseen(d, "pcb")
    out = {"from_mechanical_unreviewed": todo,
           "from_this_board_awaiting_cad": [e for e in read_log(d)["entries"] if e["from"] == "pcb"
                                            and not e.get("seen_by_other_side")]}
    if mark_seen and todo:
        out["marked_seen"] = _mark(d, "pcb", [e["id"] for e in todo], result)
    if todo and not mark_seen:
        out["next"] = "run mech_check, tell the engineer what changed and whether the board still fits, then call " \
                      "interface_changes(mark_seen=true, result=...)"
    return out


# =============================================================================== layout review
def _board_from(s: Session, which: str):
    from ..pcb.board import Board
    if not which or which == "current":
        return s.board(), "current"
    if which == "routed":
        p_ = os.path.join(s.project_dir, s.project_name + ".routed.kicad_pcb")
        if not os.path.exists(p_):
            raise UserError("no <name>.routed.kicad_pcb; run autoroute first")
        return Board(p_), "routed"
    if os.path.exists(which):
        return Board(which), os.path.basename(which)
    cp = _cp(s)
    try:
        cp.proposal(which)
    except ValueError:
        raise UserError(f"'{which}' is not 'current', 'routed', a .kicad_pcb path or a proposal id")
    p_ = os.path.join(cp.work_dir(which), os.path.basename(s.pcb_path))
    if not os.path.exists(p_):
        raise UserError(f"proposal {which} has no board file (its work copy was removed)")
    return Board(p_), f"proposal {which}"


@tool("review_layout", "Design review of the board like a senior layout engineer: return paths and planes, ground "
      "stitching, differential pairs, fast nets, switch-node size, the buck 'hot loop', ESD placement at connectors, "
      "decoupling, crystal routing, edge clearance, assembly sides. Each point has a level (concern / suggestion / info "
      "/ good), the reason, and whether it is measured or a rule of thumb. Use it to coach, not just to judge.",
      S({"focus": p(STR, "all | placement | routing | emc | power | dfm", default="all"),
         "board": p(STR, "current | routed | <proposal id> | <path>", default="current")}))
def t_review_layout(s: Session, focus: str = "all", board: str = "current"):
    from ..pcb.review import review_layout
    b, label = _board_from(s, board)
    r = review_layout(b, s.plan(), focus)
    r["board"] = label
    return r


@tool("compare_layouts", "Compare two versions of the board (a placement or routing study): unrouted, track length, "
      "vias, ratsnest, pair skew, switch-node length, review concerns — with which is better on each and what each "
      "fixes or breaks. a/b: current | routed | <proposal id> | <path>.",
      S({"a": p(STR, "First layout", default="current"), "b": p(STR, "Second layout")}, ["b"]))
def t_compare_layouts(s: Session, b: str, a: str = "current"):
    from ..pcb.review import compare_layouts
    ba, la = _board_from(s, a)
    bb, lb = _board_from(s, b)
    return compare_layouts(ba, bb, s.plan(), (la, lb))


# =============================================================================== dispatch
TOOL_MAP = {t.name: t for t in TOOLS}


def run_tool(session: Session, name: str, args: Dict[str, Any], actor: str = "ai") -> Dict[str, Any]:
    """Run a tool. Design-changing tools go through the copilot gate (mode, proposals, journal, undo)."""
    t = TOOL_MAP.get(name)
    if t is None:
        return {"error": f"Unknown tool {name}"}
    if t.writes and not session.settings.get("allow_file_writes", True):
        return {"error": "File writes are disabled in RL PCB settings (allow_file_writes=false)."}
    import inspect
    try:
        inspect.signature(t.fn).bind(session, **(args or {}))
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}. Expected: {list(t.schema.get('properties', {}))}"}
    try:
        from .copilot_pcb import gate
        res = gate(session, name, args or {}, t.fn, actor=actor)
        return res if isinstance(res, dict) else {"result": res}
    except UserError as e:
        return {"error": str(e)}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def to_json(obj: Any, limit: int = 60000) -> str:
    s = json.dumps(obj, indent=1, ensure_ascii=False, default=str)
    if len(s) > limit:
        s = s[:limit] + f"\n… (truncated {len(s) - limit} chars — narrow the query)"
    return s
