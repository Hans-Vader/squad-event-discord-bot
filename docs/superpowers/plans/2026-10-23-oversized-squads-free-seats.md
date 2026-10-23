# Übergroße Squads aus allen freien Plätzen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Im Vertreter-Modus dürfen übergroße Infanterie-Squads jeden freien Infanterie-Platz nutzen. Die Paar-Regel wird pro Event schaltbar.

**Architecture:**
- Eine reine Funktion `infantry_block_reason(event, size)` in `bot/utils.py` entscheidet, ob ein Infanterie-Squad jetzt anmeldbar ist.
- Anmeldung, Admin-Anmeldung, Wartelisten-Nachrücken, Größen-Dropdown und Embed rechnen alle über diese Funktion bzw. über `infantry_best_case(event)`, die den besten erreichbaren Endzustand berechnet.
- Der Spieler-Modus behält seine Verschnitt-Planung und bekommt nur einen `unit`-Parameter (1 = einzeln, 2 = paarweise).

**Tech Stack:** Python 3.14, discord.py 2.x, `unittest` (kein pytest), SQLite über `bot/database.py`

**Spec:** `docs/superpowers/specs/2026-10-23-oversized-squads-free-seats-design.md`

## Global Constraints

- Tests laufen im Docker-Image `squadbot-test`, das es lokal schon gibt. Fehlt es, einmalig bauen:
  `printf 'FROM python:3.14-alpine\nRUN apk add --no-cache tzdata\nCOPY requirements.txt .\nRUN pip install -q --root-user-action=ignore -r requirements.txt\n' | docker build -q -t squadbot-test -f - .`
- Testbefehl (aus dem Repo-Root), im Plan **`TEST <modul>`** genannt:
  `docker run --rm -e DISCORD_BOT_TOKEN=x -u "$(id -u):$(id -g)" -v "$PWD":/src -w /src squadbot-test python -m unittest <modul> -v`
  Die ganze Suite: `... python -m unittest discover -s tests -p 'test_*.py'`. Vorher grün: 425 Tests.
- Keine neuen Dependencies.
- `MAX_SQUAD_PLAYERS = 9` bleibt die harte Obergrenze für jede Squad-Größe.
- Gespeicherte Felder bleiben `dont_waste_slots`, `dont_waste_allowed_sizes` und `dont_waste_max_squads`. Neu kommt `dont_waste_pairs` dazu (bool, Standard `True`, fehlt = `True`). Die i18n-Keys behalten den Präfix `dont_waste_*`.
- Sichtbarer Name der Option: „**Übergroße Squads**“ (DE) / „**Oversized squads**“ (EN). Jeder i18n-Key hat `de` **und** `en`.
- Infanterie nutzt nur das Infanterie-Platzbudget `S = max_player_slots − Fahrzeug-Plätze − Heli-Plätze`. Fahrzeug- und Heli-Plätze sind tabu.
- Kein automatischer Weg vergibt mehr Infanterie-Plätze als `S`. Manuelle Orga-Eingriffe (`/admin_edit_squad`, DM-Editor-Änderungen, die `S` verkleinern) bleiben ungeprüft.
- Code-Stil wie im Umfeld: Docstrings, englische Kommentare, `ponytail:`-Kommentare für bewusste Vereinfachungen.
- Jeder Commit endet mit der Zeile `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gearbeitet wird auf dem Branch `feat/oversized-free-seats`, nicht auf `master`.

## Review Focus

1. **Überbuchung nach Orga-Eingriff** (`S` verkleinert oder Squad auf über `free` vergrößert): kein Crash, keine negativen Zahlen in Kopfzeile oder „Ungenutzt“, keine neue Anmeldung. → Task 1 `test_overbooked_after_override`, Task 3 `test_overbooked_header_never_negative`.
2. **Paar-Regel nachträglich eingeschaltet** bei ungeraden Anzahlen aus der Zeit mit ausgeschalteter Regel. Gegenstücke, die nicht mehr passen, reservieren nichts. → Task 1 `test_unreachable_mirror_reserves_nothing`, Task 2 `test_switch_on_with_odd_counts`.
3. **Mini-Konfiguration** (Squad-Obergrenze `cap < 2`) mit aktiver Option und Paar-Regel an: Ein reguläres Squad muss anmeldbar bleiben. → Task 1 `test_tiny_cap_keeps_base_registrable`.
4. **Basis-Größe 1** (8 Übergrößen, große Squad-Obergrenze): Dropdown und Embed rechnen schnell, die Auswahl bleibt unter 25 Optionen. → Task 3 `test_base_one_is_fast`.
5. **Wartelisten-Eintrag kleiner als die Basis-Größe** (nach einer Größenänderung): Er rückt normal nach, wenn er passt. → Task 4 `test_stale_smaller_entry_promoted`.

---

## Gemeinsame Test-Fixtures

Alle neuen Tests kommen in **`tests/test_oversized_free_seats.py`**. Kopf der Datei (Task 1 legt ihn an, spätere Tasks ergänzen Klassen):

```python
#!/usr/bin/env python3
"""Oversized squads from all free infantry seats + configurable pair rule.

Spec: docs/superpowers/specs/2026-10-23-oversized-squads-free-seats-design.md
"""

import itertools
import os
import random
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
import database  # noqa: E402
import utils  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402

SIX11 = [6] * 11


def _dcn(**over):
    # The motivating event "Oktober DCN": 100 server − 2 casters = 98 player
    # seats, 6×2 vehicle + 2×1 heli → S = 84 infantry seats = exactly 14 × 6.
    ev = {"mode": "rep", "dont_waste_slots": True, "max_player_slots": 98,
          "infantry_squad_size": 6, "vehicle_squad_size": 2, "heli_squad_size": 1,
          "max_vehicle_squads": 6, "max_heli_squads": 2, "squads": {}}
    ev.update(over)
    return ev


def _squads(*sizes):
    return {f"s{i}": {"name": "x", "type": "infantry", "size": s} for i, s in enumerate(sizes)}


def _reason(ev, size):
    return utils.infantry_block_reason(ev, size)
