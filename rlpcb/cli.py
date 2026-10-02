"""RL PCB command line.

  python -m rlpcb doctor                 check the installation (KiCad, libraries, API, clipboard...)
  python -m rlpcb index [--force]        build the symbol/footprint index
  python -m rlpcb serve [--open]         start the chat panel server
  python -m rlpcb mcp                    run the MCP server (stdio) for Claude Desktop / Claude Code
  python -m rlpcb check PROJECT          ghost wires & drawing problems in a schematic
  python -m rlpcb verify PROJECT         compare schematic with its design plan
  python -m rlpcb nets PROJECT [REGEX]   print the computed netlist
  python -m rlpcb ingest-docs FOLDER     add PDFs/notes to the knowledge base
  python -m rlpcb corpus seed|REPO|DIR   grow the reference-design corpus
  python -m rlpcb tool NAME '{json}'     call any copilot tool directly
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _p(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rlpcb", description="RL PCB — AI copilot for KiCad")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("doctor")
    a = sub.add_parser("index")
    a.add_argument("--force", action="store_true")
    a = sub.add_parser("serve")
    a.add_argument("--port", type=int, default=None)
    a.add_argument("--open", action="store_true")
    sub.add_parser("mcp")
    for name in ("check", "verify", "nets"):
        a = sub.add_parser(name)
        a.add_argument("project")
        if name == "nets":
            a.add_argument("pattern", nargs="?", default="")
    a = sub.add_parser("ingest-docs")
    a.add_argument("folder")
    a = sub.add_parser("corpus")
    a.add_argument("source")
    a = sub.add_parser("tool")
    a.add_argument("name")
    a.add_argument("args", nargs="?", default="{}")
    args = ap.parse_args(argv)

    if args.cmd == "doctor":
        return doctor()
    if args.cmd == "index":
        from .library.index import LibraryIndex
        ix = LibraryIndex()
        _p(ix.build(progress=lambda m: print("  " + m), force=args.force))
        _p(ix.stats())
        return 0
    if args.cmd == "serve":
        from .agent.server import serve
        from .config import load_settings
        serve(args.port or load_settings().get("server_port", 8765), args.open)
        return 0
    if args.cmd == "mcp":
        from .agent.mcp_server import main as m
        m()
        return 0
    if args.cmd in ("check", "verify", "nets"):
        from .agent.tools import Session, run_tool
        s = Session()
        r = run_tool(s, "open_project", {"path": args.project})
        if "error" in r:
            _p(r)
            return 1
        if args.cmd == "check":
            _p(run_tool(s, "check_schematic", {"min_severity": "warning"}))
        elif args.cmd == "verify":
            _p(run_tool(s, "verify_schematic", {}))
        else:
            from .kicad.connectivity import Connectivity
            import re
            c = Connectivity(s.hierarchy())
            rx = re.compile(args.pattern or ".", re.I)
            for n, pins in c.netlist().items():
                if rx.search(n):
                    print(f"{n}: {' '.join(pins)}")
        return 0
    if args.cmd == "ingest-docs":
        from .knowledge.kb import KnowledgeBase
        _p(KnowledgeBase().ingest_folder(args.folder))
        return 0
    if args.cmd == "corpus":
        from .agent.tools import Session, run_tool
        _p(run_tool(Session(), "corpus_ingest", {"source": args.source}))
        return 0
    if args.cmd == "tool":
        from .agent.tools import Session, run_tool
        _p(run_tool(Session(), args.name, json.loads(args.args)))
        return 0
    ap.print_help()
    return 0


def doctor() -> int:
    ok = True

    def line(status, msg):
        nonlocal ok
        ok = ok and status != "FAIL"
        print(f"[{status:4}] {msg}")

    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    from .kicad import cli
    from .kicad.paths import environment_report
    env = environment_report()
    line("OK" if env["kicad_install_dirs"] else "WARN", f"KiCad install: {env['kicad_install_dirs'] or 'not found (set RLPCB_KICAD_DIR)'}")
    v = cli.version()
    line("OK" if v else "FAIL", f"kicad-cli: {env['kicad_cli']} ({v})")
    if v and cli.major() < 8:
        line("WARN", "KiCad 8+ recommended (ERC/DRC via kicad-cli, newer file format). KiCad 9/10 adds the live API.")
    st = env["stock_libraries"]
    line("OK" if st.get("symbols") else "WARN", f"Stock symbol libraries: {st.get('symbols')}")
    line("OK" if st.get("footprints") else "WARN", f"Stock footprint libraries: {st.get('footprints')}")
    from .library.index import LibraryIndex
    s = LibraryIndex().stats()
    line("OK" if s["symbols"] else "WARN", f"Library index: {s['symbols']} symbols, {s['footprints']} footprints "
         + ("" if s["symbols"] else "→ run: python -m rlpcb index"))
    from .knowledge.kb import KnowledgeBase
    kb = KnowledgeBase()
    kb.ensure_builtin()
    line("OK", f"Knowledge base: {len(kb.list_docs())} documents")
    from .corpus.corpus import Corpus
    cs = Corpus().stats()
    line("OK" if cs["projects"] else "WARN", f"Reference corpus: {cs['projects']} designs, {cs['parts']} parts "
         + ("" if cs["projects"] else "→ run: python -m rlpcb corpus seed"))
    for mod, why in (("mcp", "MCP server for Claude Desktop"), ("kipy", "live KiCad API (kicad-python)"),
                     ("pymupdf", "rendering schematics/PDF books"), ("cairosvg", "SVG rendering (optional)")):
        try:
            __import__(mod)
            line("OK", f"python package {mod} ({why})")
        except Exception:
            line("WARN", f"python package {mod} missing ({why})")
    from .pcb import live
    ls = live.status()
    line("OK" if ls.get("connected") else "INFO", f"Live KiCad API: {ls}")
    from .pcb.autoroute import find_java
    j = find_java()
    line("OK" if j else "INFO", f"Java for Freerouting: {j or 'not found (only needed for autorouting)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
