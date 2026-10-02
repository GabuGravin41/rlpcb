# RL PCB — an AI design copilot for KiCad

RL PCB sits beside KiCad and works like a senior hardware engineer looking over your shoulder. You describe
what you want to build; it helps you choose real parts from your KiCad libraries, works out the values, places
the symbols for you, tells you **exactly** which pin connects to which pin, and then **checks your wiring**.
It also helps with the board: stackup, net classes, placement, routing guidance, autorouting and DRC.

**The division of labour is deliberate:** language models are bad at drawing schematics (floating "ghost"
wires, near-misses), so RL PCB never draws wires. You draw, and it does everything around the drawing:
research, parts, numbers, placement, instructions, and verification.

```
 you ──► "I need a 24 V PLC input card with 8 isolated inputs"
          │
 RL PCB ─►│ requirements → architecture → datasheet/app-note research → reference designs
          │ → parts from YOUR libraries → calculated values → design plan (parts + nets)
          │ → plan review (ERC before drawing) → symbols placed (no wires)
          │ → "wire U3 pin 7 (OUT) to R12 pin 1 …" → you wire → verify: 87 % done,
          │   R14.2 not connected, ghost wire at (120.6, 88.9) mm → fix → 100 %
          │ → stackup + net classes → placement → routing guidance / autoroute → DRC → Gerbers
```

## You choose how much the AI does

The engineer sets the AI's autonomy for each part of the design:

- **teach:** it explains.
- **advise:** it guides; you edit.
- **propose:** it prepares each change on a copy of the project, with the check results before and after, and you
  accept or reject it.
- **do:** it edits; every change is journalled and can be undone.

For example, the power block can be in "do" while the routing is in "advise". Every result says what the checks
verified and what they could not, such as part data without a datasheet or EMC that was not simulated, so a weaker
model's mistakes are caught where checks exist and flagged where they do not. See `docs/COPILOT.md`.

| Copilot tool | What it does |
|---|---|
| `copilot_status`, `copilot_mode` | Show or set the modes and scopes. |
| `proposals`, `proposal_show`, `proposal_accept`, `proposal_reject` | Review changes prepared on a copy. The chat panel has a Proposals button. |
| `undo`, `design_journal` | History of who changed what, in which mode; any change can be undone. |
| `assurance_report` | What is verified and what is not, before you order boards. |
| `kickoff`, `kickoff_apply` | From an idea to an architecture, questions, pitfalls and a project skeleton. |
| `explain_component`, `explain_net` | What a part or net does in this circuit, and why it is there. |
| `review_layout`, `compare_layouts` | Placement, routing and EMC review with reasons; side-by-side layout studies. |
| `interface_changes` | Notices between this board and the mechanical design (RL CAD). |

## What's inside

