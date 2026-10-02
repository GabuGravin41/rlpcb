import json, os, threading, urllib.request, urllib.error
import pytest

def test_server_rejects_cross_origin(rlhome):
    from http.server import ThreadingHTTPServer
    from rlpcb.agent.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        ok = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status").status
        assert ok == 200
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tool", data=b'{"name":"kicad_environment"}',
                                     headers={"Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tool", data=b'{"name":"x"}',
                                     headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req)
    finally:
        httpd.shutdown()

BLDC = os.path.join(os.environ.get("RLPCB_HOME", os.path.expanduser("~/.rlpcb")), "corpus", "repos", "vedderb__bldc-hardware", "design")

@pytest.mark.skipif(not os.path.isdir(BLDC), reason="VESC corpus repo not downloaded")
def test_legacy_kicad4_matches_its_netlist():
    from rlpcb.kicad.sexpr import parse_file
    from rlpcb.kicad.schematic import Hierarchy
    from rlpcb.kicad.connectivity import Connectivity
    k = set()
    for n in parse_file(os.path.join(BLDC, "BLDC_4.net")).child("nets").children("net"):
        s = frozenset(f"{x.value('ref')}.{x.value('pin')}" for x in n.children("node") if not str(x.value("ref")).startswith("#"))
        if s:
            k.add(s)
    mine = {frozenset(v) for v in Connectivity(Hierarchy(os.path.join(BLDC, "BLDC_4.sch"))).netlist().values()}
    assert mine == k
