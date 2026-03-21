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
1. Klicke auf **Squad anmelden** in der Event-Anzeige
2. Wähle den Squad-Typ im Dropdown: Infanterie, Fahrzeug oder Heli
3. Wähle den Spielstil: Casual, Normal oder Focused
4. Gib im Modal den Squad-Namen ein
5. Der Bot bestätigt die Anmeldung oder setzt den Squad auf die Warteliste

**Per Slash-Command:**
- `/register` — Startet denselben geführten Ablauf (Typ → Spielstil → Name)
- `/register_squad [name]` — Meldet einen Squad mit vordefiniertem Namen an

### Als Caster anmelden

- Klicke auf **Als Caster anmelden** in der Event-Anzeige, oder
- Verwende `/register_caster`

Spieler können gleichzeitig als Caster **und** mit Squads angemeldet sein.

### Status einsehen

- **Mein Squad/Caster** Button — Zeigt deine Zuweisungen und ggf. Wartelistenposition
- `/squad_list` — Zeigt alle registrierten Squads
- `/find [name]` — Sucht nach einem Squad oder Spieler
### Abmelden

- Klicke auf **Abmelden** in der Event-Anzeige, oder
- Verwende `/unregister`

Du erhältst einen Bestätigungsdialog, bevor die Abmeldung durchgeführt wird.

### Alle Spieler-Befehle

| Befehl | Beschreibung |
|---|---|
| `/register` | Geführte Squad-Anmeldung (Typ → Spielstil → Name) |
| `/register_squad [name]` | Squad mit vordefiniertem Namen anmelden |
| `/register_caster` | Als Caster anmelden |
| `/unregister` | Vom Event abmelden |
| `/squad_list` | Alle registrierten Squads anzeigen |
| `/find [name]` | Squad oder Spieler suchen |
| `/help` | Verfügbare Befehle anzeigen |

---

## Für Organisatoren

### Event erstellen

Verwende `/event`, um ein Event zu erstellen. Ein Modal erfasst die Basisdaten, danach folgt ein optionaler Rollen-Wizard:

**Modal — Basis-Informationen:**
- Event-Name, Datum, Uhrzeit, Beschreibung
- Anmeldezeitpunkt (Datum/Uhrzeit oder „sofort"/„jetzt" für sofortige Öffnung)

Das Event wird sofort nach dem Absenden des Modals erstellt und angezeigt. Server-Konfiguration (Kapazität, Squad-Größen, Limits) verwendet die Server-Standardwerte aus `/set_defaults`. Event-Erinnerungen können nachträglich mit `/set_event_reminder` gesetzt werden.

**Rollen-Wizard nach Erstellung (optional, 2 Schritte):**

Nach der Event-Erstellung erscheint automatisch ein ephemerer Rollen-Wizard:

*Schritt 1 — Squad-Rollen:*
- Squad-Rep Rollen/User — Wer Squads anmelden darf (Rollen-Gate, wird bei der Anmeldung geprüft)
- Community-Rep Rollen/User — Wer Squads **vor** Anmeldungsstart anmelden darf (Early Access)

*Schritt 2 — Caster-Rollen:*
- Caster Rollen/User — Wer sich als Caster anmelden darf (Rollen-Gate, wird bei der Anmeldung geprüft)
- Caster-Early-Access Rollen/User — Wer sich als Caster **vor** Anmeldungsstart anmelden darf

Jeder Schritt verwendet Mentionable-Select-Menüs, die sowohl Rollen als auch einzelne User unterstützen. Jeder Schritt kann übersprungen werden — ohne Auswahl wird kein Gate gesetzt und jeder kann sich anmelden. Rollen können auch nachträglich mit `/set_event_roles` konfiguriert werden.

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

Organisatoren können ein laufendes Event per DM bearbeiten: Klicke im Admin-Menü auf **Event bearbeiten**. Der Bot sendet eine nummerierte Liste mit 15 bearbeitbaren Eigenschaften:

1. Event-Name
2. Datum
3. Uhrzeit
4. Beschreibung
5. Server max. Spieler
6. Max. Caster-Slots
7. Max. Fahrzeug-Squads
8. Max. Heli-Squads
9. Infanterie-Squad-Größe
10. Fahrzeug-Squad-Größe
11. Heli-Squad-Größe
12. Max. Squads pro Spieler
13. Event-Erinnerung (Minuten, 0 = deaktivieren)
14. Anmeldezeitpunkt
15. Event-Bild (Bild hochladen oder HTTPS-URL einfügen)

Jede Änderung zeigt den alten → neuen Wert mit einem Bestätigungsschritt. Die Event-Anzeige im Kanal wird nach jeder Änderung automatisch aktualisiert.

### Rollen-Konfiguration

Alle Rollen-Befehle funktionieren als Toggle — einmal ausführen fügt hinzu, erneut ausführen entfernt. Jede Rolle unterstützt Mehrfachauswahl (mehrere Discord-Rollen und einzelne User).

| Befehl | Beschreibung |
|---|---|
| `/set_squad_rep_role [role] [user]` | Squad-Rep Rolle/User hinzufügen oder entfernen |
| `/set_community_rep_role [role] [user]` | Community-Rep Rolle/User hinzufügen oder entfernen (Early Access) |
| `/set_caster_role [role] [user]` | Caster Rolle/User hinzufügen oder entfernen |
| `/set_streamer_role [role] [user]` | Streamer Rolle/User hinzufügen oder entfernen |
| `/set_ping_role [roles]` | Rollen für Ping bei Anmeldungsstart setzen (bis zu 3) |

### Event-Verwaltung