```

---

### Task 1: Paar-Regel-Feld und zentrale Anmeldbarkeits-Prüfung

**Files:**
- Modify: `bot/utils.py` — Hilfsfunktionen neben `infantry_unused_pool` (~Z. 298–325), neue Funktion `infantry_block_reason` direkt vor `infantry_size_options` (~Z. 424)
- Modify: `bot/database.py:434-436` (Defaults), `bot/database.py:466-468` (`_CARRY_OVER_KEYS`)
- Modify: `bot/bot.py:459-461` (`_ensure_event_keys`-Defaults)
- Create: `tests/test_oversized_free_seats.py`
- Modify: `tests/test_dont_waste_slots.py` (`TestSizeOptions.test_active_gate`)

**Interfaces:**
- Produces (alle in `bot/utils.py`):
  - `dont_waste_pairs(event: dict) -> bool`: `bool(event.get("dont_waste_pairs", True))`
  - `infantry_seat_budget(event: dict) -> int`: `S`, nie negativ. `infantry_unused_pool` nutzt sie (DRY).
  - `_oversized_counts(event: dict) -> dict[int, int]`: angemeldete Infanterie-Squads mit `size > base`, nach Größe gezählt. Fehlende `size` zählt als `base`.
  - `_oversized_budget(event: dict, counts: dict | None = None) -> int | None`: Rest-Budget aus `dont_waste_max_squads`, `None` = unbegrenzt.
    - Paar-Regel an: wie das heutige `_max_pairs` (in Paaren, ein unvollständiges Paar zählt als 2).
    - Paar-Regel aus: `max(0, cap − Σcounts)` in Squads.
    - `_max_pairs` bleibt vorerst für den Spieler-Modus stehen, Task 5 entfernt es.
  - `_reserved_mirrors(event: dict, counts: dict) -> list[int]`: Größen mit ungerader Anzahl, aufsteigend. Eine Größe bleibt nur drin, solange `Anzahl + gehaltene + 1 ≤ cap` **und** `used + Σgehaltene + k ≤ S` gilt.
  - `_regular_capacity(event: dict, n_o: int, seats_o: int) -> int`: `raw = min(cap − n_o, (S − seats_o) // base)`. Ergebnis ist `raw`, wenn `cap < 2`, sonst `raw − raw % 2`.
  - `infantry_block_reason(event: dict, size: int) -> Optional[str]`: `None` = anmeldbar, sonst `"full"`, `"seats"`, `"mirror"` oder `"size"`.
  - `dont_waste_slots_possible(event)`, neue Semantik:
    - `False` bei `base ≥ MAX_SQUAD_PLAYERS`.
    - Vertreter-Modus: sonst `True`.
    - Spieler-Modus: `infantry_unused_pool(event) ≥ (2 if dont_waste_pairs(event) else 1)`.

- [ ] **Step 1: Branch anlegen und Spec + Plan committen**

```bash
git checkout -b feat/oversized-free-seats
git add docs/superpowers
git commit -m "docs: spec and plan for oversized squads from free seats" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 2: Failing tests schreiben** (Fixture-Kopf von oben, dazu):

```python
class TestPairRulePlumbing(unittest.TestCase):
    def test_default_carry_over_backfill(self):
        settings = dict(database.DEFAULT_GUILD_SETTINGS)
        self.assertIs(database.build_default_event(settings, "E", "01.01.2030", "20:00")["dont_waste_pairs"], True)
        self.assertIs(database.build_default_event(settings, "E", "01.01.2030", "20:00",
                                                   dont_waste_pairs=False)["dont_waste_pairs"], False)
        self.assertIn("dont_waste_pairs", database._CARRY_OVER_KEYS)
        ev = {}
        bot._ensure_event_keys(ev)
        self.assertIs(ev["dont_waste_pairs"], True)
        self.assertTrue(utils.dont_waste_pairs({}))
        self.assertFalse(utils.dont_waste_pairs({"dont_waste_pairs": False}))


class TestBlockReason(unittest.TestCase):
    def test_seat_budget(self):
        self.assertEqual(utils.infantry_seat_budget(_dcn()), 84)
        self.assertEqual(utils.infantry_unused_pool(_dcn()), 0)
        self.assertEqual(utils.infantry_seat_budget(_dcn(max_vehicle_squads=60)), 0)

    def test_rep_mode_active_without_leftover(self):
        self.assertTrue(utils.dont_waste_slots_active(_dcn()))
        self.assertFalse(utils.dont_waste_slots_active(_dcn(infantry_squad_size=9)))

    def test_example_a_pairs_off(self):
        ev = _dcn(dont_waste_pairs=False, squads=_squads(*SIX11))
        for k in (6, 7, 8, 9):
            self.assertIsNone(_reason(ev, k), k)
        ev = _dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9))
        for k in (6, 7, 8, 9):
            self.assertEqual(_reason(ev, k), "seats", k)

    def test_example_b_pairs_on_enabled_late(self):
        ev = _dcn(squads=_squads(*SIX11))
        self.assertIsNone(_reason(ev, 6))
        for k in (7, 8, 9):
            self.assertEqual(_reason(ev, k), "size", k)

    def test_example_c_pairs_on_enabled_early(self):
        self.assertIsNone(_reason(_dcn(), 9))
        ev = _dcn(squads=_squads(9, *[6] * 10))
        self.assertIsNone(_reason(ev, 9))               # mirror
        self.assertEqual(_reason(ev, 6), "mirror")
        # Pair complete, 10 regular: an 11th would make the regular count odd.
        self.assertEqual(_reason(_dcn(squads=_squads(9, 9, *[6] * 10)), 6), "full")

    def test_example_d_max_one_pairs_off(self):
        ev = _dcn(dont_waste_pairs=False, dont_waste_max_squads=1, squads=_squads(*SIX11, 9))
        self.assertIsNone(_reason(ev, 6))
        self.assertEqual(_reason(ev, 7), "size")
        self.assertEqual(_reason(ev, 9), "size")

    def test_example_e_mode_off_checks_seats(self):
        ev = _dcn(dont_waste_slots=False, dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9))
        self.assertEqual(_reason(ev, 6), "seats")       # 13 < cap 14, but 0 seats left

    def test_mode_off_no_oversize_no_reservation(self):
        self.assertEqual(_reason(_dcn(dont_waste_slots=False), 7), "size")
        self.assertIsNone(_reason(_dcn(dont_waste_slots=False, squads=_squads(9, *[6] * 10)), 6))

    def test_whitelist(self):
        ev = _dcn(dont_waste_pairs=False, dont_waste_allowed_sizes=[7])
        self.assertIsNone(_reason(ev, 7))
        self.assertEqual(_reason(ev, 8), "size")
        # Pairs on: the mirror of a no-longer-allowed size stays registerable — only the mirror.
        self.assertIsNone(_reason(_dcn(dont_waste_allowed_sizes=[7], squads=_squads(9)), 9))
        self.assertEqual(_reason(_dcn(dont_waste_allowed_sizes=[7], squads=_squads(9, 9)), 9), "size")

    def test_max_cap(self):
        self.assertEqual(_reason(_dcn(dont_waste_max_squads=2, squads=_squads(9, 9)), 7), "size")
        self.assertIsNone(_reason(_dcn(dont_waste_max_squads=2, squads=_squads(9, 9, 7)), 7))  # mirror beats cap
        self.assertIsNone(_reason(_dcn(dont_waste_pairs=False, dont_waste_max_squads=3,
                                       squads=_squads(9, 9)), 7))
        self.assertEqual(_reason(_dcn(dont_waste_pairs=False, dont_waste_max_squads=3,
                                      squads=_squads(9, 9, 7)), 7), "size")

    def test_tiny_cap_keeps_base_registrable(self):
        ev = _dcn(max_player_slots=8, max_vehicle_squads=0, max_heli_squads=0)  # S 8, cap 1
        self.assertIsNone(_reason(ev, 6))
        self.assertEqual(_reason(ev, 7), "size")

    def test_unreachable_mirror_reserves_nothing(self):
        # Pair rule switched on after pairs-off sign-ups: 10×6 + 9 + 8 = 77, 7 free.
        ev = _dcn(squads=_squads(*[6] * 10, 9, 8))
        self.assertEqual(_reason(ev, 9), "seats")
        self.assertEqual(_reason(ev, 8), "seats")
        self.assertEqual(_reason(ev, 6), "full")        # no reservation; parity blocks the 11th

    def test_overbooked_after_override(self):
        self.assertEqual(_reason(_dcn(max_vehicle_squads=7, squads=_squads(*[6] * 14)), 6), "full")
        self.assertEqual(_reason(_dcn(squads=_squads(*[6] * 12, 12)), 6), "seats")