| Area | What it does |
|---|---|
| **Connectivity engine** | Computes nets from the drawing itself (pins, wires, junctions, labels, power symbols, hierarchical sheets, buses incl. bus aliases). Validated against KiCad's own netlister: **identical nets on all 13 KiCad 7 demo projects**, and on the KiCad 9/10 demos (Jetson Thor carrier, CM5, VME) it matches the boards' own netlists apart from stale/mechanical items. Reads KiCad 4/5 `.sch` too. |
| **Ghost-wire detector** | Dangling wire ends (with "near-miss: meant for U3 pin 7, 0.6 mm away"), floating wire groups, wire ends on the middle of another wire without a junction (KiCad treats these as *not connected*), labels touching nothing, off-grid pins, shorted power nets, misused no-connect flags. |
| **Library index** | SQLite/FTS search over every symbol and footprint in your KiCad libraries (stock + global + project tables, KiCad 7–10 incl. `.kicad_symdir`). Pins, footprint filters, pad counts, pitch. The AI never invents a part name. |
| **Design plan** | The agreed circuit (parts + nets + no-connects + requirements + decisions), stored in `<project>/.rlpcb/plan.json`. Pins can be named (`U1.VIN`, `U2.GND` → all GND pins, `U1.GPIO20` finds `IO20`). |
| **Plan review** | ERC for intent before drawing: unconnected power pins, floating inputs, output conflicts, missing decoupling, symbol/footprint pin-count mismatches. |
| **Symbol placement** | Groups each IC with the passives that serve it and lays them out around the pins they connect to (decoupling next to VCC, pull-up next to the output…), packs the groups on the sheet, grid-aligned, value & footprint set — **no wires**. Clipboard mode (Ctrl+V into the open editor) or file mode (with backups). Hierarchical sheets per block (`add_sheet`). Optional net labels exactly on pin ends for wide buses. |
| **Parts from anywhere** | Stock/global/project libraries; LCSC/JLCPCB parts converted on the fly (`import_lcsc_part C2040` → symbol + footprint + 3D, LCSC field set); symbols borrowed from open designs in the corpus; datasheets downloaded into the knowledge base (`fetch_datasheet`). |
| **Manufacturing** | Gerbers/drill/positions/STEP via kicad-cli; JLCPCB BOM + CPL (`export_jlcpcb`); plan fields (MPN, LCSC, voltage…) written back into drawn symbols (`sync_fields_from_plan`). |
| **Circuit blocks** | Pre-verified sub-circuits (buck, LDO, battery input, ADC divider, STM32F405 core, IMU, barometer, SPI flash, USB-C device, LED, connectors) with calculated values. MCUs connect by *function* (`SPI1_SCK`, `USART1_TX`, `USB_DP`) — the block knows the pins and refuses conflicts. The drone board rebuilt from 16 blocks verifies at 100 % with KiCad agreeing on every net. |
| **Design checks** | Engineering review beyond ERC: MCU pin functions, USB-C CC/data wiring, STM32 VCAP, TVS orientation, pin role vs net (swapped regulators), LED polarity, cap voltage ratings, inductor current, missing pull-ups, back-feed between supplies, nets that go nowhere, board fit; on the PCB: decoupling distance, crystal distance, track width vs current. |
| **Guided flow** | `next_step` reads the project and returns the single next action (with the exact tool call) plus a checklist — so smaller models (and beginners) don't get lost. |
| **Multi-board systems** | `system.json` with boards and harnesses: every cable pin pair checked (ground/power/voltage/TX↔RX/driver conflicts/open pins/pin count/per-pin current) plus the supply budget across boards. |
| **Wiring guide** | Per net: shortest wiring order (minimum spanning tree over the real pin coordinates), power symbols for rails, labels for far-apart pins, done/not-done per step. |
| **Verification** | Hand-drawn schematic vs plan: progress %, missing connections, shorts between planned nets, unplanned connections, wrong values/footprints, unplaced units, plus ghost wires. |
| **See the drawing** | Renders sheets to images and "pulls up" any section: zoomed crop around `U3, R7` with red highlight boxes. |
| **PCB tools** | Board overview & routing progress, stackup advisor (layer count from BGA pitch/interfaces/rails), net classes from the plan written into `.kicad_pro`, custom DRC rules, placement suggestions with target coordinates for every small passive (decoupling one cap per supply pin, pull-ups/load caps at their pin, two-sided, collision-free), footprint moves and flips (live or file), DRC, fabrication outputs. |
| **Routing** | Guidance by net class; Freerouting autorouting round-trip (DSN → router → SES, with a pure-Python SES importer) into a *copy* of your board; live track/via creation through the KiCad API for agreed simple routes. |
| **Live KiCad API** | KiCad 9/10 IPC API (kicad-python): highlight parts, read the selection, move footprints in one undo step, add tracks/vias, refill zones. |
| **Knowledge base** | ~35 dense engineering guides (power, decoupling/PDN, buck/boost, LDOs, BMS/UPS, high current, PLC I/O, motor drives, analog, EMC, stackups, SI, USB/Ethernet/PCIe/DDR, BGA & GPU-class boards, MCU/FPGA, RF, aerospace/high-rel, printers, DFM, KiCad workflow), 10 industry reference architectures (PLC, elevator, conveyor, humanoid joint, UPS, load sharing, printer mainboard, GPU accelerator, avionics, IoT), review/bring-up/fab checklists — plus **your own PDFs/books/datasheets** (`ingest_documents`). |
| **Reference corpus** | Ingests open-source KiCad projects (KiCad demos, GitHub repos, your folders; KiCad 4–10) and learns *how real designs wire each IC*: "how do others wire the DRV8302?" returns every pin's net and neighbours in the VESC design, with a consensus across designs. Seed list: Jetson Orin/Nano & Kria carriers, VESC, LibreSolar BMS/MPPT, LumenPnP, HackRF, Cynthion… |
| **Calculators** | IPC-2221 trace width, trace/via resistance & current, microstrip/stripline/differential impedance + width solver, critical length, skew, IPC-2221 clearance, E-series, feedback dividers, LED, RC, crystal load caps, buck/boost power stage, LDO thermal, MOSFET loss, PDN target impedance, capacitor SRF, shunts, thermal vias, wavelength. Every result shows the formula and caveats. |

## Three ways to talk to it

1. **Claude Desktop (works with your Claude Pro plan — no API key).** The installer registers RL PCB as an
   MCP server; open Claude Desktop and all 90 tools are available. Say *"Open my KiCad project in
   Documents\KiCad\myboard and help me design…"*.
