# Übergroße Squads aus allen freien Plätzen + einstellbare Paar-Regel — Design

*Stand: 2026-10-23 · ersetzt das Verhalten aus [docs/dont-waste-slots.md](../../dont-waste-slots.md) im Vertreter-Modus*

Markierungen: **(Orga)** = so vom Organisator entschieden · **(Claude)** = Entscheidung im Design, vom Organisator gelesen und nicht beanstandet · ohne Markierung = folgt direkt aus den beiden.

## 1. Anlass

Beim Event „Oktober DCN 2026" (Vertreter-Modus) ist der Server exakt verplant:

```
100 Plätze − 2 Caster − 6×2 Fahrzeug − 2×1 Heli = 84 Infanterie-Plätze = 14 × 6er
```

Es gibt also keinen Verschnitt, und das Aktivieren von „Slots nicht verschwenden" im DM-Editor scheitert mit
`edit.dont_waste_no_unused` („Bei der aktuellen Konfiguration gibt es keine ungenutzten Slots."). Gleichzeitig sind
noch 20 Plätze frei (3 Infanterie-Squads + 2 Helis noch nicht angemeldet). Die Orga will, dass Squad-Vertreter auch
dann übergroße Squads anmelden können — die Plätze kommen aus den freien Plätzen, und **es ist ausdrücklich in
Ordnung, dass dadurch später weniger Squads Platz finden (Orga)**.

Heute dürfen übergroße Squads nur den *Verschnitt* nutzen (Plätze, die kein reguläres Squad füllen kann) und
verdrängen dadurch nie ein reguläres Squad. Diese Garantie fällt im Vertreter-Modus weg.

## 2. Ziele

1. **Vertreter-Modus:** Übergroße Squads dürfen **jeden freien Infanterie-Platz** nutzen, nicht nur den Verschnitt.
   Den alten Modus „nur Verschnitt" gibt es nicht mehr — er wird ersetzt, nicht ergänzt **(Orga)**.
2. Die Option lässt sich im Vertreter-Modus **immer** aktivieren, solange die Basis-Größe unter 9 liegt.
3. Die **Paar-Regel wird pro Event einstellbar** **(Orga)**:
   - **an** (Standard, = heutiges Verhalten): jede Übergröße nur paarweise, Gegenstück wird freigehalten,
     Squad-Anzahl bleibt gerade → das Event lässt sich immer spiegeln.
   - **aus**: jede erlaubte Größe einzeln, solange sie passt. Die Team-Aufteilung ist Sache der Orga.
4. Der Bot **überbucht die Infanterie-Plätze nie von sich aus**: Kein automatischer Weg (Anmeldung, Warteliste,
   Admin-Anmeldung) vergibt mehr Plätze als frei sind — auch nicht nach nachträglichen Änderungen an den
   Einstellungen **(Claude)**. Manuelle Eingriffe der Orga sind davon ausgenommen (§5.6).

## 3. Nicht-Ziele

- Freie **Fahrzeug- oder Heli-Plätze** für Infanterie nutzen. Sie bleiben für Fahrzeuge/Helis reserviert **(Claude)**.
- Übergroße Squads über die **Warteliste** — Wartelisten-Einträge bleiben Basis-Größe (wie heute).
- Ein bereits angemeldetes Squad nachträglich **vergrößern**.
- Den **Spieler-Modus** auf „alle freien Plätze" umstellen (siehe §6) **(Claude)**.
- Die **gerade Squad-Obergrenze** (Regel 1 in `docs/dont-waste-slots.md`: `_even_infantry_max`) ändern. Sie gilt
  weiter, unabhängig von der Paar-Regel.
- Teams automatisch zuweisen.

## 4. Anti-Ziele (wäre ein Fehlschlag, selbst wenn es „funktioniert")

- Ein automatischer Weg vergibt mehr Infanterie-Plätze als vorhanden — auch nicht kurzfristig, auch nicht über die
  Warteliste, die Admin-Anmeldung oder nach Abschalten der Option.
- Ein Vertreter bekommt still eine andere Größe als gewählt (Race beim Modal → Fehlermeldung, wie heute).
- Mit Paar-Regel **an** entsteht ein Zustand, der sich nicht mehr spiegeln lässt (siehe §5.2).
- Eine Anmeldung landet auf der Warteliste mit einer falschen Begründung („alle Slots belegt", obwohl es an den
  Plätzen liegt, oder umgekehrt).

## 5. Verhalten im Vertreter-Modus

### Begriffe

| Begriff | Bedeutung | heute im Code |
|---|---|---|
| `base` | Infanterie-Basisgröße | `infantry_squad_size` |
| `S` | Infanterie-Platzbudget = `max_player_slots − Fahrzeug-Plätze − Heli-Plätze` | `inf_slots` in `infantry_unused_pool` |
| `cap` | max. Anzahl Infanterie-Squads = `_even_infantry_max(S // base)` | `_max_squads_for_type` / `_get_max_infantry_squads` |
| `used` | Summe der **Kapazitäten** aller angemeldeten Infanterie-Squads | — |
| `free` | `S − used` | — |
| erlaubte Größen | `base+1 … 9`, eingeschränkt durch `dont_waste_allowed_sizes` | `_allowed_extras` |
| Max. übergroße Squads | `dont_waste_max_squads` (None = unbegrenzt) | `_max_pairs` |

Das alte Konzept „Pool" (`infantry_unused_pool`) spielt im Vertreter-Modus keine Rolle mehr; es bleibt für den
Spieler-Modus (§6).

### 5.1 Paar-Regel aus

Ein Squad der Größe `k` (Basis oder erlaubte Übergröße) ist anmeldbar, wenn **alle** gelten:

- `Anzahl Infanterie-Squads + 1 ≤ cap`
- `k ≤ free`
- bei `k > base`: Anzahl übergroßer Squads + 1 ≤ Max. übergroße Squads (falls gesetzt)

Keine Reservierungen, keine Gerade-Bedingung für die Anzahl. Wer zuerst kommt, bekommt die Plätze.

### 5.2 Paar-Regel an

Wie heute gilt pro Übergröße: gleiche Anzahl, ein angefangenes Paar reserviert für sein Gegenstück **einen
Squad-Slot und `k` Plätze**. Neu ist, dass die Reservierung aus dem gesamten Budget kommt, nicht aus dem Verschnitt.

Zusätzlich muss die Anzahl **regulärer** Squads immer auf eine gerade Zahl ergänzbar bleiben — sonst lässt sich das
Event nicht spiegeln. Formal, mit `n_o` = übergroße Squads inkl. reservierter Gegenstücke und `seats_o` = deren Plätze:

```
B = gerade_abgerundet( min(cap − n_o, (S − seats_o) // base) )   # Kapazität für reguläre Squads
Invariante: B ≥ Anzahl angemeldeter regulärer Squads
```

- **Reguläres Squad** anmeldbar ⇔ `reguläre + 1 ≤ B`.
- **Gegenstück** eines angefangenen Paars: immer anmeldbar, sofern seine Plätze noch frei sind (siehe §5.5).
- **Neues Paar der Größe `k`**: anmeldbar ⇔ mit dem Paar (2 Slots, `2k` Plätze) zu `n_o`/`seats_o` hinzugerechnet
  gilt die Invariante noch, und Max. übergroße Squads erlaubt 2 weitere (ein angefangenes Paar zählt wie heute als 2).

Ohne übergroße Squads ist `B = cap` — exakt das heutige Verhalten.

### 5.3 Rechenbeispiele (Grundlage für Tests)

Alle mit `S = 84`, `base = 6`, `cap = 14`, alle Übergrößen erlaubt, kein Max.

**A — Paar-Regel aus, Zustand des Anlass-Events (11 × 6er angemeldet, `free = 18`):**
angeboten 6er (3), 7er (2), 8er (2), 9er (2).
→ nach einem 9er: 12 Squads, `free = 9` → 6er (1), 7er (1), 8er (1), 9er (1).
→ nach zweitem 9er: 13 Squads, `free = 0` → nichts mehr; Kopfzeile `(13/13)`, Ungenutzt: —.
→ alternativ nach 9er + 6er: 13 Squads, `free = 3` → nichts passt mehr; **Ungenutzt: 3**.

**B — Paar-Regel an, gleicher Zustand (11 × 6er):** jedes neue Paar (7/8/9) ergibt
`min(12, (84 − 2k) // 6) = 11 → gerade 10 < 11` → **keine Übergröße angeboten**; nur 6er (3).
(Der Orga so erklärt: mit Paar-Regel an hilft die Option nur, wenn sie früh aktiviert wird.)

**C — Paar-Regel an, leeres Event:** angeboten 6er (14) und jedes Paar.
Nach dem ersten 9er (Gegenstück reserviert): `n_o = 2`, `seats_o = 18`, `B = min(12, 11) → 10`
→ 6er (10), 9er (1 Gegenstück + weitere Paare). Kopfzeile `(1/12)`.
Ungenutzt bleibt 0, denn im besten Fall füllen 8 × 6er + 2 × 9er-Paare die 84 Plätze exakt.

**D — Paar-Regel aus, Max. übergroße Squads = 1, 11 × 6er:** ein 9er (75), danach nur noch 6er (1) → 81,
**Ungenutzt: 3**.

**E — Option nachträglich aus, 11 × 6er + 2 × 9er (Paar-Regel aus):** 13 Squads < `cap`, aber `free = 0` → ein
neues 6er landet auf der **Warteliste**, nicht im Event.

### 5.4 Anzeige im Event-Embed

- **Squad-Größen-Auswahl** bei der Anmeldung: Basis-Größe immer als erste Option (wie heute), dazu jede erlaubte
  Übergröße, die gerade anmeldbar ist, mit Restzahl. Nicht mehr nur die „sparsamste Kombination" (`_pair_plan`) —
  jede passende erlaubte Größe wird angeboten **(Claude)**.
- **Restzahl einer Größe** = wie viele Squads genau dieser Größe jetzt noch hintereinander angemeldet werden könnten.
  Die Restzahlen verschiedener Größen hängen voneinander ab und müssen sich nicht aufsummieren.
- **Infanterie-Kopfzeile** `⚔️ Infanterie (angemeldet/max)`: `max` = angemeldet + wie viele Squads im besten Fall
  noch dazukommen können (Paar-Regel an: `n_o + B`). Der Wert sinkt, sobald Übergrößen angemeldet werden. Die
  Pro-Größe-Zähler `[(x/y) Größe: 6 | (x/y) Größe: 9]` bleiben, `y` = angemeldet + Restzahl.
- **„Ungenutzt"** = freie Infanterie-Plätze, die **selbst im besten Fall** keine weitere Anmeldung mehr füllen kann
  (gemäß aktiver Regeln, Max. und Größenauswahl). Wie heute nie „Ungenutzt: 0" anzeigen.
- **„Server: 100 Plätze (x frei)"** unverändert.

### 5.5 Warteliste, Admin-Anmeldung, nachträgliche Änderungen

- **Eine** Prüfung entscheidet, ob ein Infanterie-Squad der Größe `k` jetzt anmeldbar ist. Alle Wege nutzen sie:
  Vertreter-Anmeldung, Re-Validierung beim Modal-Submit unter dem Guild-Lock, Admin-Anmeldung (`requested_size` in
  der Admin-View), Wartelisten-Nachrücken. Heute verteilt sich das auf `_is_squad_type_full`,
  `_squad_slot_reserved`, `infantry_size_options` und `requested_size > available`. Letzteres prüft gegen alle freien
  Spielerplätze und würde Heli-/Fahrzeug-Plätze mitzählen — für Infanterie muss gegen `free` geprüft werden.
- **Wartelisten-Nachrücken** (`_process_squad_waitlist`): ein Basis-Eintrag rückt nur nach, wenn er nach den Regeln
  oben anmeldbar ist. Wird durch Abmeldung eines übergroßen Squads Platz frei, kann das mehrere 6er nachrücken lassen.
- **Wartelisten-Begründung** muss stimmen: „Gegenstück reserviert" (wie heute), „nicht genug freie Plätze" (neu,
  wenn `cap` noch nicht erreicht ist, aber die Plätze fehlen), sonst „alle Slots belegt".
- **Abmeldung** gibt Plätze frei; ein dadurch unvollständiges Paar (Paar-Regel an) reserviert wieder sein Gegenstück.
- **Server wird nie überbucht (Claude):** Nach Konfigurationsänderungen (Option aus, Paar-Regel nachträglich an,
  Server-Größe/Squad-Größe geändert) wird geklemmt statt gecrasht. Bei Konflikt **gewinnt das Platzbudget**: Ein
  Gegenstück ist nur anmeldbar, wenn seine Plätze frei sind. Das ist eine bewusste Änderung gegenüber heute
  (`docs/dont-waste-slots.md`, Grenze 3: dort hatte das Vervollständigen von Paaren Vorrang).
- **Option aus** mit bereits angemeldeten Übergrößen: keine neuen Übergrößen, keine Reservierungen; reguläre Squads
  nur, solange `Anzahl < cap` **und** `base ≤ free` (siehe Beispiel E).
- `used` wird aus den Kapazitäten der angemeldeten Infanterie-Squads berechnet, **nicht** aus `player_slots_used`
  — dieser Zähler wird an mehreren Stellen auf `max_player_slots` geklemmt und kann eine Überbuchung verstecken.

### 5.6 Manuelle Eingriffe der Orga (Claude)

Bleiben wie heute erlaubt und ungeprüft — die Orga handelt bewusst:

- `/admin_edit_squad` setzt die Größe eines angemeldeten Squads oder Wartelisten-Eintrags auf einen beliebigen Wert
  (auch über 9, auch über die freien Plätze, auch zu einem unvollständigen Paar).
- DM-Editor-Änderungen, die `S` verkleinern (Eigenschaften 5–8, 10, 11 — z. B. ein Fahrzeug-Squad mehr beim exakt
  verplanten Anlass-Event).

Der Bot muss den entstehenden Zustand vertragen:

- `free` kann negativ werden → wie 0 behandeln. Keine neue Infanterie-Anmeldung und kein Nachrücken, bis die Größe
  wieder in `free` passt (das folgt schon aus den Regeln in §5.1/§5.2).
- „Ungenutzt", Kopfzeile und Restzahlen werden nie negativ; kein Crash.
- Ein durch Resize entstandenes unvollständiges Paar (Paar-Regel an) reserviert sein Gegenstück nur, soweit die
  Plätze reichen; ist `B` kleiner als die Zahl der regulären Squads, sind keine weiteren regulären Squads anmeldbar.
- Die Garantie aus Ziel 4 gilt ab dem Eingriff wieder: Automatische Wege verschlimmern eine Überbuchung nie.

## 6. Spieler-Modus (Claude)

Der Bot plant dort die Squad-Kapazitäten selbst; „freie Plätze nutzen" hat keine Bedeutung. Verhalten bleibt wie
heute (Verschnitt-Pool, vorgeplantes Layout `planned_infantry_capacities`, Neuplanung bei Konsolidierung
`_replan_player_capacities`) — mit einer Ausnahme:

- **Paar-Regel aus** → Übergrößen werden **einzeln** statt paarweise geplant. In `_pair_plan` / `_pair_cover` ist ein
  „Coin" dann `extra` statt `2 × extra`, und `_allowed_extras` begrenzt auf `base + pool` statt `base + pool // 2`.
  Beispiel: Verschnitt 3, base 6 → Paar-Regel an: ein 7er-Paar, 1 Platz ungenutzt; aus: ein 9er, nichts ungenutzt.
- Freischaltung bleibt an den Verschnitt gebunden: Wizard-Schritt und Aktivieren im DM-Editor nur bei mindestens 1
  ungenutzten Platz. Die Fehler `edit.dont_waste_no_unused` (Verschnitt 0) und `edit.dont_waste_single_unused`
  (Verschnitt 1 bei Paar-Regel an) bleiben **nur im Spieler-Modus** bestehen.

## 7. Konfiguration

- **Neues Event-Feld** `dont_waste_pairs` (bool, Standard `True`). Fehlt es in bestehenden Events, gilt `True`. Es
  wird in die Defaults (`database.py` Event-Factory, `bot.py` `_ensure_event_keys`) und in `_CARRY_OVER_KEYS` (wiederkehrende
  Events) aufgenommen.
- **Name (Claude):** Aus „Slots nicht verschwenden" / „Don't waste slots" wird „**Übergroße Squads**" /
  „**Oversized squads**" — in Wizard, DM-Editor, Bestätigungs-Zusammenfassung und Doku. Datenfelder und i18n-Keys
  (`dont_waste_*`) bleiben, also keine Migration.
- **Wizard-Schritt** (`WizardDontWasteSlotsView`):
  - Vertreter-Modus: erscheint immer, wenn `base < 9`. Spieler-Modus: siehe §6.
  - Zusätzliche Auswahl „Paar-Regel an/aus". Discord erlaubt 5 Zeilen, damit belegt der Schritt genau 5
    (Modus, Paar-Regel, Größen, Max., Buttons).
  - Größen-Kandidaten im Vertreter-Modus: `base+1 … 9`.
  - Max.-Auswahl: Werte bis zur sinnvollen Obergrenze, höchstens 24 + „unbegrenzt" (Discord-Limit 25 Optionen;
    relevant bei sehr kleinen Basis-Größen).
  - Bestätigungs-Zusammenfassung zeigt die Paar-Regel.
