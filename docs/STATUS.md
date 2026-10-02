# Build status (first 4-hour build session)

## Verified in the cloud sandbox (KiCad 7.0.11 CLI + KiCad 9/10 demo files)
- Connectivity engine = KiCad's netlister on all 13 KiCad 7 demos; KiCad 4 VESC design = its own netlist;
  KiCad 9/10 demos (Jetson Thor carrier, CM5, VME, RoyalBlue, tinytapeout…) match their boards' netlists
  except stale/mechanical items (stitching footprints, cages).
- Plan → review → place (file mode) → labels → verify = 100 %, and KiCad's netlister agrees (tests).
- Clipboard text format matches KiCad's copy/paste format (checked against KiCad source).
- Freerouting round trip routed the pic_programmer board to 100 % (pure-Python SES import); Freerouting 2.x headless
  jobs are bounded with `router.job_timeout` (they ignore `-mp`).
- Worked example `examples/drone_fc/`: 61-part F405 flight controller, plan review 0 errors → 4 sheets placed →
  verify 100 % (KiCad netlister agrees) → 36×36 mm 4-layer board, two-sided placement with 0 overlaps → ~88 % autorouted.
- Circuit blocks (11), design checks (≈20 rules), next_step, multi-board systems (system_check). Small-model
  evaluation: Haiku with blocks averaged 18.1/19 functional checks vs 16.0/19 pin-level, in 2.4× fewer calls; final
  checks flag every flawed design and none of the correct ones (docs/EVALUATION.md).
- File-mode footprint flip (move to bottom) matches pcbnew's FOOTPRINT::Flip exactly (tests/test_flip.py).
- MCP server works with MCP SDK 1.x and 2.x; images (schematic crops) returned to Claude.
- Chat panel UI + agent loop tested with a mock OpenAI-compatible model.
- Fresh install from a clean clone (`install.sh`) → doctor all OK.
- Test suite: `python -m pytest -q tests` (10 tests).

## Not testable here — please check on your machine first
1. KiCad 9/10 on Windows: `python -m rlpcb doctor`.
2. Claude Desktop sees the `rlpcb` tools after a restart.
3. Clipboard paste (Ctrl+V) of placed parts into the open schematic editor.
4. Live API (Preferences → Plugins → Enable KiCad API): `live_status`, `highlight`, `move_footprints`.
5. The toolbar button (IPC plugin in the PCB editor; schematic editor on KiCad 10).
6. `import_lcsc_part` and `fetch_datasheet` (the sandbox blocks those sites).
7. `run_erc` / `run_drc` (need KiCad 8+ CLI; sandbox had 7).

## Next iterations (roadmap)
- Board creation from the plan/schematic (an F8 equivalent) + clustered PCB auto-placement.
- Length-matching/diff-pair rule generation per interface (USB, Ethernet, PCIe, DDR).
- Routing assistant: per-net suggested paths & via counts from current capacity, live preview tracks.
- Embedding-based semantic search over books/datasheets (FTS today).
- EasyEDA/Altium project import into the corpus; bigger seed corpus (GitLab/CERN OHWR).
- Schematic editing through the IPC API once KiCad exposes it (kipy 0.8 already ships a Schematic class).