2. **The RL PCB panel inside KiCad.** A toolbar button (PCB editor; also the schematic editor on KiCad 10)
   opens a chat panel. It needs either an Anthropic API key (Settings ⚙) or a local model through any
   OpenAI-compatible server (Ollama, LM Studio…).
3. **Claude Code / any MCP client:** `claude mcp add rlpcb -- <venv python> -m rlpcb.agent.mcp_server`.

## Install (Windows)

Requirements: KiCad 8, 9 or 10 (9/10 recommended), Python 3.10+, Git (for the corpus), optionally Java 21 for
autorouting.

```powershell
cd path\to\rlpcb
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1            # add -SeedCorpus to download reference designs
```

It creates `.venv`, installs `mcp`, `kicad-python`, `pymupdf`, indexes your libraries, installs the KiCad
plugins into `Documents\KiCad\<version>\`, registers with Claude Desktop, makes a desktop shortcut, then runs
`python -m rlpcb doctor`.

Then in KiCad 9/10: **Preferences → Plugins → Enable KiCad API** (for live highlighting and moves) and restart.

Linux/macOS: `./install.sh [--seed-corpus]`.

## First session

```
You:     Open C:\Users\me\Documents\KiCad\plc_input and let's design an 8-channel 24 V digital input card
         for a Raspberry Pi CM5, IEC 61131-2 type 1, galvanically isolated.
RL PCB:  (asks about channel count, isolation voltage, connectors, power) … proposes architecture …
         searches the knowledge base (industrial_plc_io) and reference designs … calculates the input
         divider/current limiter … builds the plan … plan_review: 0 errors …
         places 41 symbols (Ctrl+V) … "Block 'input_ch1': 1) Draw a wire from J1 pin 1 at (25.4, 40.6) to
         R1 pin 1 at (38.1, 40.6) …"
You:     done with channel 1
RL PCB:  verify → 92 %: R3 pin 2 is not connected; the wire from U2 pin 3 ends 0.64 mm short of it
         (dangling end at 120.65, 88.90). Everything else in channel 1 matches the plan.
```

## Command line

```
python -m rlpcb doctor                    # check everything
python -m rlpcb index [--force]           # (re)index libraries
python -m rlpcb check  path\to\project    # ghost wires & drawing problems
python -m rlpcb verify path\to\project    # schematic vs plan
python -m rlpcb nets   path\to\project [regex]
python -m rlpcb ingest-docs D:\Books\Electronics
python -m rlpcb corpus seed | owner/repo | D:\OpenHardware
python -m rlpcb tool <tool_name> '{"json": "args"}'
python -m rlpcb serve --open              # chat panel
python -m rlpcb mcp                       # MCP server (stdio)
```

## Safety of your files

- Schematic/board edits are *splices*: the rest of the file stays byte-for-byte identical, the result is parsed
  before writing, and a timestamped backup goes to `<project>\.rlpcb\backups\`.
- If KiCad has the file open (lock file present), RL PCB warns you; clipboard mode and the live API avoid the
  conflict entirely.
- The autorouter writes `<name>.routed.kicad_pcb`, never your original.
- `mech_export` writes `<board>.mech.json`, which describes the board for the product around it: outline, holes, connectors with the edge they face, and part heights. `mech_check` checks the board against the `enclosure.json` that RL CAD writes. See `../rlcad/docs/INTEGRATION.md`.
- `finish_routing` closes what the autorouter left (plane stitching, grid router, rip-up, negotiated congestion) and writes `<name>.finished.kicad_pcb`, checked with KiCad's own DRC after every step.
- The panel server only listens on 127.0.0.1 and rejects cross-origin requests. `allow_file_writes=false` in
  Settings makes RL PCB read-only.

## Honest limits (and the roadmap)

- It will not draw wires, by design. Net labels on pin ends are offered for buses.
- The AI's design judgement is only as good as its research: it cites the knowledge base, the datasheet section
  and real reference designs, and you should still read the datasheet's typical-application circuit.
- Autorouting is for non-critical nets; power loops, high-speed and analog nets should be routed by hand with
  the guidance given.
- A Blackwell-class accelerator board (20+ layer HDI, ~1000 A core rail, PCIe Gen5/6) is not a first project;
  the `gpu_accelerator_board` architecture file lays out a realistic learning path toward it.

See `docs/EVALUATION.md` for how a small model performs with and without blocks, `examples/drone_fc/` for a complete worked project (a drone flight controller, idea → routed board), `docs/USER_GUIDE.md` for the workflow in depth and `docs/ARCHITECTURE.md` for how it works.