```

In `tests/test_dont_waste_slots.py` wird `TestSizeOptions.test_active_gate` an die neue Semantik angepasst: Rep bei U=1 → `True`; neu `self.assertTrue(utils.dont_waste_slots_active(_event(max_player_slots=86)))` (U=0); Spieler bei U=1 → `False`, bei U=1 und `dont_waste_pairs=False` → `True`. Alle übrigen Zeilen bleiben.

- [ ] **Step 3: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: FAIL/ERROR (`AttributeError: module 'utils' has no attribute 'infantry_block_reason'` u. ä.)

- [ ] **Step 4: Implementieren**

Hilfsfunktionen und `dont_waste_slots_possible` wie im Interfaces-Block. Default `"dont_waste_pairs": overrides.get("dont_waste_pairs", True)` in `build_default_event`, `"dont_waste_pairs": True` in `_ensure_event_keys`, Key in `_CARRY_OVER_KEYS` hinter `dont_waste_max_squads`.

`infantry_block_reason`, Entscheidungsreihenfolge (erster Treffer gewinnt):

Werte:
- `inf` = angemeldete Infanterie-Squads, `used` = Σ Größen (fehlend = `base`), `count = len(inf)`, `cap = _max_squads_for_type(event, "infantry")`, `S = infantry_seat_budget(event)`.
- `active = mode != "player" and dont_waste_slots_active(event)`, `pairs = dont_waste_pairs(event)`.
- `counts = _oversized_counts(event)`, `held = _reserved_mirrors(event, counts) if pairs else []`.
- `n_o = Σcounts + len(held)`, `seats_o = Σ k·counts[k] + Σheld`, `n_regular` = Squads mit `size ≤ base`.

Regeln:
1. `count + 1 > cap` → `"full"`
2. `size > S − used` → `"seats"`
3. `size > base`:
   - a. `not active` → `"size"`
   - b. `pairs` und `counts[size]` ungerade → `None` (Gegenstück; Whitelist und Limit blockieren es nie)
   - c. Größe nicht erlaubt (`dont_waste_allowed_sizes` oder `> MAX_SQUAD_PLAYERS`) → `"size"`
   - d. `_oversized_budget(event, counts)` ist nicht `None` und `< 1` → `"size"`
   - e. `pairs` und `_regular_capacity(event, n_o + 2, seats_o + 2·size) < n_regular` → `"size"`
   - f. sonst → `None`
4. `size ≤ base`:
   - a. `active and pairs` und `n_regular + 1 > _regular_capacity(event, n_o, seats_o)` → `"mirror"`, wenn `held` nicht leer ist, sonst `"full"`
   - b. sonst → `None`

- [ ] **Step 5: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats` und die ganze Suite.
Expected: PASS, die Suite grün.

- [ ] **Step 6: Commit**

```bash
git add bot/utils.py bot/database.py bot/bot.py tests/test_oversized_free_seats.py tests/test_dont_waste_slots.py
git commit -m "feat: central infantry registerability check with configurable pair rule" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Größen-Angebot aus allen freien Plätzen

**Files:**
- Modify: `bot/utils.py` — `infantry_size_options` (~Z. 424–485) neu schreiben
- Modify: `tests/test_oversized_free_seats.py`, `tests/test_dont_waste_slots.py`

**Interfaces:**
- Consumes: `infantry_block_reason`, `_oversized_counts`, `dont_waste_slots_active` (Task 1)
- Produces: `infantry_size_options(event: dict) -> list[tuple[int, int]]` mit gleicher Signatur und neuer Semantik.
  - Spieler-Modus: unverändert `[(base, max(0, cap − count))]`.
  - Vertreter-Modus: `(base, Rest)` steht immer an erster Stelle. Ist die Option aktiv, folgt jede Größe aus `sorted(set(_oversized_counts) | erlaubte Größen base+1..9)` mit Rest > 0.
  - **Rest** = wie oft genau diese Größe auf einer Kopie (`{**event, "squads": dict(event["squads"])}`) hintereinander anmeldbar ist, solange `infantry_block_reason(...) is None`. Damit gilt per Konstruktion: Rest > 0 ⇔ Prüfung lässt zu.

- [ ] **Step 1: Failing tests schreiben**

```python
class TestSizeOptionsFreeSeats(unittest.TestCase):
    def _opts(self, **over):
        return utils.infantry_size_options(_dcn(**over))

    def test_example_a(self):
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11)),
                         [(6, 3), (7, 2), (8, 2), (9, 2)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9)),
                         [(6, 1), (7, 1), (8, 1), (9, 1)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9)), [(6, 0)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6)), [(6, 0)])

    def test_example_b(self):
        self.assertEqual(self._opts(squads=_squads(*SIX11)), [(6, 3)])

    def test_example_c(self):
        self.assertEqual(self._opts(), [(6, 14), (7, 12), (8, 10), (9, 8)])
        self.assertEqual(self._opts(squads=_squads(9)), [(6, 10), (7, 8), (8, 8), (9, 7)])

    def test_example_d_and_e(self):
        self.assertEqual(self._opts(dont_waste_pairs=False, dont_waste_max_squads=1,
                                    squads=_squads(*SIX11, 9)), [(6, 1)])
        self.assertEqual(self._opts(dont_waste_slots=False, dont_waste_pairs=False,
                                    squads=_squads(*SIX11, 9, 9)), [(6, 0)])

    def test_switch_on_with_odd_counts(self):
        self.assertEqual(self._opts(squads=_squads(*SIX11, 9)), [(6, 0), (9, 1)])
        self.assertEqual(self._opts(squads=_squads(*[6] * 10, 9, 8)), [(6, 0)])

    def test_player_mode_and_edge_inputs(self):
        self.assertEqual(self._opts(mode="player"), [(6, 14)])
        legacy = _dcn(squads={"s0": {"name": "x", "type": "infantry"}})
        self.assertEqual(utils.infantry_size_options(legacy), self._opts(squads=_squads(6)))
        veh = _dcn(squads={"v": {"type": "vehicle", "size": 2}, "h": {"type": "heli", "size": 1}})
        self.assertEqual(utils.infantry_size_options(veh), self._opts())


