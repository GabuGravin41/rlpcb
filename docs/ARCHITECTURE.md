# Architecture

```
                 Claude Desktop / Claude Code            KiCad toolbar button ─► chat panel (web UI)
                          │  MCP (stdio)                                   │ HTTP 127.0.0.1:8765
                          ▼                                                ▼
                 rlpcb.agent.mcp_server                           rlpcb.agent.server ─► rlpcb.agent.chat
                          └──────────────► rlpcb.agent.tools ◄─────────────┘   (Anthropic / OpenAI-compatible loop)
                                     (one registry of 74 tools)
   ┌──────────────┬──────────────┬───────────────┬──────────────┬──────────────┬───────────────┐
   kicad/          library/       design/          pcb/           knowledge/     corpus/        calc/
   sexpr parser    FTS index of   plan, blocks,    board model,   guides +       reference      formulas
   schematic &     symbols and    placer (no       stackup/       user docs      designs &      (IPC-2221,
   legacy models,  footprints     wires), verify,  netclasses,    (SQLite FTS)   IC neighbour-  impedance,
   connectivity,                  wiring guide,    placement,                    hoods          power …)
   kicad-cli,                     netlist export   live IPC API,
   paths                                           Freerouting
```

## Key design decisions

- **Files, not screenshots.** Everything is computed from the KiCad files (S-expressions; legacy `.sch` too).
  The connectivity engine re-implements KiCad's rules and is tested against `kicad-cli`'s netlister
  (`tests/test_connectivity.py`, `scripts/compare_netlist.py`, `scripts/compare_board.py`).
- **Splice, don't rewrite.** The parser records character spans, so edits insert/replace text in place.
  The rest of a user's file is untouched; output is re-parsed before saving; backups are automatic.
- **The plan is the contract.** Intent (plan) and drawing (schematic) are separate. Verification is the diff
  between the two, which is what lets the AI "check your work" instead of "do your work".
- **No wires by construction.** There is no tool that creates schematic wires. Labels placed by computation on
  exact pin coordinates are the only connection the AI can create in a schematic, and only on request.
- **Live when possible, files otherwise.** KiCad 9/10's IPC API (kicad-python) is used for highlight/move/tracks
  in the open editor; everything else works on files so KiCad 7/8 users are covered.
- **Structure for weaker models.** Blocks carry verified sub-circuits; checks turn expert "noticing" into pass/fail;
  `next_step` holds the workflow. Measured in `docs/EVALUATION.md`.
- **Grounded answers.** Parts come only from the library index; engineering claims from the knowledge base,
  the corpus of real designs, calculators (which print their formula), and the datasheet section the user is
  asked to read.

## Connectivity rules implemented

- Point items (pin ends, label anchors, wire ends, junctions, sheet pins, bus entries, no-connects) connect to
  any wire segment they lie on; wire ends touching a wire's middle need a junction; crossing interiors never connect.
- Local labels: per sheet instance. Global labels and power symbols (KiCad ≥ 8: Value field; KiCad ≤ 7: pin
  name) join design-wide; KiCad 10 `(power local)` joins per sheet. Hidden `power_in` pins join the net named
  after the pin. Local and hierarchical labels with the same text join within a sheet.
- Hierarchical labels ↔ sheet pins per sheet *instance* (repeated sheets get separate nets and per-instance refs).
- Buses: vector (`D[0..7]`) members match by index; groups (`USB{DP DM}`, bus aliases from sheets or `.kicad_pro`)
  match by member name; sheet pins map onto the bus's label members; KiCad text markup (`_{}`, `^{}`, `~{}`,
  `{slash}`) is not mistaken for buses.
- Pins of type `no_connect` never connect; stacked pins under a no-connect flag become separate unconnected nets.

## Copilot layer

`agent/copilot.py` (shared verbatim with RL CAD) holds the modes, proposals, journal and undo. `agent/copilot_pcb.py`
classifies each tool (design write, decision, output, read) and its scope, summarises changes in engineering terms
(plan diff, board diff with ratsnest and copper deltas, schematic diff), and computes check deltas and the
"not verified" list. `run_tool` sends every call through `copilot_pcb.gate`.

Related modules:

- `pcb/review.py`: layout review and layout comparison.
- `design/kickoff.py`: product archetypes.
- `design/explain.py`: component and net roles.
- `pcb/interface.py`: `interface_log.json` change notices, shared verbatim with RL CAD.

## Data locations

- `%USERPROFILE%\.rlpcb\` — library index, knowledge DB, corpus DB + cloned repos, settings, chat history,
  Freerouting jar, launcher config.
- `<project>\.rlpcb\` — `plan.json`, plan history, backups, exported plan netlist.

## Extending

- New tool: add a function with `@tool(name, description, schema)` in `rlpcb/agent/tools.py` — it appears in
  MCP and the panel automatically.
- New knowledge: drop Markdown (with YAML front matter) under `knowledge/` — indexed on next start.
- New calculator: add to `rlpcb/calc/formulas.py` and the `CALCULATORS` map.
