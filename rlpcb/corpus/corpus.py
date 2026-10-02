"""Reference-design corpus: learn from open-source KiCad projects.

Ingests KiCad projects (local folders, KiCad demos, GitHub repos), computes their
connectivity and stores, for every IC-like part, its *neighbourhood*: what each
pin connects to (passive values, other parts, power nets). The copilot can then
answer "how do other people wire the TPS54331 / STM32G431 / DRV8323?" with real,
cited examples — the tacit industry knowledge that lives inside schematics.

Also harvests embedded symbols (lib_symbols) so parts missing from the stock
libraries can be borrowed from a published design.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from ..config import data_dir, load_settings
from ..kicad.connectivity import Connectivity
from ..kicad.schematic import Hierarchy
from ..kicad.sexpr import dump

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, root TEXT UNIQUE, name TEXT, source TEXT, url TEXT,
  license TEXT, components INTEGER, nets INTEGER, sheets INTEGER, indexed REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS parts(id INTEGER PRIMARY KEY, project_id INTEGER, ref TEXT, lib_id TEXT, value TEXT,
  footprint TEXT, sheet TEXT, pin_count INTEGER, neighborhood TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS parts_fts USING fts5(value, lib_id, footprint, project, tokenize='unicode61 tokenchars ''-_.+''');
CREATE TABLE IF NOT EXISTS csymbols(id INTEGER PRIMARY KEY, project_id INTEGER, lib_id TEXT, sexpr TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS csymbols_fts USING fts5(lib_id, tokenize='unicode61 tokenchars ''-_.+''');
"""

# Curated open-hardware KiCad projects spanning many industries (verified to exist at time of writing).
SEED_REPOS = [
    ("antmicro/jetson-orin-baseboard", "NVIDIA Jetson Orin carrier: PCIe, USB3, Ethernet, power sequencing"),
    ("antmicro/jetson-nano-baseboard", "Jetson Nano carrier board"),
    ("antmicro/kria-k26-devboard", "Xilinx Kria SoM carrier: high-speed I/O"),
    ("antmicro/sdi-mipi-bridge", "SDI to MIPI CSI-2 bridge (FPGA)"),
    ("antmicro/arty-expansion-board", "FPGA expansion board"),
    ("vedderb/bldc-hardware", "VESC motor controller: gate drivers, current sensing, high-current layout"),
    ("LibreSolar/bms-c1", "Li-ion BMS: cell monitoring, balancing, protection MOSFETs"),
    ("LibreSolar/mppt-2420-hc", "MPPT solar charge controller: synchronous buck, high current"),
    ("opulo-inc/lumenpnp", "Pick-and-place machine electronics: steppers, motion, vacuum"),
    ("greatscottgadgets/hackrf", "Software-defined radio: RF front end, clocking, CPLD, MCU"),
    ("greatscottgadgets/cynthion-hardware", "USB analyzer: FPGA, USB PHYs"),
]


