import os
import os, sys, shutil, pytest
os.environ.setdefault("RLPCB_DEFAULT_MODE", "do")   # existing tests expect direct writes; the copilot tests set modes explicitly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_DIRS = [d for d in (os.environ.get("RLPCB_DEMOS", ""), "/usr/share/kicad/demos",
             r"C:\Program Files\KiCad\9.0\share\kicad\demos", r"C:\Program Files\KiCad\10.0\share\kicad\demos") if d and os.path.isdir(d)]

@pytest.fixture(scope="session")
def demos():
    if not DEMO_DIRS:
        pytest.skip("KiCad demo projects not found")
    return DEMO_DIRS[0]

@pytest.fixture(scope="session")
def has_cli():
    from rlpcb.kicad.paths import kicad_cli
    if not kicad_cli():
        pytest.skip("kicad-cli not available")
    return True

@pytest.fixture()
def rlhome(tmp_path, monkeypatch):
    home = tmp_path / "rlhome"
    home.mkdir()
    src = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")
    if os.path.exists(src):
        shutil.copy(src, home / "library_index.db")
    monkeypatch.setenv("RLPCB_HOME", str(home))
    return home
