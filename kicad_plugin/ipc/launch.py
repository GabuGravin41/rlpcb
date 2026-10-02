"""KiCad 9/10 IPC-API plugin action: open the RL PCB copilot panel for the current project.

KiCad runs this with the plugin's own Python environment and passes the API socket
in the environment; we only need the stdlib. The active document is discovered via
kipy when available so the panel opens on the right project.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from launcher_common import ensure_server, open_window, tell_project  # noqa: E402


def current_project():
    try:
        from kipy import KiCad
        from kipy.proto.common.types.base_types_pb2 import DocumentType
        k = KiCad()
        for dt in (DocumentType.DOCTYPE_PCB, DocumentType.DOCTYPE_SCHEMATIC):
            try:
                docs = k.get_open_documents(dt)
            except Exception:
                continue
            if docs:
                proj = docs[0].project
                if getattr(proj, "path", ""):
                    return os.path.join(proj.path, proj.name + ".kicad_pro") if proj.name else proj.path
    except Exception:
        pass
    return ""


def main():
    proj = current_project()
    ensure_server()
    tell_project(proj)
    open_window(proj)


if __name__ == "__main__":
    main()