class TestFreeSeatInvariants(unittest.TestCase):
    """Seeded random walks through the real gate, both pair rules."""

    CONFIGS = [dict(), dict(max_player_slots=90), dict(max_player_slots=91),
               dict(dont_waste_allowed_sizes=[7, 9]), dict(dont_waste_max_squads=2),
               dict(dont_waste_max_squads=3),
               dict(infantry_squad_size=7, max_vehicle_squads=0, max_heli_squads=0),
               dict(max_player_slots=8, max_vehicle_squads=0, max_heli_squads=0),
               dict(infantry_squad_size=1, max_player_slots=40, max_vehicle_squads=0, max_heli_squads=0)]

    _ids = itertools.count()

    def _add(self, ev, size):
        ev["squads"][f"p{next(self._ids)}"] = {"name": "x", "type": "infantry", "size": size}

    def _check(self, ev, trace):
        base, pairs = ev["infantry_squad_size"], utils.dont_waste_pairs(ev)
        S, cap = utils.infantry_seat_budget(ev), utils._max_squads_for_type(ev, "infantry")
        inf = list(ev["squads"].values())
        ctx = f"pairs={pairs} trace={trace}"
        self.assertLessEqual(sum(d["size"] for d in inf), S, ctx)
        self.assertLessEqual(len(inf), cap, ctx)
        counts = utils._oversized_counts(ev)
        if ev.get("dont_waste_max_squads"):
            m = ev["dont_waste_max_squads"]
            used = sum(c + (c % 2 if pairs else 0) for c in counts.values())
            self.assertLessEqual(used, m - m % 2 if pairs else m, ctx)
        opts = dict(utils.infantry_size_options(ev))
        for k in range(base, utils.MAX_SQUAD_PLAYERS + 1):
            self.assertEqual(opts.get(k, 0) > 0, utils.infantry_block_reason(ev, k) is None, f"{k} {ctx}")
        if pairs:
            probe = {**ev, "squads": dict(ev["squads"])}
            for k in sorted(k for k, c in counts.items() if c % 2):
                self.assertIsNone(utils.infantry_block_reason(probe, k), f"mirror {k} {ctx}")
                self._add(probe, k)
            self.assertFalse(any(c % 2 for c in utils._oversized_counts(probe).values()), ctx)
            n_reg = sum(1 for d in probe["squads"].values() if d["size"] <= base)
            if n_reg % 2 and cap >= 2:
                self.assertIsNone(utils.infantry_block_reason(probe, base), f"parity {ctx}")

    def test_random_walks(self):
        rng = random.Random(42)
        for cfg in self.CONFIGS:
            for pairs in (True, False):
                for _run in range(10):
                    ev = _dcn(dont_waste_pairs=pairs, **cfg)
                    trace = []
                    for _step in range(150):
                        if rng.random() < 0.6 or not ev["squads"]:
                            k = rng.choice([s for s, _ in utils.infantry_size_options(ev)])
                            if utils.infantry_block_reason(ev, k) is None:
                                self._add(ev, k)
                                trace.append(f"+{k}")
                        else:
                            sid = rng.choice(sorted(ev["squads"]))
                            trace.append(f"-{ev['squads'].pop(sid)['size']}")
                        self._check(ev, trace[-12:])
```

In `tests/test_dont_waste_slots.py` die Tests **löschen**, deren Verschnitt-Semantik im Vertreter-Modus nicht mehr gilt:

- **`TestSizeOptions`:** `test_no_pool_base_only`, `test_initial_options_u4`, `test_pool_constrains_next_offers`, `test_pair_completion_and_exhaustion`, `test_unregister_reoffers_and_resets`, `test_odd_leftover_stays_unused`, `test_pair_rule_uses_leftover_pool`, `test_allowed_sizes_whitelist`, `test_whitelist_never_blocks_a_mirror`, `test_minimal_count_priority`, `test_wasted_seats`, `test_mirror_slot_reservation`, `test_fresh_pair_needs_two_squad_slots`, `test_config_shrink_clamps`, `test_legacy_squads_without_size`, `test_vehicle_heli_ignored`, `test_new_pair_needs_two_free_squad_slots`, `test_multiple_pending_mirrors_all_reserved`.
- **`TestSizeOptions.test_odd_base_cap_rounds_down_and_feeds_pool`:** nur den ersten `assertEqual`-Block mit `[(6, 14), (7, 2), (9, 2)]` entfernen. Die Teile mit ausgeschalteter Option und die Mini-Konfiguration bleiben.
- **`TestSelectValuePlumbing`:** `test_squad_type_options_locked_size` löschen. `test_squad_type_options_mode_on_expanded` erwartet jetzt `["infantry", "infantry:7", "infantry:8", "infantry:9", "vehicle", "heli"]`, das Label von `infantry:7` enthält `"10x"`.
- **`TestPairingInvariants`:** komplett löschen, ersetzt durch `TestFreeSeatInvariants`.
- **`TestMaxSquadsCap.test_options_offer_only_capped_plan`:** löschen. Ein Limit von 2 erlaubt jetzt ein Paar *jeder* Größe.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: FAIL in `TestSizeOptionsFreeSeats` (alte Verschnitt-Werte, z. B. `[(6, 3)]` statt `[(6, 3), (7, 2), …]`)

- [ ] **Step 3: `infantry_size_options` wie im Interfaces-Block implementieren**

Den Docstring auf die neue Semantik umschreiben. `_pair_plan` wird im Vertreter-Modus nicht mehr verwendet.

- [ ] **Step 4: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats`, `TEST tests.test_dont_waste_slots`, ganze Suite.
Expected: alles PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/utils.py tests/test_oversized_free_seats.py tests/test_dont_waste_slots.py
git commit -m "feat: offer every oversized size that fits the free infantry seats" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Bester erreichbarer Zustand → „Ungenutzt“ und Kopfzeile

**Files:**
- Modify: `bot/utils.py` — neue Funktion `infantry_best_case` vor `infantry_wasted_seats`; `infantry_wasted_seats` (~Z. 488–518) Vertreter-Zweig; `format_event_details` (~Z. 1473–1510, Infanterie-Max in der Kopfzeile)
- Modify: `tests/test_oversized_free_seats.py`, `tests/test_dont_waste_slots.py`

**Interfaces:**
- Consumes: Task 1 (`_oversized_counts`, `_reserved_mirrors`, `_regular_capacity`, `_oversized_budget`, `dont_waste_pairs`, `infantry_seat_budget`)
- Produces:
  - `infantry_best_case(event: dict) -> tuple[int, int]`: `(maximal belegbare Infanterie-Plätze, maximale Squad-Anzahl)`, erreichbar durch weitere Vertreter-Anmeldungen nach den Regeln aus Task 1. Beide Werte sind mindestens `(used, count)`.
  - `infantry_wasted_seats(event)`:
    - Spieler-Zweig unverändert.
    - Vertreter-Zweig: `max(0, infantry_seat_budget(event) − infantry_best_case(event)[0])`.
  - `format_event_details`: im Vertreter-Modus mit aktiver Option ist `max_inf_squads` für die Kopfzeile `infantry_best_case(event)[1]`. Das wird **nach** der statischen `unused`-Berechnung gesetzt. Die Pro-Größe-Zähler stammen weiter aus `infantry_size_options`, ohne Codeänderung.

- [ ] **Step 1: Failing tests schreiben**

