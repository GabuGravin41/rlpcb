"""Worked example, part 2: the board. Run after design_session.py (with --labels, or after you wired the schematic)
and after F8 in KiCad (or make_board.py in the cloud demo).

    python examples/drone_fc/board_session.py <project-dir> [--route]
"""
import json
import sys

from rlpcb.agent.tools import Session, run_tool

proj = sys.argv[1]
s = Session()


def T(_tool, **a):
    r = run_tool(s, _tool, a)
    if isinstance(r, dict) and r.get("error"):
        print(f"!! {_tool}: {r['error']}")
    return r


def show(title, obj, n=1500):
    print(f"\n=== {title}\n" + (json.dumps(obj, indent=1, ensure_ascii=False)[:n] if not isinstance(obj, str) else obj))


T("open_project", path=proj)

# 1. layer count / stackup
st = T("advise_stackup", high_speed=["USB2"], power_rails=4, max_current_a=2.5, board_area_cm2=13, component_count=65)
show("advise_stackup", {k: st[k] for k in ("recommended_copper_layers", "reasons", "stackup")})

# 2. net classes from the plan's net annotations (current_a, net_class) -> .kicad_pro
show("setup_netclasses", T("setup_netclasses", apply=True))

# 3. anchor parts, following the plan's layout notes:
#    connectors on the edges, MCU in the middle, IMU at the board centre on the bottom (away from the buck and
#    motor wiring), buck converter in the lower-left corner next to the battery pads, flash + boot button underneath.
anchors = [
    # ref, x, y, rotation, side
    ("U3", 120.5, 116.5, 0, "top"),      # STM32F405 LQFP-64, centre
    ("U4", 118.0, 118.0, 0, "bottom"),   # ICM-20602 IMU, board centre (bottom side)
    ("J2", 119.5, 102.5, 180, "top"),    # USB-C on the top edge
    ("U7", 119.5, 104.5, 0, "bottom"),   # USB ESD right behind the connector
    ("U2", 110.0, 104.0, 0, "top"),      # 3.3 V LDO
    ("U5", 127.5, 104.0, 0, "top"),      # BMP280, far from the buck
    ("J4", 103.5, 110.5, 270, "top"),    # receiver UART, left edge
    ("J5", 132.5, 111.5, 90, "top"),     # VTX UART, right edge
    ("J6", 134.0, 121.0, 0, "top"),      # SWD pads, right edge
    ("Y1", 110.5, 113.0, 0, "top"),      # 8 MHz crystal at PH0/PH1
    ("U1", 106.5, 119.5, 90, "top"),     # TPS5430 buck
    ("L1", 111.0, 127.0, 0, "top"),      # buck inductor
    ("D1", 112.0, 119.5, 90, "top"),     # catch diode, tight hot loop U1-D1-C_in
    ("J1", 108.5, 133.0, 0, "top"),      # battery pads (origin = pad 1), bottom edge between the corner holes
    ("J3", 123.5, 132.5, 0, "top"),      # ESC 8-pin, bottom edge
    ("D2", 108.5, 126.5, 90, "bottom"),  # input TVS, right behind the battery pads
    ("D5", 127.5, 105.0, 90, "bottom"),   # VBUS diode next to USB
    ("U6", 127.0, 125.5, 0, "bottom"),   # blackbox flash
    ("SW1", 127.0, 113.0, 0, "bottom"),  # BOOT button
]
r = T("move_footprints", method="file",
      moves=[dict(ref=a, x_mm=x, y_mm=y, rotation=rot, side=sd) for a, x, y, rot, sd in anchors])
show("move_footprints (anchors)", {k: v for k, v in r.items() if k != "moved"} | {"moved": len(r.get("moved", []))})

# 4. passives next to the pins they serve
sug = T("placement_suggestions")
show("placement_suggestions (first 10 of %d moves)" % len(sug["moves"]),
     [f"{m['ref']:>4} → ({m['x_mm']:.2f}, {m['y_mm']:.2f}) {m['side']:6}  {m['reason']}" for m in sug["moves"][:10]], 3000)
r = T("move_footprints", moves=sug["moves"], method="file")
show("move_footprints (passives)", {"moved": len(r.get("moved", [])), "flipped": len(r.get("flipped", []))})
after = T("placement_suggestions")
show("placement check after applying", {"remaining_moves": [m["ref"] for m in after["moves"]],
                                        "courtyard_overlaps": after["courtyard_overlaps"],
                                        "suggestions": [x["detail"] for x in after["suggestions"]]}, 3000)

show("board_overview", {k: v for k, v in T("board_overview").items() if k in ("size_mm", "footprints", "top_side",
                                                                              "bottom_side", "routing")}, 800)
if "--route" in sys.argv:
    show("autoroute", T("autoroute", time_limit_min=3), 2000)