- **DM-Editor:**
  - Eigenschaft 22 (an/aus): Im Vertreter-Modus entfallen `edit.dont_waste_no_unused` und
    `edit.dont_waste_single_unused`. Abgelehnt wird nur noch bei `base ≥ 9` (`edit.dont_waste_max_size`).
  - **Neue Eigenschaft 26** `dont_waste_pairs` (bool). Damit hat `_EDIT_PROPERTIES` 26 Zeilen; pro Modus wird eine
    ausgeblendet → **genau 25 sichtbar = Discord-Limit**. Den `ponytail:`-Kommentar über der Tabelle entsprechend
    anpassen: Die nächste Eigenschaft braucht eine zweite Auswahl.
  - Eigenschaft 24 (Max.): Werte ≥ 1 erlaubt (heute: gerade ≥ 2). Mit Paar-Regel an zählt ein ungerader Wert als
    nächstkleinerer gerader — das tut `_max_pairs` bereits über `cap // 2`.
- **Größenauswahl** (Eigenschaft 23): unverändert (Werte > base und ≤ 9).

## 8. Bestehende Events

Events, bei denen die Option bereits aktiv ist, verhalten sich nach dem Update nach der neuen Logik (Paar-Regel an):
Übergrößen können dort jetzt auch reguläre Squads verdrängen. **Das ist so gewollt (Orga, „immer alle freien
Plätze")**. Bereits angemeldete Squads behalten ihre Größe; durch die neue Prüfung entsteht kein überbuchter Zustand,
weil die alte Logik nur den Verschnitt vergeben hat.

## 9. Doku und Tests

- **Doku:** `docs/dont-waste-slots.md` inhaltlich neu schreiben (Pfad bleibt, Titel „Oversized Squads"); README.md,
  USER_GUIDE.md, USER_GUIDE_GER.md anpassen. Dabei die veralteten Eigenschaftsnummern korrigieren (Doku nennt teils
  23–25, Code hat 22–24), neue Eigenschaft 26 ergänzen und den Link auf das nicht existierende
  `docs/dont-waste-slots_GER.md` entfernen oder die Datei anlegen. Der Commit-Hook erinnert an README/USER_GUIDE*.
- **Tests:** `tests/test_dont_waste_slots.py` anpassen. Die Rechenbeispiele aus §5.3 und §6 werden Unit-Tests. Die
  Random-Walk-Eigenschaftstests (`TestPairingInvariants`) auf beide Paar-Regel-Einstellungen erweitern. Invarianten
  nach jedem Schritt:
  1. `used ≤ S` und `Anzahl ≤ cap`.
  2. Paar-Regel an: jedes unvollständige Paar ist sofort vervollständigbar, `B ≥ reguläre`, und gieriges
     Vervollständigen ergibt gerade Anzahlen pro Größe und eine gerade Gesamtzahl.
  3. Keine Anmeldung überschreitet Max. übergroße Squads (ein angefangenes Paar zählt bei Paar-Regel an als 2).
  4. Die angezeigte Restzahl einer Größe ist > 0 ⇔ die zentrale Prüfung (§5.5) lässt die Anmeldung zu.

  Invariante 1 gilt für automatische Schritte. Zusätzlich Szenarien mit Orga-Eingriff (§5.6: Resize, `S`
  verkleinert): kein Crash, keine negativen Anzeigen, und kein automatischer Schritt erhöht `used`, solange
  `used > S − base` gilt.

## 10. Dem Builder überlassen

- Struktur der zentralen Anmeldbarkeits-Prüfung und ob `infantry_size_options` sie verwendet oder ersetzt.
- Berechnung von „im besten Fall noch füllbar" für „Ungenutzt" und die Kopfzeile. Die Zahlen sind klein (≤ 100
  Plätze), eine kleine DP oder Aufzählung reicht.
- Texte der neuen/geänderten i18n-Einträge (DE + EN), inkl. neuer Wartelisten-Begründung und Wizard-Beschreibung
  (die heute `{unused}` anzeigt).
- Wie die Max.-Auswahl im Wizard auf die Paar-Regel-Auswahl reagiert (neu rendern oder beim Weiter validieren).
- Verhalten bei nachträglich geänderter Basis-Größe mit bereits angemeldeten Squads — Hauptsache geklemmt, kein Crash,
  kein Überbuchen.
