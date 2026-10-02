"""Locate KiCad installations, library tables and user config on Windows/macOS/Linux (KiCad 7–10)."""
from __future__ import annotations

import glob
import os
import platform
import re
import shutil
from typing import Dict, List, Optional

from .sexpr import parse_file

VERSIONS = ["10.0", "9.99", "9.0", "8.0", "7.0"]


def system() -> str:
    return platform.system()  # Windows | Darwin | Linux


def kicad_install_dirs() -> List[str]:
    """Candidate KiCad install roots, newest first."""
    out = []
    env = os.environ.get("RLPCB_KICAD_DIR")
    if env:
        out.append(env)
    if system() == "Windows":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")]:
            if base:
                for v in VERSIONS:
                    out.append(os.path.join(base, "KiCad", v))
        # user-level installs
        la = os.environ.get("LOCALAPPDATA")
        if la:
            out += sorted(glob.glob(os.path.join(la, "Programs", "KiCad", "*")), reverse=True)
    elif system() == "Darwin":
        out += ["/Applications/KiCad/KiCad.app/Contents", "/Applications/KiCad.app/Contents"]
    else:
        out += ["/usr", "/usr/local", "/opt/kicad"]
    return [d for d in out if d and os.path.isdir(d)]


def kicad_cli() -> Optional[str]:
    env = os.environ.get("RLPCB_KICAD_CLI")
    if env and os.path.exists(env):
        return env
    exe = shutil.which("kicad-cli")
    if exe:
        return exe
    for d in kicad_install_dirs():
        for cand in (os.path.join(d, "bin", "kicad-cli.exe"), os.path.join(d, "bin", "kicad-cli"),
                     os.path.join(d, "MacOS", "kicad-cli")):
            if os.path.exists(cand):
                return cand
    return None


def kicad_python() -> Optional[str]:
    """KiCad's bundled python (has pcbnew SWIG module on 7–10)."""
    for d in kicad_install_dirs():
        for cand in (os.path.join(d, "bin", "python.exe"), os.path.join(d, "bin", "python3"),
                     os.path.join(d, "Frameworks", "Python.framework", "Versions", "Current", "bin", "python3")):
            if os.path.exists(cand):
                return cand
    return None


def stock_library_dirs() -> Dict[str, str]:
    """{'symbols': dir, 'footprints': dir, '3dmodels': dir, 'templates': dir, 'demos': dir} for the newest install."""
    res: Dict[str, str] = {}
    for key, envs in {
        "symbols": ["KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD7_SYMBOL_DIR"],
        "footprints": ["KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD7_FOOTPRINT_DIR"],
        "3dmodels": ["KICAD10_3DMODEL_DIR", "KICAD9_3DMODEL_DIR", "KICAD8_3DMODEL_DIR", "KICAD7_3DMODEL_DIR"],
        "templates": ["KICAD10_TEMPLATE_DIR", "KICAD9_TEMPLATE_DIR", "KICAD8_TEMPLATE_DIR", "KICAD7_TEMPLATE_DIR"],
    }.items():
        for e in envs:
            if os.environ.get(e) and os.path.isdir(os.environ[e]):
                res[key] = os.environ[e]
                break
    for d in kicad_install_dirs():
        share = None
        for cand in (os.path.join(d, "share", "kicad"), os.path.join(d, "SharedSupport")):
            if os.path.isdir(cand):
                share = cand
                break
        if not share:
            continue
        for key in ("symbols", "footprints", "3dmodels", "template", "demos"):
            p = os.path.join(share, key)
            k = "templates" if key == "template" else key
            if os.path.isdir(p) and k not in res:
                res[k] = p
        if res:
            break
    return res


def user_config_dirs() -> List[str]:
    """KiCad per-user config dirs (contain sym-lib-table, fp-lib-table, kicad_common.json)."""
    out = []
    if system() == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "kicad")
    elif system() == "Darwin":
        base = os.path.expanduser("~/Library/Preferences/kicad")
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "kicad")
    for v in VERSIONS:
        p = os.path.join(base, v)
        if os.path.isdir(p):
            out.append(p)
    return out