| Befehl | Beschreibung |
|---|---|
| `/event` | Neues Event erstellen (geführter Wizard) |
| `/show_event` | Event mit interaktiven Buttons anzeigen |
| `/open` | Anmeldung sofort öffnen |
| `/close` | Anmeldung schließen |
| `/delete_event` | Event löschen |
| `/set_channel` | Kanal für Event-Updates setzen |
| `/set_event_reminder [minutes]` | Erinnerung X Minuten vor Event-Start (0 = deaktivieren) |
| `/set_max_squads [count]` | Max. Squads pro Spieler setzen |
| `/update` | Event-Anzeige aktualisieren |

### Admin-Tools

| Befehl | Beschreibung |
|---|---|
| `/admin_add_squad` | Squad hinzufügen (geführter Ablauf mit Dropdown) |
| `/admin_add_caster [user]` | Caster hinzufügen (umgeht Zeit-/Rollenbeschränkungen) |
| `/admin_remove_caster` | Caster entfernen (Dropdown-Auswahl) |
| `/admin_squad_remove` | Squad entfernen (Dropdown-Auswahl) |
| `/admin_waitlist` | Vollständige Warteliste anzeigen |
| `/admin_user_assignments` | Alle User-Zuweisungen anzeigen |
| `/admin_user_info [user]` | Discord-ID, Username und Squad-/Caster-Zuweisung anzeigen |
| `/reset_team_assignment [user]` | Zuweisung eines Users zurücksetzen |
| `/export_csv` | Squad-Liste als CSV exportieren |
| `/admin_help` | Admin-Hilfe anzeigen |

### System-Befehle

| Befehl | Beschreibung |
|---|---|
| `/sync` | Slash-Commands synchronisieren |
| `/export_log` | Log-Datei exportieren |
| `/clear_log` | Log-Datei leeren |
| `/clear_messages [count]` | Nachrichten im Kanal löschen |

---

## Interaktive Buttons

Die Event-Anzeige enthält folgende Buttons. Alle Buttons sind für jeden sichtbar — Berechtigungen werden beim Klicken geprüft.

| Button | Funktion |
|---|---|
| **Squad anmelden** | Startet die geführte Anmeldung (Typ → Spielstil → Name) |
| **Als Caster anmelden** | Direkte Caster-Anmeldung |
| **Mein Squad/Caster** | Zeigt eigene Zuweisungen und Wartelistenposition |
| **Abmelden** | Squad/Caster abmelden mit Bestätigung |
| **Admin** | Öffnet Admin-Aktionen (Squad hinzufügen/entfernen, Event per DM bearbeiten, Event löschen) |

---

## Wartelisten-System

- **Automatische Platzierung** — Wenn alle Slots eines Squad-Typs belegt sind, wird der Squad automatisch auf die Warteliste gesetzt. Gleiches gilt für Caster.
- **Automatisches Nachrücken** — Sobald ein Platz frei wird (z.B. durch Abmeldung), rückt der nächste Squad auf der Warteliste automatisch nach.
- **Reihenfolge** — Squads auf der Warteliste werden nach Anmeldezeitpunkt sortiert (First Come, First Served).
- **DM-Benachrichtigung** — Wenn ein Squad von der Warteliste ins Event nachrückt, erhält der Spieler eine automatische DM-Benachrichtigung.
- **Warteliste einsehen** — Spieler sehen ihre Position über den **Mein Squad/Caster** Button. Organisatoren sehen die vollständige Warteliste mit `/admin_waitlist`.

---

## Häufig gestellte Fragen

**F: Wie melde ich meinen Squad an?**
A: Klicke auf **Squad anmelden** in der Event-Anzeige oder verwende `/register`. Du wirst durch Typ, Spielstil und Namenswahl geführt.

**F: Kann ich gleichzeitig Caster und Squad-Mitglied sein?**
A: Ja. Du kannst dich als Caster anmelden und parallel Squads registrieren.

**F: Was passiert, wenn das Event voll ist?**
A: Dein Squad wird automatisch auf die Warteliste gesetzt. Du rückst nach, sobald ein Platz frei wird, und wirst per DM benachrichtigt.

**F: Wie viele Squads kann ich anmelden?**
A: Das hängt von der Event-Konfiguration ab. Der Organisator legt die maximale Anzahl Squads pro Spieler fest (Standard: 1).

**F: Was ist der Unterschied zwischen Infanterie, Fahrzeug und Heli?**
A: Die drei Squad-Typen haben unterschiedliche Größen und separate Slot-Kontingente. Infanterie-Squads sind typischerweise am größten (z.B. 6 Spieler), Fahrzeug-Squads kleiner (z.B. 2) und Heli-Squads am kleinsten (z.B. 1).

**F: Was bedeutet „Early Access"?**
A: Spieler mit Community-Rep- oder Caster-Early-Access-Rolle können sich bereits **vor** dem offiziellen Anmeldungsstart registrieren.

**F: Ich kann mich nicht anmelden — was tun?**
A: Prüfe, ob du die nötige Rolle hast (z.B. Squad-Rep für Squad-Anmeldung) und ob die Anmeldung bereits geöffnet ist. Ohne konfigurierte Rollen kann sich jeder anmelden.

**F: Wie bearbeite ich ein laufendes Event?**
A: Klicke im Admin-Menü auf **Event bearbeiten**. Der Bot sendet dir eine DM mit einer nummerierten Liste aller Eigenschaften. Antworte mit der Nummer der Eigenschaft, die du ändern möchtest.

**F: Warum werden meine Slash-Befehle nicht angezeigt?**
A: Ein Administrator muss `/sync` ausführen, um die Befehle mit Discord zu synchronisieren.

**F: Wie stelle ich ein Event-Bild ein?**
A: Bearbeite das Event per DM (Eigenschaft 15). Du kannst ein Bild hochladen oder eine HTTPS-URL einfügen.

---

Für weitere Unterstützung wende dich an einen Server-Administrator.