```python
def _dcn_embed(**over):
    ev = _dcn(name="Test Event", date="01.01.2099", time="20:00", server_max_players=100,
              max_caster_slots=2, player_slots_used=0, caster_slots_used=0, casters={},
              infantry_waitlist=[], vehicle_waitlist=[], heli_waitlist=[], caster_waitlist=[],
              tentative=[], declined=[])
    ev.update(over)
    return ev


class TestBestCaseAndEmbed(unittest.TestCase):
    def _embed(self, **over):
        return utils.format_event_details(_dcn_embed(**over), "de")

    def _inf_name(self, embed):
        return next(f.name for f in embed.fields if "Infan" in f.name)

    def _values(self, embed):
        return "\n".join(str(f.value) for f in embed.fields)

    def test_best_case_values(self):
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9))), (84, 13))
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6))), (81, 13))
        self.assertEqual(utils.infantry_best_case(_dcn(squads=_squads(9))), (84, 12))
        self.assertEqual(utils.infantry_best_case(_dcn(squads=_squads(9, 9, *[6] * 10))), (78, 12))
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, dont_waste_max_squads=1,
                                                       squads=_squads(*SIX11, 9))), (81, 13))

    def test_header_example_a(self):
        name = self._inf_name(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11, 9)))
        self.assertIn("(12/13) [(11/12) Größe: 6 | (0/1) Größe: 7 | (0/1) Größe: 8 | (1/2) Größe: 9]", name)

    def test_header_example_b_plain(self):
        self.assertIn("(11/14) [Größe: 6]", self._inf_name(self._embed(squads=_squads(*SIX11))))

    def test_header_example_c(self):
        name = self._inf_name(self._embed(squads=_squads(9)))
        self.assertIn("(1/12) [(0/10) Größe: 6 | (0/8) Größe: 7 | (0/8) Größe: 8 | (1/8) Größe: 9]", name)

    def test_unused(self):
        self.assertIn("Ungenutzt: 3", self._values(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6))))
        self.assertIn("Ungenutzt: 6", self._values(self._embed(squads=_squads(9, 9, *[6] * 10))))
        self.assertNotIn("Ungenutzt", self._values(self._embed(squads=_squads(9))))       # best case fills 84
        self.assertNotIn("Ungenutzt", self._values(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11))))

    def test_overbooked_header_never_negative(self):
        embed = self._embed(max_vehicle_squads=7, squads=_squads(*[6] * 14))
        self.assertIn("(14/14)", self._inf_name(embed))
        self.assertNotIn("Ungenutzt", self._values(embed))
        self.assertEqual(utils.infantry_wasted_seats(_dcn(squads=_squads(*[6] * 12, 12))), 0)

    def test_base_one_is_fast(self):
        for pairs in (True, False):
            ev = _dcn(infantry_squad_size=1, max_player_slots=200, max_vehicle_squads=0,
                      max_heli_squads=0, dont_waste_pairs=pairs)
            t0 = time.monotonic()
            opts = utils.infantry_size_options(ev)
            utils.infantry_best_case(ev)
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertLessEqual(len(opts), 9)
```

In `tests/test_dont_waste_slots.py` die vier Verschnitt-Kopfzeilen-Tests löschen: `TestEmbedHeader.test_oversized_sizes_shown_in_header`, `test_header_after_nine_pair_offers_seven`, `test_header_shows_possible_sizes_before_any_register`, `test_header_user_example`. Die übrigen `TestEmbedHeader`-Tests und `TestMaxSquadsCap.test_cap_reached_stops_offers_and_reports_waste`, `test_empty_state_cap_floor_reported`, `test_cap_floor_accounts_for_registrations` und `test_mirror_completion_beats_cap` **bleiben unverändert**. Sie gelten mit den neuen Formeln weiter, die Werte wurden vorab nachgerechnet.

In `TestFreeSeatInvariants._check` (Task 2) zusätzlich `self.assertGreaterEqual(utils.infantry_wasted_seats(ev), 0)`.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: ERROR `no attribute 'infantry_best_case'`

- [ ] **Step 3: `infantry_best_case` implementieren**

Dieser Algorithmus ist durch Signatur und Tests nicht festgelegt. Seat-Summen sind klein (≤ `S`), deshalb reicht eine Mengen-DP:

```text
sizes = erlaubte Übergrößen (base+1..9, Whitelist), leer wenn Option nicht aktiv
Paar-Regel aus (oder Option inaktiv):
  L = max(0, cap − count), F = max(0, S − used), M = L bzw. min(_oversized_budget, L)
  reach[o] = {Seat-Summen genau o weiterer Übergrößen ≤ F}, o = 0..M (reach[0] = {0})
  seats = max(used + a + min(L − o, (F − a)//base)·base) über alle o, a mit L − o ≥ 0
  squads = count + min(L, F // base)
Paar-Regel an:
  erst reservierte Gegenstücke (_reserved_mirrors) als angemeldet zählen → used', count', counts'
  n_o, seats_o wie Task 1 (mit den restlichen gehaltenen Gegenstücken), n_reg = reguläre Squads
  P = (cap − n_o)//2, ggf. min(_oversized_budget)
  reach[p] = {Seat-Summen von p neuen Paaren (je 2k) mit seats_o + a ≤ S}, p = 0..P
  für jedes p, a: B = _regular_capacity(event, n_o + 2p, seats_o + a); B < n_reg → überspringen
     seats = used' + a + (B − n_reg)·base ; squads = count' + 2p + (B − n_reg)
  Maximum jeweils, mindestens (used, count)
```

Den Vertreter-Zweig von `infantry_wasted_seats` und das Kopfzeilen-Max in `format_event_details` wie im Interfaces-Block anpassen.

- [ ] **Step 4: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats`, `TEST tests.test_dont_waste_slots`, ganze Suite.
Expected: alles PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/utils.py tests/test_oversized_free_seats.py tests/test_dont_waste_slots.py
git commit -m "feat: best-case unused seats and squad max for free-seat oversized squads" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Anmeldewege an die zentrale Prüfung anschließen

**Files:**
- Modify: `bot/bot.py` — `_squad_slot_reserved` (Z. 970–980) **löschen**, an seiner Stelle `_squad_gate` anlegen.
  - `register_squad` (Z. ~1215–1260): Gate-Block und Ergebnis-Zweige
  - `_AdminSquadNameModal.on_submit` (Z. ~3605–3640): gleicher Umbau
  - `_process_squad_waitlist` (Z. 1649–1650): Infanterie über die Prüfung
  - Import von `infantry_block_reason` aus `utils` (Z. ~52)
- Modify: `tests/test_oversized_free_seats.py`, `tests/test_dont_waste_slots.py` (`TestSelectValuePlumbing.test_slot_reserved_helper` löschen)

**Interfaces:**
- Consumes: `infantry_block_reason` (Task 1)
- Produces: `_squad_gate(event: dict, squad_type: str, size: int, requested_size: int | None) -> tuple[int, str]` in `bot/bot.py`. Rückgabe ist `(zu registrierende Größe, Ergebnis)`, Ergebnis eines von `"ok"`, `"unavailable"`, `"full"`, `"mirror"`, `"seats"`:
  - Nicht-Infanterie: `"full"`, wenn `_is_squad_type_full`, sonst `"ok"`.
  - Infanterie mit `requested_size` (gesetzt und `!= size`): `(requested_size, "ok")`, wenn die Prüfung `None` liefert, sonst `(requested_size, "unavailable")`.
  - Infanterie ohne `requested_size`: Grund aus `infantry_block_reason(event, size)`. Dabei wird `None` zu `"ok"` und `"size"` zu `"full"`, `"full"`/`"mirror"`/`"seats"` bleiben unverändert.

So nutzen die beiden Aufrufer das Ergebnis:

| Ergebnis | `register_squad` | Admin-Modal |
|---|---|---|
| `"unavailable"` | `squad.size_unavailable`, Abbruch (wie heute) | `squad.size_unavailable`, Abbruch (wie heute) |
| `"full"` | `type_full`-Warteliste, Meldung `squad.type_full` | Zweig `admin.squad_type_full_waitlist` |
| `"mirror"` | `type_full`-Warteliste, Meldung `squad.waitlisted_mirror` | Zweig `admin.squad_type_full_waitlist` |
| `"seats"` | Warteliste mit `squad.waitlisted` („Nicht genügend Plätze!“) | Zweig `admin.squad_added_waitlist` |
| `"ok"` | bestehender Zweig `size <= available` | bestehender Zweig `size <= available` |

`_process_squad_waitlist`: Für Infanterie gilt `type_full = infantry_block_reason(event, size) is not None`, sonst wie bisher `_is_squad_type_full`. Die Bedingung `size <= remaining` bleibt. `/admin_edit_squad` wird **nicht** geändert (Spec §5.6).

- [ ] **Step 1: Failing tests schreiben**

```python
class TestSquadGate(unittest.TestCase):
    def test_regular_outcomes(self):
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*SIX11)), "infantry", 6, None), (6, "ok"))
        self.assertEqual(bot._squad_gate(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9)),
                                         "infantry", 6, None), (6, "seats"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(9, *[6] * 10)), "infantry", 6, None), (6, "mirror"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*[6] * 14)), "infantry", 6, None), (6, "full"))

    def test_oversized_pick(self):
        self.assertEqual(bot._squad_gate(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11)),
                                         "infantry", 6, 9), (9, "ok"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*SIX11)), "infantry", 6, 9), (9, "unavailable"))

    def test_other_types_count_only(self):
        full = _dcn(squads={f"v{i}": {"type": "vehicle", "size": 2} for i in range(6)})
        self.assertEqual(bot._squad_gate(full, "vehicle", 2, None), (2, "full"))
        self.assertEqual(bot._squad_gate(_dcn(), "heli", 1, None), (1, "ok"))


