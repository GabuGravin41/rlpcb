# Can a small model design a board with RL PCB?

The test: whether a small, cheap model (Claude Haiku) can produce a *correct* design plan for a real board through RL
PCB's tools, and which tools make the difference.

## Setup

**Brief:** a USB-C data logger. It has:

- a USB-C connector for USB 2.0 device operation, with ESD protection and correct CC configuration;
- a 3.3 V LDO powered from VBUS;
- an STM32F405 MCU with an 8 MHz crystal, decoupling, VCAP capacitors and BOOT0 handling;
- a BMP280 barometer on I2C;
- W25Q128 SPI flash;
- a status LED;
- a 4-pin UART header;
- unused MCU pins marked no-connect.

**Two conditions**, same brief, same model, and the same tool descriptions an MCP client would show:

| | Tools |
|---|---|
| **A: pin-level** | search symbols/footprints, add components, connect pins, no-connect, plan review, calculators, knowledge base |
| **B: blocks** | A + `list_blocks`, `add_block`, `block_connect`, `next_step`, `design_checks` |

Each run starts from an empty project and may make about 90 tool calls. The agent cannot read source code or files.

**Scoring** (`scripts/eval/score.py`, independent of RL PCB's own checks). It runs 19 functional checks on the final
plan. Examples:

- USB D+ reaches PA12 and D− reaches PA11 (through the ESD part), on both connector rows;
- CC pins have 5.1 kΩ to GND;
- the ESD part's ground is on GND;
- VCAP caps are 1–4.7 µF;
- the crystal is on PH0/PH1 with load caps;
- BMP280 SCL/SDA sit on a valid I2C pin pair, and the flash is on the SCK/MISO/MOSI of one valid SPI instance;
- the UART header is on a valid USART TX/RX pair;
- LED polarity and series resistor are correct, and the LDO is wired the right way round.

A hand-built reference scores 19/19. Swapping the flash's MISO and MOSI costs exactly one point, which confirms the
scorer notices real mistakes.

## Results

| Round | Pin-level (A) | Blocks (B) |
|---|---|---|
| 1 | 15/19 (68 calls) · 17/19 (70) | 16/19 (23) · **19/19** (23) |
| 2 | 16/19 (92) · 18/19 (103) | **19/19** (15) · **19/19** (47) |
| 3 | 15/19 (102) · 10/19 (70, ran out of budget) | 18/19 (91, ignored the blocks) · 17/19 (40) |
| 4 | **19/19** (103) · 18/19 (99) | **19/19** (22) · 18/19 (34) |
| **All** | **mean 16.0 / 19 · 1 of 8 perfect · 88 calls** | **mean 18.1 / 19 · 4 of 8 perfect · 37 calls** |

The tools were improved between rounds using what each round revealed (below), so the rounds aren't identical
experiments. With 16 runs, read the direction (more correct, about 2.4× fewer calls) rather than the exact numbers.

## What the small model got wrong, and what now catches it

Every mistake below happened in at least one run. Each one led to a new check or a tool change.

| Mistake (run) | Consequence | Now caught by |
|---|---|---|
| USB D+ on PA11 and D− on PA12 (A1, A2) | USB doesn't enumerate | `mcu_pin_function` (alternate-function table) |
| CC pull-downs 100 kΩ / 1 MΩ (A1, A2) | USB-C chargers never turn on VBUS | `usb_c_cc` |
| ESD array's anode on D− (A1) | clamps the data line | `tvs_orientation` |
| Connector rows A/B cross-wired, D+ shorted to D− (A2) | USB fails, or shorts when the cable is flipped | `usb_c_data` |
| Only one connector row wired (A5), 2 of 4 VBUS pins (B8) | works in one cable orientation only | `usb_c_data`, `partial_pin_group` |
| LDO GND pin on +3.3 V and output on GND (A3) | regulator shorts its own output | `pin_role` |
| LED anode to GND, directly or through its resistor (A1–A4, A6) | LED never lights | `led_polarity` |
| VCAP 100 nF, or VCAP_1 and VCAP_2 tied together (A1, A4, A6) | STM32 core regulator unstable | `stm32_vcap` |
| Nets named `SPI1_SCK`, `PA4` but the MCU pin not on them (B1, B6) | peripherals not connected at all | `mcu_pin_function`, `net_named_like_pin`, new `block_connect` tool |
| USB connector's data net reaches nothing (B5, B6) | no USB | `net_goes_nowhere`, `block_port_open` |
| ESD part's second ground pin open (A5) | weaker protection | `ground_pin_open` |
| BMP280 SDO marked no-connect (A8) | undefined I2C address | `must_connect` |
| Half-created block after a bad call (B8) | silent partial circuit | `add_block` is now all-or-nothing |
| Model built the circuit pin by pin despite blocks (B5) | back to pin-level error rates | `plan_add_components` now points to the matching block |

**Agreement check.** With the final checks, every design that the independent scorer marks as flawed gets at least one
`design_checks` error, and every design the scorer marks perfect gets none. That holds for all 17 designs (16 runs plus
the reference), and there are no false alarms on the two drone flight-controller designs either.

## What this means

- **Blocks do most of the work.** They move the error-prone detail (support parts, values, pin functions) out of the
  model, and cut the work by more than half.
- **Checks turn "noticing" into pass/fail.** Since round 2, the pin-level runs' USB was correct, because the review
  said exactly which pin to use. The limit is the budget: a small model fixing errors one at a time can run out of calls
  (A6).
- **What still needs a strong model or a human:** choosing an architecture, parts outside the block library, and
  judgement calls (thermal, EMC, layout). The checks catch wiring mistakes; they don't make design decisions.

## Reproduce

```bash
# Condition A or B, one project folder per run; the agent calls tools like this:
EVAL_COND=B python3 scripts/eval/rl.py /tmp/eval/run1 list_blocks '{}'
python3 scripts/eval/score.py /tmp/eval/run1          # 19 functional checks
```
