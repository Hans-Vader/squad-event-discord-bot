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

Jede Anmeldung ist ein **einzelner Spieler** — nur der User selbst. Der Bot weist Spieler automatisch Squads zu, in der Reihenfolge der Anmeldung: Die ersten 6 Infanterie-Anmeldungen bilden „Infantry 1", die nächsten 6 „Infantry 2", usw. Beim Event-Start — oder jederzeit manuell durch die Orga über das Admin-Panel — legt der Bot teilweise gefüllte Squads zusammen und entfernt leere Squads, damit die Übersicht kompakt bleibt. Jeder Spieler kann zusätzlich eine **optionale Rolle im Squad** (Squad Leader, Medic, Pilot, …) wählen — die Rolle erscheint hinter dem Namen im Event-Embed, und Squad Leader werden ans obere Ende ihres Squads sortiert. Kein Spielstil, kein Squad-Name, keine Caster-Rolle. **Ein User = eine Anmeldung.**

Dieser Modus eignet sich für Pick-up-Matches oder Community-Events, bei denen sich Einzelpersonen anmelden und die Squad-Zusammensetzung egal ist.

### Kurzvergleich

| Aspekt | Vertreter-Modus | Spieler-Modus |
|---|---|---|
| Was wird angemeldet | Ein Squad (Name + Typ + Spielstil) | Ein einzelner Spieler |
| Wer meldet an | Ein Vertreter für sein Squad | Jeder Spieler für sich selbst |
| Slots pro Anmeldung | `squad_size` (z.B. 6) | 1 |
| Mehrere Anmeldungen pro User | Bis zum Limit | Immer 1 |
| Spielstil-Auswahl | Ja | Nein |
| Rollen-Auswahl im Squad | Nein | Optionale Mehrfachauswahl (Squad Leader, Medic, Pilot, …) |
| Caster | Konfigurierbar | Deaktiviert |
| Anmelde-UI | Squad-Name-Modal + Spielstil | Typ + optionale Rolle, Discord-Anzeigename wird verwendet |
| Slot-Übersicht-Label | „🖥️ Server — 100 Plätze" | „📋 Plätze — 17 Plätze" |
| Admin-Hinzufügen | Squad hinzufügen (Name + Vertreter + Spielstil) | Spieler hinzufügen (Mehrfachauswahl Users + Typ + optionale Rollen) |

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

### Anmelden — Spieler-Modus

Der Button heißt **Beitreten** (🪖) statt **Squad**. Der Ablauf:

1. Klicke auf **Beitreten** (🪖) in der Event-Anzeige
2. Wähle deinen Squad-Typ im Dropdown: Infanterie, Fahrzeug oder Heli
3. Wähle **optional** eine oder mehrere Rollen im Squad — *nur wenn der Event-Ersteller die Rollenauswahl aktiviert hat* (siehe Erstellung Schritt 7; ist sie deaktiviert, gibt es kein Rollen-Dropdown und es werden keine Rollen angezeigt). Das Dropdown ist als „(optional)" gekennzeichnet, passt sich deinem Typ an und erlaubt Mehrfachauswahl:
   - **Infanterie**: Squad Leader, Medic, Rifleman, Automatic Rifleman, Machine Gunner, Combat Engineer, Light Anti Tank, Heavy Anti Tank, Grenadier, Marksman, Scout, Logi-Fahrer, Mörser
   - **Fahrzeug**: Driver, Gunner, Commander
   - **Heli**: Pilot, Spotter, Gunner

   Die Rollenauswahl ist freiwillig — wählst du nichts, erscheint nur dein Name (ohne Klammer-Zusatz).
4. Klicke auf **Weiter** — der Bot weist dich automatisch dem ersten nicht vollen Squad dieses Typs zu (erstellt automatisch ein neues Squad, falls nötig) oder setzt dich auf die Warteliste, wenn alle Plätze belegt sind. Dein Discord-Anzeigename wird verwendet; es gibt kein Namensfeld.

Deine gewählten Rollen werden in Klammern hinter deinem Namen im Event-Embed angezeigt; ohne Rolle steht nur dein Name dort, z.B. `Infantry 1 (3/6): Alice (Squad Leader, Medic), Bob (Rifleman), Carol`. **Squad Leader stehen immer ganz oben in ihrem Squad.** Wählst du **Squad Leader** (allein oder zusammen mit anderen Kits), beeinflusst das auch die Platzierung: Der Bot bevorzugt Squads ohne bestehenden SL und öffnet ein neues Squad, sobald alle aktuellen Squads bereits einen SL haben.

