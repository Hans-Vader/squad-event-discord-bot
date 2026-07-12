# "Don't Waste Slots" — Oversized Squads in Mirrored Pairs

*Deutsche Version: [dont-waste-slots_GER.md](dont-waste-slots_GER.md)*

## The Problem

Server capacity rarely divides evenly into squads. Example: 100 server slots, 6 casters, no vehicle/heli squads → 94 player seats. At infantry squad size 6 that's 15 squads (90 seats) with **4 seats left over** — and since the squad count is always rounded down to an even number (see below), it's actually 14 squads (84 seats) with **10 seats left over**. Without this feature those seats are simply wasted and shown as `Unused: 10` in the event embed.

**Don't Waste Slots** lets those leftover seats be absorbed by **oversized squads** — squads bigger than the base size — while guaranteeing that the event can always be split into two equal teams.

## Core Rules

These rules hold at every moment, in every mode:

1. **Even squad cap (always active, independent of this feature).** The maximum number of infantry squads is rounded down to an even count so both teams get the same number of squads. An odd raw cap (e.g. 15) becomes 14, and the dropped squad's seats join the leftover pool. Caps below 2 are exempt so tiny test configs stay usable.
2. **Equal numbers per size — the hard invariant.** Every oversized size must exist an even number of times, so organizers can put one of each on either team. The bot structurally guarantees that an incomplete pair can always be completed: the mirror's extra seats are reserved from the pool and one squad slot is held for it (base-size registrations and waitlist promotions cannot take it).
3. **9-player limit.** No squad ever exceeds 9 players — the in-game maximum. This also caps the base squad size everywhere it can be configured (creation modal, DM editor, guild defaults: values 1–9).
4. **Minimal oversized count.** Offered are the sizes of a canonical plan that uses the leftover seats with — in priority order — the **least waste**, then the **fewest oversized squads**, preferring **bigger squads** on ties. Pool 8 → one 9er pair + one 7er pair (4 oversized, 0 wasted), *not* eight 7-player squads. Pool 4 → one 8er pair, *not* two 7er pairs.
5. **Size whitelist (optional).** The creator can restrict which oversized sizes are allowed at all — e.g. only 7s, or 7s and 8s but no 9s. The plan then minimizes within the allowed sizes (pool 8 with only 8/9 allowed → two 8er pairs, because a lone 9er pair would waste 2 seats). A pair that no longer fits the pool is never offered; completing an already-started pair always stays possible, even if the whitelist later excludes that size — equal numbers win.

## Representative Mode

Squad reps pick the size themselves. With the mode active, the squad-type dropdown expands: one option per offerable infantry size, each with its remaining count.

Worked example — 8 leftover seats, base size 6, all sizes allowed:

| State | Dropdown offers | Notes |
|---|---|---|
| Empty | 6er, 7er (2×), 9er (2×) | the minimal plan: one 9er pair + one 7er pair |
| One 9er registered | 6er, 7er (2×), 9er (1×) | the 9er's mirror seats are reserved; a 7er pair may even start first |
| 9er pair complete | 6er, 7er (2×) | 2 seats remain → the 7er pair absorbs them |
| All pairs complete | 6er only | all 8 leftover seats in use, nothing wasted |

Further mechanics:

- **Unregistering** returns the seats to the pool. A broken pair's size is re-offered (and stays reserved) until the pair is complete again; when the last oversized squad leaves, the full plan resets. There is no auto-shrink — the remaining squad keeps its size.
- **Race safety.** The pick is re-validated under the guild lock when the name modal is submitted. If someone else took the last slot (or an admin disabled the mode) in between, the user gets a "size no longer available" error — never a silently different size.
- **Waitlist entries always use the base size.** Oversized squads exist only via direct registration. A base-size squad blocked by a mirror reservation is waitlisted with an honest message ("the last slot is reserved for an oversized squad's mirror"), not a false "all slots taken".
- **Base squads are never blocked** (beyond the mirror reservation). Consequence: if base-size squads fill up all but one squad slot before anyone picks an oversize, no pair can start anymore and the pool is wasted — visibly (see display rules). The mode reserves capacity only for *started* pairs, not for hypothetical ones.

## Player Mode

Nobody picks sizes — the bot plans the capacities:

- **Pre-planned layout.** Auto-created squads get their capacity from a deterministic layout: base-size squads first, the minimal-plan oversized pairs as the last squads (pool 8, cap 14 → squads 1–10 as 6er, then 7er pair, then 9er pair). Players fill squads in order, so the oversized capacity is used only after the regular squads are full — and nobody is waitlisted while planned seats remain.
- **Consolidation re-plans.** At event start (or via the admin Consolidate button) the capacities are re-derived from the **actual** player count: as many base squads as possible plus the minimal oversized pairs for the overflow (88 players at base 6 → 12× 6er + one 8er pair), then members are compacted into that layout. Whatever churn happened before, the event starts with a clean, paired, minimal layout. The per-unregister compaction deliberately does **not** re-plan — otherwise capacities would shrink mid-registration and could never grow back.

## Display

- The infantry field header shows **every size with its own registered/possible counter**, permanently: `⚔️ Infanterie (3/14) [(1/10) Größe: 6 | (1/6) Größe: 7 | (1/4) Größe: 8]`. In player mode the counters reflect the planned layout. Each squad row additionally shows its own seat count.
- The **"Unused" counter** appears only when seats are genuinely wasted: with the mode off, the static leftover (never "Unused: 0"); with the mode on, only the residual that no pair can absorb anymore (e.g. the 5th seat of an odd pool, or a pool crowded out by base squads). While any pair option is still open, nothing is reported as unused.

## Configuration

- **Wizard step "Don't waste slots"** — appears in both modes, but only when the feature could do anything (≥ 2 reclaimable seats and base size below 9). Contains the on/off select and, when more than one size is possible, the multi-select of allowed oversized sizes (default: all).
- **DM editor** — property **23** toggles the mode (enabling is rejected with a specific error when there are no unused seats, only a single unpairable one, or the base size is already 9); property **24** sets the allowed sizes as comma-separated text ("7, 8"; empty = all; values must be above the base size and at most 9).
- Stored per event (`dont_waste_slots`, `dont_waste_allowed_sizes`), carried over to recurring follow-up events, default off.

## Guarantees and Limits

The pairing math has been verified by an exhaustive state-space audit (every reachable register/unregister sequence over 140 configurations) plus seeded random-walk property tests that run in the regular test suite (`tests/test_dont_waste_slots.py`, `TestPairingInvariants`). Invariants checked after every step: the pool is never overbooked, every incomplete pair remains completable immediately, and greedily completing all pairs always yields even counts per size.

Inherent limits no slot system can remove:

1. **Repairable, not enforced.** The bot guarantees a started pair can always be completed — it cannot force anyone to register the mirror. An event can start with an incomplete pair if nobody takes the reserved slot.
2. **Live counts float.** The *capacity* is even; the number of squads actually registered at start can be odd (no-shows).
3. **Config edits after registration** (base size, server capacity, whitelist) can invalidate the math. The logic clamps instead of crashing and prioritizes completing pairs over pool correctness in that conflict.
