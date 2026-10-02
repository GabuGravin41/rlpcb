import pytest

pcbnew = pytest.importorskip("pcbnew")
from rlpcb.pcb import finish as F  # noqa: E402

REPORT = """** Drc report **
[unconnected_items]: Missing connection between items
    Local override; Severity: error
    @(116.7750 mm, 118.0000 mm): Pad 3 [SPI1_MOSI] of U4 on B.Cu
    @(119.7500 mm, 122.1750 mm): Pad 23 [SPI1_MOSI] of U3 on F.Cu
[unconnected_items]: Missing connection between items
    Local override; Severity: error
    @(127.1750 mm, 103.2000 mm): Track [+3V3] on F.Cu, length 1.0650 mm
    @(126.1000 mm, 104.3000 mm): Via [+3V3] on F.Cu - B.Cu
[silk_overlap]: Silkscreen overlap
"""


def test_unconnected_parser():
    import re
    blocks = re.split(r"\n(?=\[)", REPORT)
    pairs = F.unconnected(blocks)
    assert len(pairs) == 2
    assert pairs[0][0] == {"kind": "pad", "x": 116.775, "y": 118.0, "pad": "3", "net": "SPI1_MOSI", "ref": "U4", "layer": "B.Cu"}
    assert pairs[1][0]["kind"] == "track" and pairs[1][0]["layer"] == "F.Cu"
    assert pairs[1][1]["kind"] == "via"
    assert F.kinds(blocks)["unconnected_items"] == 2


def test_disk_is_symmetric():
    d = F._disk(3)
    assert (3, 0) in d and (-3, 0) in d and (0, 0) in d and (3, 3) not in d