def _db():
    d = os.path.join(data_dir(), "corpus")
    os.makedirs(d, exist_ok=True)
    db = sqlite3.connect(os.path.join(d, "corpus.db"), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


class Corpus:
    def __init__(self):
        self.db = _db()
        self.repo_dir = os.path.join(data_dir(), "corpus", "repos")
        os.makedirs(self.repo_dir, exist_ok=True)

    # ------------------------------------------------------------ ingest
    def ingest_folder(self, folder: str, source: str = "local", url: str = "", license: str = "",
                      max_projects: int = 500) -> Dict:
        roots = _find_project_roots(folder)[:max_projects]
        stats = {"projects_found": len(roots), "indexed": 0, "skipped": 0, "failed": 0, "parts": 0, "errors": []}
        for root in roots:
            try:
                n = self.ingest_project(root, source=source, url=url, license=license)
                if n is None:
                    stats["skipped"] += 1
                else:
                    stats["indexed"] += 1
                    stats["parts"] += n
            except Exception as e:  # noqa
                stats["failed"] += 1
                stats["errors"].append(f"{os.path.relpath(root, folder)}: {type(e).__name__}: {str(e)[:120]}")
        self.db.commit()
        return stats

    def ingest_project(self, root_sch: str, source: str = "local", url: str = "", license: str = "",
                       force: bool = False) -> Optional[int]:
        row = self.db.execute("SELECT id, indexed FROM projects WHERE root=?", (root_sch,)).fetchone()
        mtime = os.path.getmtime(root_sch)
        if row and not force and row["indexed"] >= mtime:
            return None
        h = Hierarchy(root_sch)
        conn = Connectivity(h)
        comps = h.components()
        cur = self.db.cursor()
        if row:
            self._delete_project(cur, row["id"])
        name = h.project_name
        cur.execute("INSERT INTO projects(root,name,source,url,license,components,nets,sheets,indexed,summary) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (root_sch, name, source, url, license, len(comps), len(conn.nets), len(h.instances), time.time(),
                     _project_summary(h, comps)))
        pid = cur.lastrowid
        # pin -> net, net -> members
        pin_net = {f"{r}.{p}": n for (r, p), n in conn.pin_net.items()}
        members = defaultdict(list)
        pin_info = {}
        for net in conn.nets.values():
            for p in net.pins:
                members[net.name].append(f"{p.ref}.{p.pin}")
                pin_info[f"{p.ref}.{p.pin}"] = (p.name, p.etype)
        n_parts = 0
        for ref, c in comps.items():
            pins = sorted({k.split(".", 1)[1] for k in pin_net if k.split(".", 1)[0] == ref}, key=_nat)
            if len(pins) < 3 and not re.match(r"^(U|IC|Q|J|P|CN|K|T|Y|X|SW|FB|F)\d", ref):
                continue  # passives: learned through their neighbours
            hood = []
            for pn in pins:
                net = pin_net.get(f"{ref}.{pn}")
                pname, ptype = pin_info.get(f"{ref}.{pn}", ("", ""))
                others = [m for m in members.get(net, []) if m.split(".")[0] != ref]
                desc = []
                for m in others[:12]:
                    oref = m.split(".")[0]
                    oc = comps.get(oref)
                    if oc is None:
                        continue
                    desc.append(f"{oref}({oc['value']})" if _is_passive(oref) else f"{oref}.{m.split('.')[1]}[{oc['value']}]")
                if len(others) > 12:
                    desc.append(f"+{len(others) - 12} more")
                hood.append({"pin": pn, "name": pname, "type": ptype, "net": _short_net(net), "to": desc})
            cur.execute("INSERT INTO parts(project_id,ref,lib_id,value,footprint,sheet,pin_count,neighborhood) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, ref, c["lib_id"], c["value"], c["footprint"], c["sheet"], len(pins), json.dumps(hood)))
            cur.execute("INSERT INTO parts_fts(rowid,value,lib_id,footprint,project) VALUES(?,?,?,?,?)",
                        (cur.lastrowid, _split(c["value"]), _split(c["lib_id"]), c["footprint"], name))
            n_parts += 1
        # embedded symbols
        seen = set()
        for sch in h.files:
            for lid, sym in sch.lib_symbols.items():
                if lid in seen or sym.power or sym.node is None:
                    continue
                seen.add(lid)
                cur.execute("INSERT INTO csymbols(project_id, lib_id, sexpr) VALUES(?,?,?)", (pid, lid, dump(sym.node)))
                cur.execute("INSERT INTO csymbols_fts(rowid, lib_id) VALUES(?,?)", (cur.lastrowid, _split(lid)))
        return n_parts

    def _delete_project(self, cur, pid):
        for r in cur.execute("SELECT id FROM parts WHERE project_id=?", (pid,)).fetchall():
            cur.execute("DELETE FROM parts_fts WHERE rowid=?", (r[0],))
        for r in cur.execute("SELECT id FROM csymbols WHERE project_id=?", (pid,)).fetchall():
            cur.execute("DELETE FROM csymbols_fts WHERE rowid=?", (r[0],))
        cur.execute("DELETE FROM parts WHERE project_id=?", (pid,))
        cur.execute("DELETE FROM csymbols WHERE project_id=?", (pid,))
        cur.execute("DELETE FROM projects WHERE id=?", (pid,))

    def ingest_github(self, repo: str, branch: Optional[str] = None) -> Dict:
        """Shallow-clone a GitHub repo ('owner/name' or URL) and index its KiCad projects."""
        repo = repo.strip()
        m = re.search(r"github\.com[/:]([^/]+/[^/.]+)", repo)
        slug = m.group(1) if m else repo
        dest = os.path.join(self.repo_dir, slug.replace("/", "__"))
        url = f"https://github.com/{slug}.git"
        if not os.path.isdir(dest):
            args = ["git", "clone", "--depth", "1", "--filter=blob:limit=20m"]
            if branch:
                args += ["--branch", branch]
            r = subprocess.run(args + [url, dest], capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                return {"repo": slug, "error": r.stderr.strip()[-400:]}
        else:
            subprocess.run(["git", "-C", dest, "pull", "--depth", "1"], capture_output=True, text=True, timeout=600)
        lic = _detect_license(dest)
        res = self.ingest_folder(dest, source="github", url=f"https://github.com/{slug}", license=lic)
        res["repo"] = slug
        res["license"] = lic
        return res

    def github_search(self, query: str, limit: int = 10) -> List[dict]:
        """Search GitHub repositories likely to contain KiCad designs (unauthenticated: ~10 requests/min)."""
        q = f"{query} kicad in:name,description,readme,topics"
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "per_page": limit})
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "rlpcb"})
        tok = load_settings().get("github_token") or os.environ.get("GITHUB_TOKEN")
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        return [{"repo": it["full_name"], "stars": it["stargazers_count"], "description": it.get("description") or "",
                 "license": (it.get("license") or {}).get("spdx_id"), "updated": it.get("pushed_at")}
                for it in data.get("items", [])]

    # ------------------------------------------------------------ query
    def stats(self) -> Dict:
        return {"projects": self.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "parts": self.db.execute("SELECT COUNT(*) FROM parts").fetchone()[0],
                "embedded_symbols": self.db.execute("SELECT COUNT(*) FROM csymbols").fetchone()[0],
                "sources": [dict(r) for r in self.db.execute("SELECT source, COUNT(*) n FROM projects GROUP BY source")]}

    def list_projects(self, limit: int = 100) -> List[dict]:
        rows = self.db.execute("SELECT id,name,source,url,license,components,nets,sheets,summary FROM projects ORDER BY name LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def part_usage(self, query: str, limit: int = 8, compact: bool = True) -> Dict:
        """How is this part wired in other designs? query: value/part number/lib_id fragment."""
        toks = [t for t in re.findall(r"[A-Za-z0-9_.+\-]+", query) if len(t) > 1]
        if not toks:
            return {"matches": []}
        fts = " AND ".join(f'"{t}"*' for t in toks)
        rows = self.db.execute(
            "SELECT p.*, pr.name project, pr.url, pr.license, pr.root FROM parts_fts JOIN parts p ON p.id = parts_fts.rowid "
            "JOIN projects pr ON pr.id = p.project_id WHERE parts_fts MATCH ? ORDER BY bm25(parts_fts) LIMIT ?",
            (fts, limit * 4)).fetchall()
        out = []
        seen_proj = Counter()
        for r in rows:
            if seen_proj[r["project"]] >= 2:
                continue
            seen_proj[r["project"]] += 1
            hood = json.loads(r["neighborhood"])
            item = {"project": r["project"], "source": r["url"] or r["root"], "license": r["license"], "ref": r["ref"],
                    "value": r["value"], "symbol": r["lib_id"], "footprint": r["footprint"], "sheet": r["sheet"]}
            if compact:
                item["pins"] = [f"{h['pin']} {h['name']}: {h['net']}" + (f" → {', '.join(h['to'][:6])}" if h["to"] else " (unconnected)")
                                for h in hood]
            else:
                item["pins"] = hood
            out.append(item)
            if len(out) >= limit:
                break
        consensus = self._consensus(out) if len(out) >= 2 else None
        return {"query": query, "matches": out, "consensus": consensus,
                "note": "Real designs, not verified to be correct — cross-check against the datasheet's typical application."}

    @staticmethod
    def _consensus(matches: List[dict]) -> Dict[str, List[str]]:
        """For each pin name, the most common neighbour types (e.g. 'VIN': ['C 10u', 'C 100n'])."""
        by_pin = defaultdict(Counter)
        for m in matches:
            for line in m["pins"]:
                head, _, rest = line.partition(": ")
                pname = head.split(" ", 1)[1] if " " in head else head
                if "→" in rest:
                    for t in rest.split("→", 1)[1].split(","):
                        t = t.strip()
                        mm = re.match(r"([A-Z]+)\d+\(([^)]*)\)", t)
                        if mm:
                            by_pin[pname][f"{mm.group(1)} {mm.group(2)}"] += 1
                        else:
                            mm = re.match(r"([A-Z]+)\d+\.[^\[]*\[([^\]]*)\]", t)
                            if mm:
                                by_pin[pname][f"{mm.group(1)} {mm.group(2)}"] += 1
                net = rest.split("→")[0].strip()
                if re.match(r"^(GND|\+|-|V)", net):
                    by_pin[pname][f"net {net.split(' ')[0]}"] += 1
        return {p: [f"{k} ×{v}" for k, v in c.most_common(5)] for p, c in by_pin.items() if c}

    def design_detail(self, project: str, ref: Optional[str] = None) -> Dict:
        pr = self.db.execute("SELECT * FROM projects WHERE name LIKE ? LIMIT 1", (f"%{project}%",)).fetchone()
        if not pr:
            return {"error": f"No project matching {project}"}
        d = dict(pr)
        if ref:
            r = self.db.execute("SELECT * FROM parts WHERE project_id=? AND ref=?", (pr["id"], ref)).fetchone()
            d["part"] = dict(r, neighborhood=json.loads(r["neighborhood"])) if r else None
        else:
            d["parts"] = [f"{r['ref']} {r['value']} ({r['lib_id']})" for r in
                          self.db.execute("SELECT ref,value,lib_id FROM parts WHERE project_id=? ORDER BY ref", (pr["id"],))][:300]
        return d

    def find_symbol(self, query: str, limit: int = 10) -> List[dict]:
        toks = [t for t in re.findall(r"[A-Za-z0-9_.+\-]+", query) if len(t) > 1]
        if not toks:
            return []
        fts = " AND ".join(f'"{t}"*' for t in toks)
        rows = self.db.execute("SELECT c.id, c.lib_id, pr.name project, pr.url, pr.license FROM csymbols_fts JOIN csymbols c ON "
                               "c.id = csymbols_fts.rowid JOIN projects pr ON pr.id=c.project_id WHERE csymbols_fts MATCH ? LIMIT ?",
                               (fts, limit)).fetchall()
        return [dict(r) for r in rows]

    def export_symbol(self, symbol_row_id: int, dest_lib: str, new_name: Optional[str] = None) -> Dict:
        """Copy an embedded symbol from a corpus design into a project .kicad_sym library."""
        from ..kicad.sexpr import parse, QStr
        r = self.db.execute("SELECT * FROM csymbols WHERE id=?", (symbol_row_id,)).fetchone()
        if not r:
            return {"error": "unknown symbol id"}
        node = parse(r["sexpr"])
        name = new_name or str(node.items[1]).split(":")[-1]
        node.items[1] = QStr(name)
        for sub in node.children("symbol"):
            sub.items[1] = QStr(re.sub(r"^.*?(_\d+_\d+)$", lambda m: name + m.group(1), str(sub.items[1])))
        if os.path.exists(dest_lib):
            with open(dest_lib, encoding="utf-8") as f:
                text = f.read()
            root = parse(text)
            if any(str(s.items[1]) == name for s in root.children("symbol")):
                return {"error": f"{name} already exists in {dest_lib}"}
            pos = root.end - 1
            text = text[:pos] + "\t" + dump(node, 1) + "\n" + text[pos:]
        else:
            text = f'(kicad_symbol_lib\n\t(version 20231120)\n\t(generator "rlpcb")\n\t{dump(node, 1)}\n)\n'
        with open(dest_lib, "w", encoding="utf-8") as f:
            f.write(text)
        return {"library": dest_lib, "symbol": name,
                "next": "Add the library to the project's Symbol Library Table (Preferences → Manage Symbol Libraries → Project) if it isn't there."}


# ---------------------------------------------------------------- helpers
def _find_project_roots(folder: str) -> List[str]:
    roots = []
    for pro in glob.glob(os.path.join(folder, "**", "*.kicad_pro"), recursive=True):
        sch = pro[:-len(".kicad_pro")] + ".kicad_sch"
        if os.path.exists(sch):
            roots.append(sch)
    for pro in glob.glob(os.path.join(folder, "**", "*.pro"), recursive=True):  # KiCad 4/5 projects
        sch = pro[:-len(".pro")] + ".sch"
        if os.path.exists(sch) and not os.path.exists(pro[:-len(".pro")] + ".kicad_sch"):
            with open(sch, encoding="utf-8", errors="replace") as f:
                if f.read(40).startswith("EESchema Schematic"):
                    roots.append(sch)
    if not roots:  # schematics without project files: treat files not referenced as sheets as roots
        schs = glob.glob(os.path.join(folder, "**", "*.kicad_sch"), recursive=True)
        referenced = set()
        for s in schs:
            try:
                with open(s, encoding="utf-8", errors="replace") as f:
                    for m in re.finditer(r'\(property "Sheet ?[Ff]ile" "([^"]+)"', f.read()):
                        referenced.add(os.path.normpath(os.path.join(os.path.dirname(s), m.group(1))))
            except OSError:
                pass
        roots = [s for s in schs if os.path.normpath(s) not in referenced]
    return sorted(roots)


def _detect_license(folder: str) -> str:
    for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE"):
        p = os.path.join(folder, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                t = f.read(3000)
            for key, lic in (("CERN Open Hardware Licence Version 2 - Strongly", "CERN-OHL-S-2.0"),
                             ("CERN Open Hardware Licence Version 2 - Weakly", "CERN-OHL-W-2.0"),
                             ("CERN Open Hardware Licence Version 2 - Permissive", "CERN-OHL-P-2.0"),
                             ("Apache License", "Apache-2.0"), ("MIT License", "MIT"), ("Creative Commons Attribution-ShareAlike", "CC-BY-SA"),
                             ("Creative Commons Attribution", "CC-BY"), ("GNU GENERAL PUBLIC LICENSE", "GPL"),
                             ("BSD", "BSD"), ("Solderpad", "Solderpad")):
                if key.lower() in t.lower():
                    return lic
            return "see LICENSE"
    return "unknown"


def _project_summary(h: Hierarchy, comps: Dict[str, dict]) -> str:
    ics = [f"{c['value']}" for r, c in comps.items() if re.match(r"^(U|IC)\d", r)]
    common = Counter(ics).most_common(25)
    sheets = [i.name_path for i in h.instances][:30]
    return json.dumps({"sheets": sheets, "ics": [f"{v}×{n}" if n > 1 else v for v, n in common]})


def _is_passive(ref: str) -> bool:
    return bool(re.match(r"^(R|C|L|FB|D|LED|TP)\d", ref))


def _short_net(net: Optional[str]) -> str:
    if not net:
        return "?"
    if net.startswith("Net-(") or net.startswith("unconnected-"):
        return "(local)"
    return net


def _split(s: str) -> str:
    parts = re.split(r"[:_\-/\s]", s or "")
    return " ".join([s or ""] + [p for p in parts if p])


def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
