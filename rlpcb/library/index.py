"""Searchable index of symbol and footprint libraries (SQLite + FTS5).

Built once (a few minutes for the full KiCad library set) and refreshed
incrementally by file mtime. Everything the copilot says about parts comes
from here, so it never invents a symbol or footprint name.
"""
from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import sqlite3
import time
from typing import Dict, Iterable, List, Optional

from ..config import data_dir
from ..kicad.footprints import parse_footprint_node
from ..kicad.paths import library_tables
from ..kicad.sexpr import parse_file
from ..kicad.symbols import SymbolLibrary

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, kind TEXT, lib TEXT);
CREATE TABLE IF NOT EXISTS symbols(
  lib_id TEXT PRIMARY KEY, lib TEXT, name TEXT, description TEXT, keywords TEXT,
  fp_filters TEXT, footprint TEXT, datasheet TEXT, ref_prefix TEXT, value TEXT,
  pin_count INTEGER, units INTEGER, power INTEGER, extends TEXT, pins TEXT, path TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
  lib_id, name, description, keywords, value, pin_names, lib, tokenize='unicode61 remove_diacritics 2 tokenchars ''-_.+''');
CREATE TABLE IF NOT EXISTS footprints(
  fpid TEXT PRIMARY KEY, lib TEXT, name TEXT, description TEXT, tags TEXT, mount TEXT,
  pad_count INTEGER, width REAL, height REAL, min_pitch REAL, min_drill REAL, model TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS project_libs(lib TEXT, kind TEXT, project_dir TEXT, PRIMARY KEY(lib, kind, project_dir));
CREATE VIRTUAL TABLE IF NOT EXISTS footprints_fts USING fts5(
  fpid, name, description, tags, lib, tokenize='unicode61 remove_diacritics 2 tokenchars ''-_.+''');
"""


def _db_path():
    return os.path.join(data_dir(), "library_index.db")


class LibraryIndex:
    def __init__(self, db_path: Optional[str] = None, project_dir: Optional[str] = None):
        self.db_path = db_path or _db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.project_dir = project_dir

    # ------------------------------------------------------------ building
    def build(self, extra_symbol_files: Iterable[str] = (), extra_fp_dirs: Iterable[str] = (),
              progress=None, force: bool = False) -> Dict[str, int]:
        tables = library_tables(self.project_dir)
        for kind in ("symbols", "footprints"):
            for d in tables[kind]:
                if d.get("scope") == "project" and self.project_dir:
                    self.db.execute("INSERT OR IGNORE INTO project_libs VALUES(?,?,?)", (d["name"], kind, os.path.normcase(self.project_dir)))
        sym_files = [(d["name"], d["uri"]) for d in tables["symbols"] if not d.get("disabled")
                     and (d["uri"].endswith(".kicad_sym") or d["uri"].rstrip("/\\").endswith(".kicad_symdir"))]
        sym_files += [(os.path.splitext(os.path.basename(p))[0], p) for p in extra_symbol_files]
        fp_dirs = [(d["name"], d["uri"]) for d in tables["footprints"] if not d.get("disabled")]
        fp_dirs += [(os.path.splitext(os.path.basename(p.rstrip("/\\")))[0], p) for p in extra_fp_dirs]
        stats = {"symbol_libs": 0, "symbols": 0, "footprint_libs": 0, "footprints": 0, "skipped_unchanged": 0, "errors": 0}
        cur = self.db.cursor()
        t0 = time.time()
        for i, (nick, path) in enumerate(sym_files):
            if not os.path.exists(path):
                continue
            if not force and self._unchanged(path):
                stats["skipped_unchanged"] += 1
                continue
            try:
                n = self._index_symbol_lib(cur, nick, path)
                stats["symbol_libs"] += 1
                stats["symbols"] += n
            except Exception as e:  # noqa
                stats["errors"] += 1
                if progress:
                    progress(f"! {path}: {e}")
            if progress and i % 20 == 0:
                progress(f"symbols {i+1}/{len(sym_files)} ({time.time()-t0:.0f}s)")
        self.db.commit()
        for i, (nick, path) in enumerate(fp_dirs):
            if not os.path.isdir(path):
                continue
            if not force and self._unchanged(path):
                stats["skipped_unchanged"] += 1
                continue
            try:
                n = self._index_fp_lib(cur, nick, path)
                stats["footprint_libs"] += 1
                stats["footprints"] += n
            except Exception as e:  # noqa
                stats["errors"] += 1
                if progress:
                    progress(f"! {path}: {e}")
            if progress and i % 20 == 0:
                progress(f"footprints {i+1}/{len(fp_dirs)} ({time.time()-t0:.0f}s)")
        self.db.commit()
        return stats

    def _unchanged(self, path):
        mt = _mtime(path)
        row = self.db.execute("SELECT mtime FROM files WHERE path=?", (path,)).fetchone()
        return row is not None and abs(row["mtime"] - mt) < 1e-6

    def _index_symbol_lib(self, cur, nick, path) -> int:
        lib = SymbolLibrary(path, nick)
        cur.execute("DELETE FROM symbols WHERE lib=?", (nick,))
        cur.execute("DELETE FROM symbols_fts WHERE lib=?", (nick,))
        n = 0
        for s in lib.symbols.values():
            d = s.summary(with_pins=True, max_pins=2000)
            pins = d.get("pins", [])
            pin_names = " ".join(sorted({p["name"] for p in pins if p["name"] not in ("~", "")}))
            cur.execute("INSERT OR REPLACE INTO symbols VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                s.lib_id, nick, s.name, d["description"], d["keywords"], d["footprint_filters"], d["footprint"],
                d["datasheet"], d["reference_prefix"], d["value"], d.get("pin_count", 0), d["units"], int(s.power),
                s.extends or "", json.dumps(pins), path))
            cur.execute("INSERT INTO symbols_fts VALUES(?,?,?,?,?,?,?)", (
                s.lib_id, _split_name(s.name), d["description"], d["keywords"], d["value"], pin_names, nick))
            n += 1
        cur.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (path, _mtime(path), "sym", nick))
        return n

    def _index_fp_lib(self, cur, nick, path) -> int:
        cur.execute("DELETE FROM footprints WHERE lib=?", (nick,))
        cur.execute("DELETE FROM footprints_fts WHERE lib=?", (nick,))
        n = 0
        for f in glob.glob(os.path.join(path, "*.kicad_mod")):
            try:
                fp = parse_footprint_node(parse_file(f), nick)
            except Exception:
                continue
            s = fp.summary()
            w, h = s["courtyard_mm"]
            cur.execute("INSERT OR REPLACE INTO footprints VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                fp.fpid, nick, fp.name, fp.description, fp.tags, fp.mount, s["pad_count"], w, h,
                s["min_pitch_mm"], s["min_drill_mm"], fp.model, f))
            cur.execute("INSERT INTO footprints_fts VALUES(?,?,?,?,?)", (fp.fpid, _split_name(fp.name), fp.description, fp.tags, nick))
            n += 1
        cur.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (path, _mtime(path), "fp", nick))
        return n

    # ------------------------------------------------------------ queries
    def stats(self):
        return {
            "symbols": self.db.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
            "symbol_libraries": self.db.execute("SELECT COUNT(DISTINCT lib) FROM symbols").fetchone()[0],
            "footprints": self.db.execute("SELECT COUNT(*) FROM footprints").fetchone()[0],
            "footprint_libraries": self.db.execute("SELECT COUNT(DISTINCT lib) FROM footprints").fetchone()[0],
            "db": self.db_path,
        }

    def search_symbols(self, query: str, limit: int = 15, lib: Optional[str] = None,
                       ref_prefix: Optional[str] = None, min_pins: Optional[int] = None,
                       max_pins: Optional[int] = None, include_power: bool = False) -> List[dict]:
        filters, fargs = "", []
        if lib:
            filters += " AND s.lib = ?"
            fargs.append(lib)
        if ref_prefix:
            filters += " AND s.ref_prefix = ?"
            fargs.append(ref_prefix)
        if min_pins is not None:
            filters += " AND s.pin_count >= ?"
            fargs.append(min_pins)
        if max_pins is not None:
            filters += " AND s.pin_count <= ?"
            fargs.append(max_pins)
        if not include_power:
            filters += " AND s.power = 0"
        # hide libraries that belong to *other* projects' library tables
        filters += " AND s.lib NOT IN (SELECT lib FROM project_libs WHERE kind='symbols' AND project_dir != ?)"
        fargs.append(os.path.normcase(self.project_dir or ""))
        base = ("SELECT s.*, bm25(symbols_fts, 8.0, 10.0, 3.0, 4.0, 2.0, 1.0, 1.5) AS score FROM symbols_fts "
                "JOIN symbols s ON s.lib_id = symbols_fts.lib_id WHERE symbols_fts MATCH ?")
        rows = []
        if not (query or "").strip():
            rows = self.db.execute("SELECT s.*, 0 AS score FROM symbols s WHERE 1" + filters + " LIMIT ?",
                                   fargs + [limit]).fetchall()
            return [self._sym_row(r, pins=False) for r in rows]
        seen = set()
        toks = _tokens(query)
        for mode in ("AND", "OR"):
            fts = _fts_query(query, mode)
            if not fts:
                break
            try:
                got = self.db.execute(base + filters + " ORDER BY score LIMIT ?", [fts] + fargs + [limit * 6]).fetchall()
            except sqlite3.OperationalError:
                got = []
            for r in got:
                if r["lib_id"] not in seen:
                    seen.add(r["lib_id"])
                    rows.append((mode, r))
            if len(rows) >= limit:
                break
        allowed = self._allowed_libs()
        if allowed:
            rows = [(m, r) for m, r in rows if r["lib"] in allowed] or rows
        q = query.strip().lower()

        def rank(item):
            mode, r = item
            name = r["name"].lower()
            hay = " ".join(str(r[k] or "") for k in ("name", "description", "keywords", "value", "fp_filters")).lower()
            cover = sum(1 for t in toks if t.lower().strip("*") in hay)
            exact = 0 if name == q else (1 if name.startswith(q) or q in name else 2)
            generic = 0 if r["lib"] in ("Device", "power") else 1
            return (exact, -cover, 0 if mode == "AND" else 1, generic, r["score"])
        rows = sorted(rows, key=rank)[:limit]
        return [self._sym_row(r, pins=False) for _, r in rows]

    def _allowed_libs(self):
        """Libraries visible to the active project: stock + global table + this project's table + files inside it."""
        if getattr(self, "_allowed", None) is None:
            try:
                names = {d["name"] for d in library_tables(self.project_dir)["symbols"]}
                if self.project_dir:
                    pd = os.path.normcase(os.path.abspath(self.project_dir))
                    for lib, path in self.db.execute("SELECT lib, path FROM files WHERE kind='sym'"):
                        if os.path.normcase(os.path.abspath(path)).startswith(pd + os.sep):
                            names.add(lib)
                self._allowed = names
            except Exception:
                self._allowed = set()
        return self._allowed

    def _sym_row(self, r, pins=True):
        d = {"lib_id": r["lib_id"], "description": r["description"], "keywords": r["keywords"],
             "default_footprint": r["footprint"], "footprint_filters": r["fp_filters"],
             "datasheet": r["datasheet"], "reference_prefix": r["ref_prefix"], "pin_count": r["pin_count"],
             "units": r["units"]}
        if r["extends"]:
            d["derived_from"] = r["extends"]
        if pins:
            d["pins"] = json.loads(r["pins"] or "[]")
        return d

    def get_symbol(self, lib_id: str) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM symbols WHERE lib_id=?", (lib_id,)).fetchone()
        if r is None:
            r = self.db.execute("SELECT * FROM symbols WHERE name=? COLLATE NOCASE LIMIT 1", (lib_id.split(":")[-1],)).fetchone()
        return self._sym_row(r) if r else None

    def symbol_path(self, lib_id: str) -> Optional[str]:
        r = self.db.execute("SELECT path FROM symbols WHERE lib_id=?", (lib_id,)).fetchone()
        return r["path"] if r else None

    def search_footprints(self, query: str = "", limit: int = 15, lib: Optional[str] = None,
                          pad_count: Optional[int] = None, mount: Optional[str] = None,
                          pitch: Optional[float] = None) -> List[dict]:
        fts = _fts_query(query)
        if fts and not self.db.execute("SELECT 1 FROM footprints_fts WHERE footprints_fts MATCH ? LIMIT 1", (fts,)).fetchone():
            fts = _fts_query(query, "OR")
        if fts:
            sql = ("SELECT f.*, bm25(footprints_fts, 6.0, 10.0, 2.0, 3.0, 2.0) AS score FROM footprints_fts "
                   "JOIN footprints f ON f.fpid = footprints_fts.fpid WHERE footprints_fts MATCH ?")
            args: list = [fts]
        else:
            sql, args = "SELECT f.*, 0 AS score FROM footprints f WHERE 1", []
        if lib:
            sql += " AND f.lib=?"
            args.append(lib)
        if pad_count is not None:
            sql += " AND f.pad_count=?"
            args.append(pad_count)
        if mount:
            sql += " AND f.mount=?"
            args.append(mount)
        if pitch is not None:
            sql += " AND abs(f.min_pitch-?) < 0.02"
            args.append(pitch)
        sql += " ORDER BY score LIMIT ?"
        args.append(limit)
        try:
            rows = self.db.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            rows = []
        return [self._fp_row(r) for r in rows]

    def _fp_row(self, r):
        return {"footprint": r["fpid"], "description": r["description"], "tags": r["tags"], "mount": r["mount"],
                "pad_count": r["pad_count"], "courtyard_mm": [r["width"], r["height"]],
                "min_pitch_mm": r["min_pitch"], "min_drill_mm": r["min_drill"]}

    def get_footprint(self, fpid: str) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM footprints WHERE fpid=?", (fpid,)).fetchone()
        return self._fp_row(r) | {"path": r["path"]} if r else None

    def footprints_for_symbol(self, lib_id: str, limit: int = 25) -> List[dict]:
        """Footprints matching the symbol's ki_fp_filters and pin count."""
        sym = self.db.execute("SELECT * FROM symbols WHERE lib_id=?", (lib_id,)).fetchone()
        if not sym:
            return []
        out = []
        if sym["footprint"]:
            fp = self.get_footprint(sym["footprint"])
            if fp:
                fp["why"] = "symbol's default footprint"
                out.append(fp)
        filters = (sym["fp_filters"] or "").split()
        if not filters:
            return out
        pc = sym["pin_count"]
        seen = {o["footprint"] for o in out}
        for flt in filters:
            like = flt.replace("*", "%").replace("?", "_")
            if ":" in flt:
                rows = self.db.execute("SELECT * FROM footprints WHERE fpid LIKE ? LIMIT 400", (like,)).fetchall()
            else:
                rows = self.db.execute("SELECT * FROM footprints WHERE name LIKE ? LIMIT 400", (like,)).fetchall()
            for r in rows:
                if r["fpid"] in seen:
                    continue
                if not fnmatch.fnmatch(r["name"], flt.split(":")[-1]):
                    continue
                if pc and r["pad_count"] and r["pad_count"] not in (pc, pc + 1) and pc > 2:
                    continue  # allow +1 for exposed pad
                seen.add(r["fpid"])
                d = self._fp_row(r)
                d["why"] = f"matches filter {flt}"
                out.append(d)
                if len(out) >= limit:
                    return out
        return out


def _mtime(path):
    if os.path.isdir(path):
        try:
            return max([os.path.getmtime(path)] + [os.path.getmtime(f) for f in glob.glob(os.path.join(path, "*.kicad_mod"))]
                       + [os.path.getmtime(f) for f in glob.glob(os.path.join(path, "*.kicad_sym"))])
        except ValueError:
            return os.path.getmtime(path)
    return os.path.getmtime(path)


def _split_name(name: str) -> str:
    """Index 'TPS54331DR' also as its alnum prefixes so 'TPS5433' finds it."""
    parts = re.split(r"[_\-\s]", name)
    extra = []
    m = re.match(r"([A-Za-z]+)(\d+)", name)
    if m:
        extra.append(m.group(1) + m.group(2))
        extra.append(m.group(2))
    return " ".join([name] + parts + extra)


_SYN = {
    "mosfet": "MOSFET NMOS PMOS Q_NMOS Q_PMOS",
    "opamp": "opamp operational",
    "op-amp": "opamp operational",
    "ldo": "LDO regulator",
    "buck": "buck step-down stepdown",
    "boost": "boost step-up",
    "mcu": "MCU microcontroller",
    "usb-c": "USB_C Type-C USB-C",
    "crystal": "crystal Crystal resonator",
    "resistor": "resistor",
    "capacitor": "capacitor",
    "inductor": "inductor",
    "diode": "diode",
    "led": "LED",
    "connector": "Conn connector",
    "optocoupler": "optocoupler opto photocoupler optoisolator isolator",
    "opto": "optocoupler opto photocoupler optoisolator",
    "optoisolator": "optocoupler opto photocoupler optoisolator",
    "isolator": "isolator isolation optocoupler",
    "tvs": "TVS transient suppressor",
    "terminal": "terminal Screw_Terminal TerminalBlock",
    "relay": "relay Relay",
    "fuse": "fuse Fuse polyfuse",
    "eeprom": "EEPROM",
    "flash": "flash Flash",
}
_NOISE = {"a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "pin", "pins", "type", "part", "chip", "ic"}


_VALUE_RE = re.compile(r"^\d+(\.\d+)?[pnuµmkKM]\d*(F|H|ohm|Ω)?$|^\d+(\.\d+)?(F|H|ohm|Ω|R)$|^\d+[pnumkMR]\d+$")


def _tokens(q: str) -> List[str]:
    toks = [t for t in re.findall(r"[A-Za-z0-9_.+\-]+", q or "") if t.lower() not in _NOISE and t.lower() not in ("and", "or", "not", "near")]
    # component values (10k, 100n, 4u7, 3.3V) describe the part, not the symbol: ignore them unless nothing else is left
    kept = [t for t in toks if not _VALUE_RE.match(t)]
    if any(t.lower() in ("capacitor", "resistor", "inductor", "ferrite", "cap", "res") for t in kept):
        kept = [t for t in kept if not re.match(r"^\d", t)]  # "10uF 25V capacitor" -> capacitor (Device:C)
    return kept or toks


def _fts_query(q: str, mode: str = "AND") -> str:
    toks = _tokens(q)
    if not toks:
        return ""
    parts = []
    for t in toks:
        low = t.lower()
        alts = set()
        if low in _SYN:
            alts |= set(_SYN[low].split())
        alts.add(t.replace('"', ""))
        m = re.fullmatch(r"(\d)x(\d+)", low)  # 1x05 -> 01x05
        if m:
            alts.add(f"0{m.group(1)}x{int(m.group(2)):02d}")
        parts.append("(" + " OR ".join(f'"{a}"*' for a in sorted(alts)) + ")")
    return f" {mode} ".join(parts)
