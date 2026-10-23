# Oversized Squads

Optional per-event mode (internally still `dont_waste_slots`) that lets infantry squads be bigger than the base squad size — up to **9 players**, the in-game squad limit.

## Why

Two situations call for bigger squads:

- **A community brings more players than the squad size allows** and wants to stay together — even if that means another squad no longer fits into the event.
- **Leftover seats.** Server capacity rarely divides evenly into squads. Example: 100 server slots, 6 casters, no vehicle/heli squads → 94 player seats. At infantry squad size 6 that's 15 squads; since the squad count is always rounded down to an even number (see below), it's 14 squads (84 seats) with **10 seats left over**.

## Core Rules

1. **Even squad cap (always active, independent of this mode).** The maximum number of infantry squads is rounded down to an even count so both teams get the same number of squads. An odd raw cap (e.g. 15) becomes 14. Caps below 2 are exempt so tiny test configs stay usable.
2. **Infantry seats only.** Oversized squads use the infantry seat budget `S = player seats − vehicle seats − heli seats`. Free vehicle and heli seats stay reserved for vehicles and helis.
3. **9-player limit.** No squad ever exceeds 9 players. This also caps the base squad size everywhere it can be configured (values 1–9).
4. **Size whitelist (optional).** The creator can restrict which oversized sizes are allowed at all — e.g. only 7s, or 7s and 8s but no 9s.
5. **Squad-count cap (optional).** The creator can cap the total number of oversized squads. With the pair rule an odd cap acts as the next lower even one.
6. **The bot never overbooks on its own.** No registration, admin add or waitlist promotion hands out more infantry seats than are free.

## Representative Mode — Every Free Infantry Seat

Squad reps pick the size themselves: the squad-type dropdown shows one option per offerable infantry size, each with how many squads of exactly that size could still register one after another. Oversized squads may use **any free infantry seat**, not just the leftover — first come, first served. Regular squads can therefore be crowded out; how much is up to the organizer via the whitelist and the squad-count cap.

### Pair Rule (per event, default: on)

- **On — mirrored pairs.** Every oversized size exists an even number of times, so organizers can put one of each on either team. When the first squad of a pair registers, its mirror's squad slot and seats are held back. In addition, the number of **regular** squads must always stay completable to an even number: regular squads fit as long as `B = even(min(cap − oversized squads, (S − oversized seats) // base))` is at least their count. A new pair is only offered if this still holds afterwards. Completing a started pair is always possible (the whitelist and the cap never block a mirror) — as long as its seats are still free.
- **Off — single squads.** Any allowed size registers on its own while it fits the free infantry seats and the squad cap. Nothing is held back; splitting the teams is up to the organizers.

### Worked Examples

All on the event that motivated this mode: 100 server slots, 2 casters, 6 vehicle squads × 2, 2 heli squads × 1, base size 6 → `S = 84` infantry seats = exactly 14 squads of 6, no leftover. All oversized sizes allowed, no cap.

| | State | Offered (remaining) | Notes |
|---|---|---|---|
| A | Pair rule **off**, 11 × 6 registered (18 seats free) | 6 (3), 7 (2), 8 (2), 9 (2) | |
| | … + one 9 | 6 (1), 7 (1), 8 (1), 9 (1) | header `(12/13)` |
| | … + another 9 | — | 13 squads, 0 seats left |
| | … or + a 6 instead | — | **Unused: 3** |
| B | Pair rule **on**, 11 × 6 registered | 6 (3) | every new pair would leave room for only 10 regular squads — the 12th regular is held for an even count, the 12 seats left can't fit even a 7-pair (14). With the pair rule on, enable the mode early. |
| C | Pair rule **on**, empty event | 6 (14), 7 (12), 8 (10), 9 (8) | |
| | … + one 9 (mirror held) | 6 (10), 7 (8), 8 (8), 9 (7) | header `(1/12)`; 8 × 6 + 2 × 9-pairs would fill all 84 seats |
| D | Pair rule **off**, cap 1, 11 × 6 + one 9 | 6 (1) | **Unused: 3** |
| E | Mode switched **off** afterwards, 11 × 6 + two 9s | — | 13 squads < cap 14, but no seats left → a new 6 is waitlisted |

