# Squad-Event-Registration Bot — Benutzerhandbuch

Der Squad-Event-Registration Bot organisiert squad-basierte Events auf Discord. Spieler melden sich über Buttons oder Slash-Commands an, und der Bot verteilt Server-Slots, verwaltet die Warteliste, kümmert sich um Wiederholungen und hält alles synchron. Organisatoren erstellen Events per Wizard, bearbeiten Einstellungen per DM und verwalten Rollen und Erinnerungen — alles direkt in Discord.

## Inhaltsverzeichnis

- [Event-Modi](#event-modi)
- [Für Spieler](#für-spieler)
- [Für Organisatoren](#für-organisatoren)
- [Interaktive Buttons](#interaktive-buttons)
- [Wartelisten-System](#wartelisten-system)
- [Häufig gestellte Fragen](#häufig-gestellte-fragen)

---

## Event-Modi

Events werden in einem von zwei Modi erstellt, ausgewählt bei der Erstellung. Der Modus ist danach fest; er kann auf einem laufenden Event nicht mehr gewechselt werden.

### Vertreter-Modus (Standard)

Das klassische Verhalten. Jede Anmeldung ist ein **Squad** mit Name, Typ, Spielstil und einem Discord-User als Vertreter. Eine Anmeldung belegt `squad_size` Plätze (z.B. 6 für Infanterie, 2 für Fahrzeug, 1 für Heli). Ein User kann **mehrere Squads** anmelden (bis zum konfigurierten Limit). Caster melden sich separat an.

Dieser Modus passt, wenn Squad-Leads ihre eigenen Teams koordinieren und der Organisator Squad-spezifische Informationen (Spielstil, Vertretername) benötigt.

### Spieler-Modus

Jede Anmeldung ist ein **einzelner Spieler** — nur der User selbst. Der Bot weist Spieler automatisch Squads zu, in der Reihenfolge der Anmeldung: Die ersten 6 Infanterie-Anmeldungen bilden „Infantry 1", die nächsten 6 „Infantry 2", usw. Kein Spielstil, kein Squad-Name, keine Caster-Rolle. **Ein User = eine Anmeldung.**

Dieser Modus eignet sich für Pick-up-Matches oder Community-Events, bei denen sich Einzelpersonen anmelden und die Squad-Zusammensetzung egal ist.

### Kurzvergleich

| Aspekt | Vertreter-Modus | Spieler-Modus |
|---|---|---|
| Was wird angemeldet | Ein Squad (Name + Typ + Spielstil) | Ein einzelner Spieler |
| Wer meldet an | Ein Vertreter für sein Squad | Jeder Spieler für sich selbst |
| Slots pro Anmeldung | `squad_size` (z.B. 6) | 1 |
| Mehrere Anmeldungen pro User | Bis zum Limit | Immer 1 |
| Spielstil-Auswahl | Ja | Nein |
| Caster | Konfigurierbar | Deaktiviert |
| Anmelde-UI | Squad-Name-Modal + Spielstil | Ein Klick auf Typ, Discord-Anzeigename wird verwendet |
| Slot-Übersicht-Label | „🖥️ Server — 100 Plätze" | „📋 Plätze — 17 Plätze" |
| Admin-Hinzufügen | Squad hinzufügen (Name + Vertreter + Spielstil) | Spieler hinzufügen (Mehrfachauswahl Users + Typ) |

---

## Für Spieler

### Anmelden — Vertreter-Modus

Es gibt zwei Wege, einen Squad anzumelden:

**Per Button (empfohlen):**
1. Klicke auf **Squad** (🪖) in der Event-Anzeige
2. Wähle den Squad-Typ im Dropdown: Infanterie, Fahrzeug oder Heli
3. Wähle den Spielstil: Casual, Normal oder Focused
4. Gib im Modal den Squad-Namen ein
5. Der Bot bestätigt die Anmeldung oder setzt den Squad auf die Warteliste

**Per Slash-Command:**
- `/register` — Startet denselben geführten Ablauf (Typ → Spielstil → Name)

### Anmelden — Spieler-Modus

Der Button heißt **Beitreten** (🪖) statt **Squad**. Der Ablauf ist kürzer:

1. Klicke auf **Beitreten** (🪖) in der Event-Anzeige
2. Wähle deinen Squad-Typ im Dropdown: Infanterie, Fahrzeug oder Heli
3. Fertig — der Bot weist dich automatisch dem ersten nicht vollen Squad dieses Typs zu (erstellt automatisch ein neues Squad, falls nötig) oder setzt dich auf die Warteliste, wenn alle Plätze belegt sind. Dein Discord-Anzeigename wird verwendet; es gibt kein Namensfeld.

Slash-Command: `/register` — derselbe Ablauf, angepasst für den Spieler-Modus.

**Ein User, eine Anmeldung.** Wenn du dich erneut anmeldest, obwohl du bereits registriert bist, meldet der Bot das zurück.

### Als Caster anmelden

Nur im **Vertreter-Modus** verfügbar (Caster ist im Spieler-Modus deaktiviert).

- Klicke auf **Caster** (🎙️) in der Event-Anzeige

Spieler können gleichzeitig als Caster **und** mit Squads angemeldet sein.

### Status einsehen

- **Info** (ℹ️) Button — Zeigt deine Zuweisungen und ggf. Wartelistenposition

### Abmelden

- Klicke auf **Abmelden** (❌) in der Event-Anzeige, oder
- Verwende `/unregister`

In **beiden Modi** erscheint ein Bestätigungsdialog, bevor die Abmeldung durchgeführt wird — „Möchtest du dich wirklich abmelden? Du verlierst deinen Platz." Du musst auf Abmelden klicken, um zu bestätigen. Nach Abschluss erhältst du eine Bestätigungsnachricht.

### Alle Spieler-Befehle

| Befehl | Beschreibung |
|---|---|
| `/register` | Geführte Squad-Anmeldung (Typ → Spielstil → Name) |
| `/unregister` | Vom Event abmelden |
| `/help` | Verfügbare Befehle anzeigen |

---

## Für Organisatoren

### Ersteinrichtung des Servers

Bevor Events erstellt werden können, muss ein Admin `/setup` ausführen:
- **Organisator-Rolle** — welche Rolle Events verwalten darf
- **Log-Kanal** — wohin der Bot alle Aktionen protokolliert
- **Sprache** — Deutsch (de) oder Englisch (en)

Mit `/set_defaults` können die Standardwerte für Event-Erstellung angepasst werden (Serverkapazität, Squad-Größen, Limits, Countdown).

Mit `/settings` wird die aktuelle Serverkonfiguration angezeigt.

### Event erstellen

Verwende `/create_event`, um ein Event zu erstellen. Der Command hat einen **optionalen Choice-Parameter**:

- `mode: Register as representative (squad rep)` — Standard; durchläuft den vollen Wizard unten.
- `mode: Register as player (individual)` — überspringt den Caster-Rollen-Schritt und den Max-Squads-pro-User-Schritt, setzt `max_caster_slots = 0` zwangsweise und beschriftet „Server Max Spieler" als „Plätze gesamt".

Nach dem Command führt dich ein mehrstufiger Wizard durch:

**Schritt 1 — Basis-Informationen (Modal):**
- Event-Name, Datum, Uhrzeit, Beschreibung
- Anmeldezeitpunkt (Datum/Uhrzeit oder „sofort"/„jetzt" für sofortige Öffnung)

**Schritt 2 — Server-Konfiguration (Modal):**
- Server Max Spieler (Vertreter-Modus) bzw. Plätze gesamt (Spieler-Modus), Max Caster (0 = Caster deaktiviert; im Spieler-Modus fest auf 0 gesetzt und ausgeblendet), Squad-Größen (Inf / Fahr / Heli), Max Fahrzeug-Squads, Max Heli-Squads
- Alle Werte vorausgefüllt aus den Server-Standardwerten (`/set_defaults`)

**Schritt 3 — Squad-Rollen:**
- Squad-Rep Rollen/User — Wer Squads anmelden darf / beitreten kann (Rollen-Gate)
- Community-Rep Rollen/User — Wer **vor** Anmeldungsstart anmelden darf (Early Access)
- Ping bei Öffnung — Ob diese Rollen bei Anmeldungsstart gepingt werden sollen

**Schritt 4 — Caster-Rollen (nur Vertreter-Modus — im Spieler-Modus übersprungen):**
- Caster Rollen/User — Wer sich als Caster anmelden darf (Rollen-Gate)
- Caster-Early-Access Rollen/User — Wer sich als Caster **vor** Anmeldungsstart anmelden darf
- Ping bei Öffnung

**Schritt 5 — Timing:**
- Event-Erinnerung — Benachrichtigung X Minuten vor Event-Start (0 = deaktiviert)
- Countdown — Nachricht X Sekunden vor Anmeldungsstart (wird bei Öffnung automatisch gelöscht)

**Schritt 6 — Squad-Limit (nur Vertreter-Modus — im Spieler-Modus übersprungen, immer 1):**
- Max. Squads pro Spieler (1–20)

**Schritt 7 — Bestätigung:**
- Zusammenfassungs-Embed mit allen Einstellungen inkl. ungenutzter Slots — Bestätigen oder Abbrechen

Jeder Schritt kann übersprungen werden — ohne Auswahl werden die Server-Standardwerte verwendet. Rollen können auch nachträglich mit `/set_event_roles` konfiguriert werden.

**Slot-Berechnung — Beispiel:**
```
Server: 100 Slots
- Caster: 2 Slots
- Fahrzeug: 5 Squads × 2 = 10 Slots
- Heli: 2 Squads × 1 = 2 Slots
- Infanterie: (100 − 2 − 10 − 2) / 6 = 14 Squads (84 Slots)
- Ungenutzt: 2 Slots
```

### Event per DM bearbeiten

Organisatoren können ein laufendes Event per DM bearbeiten: Klicke im Admin-Panel auf **Event bearbeiten**. Der Bot sendet eine gruppierte Eigenschaftenliste:

**Allgemein:**
1. Event-Name
2. Datum
3. Uhrzeit
4. Beschreibung

**Squad-Konfiguration:**
5. Server max. Spieler
6. Max. Caster-Slots
7. Max. Fahrzeug-Squads
8. Max. Heli-Squads
9. Infanterie-Squad-Größe
10. Fahrzeug-Squad-Größe
11. Heli-Squad-Größe
12. Max. Squads pro Spieler

**Extras:**
13. Event-Erinnerung (Minuten, 0 = deaktivieren)
14. Anmeldezeitpunkt
15. Event-Bild (Bild hochladen oder HTTPS-URL einfügen)
16. Wiederholung (wie das Event zyklisch wiederkehrt — siehe unten)
17. Dauer (Länge des Events; Standard 2 Std.)
18. Folgeevent-Verzögerung (bei Wiederholung: Zeit nach dem Ende, bis das nächste Event erstellt wird)

Jede Änderung zeigt den alten → neuen Wert mit einem Bestätigungsschritt. Die Event-Anzeige im Kanal wird nach jeder Änderung automatisch aktualisiert.

Änderungen an Datum/Uhrzeit, Wiederholung, Dauer oder Folgeevent-Verzögerung werden validiert — falls die nächste Wiederholung noch während des aktuellen Events (bis `Start + Dauer + Verzögerung`) fallen würde, wird die Änderung mit einer Erklärung abgelehnt. Verkürze das Event, reduziere die Verzögerung oder wähle einen längeren Wiederholungsrhythmus.

### Wiederkehrende Events

Du kannst festlegen, dass ein Event automatisch ein Folgeevent erstellt. Konfiguriert wird das per DM-Bearbeitung über die Eigenschaften 16 (Wiederholung), 17 (Dauer) und 18 (Folgeevent-Verzögerung).

**Wiederholungs-Optionen (12):**

1. Nie — Standard; das Event wird am Ende archiviert und nichts Neues erstellt
2. Alle X Minuten
3. Alle X Stunden
4. Alle X Tage
5. Alle X Wochen (1 = wöchentlich, 2 = zweiwöchentlich, …)
6. Jeden Monat
7. Am 1. `{Wochentag}` des nächsten Monats — Wochentag wird vom Start-Datum deines Events übernommen
8. Am 4. `{Wochentag}` des nächsten Monats
9. Am letzten `{Wochentag}` des nächsten Monats
10. Bestimmtes Datum (+ optionale Uhrzeit) — einmalig
11. Bestimmte Wochentage (z.B. Mo, Mi, Fr)
12. Bestimmte Tage im Monat (z.B. 1. und 15.)

**Dauer-Presets:** 30 Min, 1 Std, 2 Std (Standard), 4 Std, 6 Std, 8 Std, 12 Std, 24 Std.

**Verzögerungs-Presets:** 1 Min, 5 Min (Standard), 10 Min, 30 Min, 1 Std, 6 Std, 1 Tag, 1 Woche.

**Ablauf:**

- Bei `Start` — die Anmeldung wird automatisch geschlossen. Neue Anmeldungen, Abmeldungen und Squad-Wechsel werden abgelehnt.
- Bei `Start + Dauer` — für **nicht wiederkehrende** Events: Zusammenfassung wird in den Log-Kanal geschrieben, das Embed wird gelöscht. Fertig.
- Bei `Start + Dauer` — für **wiederkehrende** Events: nichts Sichtbares passiert. Das Embed bleibt als schreibgeschützter Snapshot des Endstands im Kanal sichtbar.
- Bei `Start + Dauer + Verzögerung` — für **wiederkehrende** Events: die Zusammenfassung wird geloggt, das alte Embed wird gelöscht, ein frisches Event wird erstellt und gepostet. Das neue Event übernimmt die komplette Konfiguration (Name, Slot-Größen, Rollen-Pings, Wiederholung, Dauer, Verzögerung) und setzt den Laufzeit-Zustand zurück.

### Admin-Panel — Vertreter-Modus

Klicke auf den **Admin** (⚙️) Button im Event-Embed, um das Admin-Panel zu öffnen. Im Vertreter-Modus enthält es 6 Buttons in 3 Reihen:

| Reihe | Button | Beschreibung |
|---|---|---|
| Squad | **Squad hinzufügen** | Typ, Spielstil und Vertreter auswählen, dann Squad-Name eingeben |
| Squad | **Squad entfernen** | Squad zum Entfernen auswählen (inkl. Warteliste) |
| Caster | **Caster hinzufügen** | Discord-User als Caster hinzufügen |
| Caster | **Caster entfernen** | Caster zum Entfernen auswählen (inkl. Warteliste) |
| Event | **Event bearbeiten** | Öffnet DM-basierte Bearbeitungssitzung (siehe oben) |
| Event | **Event löschen** | Event mit Bestätigung löschen |

Beim Hinzufügen eines Squads als Admin wird der ausgewählte Vertreter für das Squad-Limit des Users gezählt, aber das Limit wird nicht erzwungen — Admins können immer hinzufügen.

### Admin-Panel — Spieler-Modus

Im Spieler-Modus hat das Admin-Panel 4 Buttons — die Squad- und Caster-Reihen werden durch eine einzige Spieler-Reihe ersetzt:

| Reihe | Button | Beschreibung |
|---|---|---|
| Spieler | **Spieler hinzufügen** | Mehrere Discord-User (Mehrfachauswahl) + einen Squad-Typ wählen, dann bestätigen. Alle ausgewählten User werden in einem Submit angemeldet. Wenn die Kapazität mitten im Batch aufgebraucht ist, werden die restlichen auf die Warteliste gesetzt. |
| Spieler | **Spieler entfernen** | Einen oder mehrere Spieler auswählen (Mehrfachauswahl) — aus aktuellen Squad-Mitgliedern **und** aus jeder Warteliste (Wartelisten-Einträge sind mit `[WL-Inf]` / `[WL-Veh]` / `[WL-Heli]` markiert). Die Aktion ist hinter einem roten „Abmelden"-Bestätigungsbutton abgesichert. |
| Event | **Event bearbeiten** | Öffnet DM-basierte Bearbeitungssitzung |
| Event | **Event löschen** | Event mit Bestätigung löschen |

Wenn ein Spieler aus einem Squad entfernt wird, wird die Warteliste-Beförderung ausgelöst (DM + Log-Channel-Eintrag für jeden nachgerückten Spieler). Spieler, die von der Warteliste entfernt werden, verschwinden einfach aus der Queue.

### Rollen-Konfiguration

| Befehl | Beschreibung |
|---|---|
| `/set_event_roles` | Rollen zum Event hinzufügen (Ping, Squad-Rep, Community-Rep, Caster, Caster Early-Access) |
| `/clear_event_roles` | Event-Rollen löschen — alle auf einmal oder nach Kategorie |

### Event-Verwaltung

| Befehl | Beschreibung |
|---|---|
| `/create_event` | Neues Event erstellen (geführter Wizard) |
| `/open` | Anmeldung sofort öffnen |
| `/close` | Anmeldung schließen |
| `/delete_event` | Event löschen |
| `/update` | Event-Anzeige aktualisieren |

### Admin-Tools

| Befehl | Beschreibung |
|---|---|
| `/admin_edit_squad` | Squad-Größe bearbeiten |
| `/admin_waitlist` | Vollständige Warteliste anzeigen |
| `/admin_user_assignments` | Alle User-Zuweisungen anzeigen |
| `/admin_reset_assignment` | Zuweisung eines Users zurücksetzen |
| `/export_csv` | Squad-Liste als CSV exportieren |

### Server-Setup-Befehle (nur Admin)

| Befehl | Beschreibung |
|---|---|
| `/setup` | Ersteinrichtung (Organisator-Rolle, Log-Kanal, Sprache) |
| `/set_organizer_role` | Organisator-Rolle setzen |
| `/set_language` | Bot-Sprache setzen (de/en) |
| `/set_log_channel` | Log-Kanal setzen |
| `/set_defaults` | Server-weite Standardwerte setzen |
| `/settings` | Aktuelle Servereinstellungen anzeigen |
| `/sync` | Slash-Commands mit Discord synchronisieren |

---

## Interaktive Buttons

Die Event-Anzeige enthält folgende Buttons. Alle Buttons sind für jeden sichtbar — Berechtigungen werden beim Klicken geprüft.

| Button | Funktion |
|---|---|
| **Squad** (🪖) | Startet die geführte Anmeldung (Typ → Spielstil → Name) |
| **Caster** (🎙️) | Direkte Caster-Anmeldung |
| **Info** (ℹ️) | Zeigt eigene Zuweisungen und Wartelistenposition |
| **Abmelden** (❌) | Squad/Caster abmelden mit Bestätigung |
| **Admin** (⚙️) | Öffnet Admin-Panel (nur Organisator) |

---

## Wartelisten-System

Die Wartelisten-Semantik ist in beiden Modi identisch — nur die Einheit unterscheidet sich (ein kompletter Squad im Vertreter-Modus, ein einzelner Spieler im Spieler-Modus).

- **Automatische Platzierung** — Wenn alle Slots eines Typs belegt sind, wird die neue Anmeldung auf die Warteliste gesetzt. Im Vertreter-Modus ist das ein ganzer Squad; im Spieler-Modus ein einzelner Spieler. Caster haben eine eigene Warteliste im Vertreter-Modus (nicht relevant im Spieler-Modus).
- **Automatisches Nachrücken** — Sobald ein Platz frei wird (jemand meldet sich ab), rückt der nächste Warteliste-Eintrag automatisch ins Event. Im Vertreter-Modus rückt ein ganzer Squad nach, wenn er reinpasst; im Spieler-Modus rückt ein Spieler in das erste Squad mit Kapazität nach (erstellt ein neues Squad, falls nötig).
- **Reihenfolge** — First Come, First Served. Die Warteliste wird strikt von vorne nach hinten abgearbeitet.
- **DM-Benachrichtigung** — Wenn du von der Warteliste ins Event nachrückst, erhältst du eine automatische DM. Im Vertreter-Modus erhält der Squad-Vertreter die DM; im Spieler-Modus der einzelne Spieler.
- **Log-Channel-Eintrag** — Der Bot schreibt pro Nachrücken einen Eintrag in den Log-Kanal des Servers für den Audit-Trail.
- **Warteliste einsehen** — Spieler sehen ihre Position über den **Info** Button. Organisatoren sehen die vollständige Warteliste mit `/admin_waitlist`.
- **Von der Warteliste entfernen** — Ein Warteliste-User kann sich selbst abmelden (mit Bestätigung). Organisatoren können Warteliste-Einträge über **Admin → Squad entfernen** (Vertreter-Modus) bzw. **Admin → Spieler entfernen** (Spieler-Modus) entfernen — die Auswahl listet sowohl registrierte als auch Warteliste-Einträge.

---

## Häufig gestellte Fragen

**F: Was ist der Unterschied zwischen Vertreter-Modus und Spieler-Modus?**
A: Im Vertreter-Modus meldest du einen ganzen Squad an (mit Name, Spielstil und einem User als Vertreter). Im Spieler-Modus meldest du dich als einzelne Person an, und der Bot gruppiert Spieler automatisch zu Squads (die ersten 6 Infanterie-Anmeldungen bilden „Infantry 1", die nächsten 6 „Infantry 2", usw.). Caster sind im Spieler-Modus deaktiviert. Organisatoren wählen den Modus bei der Event-Erstellung; er kann nicht mehr geändert werden.

**F: Warum hat mein Event einen „Beitreten"-Button statt einem „Squad"-Button?**
A: Das Event wurde im Spieler-Modus erstellt. Du meldest dich als einzelne Person an — der Bot kümmert sich um die Squad-Zuweisung. Dein Discord-Anzeigename wird automatisch verwendet.

**F: Wie melde ich meinen Squad an?**
A: Klicke auf **Squad** (🪖) in der Event-Anzeige oder verwende `/register`. Du wirst durch Typ, Spielstil und Namenswahl geführt. (Das ist der Vertreter-Modus — der Spieler-Modus hat einen einstufigen Beitreten-Ablauf.)

**F: Kann ich gleichzeitig Caster und Squad-Mitglied sein?**
A: Ja. Du kannst dich als Caster anmelden und parallel Squads registrieren.

**F: Was passiert, wenn das Event voll ist?**
A: Dein Squad wird automatisch auf die Warteliste gesetzt. Du rückst nach, sobald ein Platz frei wird, und wirst per DM benachrichtigt.

**F: Wie viele Squads kann ich anmelden?**
A: Im Vertreter-Modus hängt das vom Event-Setting „Max Squads pro User" ab (Standard: 1, Maximum: 20). Im Spieler-Modus ist es immer **genau 1** — ein User, eine Anmeldung.

**F: Wie melden Admins eine Gruppe von Spielern im Spieler-Modus an?**
A: Admin → Spieler hinzufügen. Die Auswahl erlaubt Mehrfachauswahl von Discord-Usern zusammen mit einem einzelnen Squad-Typ. Alle ausgewählten User werden mit einem Bestätigungsklick angemeldet. Wenn die Kapazität mitten im Batch aufgebraucht ist, gehen die restlichen automatisch auf die Warteliste.

**F: Was ist der Unterschied zwischen Infanterie, Fahrzeug und Heli?**
A: Die drei Squad-Typen haben unterschiedliche Größen und separate Slot-Kontingente. Infanterie-Squads sind typischerweise am größten (z.B. 6 Spieler), Fahrzeug-Squads kleiner (z.B. 2) und Heli-Squads am kleinsten (z.B. 1).

**F: Was bedeutet „Early Access"?**
A: Spieler mit Community-Rep- oder Caster-Early-Access-Rolle können sich bereits **vor** dem offiziellen Anmeldungsstart registrieren.

**F: Ich kann mich nicht anmelden — was tun?**
A: Prüfe, ob du die nötige Rolle hast (z.B. Squad-Rep für Squad-Anmeldung) und ob die Anmeldung bereits geöffnet ist. Ohne konfigurierte Rollen kann sich jeder anmelden.

**F: Wie bearbeite ich ein laufendes Event?**
A: Klicke auf **Admin** → **Event bearbeiten**. Der Bot sendet dir eine DM mit einer nummerierten Liste aller 18 Eigenschaften. Antworte mit der Nummer der Eigenschaft, die du ändern möchtest.

**F: Wie lasse ich ein Event automatisch wiederkehren?**
A: Bearbeite das Event per DM und öffne Eigenschaft 16 (Wiederholung). Wähle einen der 12 Typen — z.B. „Alle X Wochen" für einen wöchentlichen Zyklus oder „Am letzten Sonntag des nächsten Monats" für ein monatliches Muster, das dem Wochentag deines Events folgt. Das Folgeevent wird automatisch erstellt, sobald das aktuelle endet.

**F: Wie lange bleibt das alte Event sichtbar, nachdem es zu Ende ist?**
A: Bei nicht wiederkehrenden Events wird es direkt bei `Ende` archiviert. Bei wiederkehrenden Events bleibt es bis zum Erstellen des Folgeevents sichtbar (gesteuert über Eigenschaft 18, Folgeevent-Verzögerung — Standard 5 Minuten).

**F: Warum wurde meine Wiederholungs-Änderung abgelehnt?**
A: Die nächste Wiederholung würde noch während des aktuellen Events (oder während der Verzögerungs-Phase) anstehen. Verkürze das Event, reduziere die Verzögerung oder wähle einen längeren Wiederholungsrhythmus.

**F: Wie richte ich den Bot erstmalig ein?**
A: Ein Admin führt `/setup` aus, um Organisator-Rolle, Log-Kanal und Sprache zu konfigurieren. Dann `/set_defaults` für Serverkapazität und Squad-Größen. Danach können Organisatoren Events mit `/create_event` erstellen.

**F: Warum werden meine Slash-Befehle nicht angezeigt?**
A: Ein Administrator muss `/sync` ausführen, um die Befehle mit Discord zu synchronisieren.

**F: Wie stelle ich ein Event-Bild ein?**
A: Bearbeite das Event per DM (Eigenschaft 15). Du kannst ein Bild hochladen oder eine HTTPS-URL einfügen.

---

Für weitere Unterstützung wende dich an einen Server-Administrator.
