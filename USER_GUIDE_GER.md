# Squad-Event-Registration Bot — Benutzerhandbuch

Der Squad-Event-Registration Bot organisiert squad-basierte Events auf Discord. Spieler melden ihre Squads über Buttons oder Slash-Commands an, wählen Squad-Typ (Infanterie/Fahrzeug/Heli) und Spielstil, und der Bot verteilt die Server-Slots automatisch. Organisatoren erstellen Events per Wizard, bearbeiten Einstellungen per DM und verwalten Warteliste, Rollen und Erinnerungen — alles direkt in Discord.

## Inhaltsverzeichnis

- [Für Spieler](#für-spieler)
- [Für Organisatoren](#für-organisatoren)
- [Interaktive Buttons](#interaktive-buttons)
- [Wartelisten-System](#wartelisten-system)
- [Häufig gestellte Fragen](#häufig-gestellte-fragen)

---

## Für Spieler

### Squad anmelden

Es gibt zwei Wege, einen Squad anzumelden:

**Per Button (empfohlen):**
1. Klicke auf **Squad** (🪖) in der Event-Anzeige
2. Wähle den Squad-Typ im Dropdown: Infanterie, Fahrzeug oder Heli
3. Wähle den Spielstil: Casual, Normal oder Focused
4. Gib im Modal den Squad-Namen ein
5. Der Bot bestätigt die Anmeldung oder setzt den Squad auf die Warteliste

**Per Slash-Command:**
- `/register` — Startet denselben geführten Ablauf (Typ → Spielstil → Name)

### Als Caster anmelden

- Klicke auf **Caster** (🎙️) in der Event-Anzeige

Spieler können gleichzeitig als Caster **und** mit Squads angemeldet sein.

### Status einsehen

- **Info** (ℹ️) Button — Zeigt deine Zuweisungen und ggf. Wartelistenposition

### Abmelden

- Klicke auf **Abmelden** (❌) in der Event-Anzeige, oder
- Verwende `/unregister`

Du erhältst einen Bestätigungsdialog, bevor die Abmeldung durchgeführt wird. Nach Abschluss erhältst du eine Bestätigungsnachricht.

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

Verwende `/event`, um ein Event zu erstellen. Ein mehrstufiger Wizard führt dich durch:

**Schritt 1 — Basis-Informationen (Modal):**
- Event-Name, Datum, Uhrzeit, Beschreibung
- Anmeldezeitpunkt (Datum/Uhrzeit oder „sofort"/„jetzt" für sofortige Öffnung)

**Schritt 2 — Server-Konfiguration (Modal):**
- Server Max Spieler, Max Caster (0 = Caster deaktiviert), Squad-Größen (Inf / Fahr / Heli), Max Fahrzeug-Squads, Max Heli-Squads
- Alle Werte vorausgefüllt aus den Server-Standardwerten (`/set_defaults`)

**Schritt 3 — Squad-Rollen:**
- Squad-Rep Rollen/User — Wer Squads anmelden darf (Rollen-Gate, wird bei der Anmeldung geprüft)
- Community-Rep Rollen/User — Wer Squads **vor** Anmeldungsstart anmelden darf (Early Access)
- Ping bei Öffnung — Ob diese Rollen bei Anmeldungsstart gepingt werden sollen

**Schritt 4 — Caster-Rollen:**
- Caster Rollen/User — Wer sich als Caster anmelden darf (Rollen-Gate)
- Caster-Early-Access Rollen/User — Wer sich als Caster **vor** Anmeldungsstart anmelden darf
- Ping bei Öffnung

**Schritt 5 — Timing:**
- Event-Erinnerung — Benachrichtigung X Minuten vor Event-Start (0 = deaktiviert)
- Countdown — Nachricht X Sekunden vor Anmeldungsstart (wird bei Öffnung automatisch gelöscht)

**Schritt 6 — Squad-Limit:**
- Max. Squads pro Spieler (1–10)

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

Jede Änderung zeigt den alten → neuen Wert mit einem Bestätigungsschritt. Die Event-Anzeige im Kanal wird nach jeder Änderung automatisch aktualisiert.

### Admin-Panel

Klicke auf den **Admin** (⚙️) Button im Event-Embed, um das Admin-Panel zu öffnen. Es enthält 6 Buttons in 3 Reihen:

| Reihe | Button | Beschreibung |
|---|---|---|
| Squad | **Squad hinzufügen** | Typ, Spielstil und Vertreter auswählen, dann Squad-Name eingeben |
| Squad | **Squad entfernen** | Squad zum Entfernen auswählen (inkl. Warteliste) |
| Caster | **Caster hinzufügen** | Discord-User als Caster hinzufügen |
| Caster | **Caster entfernen** | Caster zum Entfernen auswählen (inkl. Warteliste) |
| Event | **Event bearbeiten** | Öffnet DM-basierte Bearbeitungssitzung (siehe oben) |
| Event | **Event löschen** | Event mit Bestätigung löschen |

Beim Hinzufügen eines Squads als Admin wird der ausgewählte Vertreter für das Squad-Limit des Users gezählt, aber das Limit wird nicht erzwungen — Admins können immer hinzufügen.

### Rollen-Konfiguration

| Befehl | Beschreibung |
|---|---|
| `/set_event_roles` | Rollen zum Event hinzufügen (Ping, Squad-Rep, Community-Rep, Caster, Caster Early-Access) |
| `/clear_event_roles` | Event-Rollen löschen — alle auf einmal oder nach Kategorie |

### Event-Verwaltung

| Befehl | Beschreibung |
|---|---|
| `/event` | Neues Event erstellen (geführter Wizard) |
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

- **Automatische Platzierung** — Wenn alle Slots eines Squad-Typs belegt sind, wird der Squad automatisch auf die Warteliste gesetzt. Gleiches gilt für Caster.
- **Automatisches Nachrücken** — Sobald ein Platz frei wird (z.B. durch Abmeldung), rückt der nächste Squad auf der Warteliste automatisch nach.
- **Reihenfolge** — Squads auf der Warteliste werden nach Anmeldezeitpunkt sortiert (First Come, First Served).
- **DM-Benachrichtigung** — Wenn ein Squad von der Warteliste ins Event nachrückt, erhält der Spieler eine automatische DM-Benachrichtigung.
- **Warteliste einsehen** — Spieler sehen ihre Position über den **Info** Button. Organisatoren sehen die vollständige Warteliste mit `/admin_waitlist`.

---

## Häufig gestellte Fragen

**F: Wie melde ich meinen Squad an?**
A: Klicke auf **Squad** (🪖) in der Event-Anzeige oder verwende `/register`. Du wirst durch Typ, Spielstil und Namenswahl geführt.

**F: Kann ich gleichzeitig Caster und Squad-Mitglied sein?**
A: Ja. Du kannst dich als Caster anmelden und parallel Squads registrieren.

**F: Was passiert, wenn das Event voll ist?**
A: Dein Squad wird automatisch auf die Warteliste gesetzt. Du rückst nach, sobald ein Platz frei wird, und wirst per DM benachrichtigt.

**F: Wie viele Squads kann ich anmelden?**
A: Das hängt von der Event-Konfiguration ab. Der Organisator legt die maximale Anzahl Squads pro Spieler fest (Standard: 1, Maximum: 10).

**F: Was ist der Unterschied zwischen Infanterie, Fahrzeug und Heli?**
A: Die drei Squad-Typen haben unterschiedliche Größen und separate Slot-Kontingente. Infanterie-Squads sind typischerweise am größten (z.B. 6 Spieler), Fahrzeug-Squads kleiner (z.B. 2) und Heli-Squads am kleinsten (z.B. 1).

**F: Was bedeutet „Early Access"?**
A: Spieler mit Community-Rep- oder Caster-Early-Access-Rolle können sich bereits **vor** dem offiziellen Anmeldungsstart registrieren.

**F: Ich kann mich nicht anmelden — was tun?**
A: Prüfe, ob du die nötige Rolle hast (z.B. Squad-Rep für Squad-Anmeldung) und ob die Anmeldung bereits geöffnet ist. Ohne konfigurierte Rollen kann sich jeder anmelden.

**F: Wie bearbeite ich ein laufendes Event?**
A: Klicke auf **Admin** → **Event bearbeiten**. Der Bot sendet dir eine DM mit einer nummerierten Liste aller Eigenschaften. Antworte mit der Nummer der Eigenschaft, die du ändern möchtest.

**F: Wie richte ich den Bot erstmalig ein?**
A: Ein Admin führt `/setup` aus, um Organisator-Rolle, Log-Kanal und Sprache zu konfigurieren. Dann `/set_defaults` für Serverkapazität und Squad-Größen. Danach können Organisatoren Events mit `/event` erstellen.

**F: Warum werden meine Slash-Befehle nicht angezeigt?**
A: Ein Administrator muss `/sync` ausführen, um die Befehle mit Discord zu synchronisieren.

**F: Wie stelle ich ein Event-Bild ein?**
A: Bearbeite das Event per DM (Eigenschaft 15). Du kannst ein Bild hochladen oder eine HTTPS-URL einfügen.

---

Für weitere Unterstützung wende dich an einen Server-Administrator.