class TestWaitlistPromotion(unittest.IsolatedAsyncioTestCase):
    async def _promote(self, ev, free):
        with patch.object(bot, "save_event"), \
             patch.object(bot, "_send_squad_dm", new=AsyncMock()), \
             patch.object(bot, "send_to_log_channel", new=AsyncMock()), \
             patch.object(bot, "get_guild_language", return_value="de"), \
             patch.object(bot, "_build_event_message_link", return_value=None):
            await bot._process_squad_waitlist(ev, {}, 1, 1, 2, free, freed_type="infantry")

    def _ev(self, squads, entry_size=6, **over):
        return _dcn(squads=_squads(*squads), player_slots_used=0, vehicle_waitlist=[], heli_waitlist=[],
                    infantry_waitlist=[("W", "infantry", entry_size, "w1", "Rep")], **over)

    async def test_no_promotion_without_infantry_seats(self):
        # Example E: option switched off after a pairs-off 9er pair — 13 < cap 14, but 0 seats.
        ev = self._ev([*SIX11, 9, 9], dont_waste_slots=False, dont_waste_pairs=False)
        await self._promote(ev, 6)
        self.assertNotIn("w1", ev["squads"])

    async def test_promotion_when_seats_free(self):
        ev = self._ev([*SIX11, 9], dont_waste_pairs=False)
        await self._promote(ev, 9)
        self.assertIn("w1", ev["squads"])

    async def test_stale_smaller_entry_promoted(self):
        ev = self._ev([6] * 13, entry_size=5)
        await self._promote(ev, 6)
        self.assertIn("w1", ev["squads"])
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: ERROR `no attribute '_squad_gate'`, und `test_no_promotion_without_infantry_seats` schlägt fehl. Die alte Logik prüft bei ausgeschalteter Option nur die Squad-Anzahl (13 < 14) und promotet.

- [ ] **Step 3: `_squad_gate` implementieren und die drei Aufrufstellen umbauen** (Tabelle oben). Den Kommentar an der `type_full_waitlisted`-Meldung beibehalten.

- [ ] **Step 4: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats`, ganze Suite.
Expected: alles PASS. `grep -n "_squad_slot_reserved" bot tests -r` liefert keine Treffer.

- [ ] **Step 5: Commit**

```bash
git add bot/bot.py tests/test_oversized_free_seats.py tests/test_dont_waste_slots.py
git commit -m "feat: route rep, admin and waitlist registration through the infantry gate" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Paar-Regel im Spieler-Modus

**Files:**
- Modify: `bot/utils.py` — `_allowed_extras` (Z. 328), `_max_pairs` (Z. 338, **löschen**), `_pair_plan` (Z. 350), `_pair_cover` (Z. 375), `planned_infantry_capacities` (Z. 405), `infantry_wasted_seats` Spieler-Zweig, `_replan_player_capacities` (Z. ~628)
- Modify: `tests/test_oversized_free_seats.py`

**Interfaces:**
- Consumes: `dont_waste_pairs`, `_oversized_budget` (Task 1)
- Produces:
  - `_plan_unit(event: dict) -> int`: `2 if dont_waste_pairs(event) else 1`
  - `_pair_plan(free_pool, extras, max_pairs=None, unit=2)` und `_pair_cover(target, extras, max_pairs=None, unit=2)`: Ein Coin ist `unit · extra`, `max_pairs` zählt Einheiten. Die Rückgabe bleibt `{extra: anzahl_einheiten}`. Mit dem Default `unit=2` bleiben die bestehenden Tests unverändert.
  - `_allowed_extras(event, free_pool)`: obere Grenze `base + free_pool // _plan_unit(event)`.
  - Die drei Spieler-Aufrufer übergeben `unit=_plan_unit(event)` und `_oversized_budget(event)` statt `_max_pairs(event)`. Beim Auffächern wird aus `range(2 * pairs)` jetzt `range(unit * n)`, die absorbierten Plätze sind `unit · extra · n`.

- [ ] **Step 1: Failing tests schreiben**

```python
def _pev(**over):
    # 27 seats, base 6 → cap 4, leftover pool 3.
    ev = _dcn(mode="player", max_player_slots=27, max_vehicle_squads=0, max_heli_squads=0,
              player_slots_used=0, infantry_waitlist=[])
    ev.update(over)
    return ev


class TestPlayerModePairRule(unittest.TestCase):
    def test_layout_pool_three(self):
        self.assertEqual(utils.planned_infantry_capacities(_pev()), [6, 6, 7, 7])
        self.assertEqual(utils.infantry_wasted_seats(_pev()), 1)
        self.assertEqual(utils.planned_infantry_capacities(_pev(dont_waste_pairs=False)), [6, 6, 6, 9])
        self.assertEqual(utils.infantry_wasted_seats(_pev(dont_waste_pairs=False)), 0)

    def test_single_leftover_seat(self):
        self.assertFalse(utils.dont_waste_slots_active(_pev(max_player_slots=25)))
        self.assertEqual(utils.planned_infantry_capacities(_pev(max_player_slots=25)), [6, 6, 6, 6])
        ev = _pev(max_player_slots=25, dont_waste_pairs=False)
        self.assertTrue(utils.dont_waste_slots_active(ev))
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 7])

    def test_max_cap_counts_squads(self):
        ev = _pev(max_player_slots=44, dont_waste_pairs=False)           # cap 6, pool 8
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 8, 9, 9])
        ev["dont_waste_max_squads"] = 1
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 6, 6, 9])
        self.assertEqual(utils.infantry_wasted_seats(ev), 5)

    def test_consolidation_singles(self):
        ev, ua = _pev(dont_waste_pairs=False), {}
        for i in range(27):
            utils._player_register(ev, ua, f"u{i}", f"P{i}", "infantry")
        utils.consolidate_all_player_squads(ev, ua)
        self.assertEqual(sorted(d["size"] for d in ev["squads"].values()), [6, 6, 6, 9])
        self.assertEqual(sum(len(d["members"]) for d in ev["squads"].values()), 27)
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: FAIL. Bei ausgeschalteter Paar-Regel wird noch paarweise geplant, z. B. `[6, 6, 7, 7]` statt `[6, 6, 6, 9]`.

- [ ] **Step 3: Implementieren** wie im Interfaces-Block. Die Docstrings von `_pair_plan`/`_pair_cover` nennen `unit`.

- [ ] **Step 4: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats`, `TEST tests.test_dont_waste_slots`, ganze Suite.
Expected: alles PASS. `grep -n "_max_pairs" bot tests -r` liefert keine Treffer.