def user_documents_dir() -> Optional[str]:
    """Where KiCad keeps user plugins/3rd-party content (Documents/KiCad/<ver>)."""
    home = os.path.expanduser("~")
    for v in VERSIONS:
        for base in (os.path.join(home, "Documents", "KiCad", v), os.path.join(home, ".local", "share", "kicad", v)):
            if os.path.isdir(base):
                return base
    return None


_var_re = re.compile(r"\$\{([^}]+)\}|\$\(([^)]+)\)")


def expand_vars(uri: str, extra: Optional[Dict[str, str]] = None) -> str:
    stock = stock_library_dirs()
    env = dict(os.environ)
    for v in ("10", "9", "8", "7"):
        env.setdefault(f"KICAD{v}_SYMBOL_DIR", stock.get("symbols", ""))
        env.setdefault(f"KICAD{v}_FOOTPRINT_DIR", stock.get("footprints", ""))
        env.setdefault(f"KICAD{v}_3DMODEL_DIR", stock.get("3dmodels", ""))
        env.setdefault(f"KICAD{v}_3RD_PARTY", os.path.join(user_documents_dir() or "", "3rdparty"))
    env.setdefault("KICAD_USER_TEMPLATE_DIR", "")
    if extra:
        env.update(extra)

    def rep(m):
        name = m.group(1) or m.group(2)
        return env.get(name, m.group(0))

    return os.path.normpath(_var_re.sub(rep, uri))


def read_lib_table(path: str, extra_vars: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Parse sym-lib-table / fp-lib-table into [{name, type, uri, descr, disabled}]."""
    if not os.path.exists(path):
        return []
    root = parse_file(path)
    out = []
    for lib in root.children("lib"):
        d = {"name": str(lib.value("name", "")), "type": str(lib.value("type", "KiCad")),
             "uri_raw": str(lib.value("uri", "")), "descr": str(lib.value("descr", "") or "")}
        d["disabled"] = lib.child("disabled") is not None
        d["uri"] = expand_vars(d["uri_raw"], extra_vars)
        out.append(d)
    return out


def library_tables(project_dir: Optional[str] = None) -> Dict[str, List[Dict[str, str]]]:
    """Resolve global + project symbol/footprint library tables. Falls back to scanning stock dirs."""
    sym, fp = [], []
    extra = {"KIPRJMOD": project_dir} if project_dir else {}
    for cfg in user_config_dirs()[:1]:
        sym += read_lib_table(os.path.join(cfg, "sym-lib-table"), extra)
        fp += read_lib_table(os.path.join(cfg, "fp-lib-table"), extra)
    if project_dir:
        sym += [dict(d, scope="project") for d in read_lib_table(os.path.join(project_dir, "sym-lib-table"), extra)]
        fp += [dict(d, scope="project") for d in read_lib_table(os.path.join(project_dir, "fp-lib-table"), extra)]
    stock = stock_library_dirs()
    have_sym = {d["name"] for d in sym}
    have_fp = {d["name"] for d in fp}
    if "symbols" in stock:
        for f in sorted(glob.glob(os.path.join(stock["symbols"], "*.kicad_sym")) + glob.glob(os.path.join(stock["symbols"], "*.kicad_symdir"))):
            n = os.path.splitext(os.path.basename(f))[0]
            if n not in have_sym:
                sym.append({"name": n, "type": "KiCad", "uri": f, "descr": "", "disabled": False, "scope": "stock"})
    if "footprints" in stock:
        for f in sorted(glob.glob(os.path.join(stock["footprints"], "*.pretty"))):
            n = os.path.splitext(os.path.basename(f))[0]
            if n not in have_fp:
                fp.append({"name": n, "type": "KiCad", "uri": f, "descr": "", "disabled": False, "scope": "stock"})
    return {"symbols": sym, "footprints": fp}


def environment_report() -> Dict[str, object]:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "kicad_install_dirs": kicad_install_dirs(),
        "kicad_cli": kicad_cli(),
        "kicad_python": kicad_python(),
        "stock_libraries": stock_library_dirs(),
        "user_config_dirs": user_config_dirs(),
        "user_documents_dir": user_documents_dir(),
    }
