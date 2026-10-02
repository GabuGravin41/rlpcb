# Working with the AI: modes, proposals, checks

RL PCB and RL CAD work the same way here. This page applies to both.

The engineer decides how much the AI does, part by part. A confident engineer can let it design a whole block. A
cautious one can ask only for guidance. Whatever the setting, every change is checked, recorded and reversible, and
the AI says what the checks could not verify.

## The four modes

| Mode | The AI | The engineer |
|---|---|---|
| teach | explains parts, nets, checks and trade-offs; no design changes | learns and decides |
| advise | gives exact guidelines and reviews; its design tools refuse to write and return the change as advice | makes the edit |
| propose | prepares each change on a copy of the design and shows the summary and the check results before and after | accepts or rejects, with a reason |
| do | changes the design directly; every change is journalled with a snapshot | can undo any change |

Modes are set per scope, so different parts of one design can be handled differently. Some examples:

- PCB: `block:power` in do, `board:routing` in advise, everything else in propose.
- CAD: `part:fuselage` in advise, `part:pods` in propose.

When a change touches several scopes, the strictest mode wins.

The engineer sets modes:

- RL PCB: the mode menu in the chat panel, or by asking in the chat (`copilot_mode`).
- RL CAD: **RL CAD → AI mode…** in FreeCAD, or by asking in the chat.

The AI does not change modes on its own. The engineer's own edits always apply, whatever the mode, and they are
journalled too: FreeCAD Sync, `rlcad set`, and accept/reject from the panels.

Two kinds of action never run on the AI's own authority:

- **Accepting a warning** (`design_checks acknowledge`, `decision_add "ACK …"`) always becomes a proposal, because it
  is the engineer's decision.
- **Uploading to Onshape** needs the engineer's confirmation.

## Proposals

In propose mode a change runs on a copy of the design:

- RL PCB: a copy of the KiCad project.
- RL CAD: a copy of the design folder, which is then built and fully checked.

The proposal records:

- what changed, in engineering terms ("C11 moved (127.5,109.2) → (120,120); ratsnest 632 → 633 mm, worse placement");
- the check results before and after (new findings, resolved findings);
- what is not verified (see below).

To accept or reject a proposal:

- **RL PCB:** use the Proposals panel in the chat, or `proposal_accept` / `proposal_reject`. If KiCad has the board
  open and its API is reachable, accepted placement moves are applied live. Otherwise reload the file in KiCad.
- **RL CAD:** use **RL CAD → Proposals…** in FreeCAD. It accepts the proposal, rebuilds and reloads the model. Its
  build results carry over, so accepting needs no second build.

A rejection keeps the engineer's reason. `copilot_status` shows recent reasons to the AI, so it can follow this
engineer's preferences.

A proposal is refused if the design changed after it was made. The AI then makes a fresh one.

## Journal and undo

Every change is recorded in the journal, whether made directly in do mode, accepted from a proposal, or made by the
engineer. The journal records:

- who made it (AI or engineer);
- which mode it was made in;
- a summary of the change;
- a snapshot of the files before it.

`design_journal` lists the history. `undo` restores the files of a change. It refuses if a later change touched the
same files, unless forced. The journal is also a plain record a colleague can read to see what happened and why.

Files:

- RL PCB: `<project>/.rlpcb/copilot/`
- RL CAD: `<design>/.rlcad/copilot/`

Both hold `settings.json`, `journal.jsonl`, `snapshots/` and `proposals/`.

## What was checked, and what was not

Each change and each proposal returns `checks` (before/after) and `assurance.not_verified`. `assurance_report` lists
them for the whole design.

The checks catch many mistakes a model makes, such as pin functions, polarity, ratings, interference, connector
reach and printability. They cannot vouch for everything. These items are reported as not verified:

- **RL PCB:** active parts without a datasheet, MPN or LCSC field; parts without footprints; symbols missing from the
  libraries; power nets without a current; EMC, signal integrity and thermal behaviour, which are not simulated;
  firmware pin mapping.
- **RL CAD:** part data marked nominal or estimated in the catalog; strength beyond the cantilever check (there is no
  FEA); aerodynamics; the print audit, which approximates a slicer; printed fits.

The AI is instructed to say this plainly. A smaller model makes more mistakes; the checks catch the ones they cover,
and the `not_verified` list tells the engineer where a stronger model or a human has to look.

## Starting from a blank page

`kickoff(idea)` turns an idea into a starting point:

- **RL PCB:** the usual architecture for that kind of product (blocks, typical parts, what to watch in each, which
  blocks RL PCB already has pre-verified), the questions whose answers change the design, the pitfalls, and the
  layer count. Archetypes cover IoT sensor nodes, USB devices, drone flight controllers, motor controllers, battery
  devices, industrial I/O, printers (multi-board) and power supplies.
- **RL CAD:** the questions, the manufacturing route for the quantity, the pitfalls, and whether RL CAD has a family
  for it (ducted quad, enclosure) or the engineer designs it in FreeCAD/Onshape with RL CAD reviewing the parts.

`kickoff_apply` creates the project once the engineer agrees. It is subject to the mode like any other change.

- **RL PCB** creates the KiCad project, one sheet per group of blocks, the plan's blocks with their purpose and
  watch-outs, and the requirements, plus `docs/requirements.md` (open questions), `docs/decisions.md` and a
  `datasheets/` folder.
- **RL CAD** creates the design folder, its spec and `docs/requirements.md`, and links the board when one is given.

## Teaching and reviews

- **RL PCB `explain_component`** says what a part does in this circuit and why it is there, what goes wrong without
  it, and what to check. It reads the role from the plan, or infers it from the connections, and says which it did.
  It recognises roles such as decoupling, bulk storage, pull-up, divider, USB-C CC resistor, catch diode, ESD clamp
  and crystal load capacitor.
- **RL PCB `explain_net`** says what kind of net it is and how to route it.
- **RL PCB `review_layout`** reviews a board the way a senior layout engineer would, with the reason for each point.
  It covers:
  - return paths and reference planes;
  - ground stitching;
  - differential-pair skew and vias;
  - fast nets;
  - switch-node size;
  - the buck converter's input loop;
  - ESD clamps at the connectors;
  - decoupling;
  - crystal routing;
  - edge clearance;
  - assembly sides.

  Each point is marked "measured" or "rule of thumb".
- **RL PCB `compare_layouts`** compares two versions of a board (the current one, an autorouted one, or a proposal)
  for placement and routing studies.
- **RL CAD `review_part`** reviews manufacturability for FDM printing or injection molding:
  - **FDM:** walls, overhangs, bridges, hole sizes, adhesion, layer strength.
  - **Injection molding:** draft, undercuts, wall-thickness uniformity, mold cost.

  It works on any STEP or STL, including parts the engineer drew in FreeCAD or Onshape.
- **RL CAD `explain`** covers what each check protects against and what each parameter moves.

## Electronics and mechanics: change notices

See `INTEGRATION.md`. Each board's KiCad project holds `interface_log.json`:

- When RL PCB rewrites the board's `mech.json`, the differences are logged for the mechanical side ("J2 moved 4 mm;
  affects connector_access, cutouts").
- When RL CAD rewrites `enclosure.json`, its differences are logged for the electronics side ("height allowed above
  the board 16 → 12 mm").

Each side shows the other's notices it has not seen yet, and marks them as seen after checking: RL CAD's
`integration_check`, RL PCB's `interface_changes`.
