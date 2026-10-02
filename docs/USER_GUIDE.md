# RL PCB user guide

## 1. The loop you'll use every day

1. **Tell it the goal and constraints.** Input power, loads and currents, interfaces, environment
   (temperature, vibration, mains, EMC), size, quantity, budget, fab/assembly house. It records them in the plan.
2. **Agree the architecture.** It proposes blocks (power tree, controller, interfaces, drivers, protection),
   with reasons. Push back; it logs every decision with its rationale (`plan_show` → `decisions`).
3. **One block at a time:** it researches (knowledge base, reference designs, datasheet section to read),
   calculates values, picks parts from *your* libraries, and writes the block into the plan.
4. **Plan review.** Fix all errors before placing anything (unconnected power pins, floating inputs, missing
   decoupling, footprint mismatches).
5. **Place.** With the schematic open in KiCad, it copies the parts to the clipboard; click in the schematic,
   press **Ctrl+V**, move the group, click to drop. (With the schematic closed it can write the file directly.)
6. **Wire.** Ask for the wiring guide. Wire a block, then say "check". It reports progress, what's missing,
   shorts, and ghost wires with coordinates.
7. **Repeat** for the next block. When the schematic is 100 %, run ERC (`run_erc`), then move to the board.

### Useful phrases

| Say | It does |
|---|---|
| "show me the part of the schematic around U3 and explain it" | `render_schematic focus=U3` + `component_connections` |
| "how do other designs wire the TPS54331?" | `reference_designs` across the corpus |
| "what should C12 be?" | datasheet guidance + `calculate` |
| "why is this net not connected?" | `check_schematic`, `find_nets`, `locate` |
| "I only want to wire the power block now" | `wiring_guide block=power` |
| "use labels for the MCU bus" | `place_parts labels=true` for those parts only |
| "this part isn't in my library" | corpus symbol import, or instructions for the Symbol Editor / SnapEDA / LCSC |
| "import my existing project so you can review it" | `plan_import_schematic`, then `plan_review` |

## 2. Wiring in KiCad without ghost wires

- Hover exactly over a pin's end (the small circle) and press **W**; click once on the other pin's end.
  **Esc** / double-click finishes.
- A wire connects only at pin *ends*. Crossing the middle of a pin or wire does nothing.
- Ending a wire on the middle of another wire only connects if there is a junction dot (KiCad adds one when
  you end on a wire; moving things later can leave a T without a dot — the checker catches it).
- The pin-end circle disappears when something is connected to it — that's your visual check.
- Use power symbols (**P**) for rails and ground instead of long wires; use labels (**L**, global **Ctrl+L**)
  for connections between distant parts or sheets.
- After a block, ask RL PCB to verify. It reads the file on disk — **save first (Ctrl+S)**.

The full beginner walkthrough is in `knowledge/checklists/kicad_wiring_howto.md` (it's also searchable from chat).

## 3. From schematic to board

1. `advise_stackup` — layer count and order from BGA pitch, interfaces, rails, density, mains/RF.
2. In KiCad set the stackup (Board Setup → Physical Stackup) to your fab's standard values.
3. `setup_netclasses apply=true` — Power/HighCurrent/Diff90/Diff100/HighSpeed/HighVoltage/Analog/RF50
   classes and patterns from the plan's net annotations. `add_design_rules` for special constraints.
4. In the PCB editor: **Tools → Update PCB from Schematic (F8)**.
5. `placement_suggestions` → review → "apply the moves" (live via the KiCad API: one Ctrl+Z undoes them).
6. Route by priority: power loops (switching regulators) → clocks/crystals → high-speed & differential pairs →
   analog/sense → everything else. Ask "how should I route <net/block>?" for specific guidance.
7. Optional: `autoroute` finishes non-critical nets into `<name>.routed.kicad_pcb` (Java 21 + Freerouting,
   downloaded automatically). Review everything it did.
8. Pour zones, refill (**B**), `run_drc`, fix, `export_fabrication`.

## 4. Growing its knowledge

- **Your books & datasheets:** `python -m rlpcb ingest-docs "D:\Electronics Books"` (PDF, MD, TXT, HTML).
- **Open-source designs:** `python -m rlpcb corpus seed`, or any GitHub repo: `python -m rlpcb corpus owner/repo`,
  or a folder of projects. KiCad 4 to 10 formats are understood. Ask "search GitHub for LiFePO4 BMS designs"
  and it will find and ingest candidates (respect each project's licence when you reuse circuits).
- **Your own past projects** are the best corpus of all: ingest your KiCad folder.

## 5. Settings (`%USERPROFILE%\.rlpcb\settings.json` or ⚙ in the panel)

| Key | Meaning |
|---|---|
| `provider` | `anthropic` or `openai` (any OpenAI-compatible server, e.g. Ollama) |
| `anthropic_api_key`, `model` | API key; `auto` picks the newest Sonnet available to your key |
| `openai_base_url`, `openai_model`, `openai_api_key` | local/other model |
| `web_search` | let Claude search the web from the panel |
| `allow_file_writes` | `false` makes RL PCB read-only |
| `github_token` | optional, raises GitHub search limits for corpus discovery |
| `freerouting_jar` | use your own Freerouting build |

## 6. Troubleshooting

- `python -m rlpcb doctor` explains what's missing.
- "Cannot reach KiCad's API": enable Preferences → Plugins → *Enable KiCad API* (KiCad 9+), restart KiCad,
  keep the PCB editor open.
- Parts pasted but not visible: you pasted into a different sheet, or KiCad was showing a stale file — save,
  close, reopen.
- Verification disagrees with what you see: save the schematic first; RL PCB reads the file on disk.
- Library part not found: `rebuild_library_index`, and check the library is enabled in KiCad's library table.

## Blocks, checks and the guided flow (new)

- **Blocks.** Ask for "a 5 V buck from 2–6S" or "an STM32F405 core"; the copilot uses `add_block` with calculated
  values. MCU peripherals are connected by function: `block_connect(instance='mcu', connect={'SPI1_SCK': 'FLASH_SCK'})`.
  A block call either succeeds completely or changes nothing, and it tells you why.
- **Checks.** `plan_review` now includes the engineering checks; `design_checks` also looks at the board. Errors are
  real wiring faults. Warnings you can fix, or accept with a reason (they're logged as design decisions).
- **Where am I?** Say "what's next?" — `next_step` answers with one action and a checklist of the whole flow.
- **Several boards.** `system_create` in a folder above the board projects, add boards and cables, then
  `system_check` verifies every harness pin and the power budget.