**Ein User, eine Anmeldung.** Wenn du dich erneut anmeldest, obwohl du bereits registriert bist, meldet der Bot das zurück.

### Vorläufig anmelden — Spieler-Modus

Bist du dir noch nicht sicher, ob du mitspielst? Mit dem Button **Vorläufig** (🤔) gibst du an, dass du *vielleicht* dabei bist.

1. Klicke auf **Vorläufig** (🤔) in der Event-Anzeige
2. Wähle deinen **Squad-Typ** und – optional – deine Rolle (wie beim Beitreten)
3. Klicke auf **Weiter**

Vorläufig Angemeldete **belegen keinen echten Squad-Platz**. Sie werden ganz unten im Event-Embed in eigenen Feldern je Squad-Typ gelistet (z.B. „🤔 Vorläufig – Infanterie"), mit der optional gewählten Rolle.

**Wechseln:**
- Bist du bereits **fest** angemeldet und klickst auf **Vorläufig**, erscheint ein Bestätigungsdialog — bei Bestätigung wird dein Squad-Platz freigegeben (Nachrücker von der Warteliste rücken auf) und dein Squad-Typ samt Rolle **übernommen**.
- Bist du **vorläufig** angemeldet und klickst auf **Beitreten** (🪖), öffnet sich die Auswahl bereits mit deinem Typ und deiner Rolle vorausgefüllt; nach **Weiter** bist du fest angemeldet und die vorläufige Anmeldung entfällt.
- Mit **Abmelden** (❌) entfernst du auch eine rein vorläufige Anmeldung (mit Bestätigungsdialog).

### Absagen („Kommt nicht") — Spieler-Modus

Der Button **Abmelden** (❌) hat im Spieler-Modus eine zweite Aktion. Klickst du darauf, während du **nicht** angemeldet bist (kein Platz, keine Warteliste, keine vorläufige Anmeldung), wirst du als **abgemeldet** eingetragen — ein ausdrückliches „Ich komme nicht". Abgemeldete werden in einem Feld **🚫 Abgemeldet** als **allerletzter Abschnitt** des Event-Embeds angezeigt. Es erscheint kein Bestätigungsdialog, da nichts entfernt wird.

- Klicke erneut auf **Abmelden** (❌), um deine Absage zurückzunehmen (Toggle).
- Meldest du dich später fest an (**Beitreten** 🪖) oder **Vorläufig** (🤔), wird die Absage automatisch entfernt.

### Als Caster anmelden

Nur im **Vertreter-Modus** verfügbar (Caster ist im Spieler-Modus deaktiviert).

- Klicke auf **Caster** (🎙️) in der Event-Anzeige

Spieler können gleichzeitig als Caster **und** mit Squads angemeldet sein.

### Abmelden

- Klicke auf **Abmelden** (❌) in der Event-Anzeige

In **beiden Modi** erscheint ein Bestätigungsdialog, bevor die Abmeldung durchgeführt wird — „Möchtest du dich wirklich abmelden? Du verlierst deinen Platz." Du musst auf Abmelden klicken, um zu bestätigen. Nach Abschluss erhältst du eine Bestätigungsnachricht.

Im **Spieler-Modus** gilt: Klickst du auf **Abmelden**, obwohl du *gar keine* Anmeldung hast, gibt es nichts abzumelden — stattdessen wirst du als abgemeldet eingetragen (siehe „Absagen — Spieler-Modus" oben).

### Alle Spieler-Befehle

| Befehl | Beschreibung |
|---|---|
| `/help` | Verfügbare Befehle anzeigen |

---

## Für Organisatoren

### Ersteinrichtung des Servers

Bevor Events erstellt werden können, muss ein Admin `/setup` ausführen:
- **Organisator-Rolle** — welche Rolle Events verwalten darf
- **Log-Kanal** — wohin der Bot alle Aktionen protokolliert
- **Sprache** — Deutsch (de) oder Englisch (en)

Mit `/config_defaults` können die Standardwerte für Event-Erstellung per DM-Dialog bearbeitet werden. Die Übersicht zeigt alle 10 bearbeitbaren Standardwerte mit aktuellen Werten; über das Dropdown kann eine Eigenschaft geändert werden. Änderungen wirken sich auf neu erstellte Events aus.

### Event erstellen

Verwende `/create_event`, um ein Event zu erstellen. Der Bot antwortet mit einer Nachricht, die beide Modi nebeneinander erklärt; wähle einen per Button:

- **🪖 Vertreter-Modus** — durchläuft den vollen Wizard unten.
- **🎮 Spieler-Modus** — überspringt den Caster-Rollen-Schritt und den Max-Squads-pro-User-Schritt, setzt `max_caster_slots = 0` zwangsweise und beschriftet „Server Max Spieler" als „Plätze gesamt".

Nach der Modus-Wahl führt dich ein mehrstufiger Wizard durch:

**Schritt 1 — Basis-Informationen (Modal):**
- Event-Name, Datum, Uhrzeit, Beschreibung
- Anmeldezeitpunkt (Datum/Uhrzeit oder „sofort"/„jetzt" für sofortige Öffnung)

**Schritt 2 — Server-Konfiguration (Modal):**
- Server Max Spieler (Vertreter-Modus) bzw. Plätze gesamt (Spieler-Modus), Max Caster (0 = Caster deaktiviert; im Spieler-Modus fest auf 0 gesetzt und ausgeblendet), Squad-Größen (Inf / Fahr / Heli), Max Fahrzeug-Squads, Max Heli-Squads
- Alle Werte vorausgefüllt aus den Server-Standardwerten (`/config_defaults`)

**Schritt 3 — Anmelde-Rollen:**
- Rollen mit Anmeldeberechtigung — Rollen, deren Mitglieder Squads anmelden dürfen / beitreten können (Rollen-Gate)
- Rollen mit Vorab-Zugang — Rollen, deren Mitglieder **vor** Anmeldungsstart anmelden dürfen
- Benachrichtigung bei Öffnung — Ob diese Rollen bei Anmeldungsstart per @-Erwähnung benachrichtigt werden (wird nur gefragt, wenn die Anmeldung nicht sofort öffnet)

> Diese beiden sind **nur Rollen** — einzelne User können hier nicht ausgewählt werden (Caster in Schritt 5 erlauben weiterhin User).

**Schritt 4 — Slot-Limits (nur sichtbar, wenn eine Anmelde-Rolle konfiguriert ist):**

Begrenze optional, wie viel jede Anmeldegruppe belegen darf. Caster zählen nie mit, und Prozente beziehen sich nur auf die Spieler-Slots. Mitglieder, die das Limit ihrer Gruppe überschreiten, werden mit einer Meldung abgelehnt.
- Rollen mit Vorab-Zugang — max. **% der Spieler-Slots** (alle Vorab-Rollen teilen sich dieses Kontingent)
- Rollen mit Vorab-Zugang — max. **Squads pro Rolle** (nur Vertreter-Modus)
- Reguläre Rollen — max. **Squads pro Nutzer** (nur Vertreter-Modus — das Per-User-Squad-Limit; im Spieler-Modus immer 1)

Die beiden Vorab-Zugang-Limits (% und Squads pro Rolle) gelten **nur bis zur Öffnung der Anmeldung** — sobald die Anmeldung für alle offen ist, melden sich Vorab-Zugang-Mitglieder ohne diese Limits an. Solange die Anmeldung geschlossen ist, gilt für Vorab-Zugang-Mitglieder das Squad-Limit pro Rolle und **nicht** das Per-User-Squad-Limit; sobald die Anmeldung öffnet, gilt auch für sie das Per-User-Limit. Reguläre Anmeldungen unterliegen immer dem Per-User-Squad-Limit.

Im Spieler-Modus wird nur das %-Limit für Vorab-Zugang angezeigt.

**Schritt 5 — Caster-Rollen (nur Vertreter-Modus — im Spieler-Modus übersprungen):**
- Caster Rollen/User — Wer sich als Caster anmelden darf (Rollen-Gate)
- Caster-Early-Access Rollen/User — Wer sich als Caster **vor** Anmeldungsstart anmelden darf
- Ping bei Öffnung

**Schritt 6 — Timing:**
- Event-Erinnerung — Benachrichtigung X Minuten vor Event-Start (0 = deaktiviert)
- Countdown — Nachricht X Sekunden vor Anmeldungsstart (wird bei Öffnung automatisch gelöscht)

**Schritt 7 — Spielstil & Squad-Limit (Vertreter-Modus) / Rollen-Auswahl (Spieler-Modus):**
- *Vertreter-Modus:* Spielstil-Auswahl — ob Squads bei der Anmeldung einen Spielstil wählen. Plus Max. Squads pro Spieler (1–20) — wird hier nur gefragt, wenn **keine** Anmelde-Rolle gesetzt ist; mit Rollen-Gate wird dies in Schritt 4 (Slot-Limits) festgelegt.
- *Spieler-Modus:* Rollen-Auswahl — ob Spieler bei der Anmeldung eine Rolle im Squad (Squad Leader, Medic, Pilot, …) wählen können. **Ist sie deaktiviert, gibt es kein Rollen-Dropdown und im Embed werden keine Rollen angezeigt.** Standard: aktiviert. Kann später auch über den DM-Editor geändert werden.

**Schritt 8 — Slots nicht verschwenden** *(erscheint nur, wenn die Slot-Berechnung mindestens 2 ungenutzte Plätze übrig lässt)*:
- Wenn aktiviert, können die übrigen Infanterie-Plätze durch **übergroße Squads** genutzt werden: bei 4 ungenutzten Plätzen und Squad-Größe 6 kann man ein 6er-, 7er- oder 8er-Squad anmelden. Übergroße Squads gibt es immer in **gleicher Anzahl pro Größe**, damit die Organisatoren beide Teams spiegeln können — die erste übergroße Anmeldung legt die Größe fest (z. B. entweder 4× 7er oder 2× 8er), die verbleibende Anzahl steht neben jeder Option. Meldet sich ein übergroßes Squad ab, wird seine Größe wieder angeboten, bis das Paar erneut vollständig ist; sind alle übergroßen Squads weg, gibt es wieder die volle Auswahl. Plätze, die kein Paar mehr ergeben, bleiben ungenutzt. Mit aktiviertem Modus verschwindet der „Ungenutzt"-Zähler aus dem Event-Embed. Standard: deaktiviert. Kann später auch über den DM-Editor geändert werden (Eigenschaft 23).

**Schritt 9 — Bestätigung:**
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

Mit aktiviertem **Slots nicht verschwenden** würden diese 2 ungenutzten Slots stattdessen ein Paar 7er-Infanterie-Squads erlauben.

### Event per DM bearbeiten

Organisatoren können ein laufendes Event per DM bearbeiten: Klicke im Admin-Panel auf **Event bearbeiten**. Der Bot sendet dir eine einzelne DM mit einer Übersicht aller Eigenschaften und ihrer aktuellen Werte, einem **Dropdown** zur Auswahl der zu ändernden Eigenschaft und einem **Fertig**-Button. Wähle eine Eigenschaft → ein kleiner Editor erscheint (Texteingabe, Ja/Nein-Schalter oder Wert-Dropdown) → deine Änderung wird **sofort gespeichert** und die Übersicht aktualisiert sich. Drücke **Fertig**, wenn du fertig bist. Die Event-Anzeige im Kanal wird nach jeder Änderung automatisch aktualisiert.

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
17. Eventdauer (Länge des Events; Standard 2 Std.)
18. Folge-Event erstellen nach (bei Wiederholung: Verzögerung nach dem Ende, bis das nächste Event erstellt wird)
19. Spielstil-Auswahl bei Anmeldung (an/aus)
20. Slot-Limit: Vorab-Zugang (% der Spieler-Slots)
21. Max. Squads pro Vorab-Zugang-Rolle
22. Rollenauswahl bei Anmeldung (Spieler-Modus, an/aus)
23. Slots nicht verschwenden (größere Squads, an/aus)

Es gibt keinen separaten Bestätigungsschritt — jede Änderung greift sofort.

Änderungen an Datum/Uhrzeit, Wiederholung, Eventdauer oder „Folge-Event erstellen nach" werden validiert — falls die nächste Wiederholung noch während des aktuellen Events (bis `Start + Dauer + Verzögerung`) fallen würde, wird die Änderung mit einer Erklärung abgelehnt. Verkürze das Event, reduziere die Verzögerung oder wähle einen längeren Wiederholungsrhythmus.

### Wiederkehrende Events

Du kannst festlegen, dass ein Event automatisch ein Folgeevent erstellt. Konfiguriert wird das per DM-Bearbeitung über die Eigenschaften 16 (Wiederholung), 17 (Eventdauer) und 18 (Folge-Event erstellen nach).

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

**„Folge-Event erstellen nach"-Presets:** 1 Min, 5 Min (Standard), 10 Min, 30 Min, 1 Std, 6 Std, 1 Tag, 1 Woche.

**Ablauf:**

- Bei `Start` — die Anmeldung wird automatisch geschlossen. Neue Anmeldungen, Abmeldungen und Squad-Wechsel werden abgelehnt. Im Spieler-Modus werden dabei teilweise gefüllte Squads automatisch zusammengelegt.
- Bei `Start + Dauer` — für **nicht wiederkehrende** Events: Zusammenfassung wird in den Log-Kanal geschrieben, das Embed wird gelöscht. Fertig.
- Bei `Start + Dauer` — für **wiederkehrende** Events: nichts Sichtbares passiert. Das Embed bleibt als schreibgeschützter Snapshot des Endstands im Kanal sichtbar.
- Bei `Start + Dauer + Verzögerung` — für **wiederkehrende** Events: die Zusammenfassung wird geloggt, das alte Embed wird gelöscht, ein frisches Event wird erstellt und gepostet. Das neue Event übernimmt die komplette Konfiguration (Name, Slot-Größen, Rollen-Pings, Wiederholung, Dauer, Verzögerung) und setzt den Laufzeit-Zustand zurück.

### Admin-Panel — Vertreter-Modus

Klicke auf den **Admin** (⚙️) Button im Event-Embed, um das Admin-Panel zu öffnen. Im Vertreter-Modus enthält es 8 Buttons in 4 Reihen:

| Reihe | Button | Beschreibung |
|---|---|---|
| Squad | **Squad hinzufügen** | Typ, Spielstil und Vertreter auswählen, dann Squad-Name eingeben |
| Squad | **Squad entfernen** | Squad zum Entfernen auswählen (inkl. Warteliste) |
| Caster | **Caster hinzufügen** | Discord-User als Caster hinzufügen |
| Caster | **Caster entfernen** | Caster zum Entfernen auswählen (inkl. Warteliste) |
| Anmeldung | **Anmeldung öffnen** | Anmeldung manuell öffnen — hinter einer Bestätigungsabfrage abgesichert (beim Öffnen kann ein Ping an die konfigurierten Rollen gesendet werden) |
| Anmeldung | **Anmeldung schließen** | Anmeldung manuell schließen — hinter einer Bestätigungsabfrage abgesichert. Bei Vertreter-/Caster-Events wird das Event in den Early-Access-Zustand zurückgesetzt (nur Early-Access-Rollen können sich anmelden) |
| Event | **Event bearbeiten** | Öffnet DM-basierte Bearbeitungssitzung (siehe oben) |
| Event | **Event löschen** | Event mit Bestätigung löschen |

Beim Hinzufügen eines Squads als Admin wird der ausgewählte Vertreter für das Squad-Limit des Users gezählt, aber das Limit wird nicht erzwungen — Admins können immer hinzufügen.

### Admin-Panel — Spieler-Modus

Im Spieler-Modus hat das Admin-Panel 8 Buttons in 3 Reihen — die Squad- und Caster-Reihen werden durch eine einzige Spieler-Reihe ersetzt:

| Reihe | Button | Beschreibung |
|---|---|---|
| Spieler | **Spieler hinzufügen** | Mehrere Discord-User (Mehrfachauswahl), einen Squad-Typ und (optional) eine oder mehrere Rollen im Squad wählen, die für alle ausgewählten User gelten; dann bestätigen. Alle User werden in einem Submit angemeldet. Wenn die Kapazität mitten im Batch aufgebraucht ist, werden die restlichen auf die Warteliste gesetzt. Die gewählten Rollen werden für jeden User gespeichert und neben seinem Namen im Event-Embed angezeigt (ohne Rolle nur der Name). |
| Spieler | **Spieler entfernen** | Einen oder mehrere Spieler auswählen (Mehrfachauswahl) — aus aktuellen Squad-Mitgliedern, aus jeder Warteliste (markiert mit `[WL-Inf]` / `[WL-Veh]` / `[WL-Heli]`) **und** aus der Vorläufig-Liste (markiert mit `[Vorl-Inf]` / `[Vorl-Veh]` / `[Vorl-Heli]`). Die Aktion ist hinter einem roten „Abmelden"-Bestätigungsbutton abgesichert. |
| Spieler | **Vorläufige fragen** (📨) | Fragt die vorläufig Angemeldeten, ob sie teilnehmen. Zuerst wählst du aus, **wen** du fragen willst (Mehrfach-Dropdown) oder drückst **Alle fragen**. Danach **Thread** oder **DM**; beim Thread dann **öffentlich** (direkt an der Event-Nachricht erstellt) oder **privat** (privater Thread, der zusätzlich dich als Orga hinzufügt). Die Nachricht pingt/verlinkt die gewählten Vorläufigen, sodass sie über die vorhandenen **Beitreten** / **Abmelden**-Buttons bestätigen. Wird nur angezeigt, wenn es vorläufig Angemeldete gibt. |
| Anmeldung | **Anmeldung öffnen** | Anmeldung manuell öffnen — hinter einer Bestätigungsabfrage abgesichert (beim Öffnen kann ein Ping an die konfigurierten Rollen gesendet werden) |
| Anmeldung | **Anmeldung schließen** | Anmeldung manuell schließen — hinter einer Bestätigungsabfrage abgesichert |
| Anmeldung | **Squads zusammenlegen** | Teilweise gefüllte Squads zusammenlegen und leere Squads entfernen — hinter einer Bestätigungsabfrage abgesichert. Passiert automatisch auch beim Event-Start. Nur im Spieler-Modus verfügbar. |
| Event | **Event bearbeiten** | Öffnet DM-basierte Bearbeitungssitzung |
| Event | **Event löschen** | Event mit Bestätigung löschen |

Wenn ein Spieler aus einem Squad entfernt wird, wird die Warteliste-Beförderung ausgelöst (DM + Log-Channel-Eintrag für jeden nachgerückten Spieler). Spieler, die von der Warteliste entfernt werden, verschwinden einfach aus der Queue. Die Vorläufig-Liste bleibt beim Event-Start erhalten (wird nicht geleert), sodass **Vorläufige fragen** auch kurz vor Start zum Auffüllen offener Plätze nützlich bleibt.

### Rollen-Konfiguration

| Befehl | Beschreibung |
|---|---|
| `/set_event_roles` | Rollen zum Event hinzufügen (Ping, Squad-Rep, Community-Rep, Caster, Caster Early-Access) |
| `/clear_event_roles` | Event-Rollen löschen — alle auf einmal oder nach Kategorie |

### Event-Verwaltung

| Befehl | Beschreibung |
|---|---|
| `/create_event` | Neues Event erstellen (geführter Wizard) |
| `/delete_event` | Event löschen |
| `/update` | Event-Anzeige aktualisieren |

Anmeldung manuell öffnen oder schließen über den **⚙️ Admin**-Button im Event-Embed.


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
| `/config_defaults` | Server-weite Standardwerte per DM-Dialog bearbeiten |
| `/sync` | Slash-Commands mit Discord synchronisieren |

---

## Interaktive Buttons

Die Event-Anzeige enthält folgende Buttons. Alle Buttons sind für jeden sichtbar — Berechtigungen werden beim Klicken geprüft.

| Button | Funktion |
|---|---|
| **Squad** (🪖) | Vertreter-Modus: startet die geführte Anmeldung (Typ → Spielstil → Name) |
| **Beitreten** (🪖) | Spieler-Modus: Typ und optionale Rolle im Squad wählen, dann automatische Zuweisung zu einem Squad |
| **Caster** (🎙️) | Direkte Caster-Anmeldung |
| **Abmelden** (❌) | Squad/Caster abmelden (mit Bestätigung); im Spieler-Modus schaltet ein Klick ohne aktive Anmeldung stattdessen eine „abgemeldet"-Markierung um |
| **Admin** (⚙️) | Öffnet Admin-Panel (nur Organisator) |
| **Kalender** (📅) | Lädt eine `.ics`-Datei zum Import des Events in deinen Kalender herunter |

---

## Wartelisten-System

Die Wartelisten-Semantik ist in beiden Modi identisch — nur die Einheit unterscheidet sich (ein kompletter Squad im Vertreter-Modus, ein einzelner Spieler im Spieler-Modus).

- **Automatische Platzierung** — Wenn alle Slots eines Typs belegt sind, wird die neue Anmeldung auf die Warteliste gesetzt. Im Vertreter-Modus ist das ein ganzer Squad; im Spieler-Modus ein einzelner Spieler. Caster haben eine eigene Warteliste im Vertreter-Modus (nicht relevant im Spieler-Modus).
- **Automatisches Nachrücken** — Sobald ein Platz frei wird (jemand meldet sich ab), rückt der nächste Warteliste-Eintrag automatisch ins Event. Im Vertreter-Modus rückt ein ganzer Squad nach, wenn er reinpasst; im Spieler-Modus rückt ein Spieler in das erste Squad mit Kapazität nach (erstellt ein neues Squad, falls nötig).
- **Reihenfolge** — First Come, First Served. Die Warteliste wird strikt von vorne nach hinten abgearbeitet.
- **DM-Benachrichtigung** — Wenn du von der Warteliste ins Event nachrückst, erhältst du eine automatische DM. Im Vertreter-Modus erhält der Squad-Vertreter die DM; im Spieler-Modus der einzelne Spieler.
- **Log-Channel-Eintrag** — Der Bot schreibt pro Nachrücken einen Eintrag in den Log-Kanal des Servers für den Audit-Trail.
- **Warteliste einsehen** — Organisatoren sehen die vollständige Warteliste mit `/admin_waitlist`.
- **Von der Warteliste entfernen** — Ein Warteliste-User kann sich selbst abmelden (mit Bestätigung). Organisatoren können Warteliste-Einträge über **Admin → Squad entfernen** (Vertreter-Modus) bzw. **Admin → Spieler entfernen** (Spieler-Modus) entfernen — die Auswahl listet sowohl registrierte als auch Warteliste-Einträge.

---

## Häufig gestellte Fragen

**F: Was ist der Unterschied zwischen Vertreter-Modus und Spieler-Modus?**
A: Im Vertreter-Modus meldest du einen ganzen Squad an (mit Name, Spielstil und einem User als Vertreter). Im Spieler-Modus meldest du dich als einzelne Person an, und der Bot gruppiert Spieler automatisch zu Squads (die ersten 6 Infanterie-Anmeldungen bilden „Infantry 1", die nächsten 6 „Infantry 2", usw.). Caster sind im Spieler-Modus deaktiviert. Organisatoren wählen den Modus bei der Event-Erstellung; er kann nicht mehr geändert werden.

**F: Warum hat mein Event einen „Beitreten"-Button statt einem „Squad"-Button?**
A: Das Event wurde im Spieler-Modus erstellt. Du meldest dich als einzelne Person an — der Bot kümmert sich um die Squad-Zuweisung. Du wählst einen Squad-Typ, optional eine Rolle im Squad (Squad Leader, Medic, …), und klickst dann auf Weiter; dein Discord-Anzeigename wird automatisch verwendet.

**F: Wie melde ich meinen Squad an?**
A: Klicke auf **Squad** (🪖) in der Event-Anzeige. Du wirst durch Typ, Spielstil und Namenswahl geführt. (Das ist der Vertreter-Modus — der Spieler-Modus hat einen **Beitreten**-Ablauf mit Typ und optionaler Rolle.)

**F: Was macht der Rollen-Picker im Spieler-Modus?**
A: Rollen signalisieren, was du gerne spielen würdest (Squad Leader, Medic, Pilot, …), damit andere sehen, wer welche Kits übernimmt. Du kannst **mehrere Rollen** in einer Anmeldung wählen — z.B. „Squad Leader + Medic", falls du beides spielen kannst. Die Liste passt sich dem gewählten Squad-Typ an. Rollen sind für alle in der Squad-Liste sichtbar (`Name (Rolle)` oder `Name (Rolle1, Rolle2)`). Squad Leader werden ans obere Ende ihres Squads sortiert, und ein neuer SL wird bevorzugt in ein Squad ohne bestehenden SL platziert, sofern Kapazität vorhanden ist. Wähle nichts aus, um als **Egal** registriert zu werden.

**F: Kann ich gleichzeitig Caster und Squad-Mitglied sein?**
A: Ja. Du kannst dich als Caster anmelden und parallel Squads registrieren.

**F: Was passiert, wenn das Event voll ist?**
A: Dein Squad wird automatisch auf die Warteliste gesetzt. Du rückst nach, sobald ein Platz frei wird, und wirst per DM benachrichtigt.

**F: Wie viele Squads kann ich anmelden?**
A: Im Vertreter-Modus hängt das vom Event-Setting „Max Squads pro User" ab (Standard: 1, Maximum: 20). Im Spieler-Modus ist es immer **genau 1** — ein User, eine Anmeldung.

**F: Wie melden Admins eine Gruppe von Spielern im Spieler-Modus an?**
A: Admin → Spieler hinzufügen. Die Auswahl erlaubt Mehrfachauswahl von Discord-Usern zusammen mit einem einzelnen Squad-Typ und (optional) einer oder mehrerer Rollen im Squad, die für jeden User im Batch gelten. Alle ausgewählten User werden mit einem Bestätigungsklick angemeldet. Wenn die Kapazität mitten im Batch aufgebraucht ist, gehen die restlichen automatisch auf die Warteliste. Wenn unterschiedliche Rollen-Sets für unterschiedliche Spieler gewünscht sind, einfach mehrere Batches hintereinander durchführen.

**F: Was ist der Unterschied zwischen Infanterie, Fahrzeug und Heli?**
A: Die drei Squad-Typen haben unterschiedliche Größen und separate Slot-Kontingente. Infanterie-Squads sind typischerweise am größten (z.B. 6 Spieler), Fahrzeug-Squads kleiner (z.B. 2) und Heli-Squads am kleinsten (z.B. 1).

**F: Was bedeutet „Early Access"?**
A: Mitglieder einer Rolle mit Vorab-Zugang (oder einer Caster-Early-Access-Rolle) können sich bereits **vor** dem offiziellen Anmeldungsstart registrieren.

**F: Ich kann mich nicht anmelden — was tun?**
A: Prüfe, ob du eine nötige Rolle hast (wenn „Rollen mit Anmeldeberechtigung" konfiguriert sind) und ob die Anmeldung bereits geöffnet ist. Eventuell hast du auch das Slot-Limit deiner Anmeldegruppe erreicht. Ohne konfigurierte Rollen kann sich jeder anmelden.

**F: Wie bearbeite ich ein laufendes Event?**
A: Klicke auf **Admin** → **Event bearbeiten**. Der Bot sendet dir eine DM mit einer Übersicht und einem Dropdown — wähle die zu ändernde Eigenschaft (insgesamt 21), bearbeite sie (die Änderung wird sofort gespeichert) und drücke **Fertig**, wenn du fertig bist.

**F: Wie lasse ich ein Event automatisch wiederkehren?**
A: Bearbeite das Event per DM und öffne Eigenschaft 16 (Wiederholung). Wähle einen der 12 Typen — z.B. „Alle X Wochen" für einen wöchentlichen Zyklus oder „Am letzten Sonntag des nächsten Monats" für ein monatliches Muster, das dem Wochentag deines Events folgt. Das Folgeevent wird automatisch erstellt, sobald das aktuelle endet.

**F: Wie lange bleibt das alte Event sichtbar, nachdem es zu Ende ist?**
A: Bei nicht wiederkehrenden Events wird es direkt bei `Ende` archiviert. Bei wiederkehrenden Events bleibt es bis zum Erstellen des Folgeevents sichtbar (gesteuert über Eigenschaft 18, „Folge-Event erstellen nach" — Standard 5 Minuten).

**F: Warum wurde meine Wiederholungs-Änderung abgelehnt?**
A: Die nächste Wiederholung würde noch während des aktuellen Events (oder während der Verzögerungs-Phase) anstehen. Verkürze das Event, reduziere die Verzögerung oder wähle einen längeren Wiederholungsrhythmus.

**F: Wie richte ich den Bot erstmalig ein?**
A: Ein Admin führt `/setup` aus, um Organisator-Rolle, Log-Kanal und Sprache zu konfigurieren. Dann `/config_defaults` für Serverkapazität und Squad-Größen per DM-Editor. Danach können Organisatoren Events mit `/create_event` erstellen.

**F: Warum werden meine Slash-Befehle nicht angezeigt?**
A: Ein Administrator muss `/sync` ausführen, um die Befehle mit Discord zu synchronisieren.

**F: Wie stelle ich ein Event-Bild ein?**
A: Bearbeite das Event per DM (Eigenschaft 15). Du kannst ein Bild hochladen oder eine HTTPS-URL einfügen.

---

Für weitere Unterstützung wende dich an einen Server-Administrator.