### Further Mechanics

- **Race safety.** The pick is re-validated under the guild lock when the name modal is submitted. If the size is gone in between (someone else took the seats, an admin changed the settings), the user gets a "size no longer available" error — never a silently different size.
- **Waitlist entries always use the base size.** Oversized squads exist only via direct registration. A waitlisted squad is promoted only if it fits under the same rules. The waitlist message tells the reason: all slots taken, slot held for an oversized squad's mirror, or not enough free seats.
- **Unregistering** frees the seats; a broken pair's mirror is held again (pair rule on).
- **Mode switched off** with oversized squads registered: no new oversized squads, nothing held back; regular squads only while the squad cap **and** the free seats allow.
- **Organizer overrides stay unchecked.** `/admin_edit_squad` may set any size, and DM-editor changes may shrink `S` (more vehicles, a smaller server, …). The bot tolerates the result: no new infantry registration until there's room again, no negative numbers anywhere, and a mirror is only held while it still fits.

## Player Mode

Nobody picks sizes — the bot plans the capacities from the **leftover pool** only (the seats no base squad can use):

- **Pre-planned layout.** Auto-created squads get their capacity from a deterministic layout: base-size squads first, the oversized squads last, chosen with the least waste, then the fewest oversized squads, preferring bigger squads. Pool 8, cap 14 → squads 1–10 as 6, then a 7-pair, then a 9-pair.
- **Pair rule.** On: oversized squads in pairs. Off: single oversized squads. Example: pool 3, base 6 → on: one 7-pair, 1 seat unused; off: one 9, nothing unused.
- **Consolidation re-plans.** At event start (or via the admin Consolidate button) the capacities are re-derived from the actual player count (88 players at base 6 → 12 × 6 + one 8-pair), then members are compacted into that layout. The per-unregister compaction does **not** re-plan.

## Display

- The infantry field header shows the registered count and how many squads can still fit in the best case — it drops as oversized squads register. Every size gets its own registered/possible counter: `⚔️ Infanterie (12/13) [(11/12) Größe: 6 | (0/1) Größe: 7 | (0/1) Größe: 8 | (1/2) Größe: 9]`. In player mode the counters reflect the planned layout.
- The **"Unused" counter** shows infantry seats that no further registration could fill even in the best case — never "Unused: 0". With the mode off it is the static leftover.

## Configuration

- **Wizard step "Oversized squads"** — rep mode: always (unless the base size is already 9). Player mode: only when at least 1 seat is left over. Contains the on/off select, the pair rule, the multi-select of allowed sizes (default: all) and the cap select (even values, default: unlimited).
- **DM editor** — property **22** toggles the mode (rejected only at base size 9; in player mode also without leftover, or with a single leftover seat while the pair rule is on); **23** allowed sizes as comma-separated text ("7, 8"; empty = all; values above the base size and at most 9); **24** the cap (at least 1; 0 or empty = unlimited); **26** the pair rule.
- Stored per event (`dont_waste_slots`, `dont_waste_pairs` — default on, `dont_waste_allowed_sizes`, `dont_waste_max_squads`), carried over to recurring follow-up events.

## Guarantees and Limits

Seeded random-walk tests (`tests/test_oversized_free_seats.py`, `TestFreeSeatInvariants`) drive register/unregister sequences through the real gate for both pair-rule settings and check after every step: the infantry seats and the squad cap are never overbooked, the cap on oversized squads holds, an offered size is always registrable (and only then), and — with the pair rule — every incomplete pair is completable and the regular count can still be made even.

Inherent limits no slot system can remove:

1. **Repairable, not enforced.** The bot guarantees a started pair can be completed — it cannot force anyone to register the mirror.
2. **Live counts float.** The *capacity* is even; the number of squads actually registered at start can be odd (no-shows).
3. **Organizer overrides** (see above) can leave the event overbooked; the bot then simply stops adding infantry until it fits again.