- [ ] **Step 5: Commit**

```bash
git add bot/utils.py tests/test_oversized_free_seats.py
git commit -m "feat: pair rule switch for player-mode capacity planning" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wizard, Bestätigung, DM-Editor, Texte

**Files:**
- Modify: `bot/bot.py`:
  - `_EDIT_PROPERTIES` (Z. 115–144) und der `ponytail:`-Kommentar darunter
  - `_apply_property_change` (Z. 4257–4271)
  - `_advance_to_dont_waste_or_confirmation` und `WizardDontWasteSlotsView` (Z. 5945–6075)
  - `_build_confirmation_embed` (Z. 6138–6148)
- Modify: `bot/i18n.py` (Keys unten)
- Modify: `tests/test_oversized_free_seats.py`, `tests/test_dont_waste_slots.py` (`TestModelPlumbing.test_enable_via_editor_requires_unused_slots`, `TestMaxSquadsCap.test_editor_validation`, `TestI18nKeys.KEYS`)

**Interfaces:**
- Consumes: `dont_waste_pairs`, `infantry_seat_budget`, `infantry_unused_pool` (utils)
- Produces:
  - `_dont_waste_step_available(event: dict) -> bool` in `bot/bot.py`: `base < MAX_SQUAD_PLAYERS and (not is_player_mode(event) or infantry_unused_pool(event) >= 1)`. Dieser Helper steuert den Wizard-Schritt **und** das Summary-Feld, er ersetzt dort `dont_waste_slots_possible`.
  - Neue Eigenschaftszeile `(26, "dont_waste_pairs", "edit.property.dont_waste_pairs", "bool", None)`.
  - `WizardDontWasteSlotsView`, Zeilenbelegung:
    - row 0: `mode_select`
    - row 1: **`pairs_select`** (Werte `"yes"`/`"no"`, Default aus `dont_waste_pairs(event)`, speichert `dont_waste_pairs`)
    - row 2: `sizes_select`
    - row 3: `max_select`
    - row 4: Buttons
- Regeln:
  - **Wizard-Text:** Vertreter-Modus nutzt `wizard.dont_waste_step_desc` (ohne Platzhalter), Spieler-Modus `wizard.dont_waste_step_desc_player` (mit `{unused}`).
  - **Größen-Kandidaten:** Vertreter-Modus `base+1..9`, Spieler-Modus `base+1..min(base + pool, 9)`.
  - **Max-Auswahl:** `max_total` ist im Vertreter-Modus `min(_get_max_infantry_squads(event), infantry_seat_budget(event) // (base + 1))` und im Spieler-Modus `min(_get_max_infantry_squads(event), pool)`. Angeboten werden gerade Werte `2..min(max_total, 48)` plus „unbegrenzt“, also höchstens 25 Optionen. Die Auswahl erscheint ab `max_total ≥ 4`.
  - **Bestätigung:** Ist die Option aktiv, hängt der Wert `" · " + t("wizard.summary_dont_waste_pairs_on"/"_off")` an.
  - **Editor, Max-Wert:** Werte `< 1` werden mit `edit.dont_waste_max_invalid` abgelehnt, ungerade sind erlaubt.
  - **Editor, Aktivieren:**
    - `base ≥ 9` → `edit.dont_waste_max_size`
    - nur im Spieler-Modus: Verschnitt 0 → `edit.dont_waste_no_unused`, Verschnitt 1 bei eingeschalteter Paar-Regel → `edit.dont_waste_single_unused`
    - im Vertreter-Modus sonst immer ok
  - **`ponytail:`-Kommentar** bekommt den neuen Text: *26 rows; `_visible_edit_properties` hides exactly one per mode, so the dropdown sits at Discord's hard cap of 25. One more property needs a second chained select — slicing [:25] would silently drop the tail.*
- **i18n** (DE + EN, Wortlaut außer dem Namen frei):
  - Umbenennen auf „Übergroße Squads“ / „Oversized squads“: `edit.property.dont_waste_slots` (mit Präfix „22. “), `wizard.dont_waste_step_title`, `wizard.summary_dont_waste`, `wizard.dont_waste_select_placeholder`, `wizard.dont_waste_enabled`, `wizard.dont_waste_disabled`.
  - Neu schreiben: `wizard.dont_waste_step_desc` (Vertreter-Modus: freie Infanterie-Plätze, reguläre Squads können verdrängt werden, Paar-Regel erklärt) und `edit.dont_waste_max_invalid` (≥ 1 oder 0; mit Paar-Regel zählt ein ungerader Wert wie der nächstkleinere gerade).
  - `wizard.dont_waste_max_option`: nur noch `{n}`, kein `{per_team}` mehr.
  - Neu anlegen: `edit.property.dont_waste_pairs` (Präfix „26. “), `wizard.dont_waste_step_desc_player` (`{unused}`), `wizard.dont_waste_pairs_placeholder`, `wizard.dont_waste_pairs_on`, `wizard.dont_waste_pairs_off`, `wizard.summary_dont_waste_pairs_on`, `wizard.summary_dont_waste_pairs_off`.

- [ ] **Step 1: Failing tests schreiben**

```python
def _apply(ev, key, vtype, value):
    return bot._apply_property_change(ev, key, vtype, None, value, "de")


class TestConfigUi(unittest.TestCase):
    def test_step_available(self):
        self.assertTrue(bot._dont_waste_step_available(_dcn()))
        self.assertFalse(bot._dont_waste_step_available(_dcn(infantry_squad_size=9)))
        self.assertFalse(bot._dont_waste_step_available(_dcn(mode="player")))                    # pool 0
        self.assertTrue(bot._dont_waste_step_available(_dcn(mode="player", max_player_slots=99)))  # pool 1

    def test_editor_enable_rules(self):
        ev = _dcn(dont_waste_slots=False)
        self.assertTrue(_apply(ev, "dont_waste_slots", "bool", True)[0])               # rep, no leftover
        ok, err = _apply(_dcn(mode="player", dont_waste_slots=False), "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("keine ungenutzten Slots", err)
        ev = _dcn(mode="player", max_player_slots=99, dont_waste_slots=False)
        ok, err = _apply(ev, "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("nur 1 Slot", err)
        ev["dont_waste_pairs"] = False
        self.assertTrue(_apply(ev, "dont_waste_slots", "bool", True)[0])
        ok, err = _apply(_dcn(infantry_squad_size=9, dont_waste_slots=False), "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("maximal 9 Spieler", err)

    def test_editor_max_values(self):
        ev = _dcn()
        for good in (1, 3, 4):
            self.assertTrue(_apply(ev, "dont_waste_max_squads", "int_nullable", good)[0], good)
        self.assertFalse(_apply(ev, "dont_waste_max_squads", "int_nullable", -2)[0])
        self.assertTrue(_apply(ev, "dont_waste_max_squads", "int_nullable", None)[0])
        self.assertIsNone(ev["dont_waste_max_squads"])

    def test_pair_property_row(self):
        self.assertIn((26, "dont_waste_pairs", "edit.property.dont_waste_pairs", "bool", None), bot._EDIT_PROPERTIES)
        for ev in (_dcn(), _dcn(mode="player"), _dcn(max_caster_slots=0)):
            keys = [p[1] for p in bot._visible_edit_properties(ev)]
            self.assertIn("dont_waste_pairs", keys)
            self.assertLessEqual(len(keys), 25)

    def test_wizard_view(self):
        with patch.object(bot, "get_guild_language", return_value="de"):
            view = bot.WizardDontWasteSlotsView(0, 0, _dcn(), {}, {}, None)
        self.assertEqual({o.value for o in view.pairs_select.options}, {"yes", "no"})
        self.assertEqual([o.value for o in view.sizes_select.options], ["7", "8", "9"])
        self.assertLessEqual(len(view.max_select.options), 25)
        self.assertTrue(all(c.row is not None and c.row <= 4 for c in view.children))

    def test_summary_shows_pair_rule(self):
        ev = _dcn_embed(dont_waste_pairs=False)   # summary reads only name/date by index, rest via .get
        with patch.object(bot, "get_guild_language", return_value="de"):
            fields = {f.name: f.value for f in bot._build_confirmation_embed(ev, 0).fields}
        self.assertIn(t("wizard.summary_dont_waste_pairs_off", "de"), fields[t("wizard.summary_dont_waste", "de")])
        self.assertIn("Übergroße Squads", t("wizard.summary_dont_waste", "de"))
        self.assertIn("Oversized squads", t("wizard.summary_dont_waste", "en"))

    def test_i18n_keys(self):
        for key in ("edit.property.dont_waste_pairs", "wizard.dont_waste_step_desc_player",
                    "wizard.dont_waste_pairs_placeholder", "wizard.dont_waste_pairs_on",
                    "wizard.dont_waste_pairs_off", "wizard.summary_dont_waste_pairs_on",
                    "wizard.summary_dont_waste_pairs_off"):
            for lang in ("de", "en"):
                self.assertIn(lang, _STRINGS.get(key, {}), f"{key}:{lang}")
        self.assertNotIn("{", t("wizard.dont_waste_step_desc", "de"))
```

In `tests/test_dont_waste_slots.py`:
- **`TestModelPlumbing.test_enable_via_editor_requires_unused_slots`:** auf Spieler-Modus umstellen. Die ersten beiden Prüfungen mit `_event(mode="player", max_player_slots=86/87, …)` erwarten weiter die Fehlermeldung. Neu kommt dazu: `_event(max_player_slots=86, dont_waste_slots=False)` im Vertreter-Modus → ok.
- **`TestMaxSquadsCap.test_editor_validation`:** `(3, 1, -2)` → nur noch `-2` ist ungültig, `3` und `1` sind ok.
- **`TestI18nKeys.KEYS`:** bleibt, alle Keys existieren weiter.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `TEST tests.test_oversized_free_seats`
Expected: ERROR `no attribute '_dont_waste_step_available'` u. ä.

- [ ] **Step 3: Implementieren** wie im Interfaces-Block.

- [ ] **Step 4: Tests laufen lassen**

Run: `TEST tests.test_oversized_free_seats`, `TEST tests.test_dont_waste_slots`, ganze Suite.
Expected: alles PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/bot.py bot/i18n.py tests/test_oversized_free_seats.py tests/test_dont_waste_slots.py
git commit -m "feat: pair rule and oversized-squads naming in wizard, summary and DM editor" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Dokumentation

**Files:**
- Modify: `docs/dont-waste-slots.md`: inhaltlich neu, Titel „Oversized Squads“, der Pfad bleibt
- Modify: `README.md` (Feature-Bullet Z. 17, Abschnitt Z. ~131, Slot-Beispiel Z. ~148)
- Modify: `USER_GUIDE.md`, `USER_GUIDE_GER.md` (Schritt 8 „Übergroße Squads“, Slot-Berechnung Z. ~212, DM-Editor-Liste: 22 umbenennen, 26 ergänzen)

**Inhalt** (aus der Spec, nichts Neues erfinden):
- **Vertreter-Modus:** alle freien Infanterie-Plätze, reguläre Squads können verdrängt werden, nur Infanterie-Plätze.
- **Paar-Regel an/aus** mit den Regeln aus Spec §5.1/§5.2 in Prosa und den Rechenbeispielen A–E aus §5.3.
- **Anzeige** (§5.4) und Warteliste/Orga-Eingriffe (§5.5/§5.6).
- **Spieler-Modus** (§6) mit dem Beispiel Verschnitt 3.
- **Konfiguration:** Wizard, DM-Editor 22–24 und 26, gespeicherte Felder inkl. `dont_waste_pairs`.
- **Garantien:** Random-Walk-Tests in `tests/test_oversized_free_seats.py` für beide Einstellungen.
- **Aufräumen:**
  - Die tote Zeile mit dem Link auf `dont-waste-slots_GER.md` in `docs/dont-waste-slots.md` und den Link in `USER_GUIDE_GER.md` auf `docs/dont-waste-slots.md` umbiegen.
  - Veraltete Eigenschaftsnummern (23–25) korrigieren.
  - USER_GUIDE-Sätze wie „Wizard-Schritt erscheint nur bei ≥ 2 ungenutzten Plätzen“ und „Aktivieren wird abgelehnt, solange es keine ungenutzten Slots gibt“ auf Spieler-Modus einschränken.

- [ ] **Step 1: Docs umschreiben**

- [ ] **Step 2: Reste prüfen**

Run: `grep -n "Don't waste slots\|Slots nicht verschwenden\|dont-waste-slots_GER\|Eigenschaften 22–24\|properties 23\|23–25" README.md USER_GUIDE.md USER_GUIDE_GER.md docs/dont-waste-slots.md`
Expected: keine Treffer.

- [ ] **Step 3: Ganze Suite ein letztes Mal**

Run: `docker run --rm -e DISCORD_BOT_TOKEN=x -u "$(id -u):$(id -g)" -v "$PWD":/src -w /src squadbot-test python -m unittest discover -s tests -p 'test_*.py'`
Expected: `OK`. `git status` zeigt keine fremden Dateien.

- [ ] **Step 4: Commit**

```bash
git add README.md USER_GUIDE.md USER_GUIDE_GER.md docs/dont-waste-slots.md
git commit -m "docs: oversized squads from free seats and the pair rule" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
