#!/usr/bin/env python3
"""
Internationalization module for the Event Registration Bot.
Supports German (de) and English (en). Default language: German.
"""

from typing import Optional

SUPPORTED_LANGUAGES = {"de", "en"}
DEFAULT_LANGUAGE = "de"

# ---------------------------------------------------------------------------
# Translation strings keyed by dotted path
# ---------------------------------------------------------------------------
_STRINGS: dict[str, dict[str, str]] = {
    # ── General ───────────────────────────────────────────────────────────
    "general.no_active_event": {
        "de": "Es gibt derzeit kein aktives Event in diesem Kanal.",
        "en": "There is no active event in this channel.",
    },
    "general.no_permission": {
        "de": "Du hast keine Berechtigung für diese Aktion.",
        "en": "You do not have permission for this action.",
    },
    "general.requires_organizer": {
        "de": "Nur Mitglieder mit der Organisator-Rolle können diese Aktion ausführen.",
        "en": "Only members with the organizer role can perform this action.",
    },
    "general.requires_admin": {
        "de": "Nur Server-Administratoren können diese Aktion ausführen.",
        "en": "Only server administrators can perform this action.",
    },
    "general.cancelled": {
        "de": "Abgebrochen.",
        "en": "Cancelled.",
    },
    "general.timeout": {
        "de": "Zeitüberschreitung. Bitte starte den Vorgang neu.",
        "en": "Timeout. Please start the process again.",
    },
    "general.error": {
        "de": "Ein Fehler ist aufgetreten: {error}",
        "en": "An error occurred: {error}",
    },
    "general.success": {
        "de": "Erfolgreich!",
        "en": "Success!",
    },
    "general.confirm": {
        "de": "Bestätigen",
        "en": "Confirm",
    },
    "general.cancel": {
        "de": "Abbrechen",
        "en": "Cancel",
    },
    "general.yes": {
        "de": "Ja",
        "en": "Yes",
    },
    "general.no": {
        "de": "Nein",
        "en": "No",
    },
    "general.back": {
        "de": "Zurück",
        "en": "Back",
    },
    "general.skip": {
        "de": "Überspringen",
        "en": "Skip",
    },
    "general.done": {
        "de": "Fertig",
        "en": "Done",
    },

    # ── Setup ─────────────────────────────────────────────────────────────
    "setup.welcome": {
        "de": "**Server-Setup für den Event-Bot**\nBitte wähle die Organisator-Rolle, die Events verwalten darf.",
        "en": "**Server setup for the Event Bot**\nPlease select the organizer role that may manage events.",
    },
    "setup.role_set": {
        "de": "Organisator-Rolle wurde auf **{role}** gesetzt.",
        "en": "Organizer role set to **{role}**.",
    },
    "setup.language_set": {
        "de": "Sprache wurde auf **{language}** gesetzt.",
        "en": "Language set to **{language}**.",
    },
    "setup.log_channel_set": {
        "de": "Log-Kanal wurde auf **#{channel}** gesetzt.",
        "en": "Log channel set to **#{channel}**.",
    },
    "setup.complete": {
        "de": "Setup abgeschlossen! Du kannst die Einstellungen jederzeit mit `/set` ändern.",
        "en": "Setup complete! You can change settings anytime with `/set`.",
    },
    "setup.already_configured": {
        "de": "Dieser Server ist bereits konfiguriert. Nutze `/set` um Einstellungen zu ändern.",
        "en": "This server is already configured. Use `/set` to change settings.",
    },
    "setup.not_configured": {
        "de": "Dieser Server ist noch nicht konfiguriert. Ein Administrator muss zuerst `/setup` ausführen.",
        "en": "This server is not configured yet. An administrator must run `/setup` first.",
    },

    # ── Set commands ──────────────────────────────────────────────────────
    "set.organizer_role": {
        "de": "Organisator-Rolle wurde auf **{role}** geändert.",
        "en": "Organizer role changed to **{role}**.",
    },
    "set.language": {
        "de": "Sprache wurde auf **{language_name}** geändert.",
        "en": "Language changed to **{language_name}**.",
    },
    "set.log_channel": {
        "de": "Log-Kanal wurde auf **#{channel}** geändert.",
        "en": "Log channel changed to **#{channel}**.",
    },
    "set.server_max_players": {
        "de": "Server-Kapazität wurde auf **{value}** Spieler gesetzt.",
        "en": "Server capacity set to **{value}** players.",
    },
    "set.infantry_squad_size": {
        "de": "Infanterie-Squadgröße wurde auf **{value}** gesetzt.",
        "en": "Infantry squad size set to **{value}**.",
    },
    "set.vehicle_squad_size": {
        "de": "Fahrzeug-Squadgröße wurde auf **{value}** gesetzt.",
        "en": "Vehicle squad size set to **{value}**.",
    },
    "set.heli_squad_size": {
        "de": "Heli-Squadgröße wurde auf **{value}** gesetzt.",
        "en": "Heli squad size set to **{value}**.",
    },
    "set.max_vehicle_squads": {
        "de": "Max. Fahrzeug-Squads wurde auf **{value}** gesetzt.",
        "en": "Max vehicle squads set to **{value}**.",
    },
    "set.max_heli_squads": {
        "de": "Max. Heli-Squads wurde auf **{value}** gesetzt.",
        "en": "Max heli squads set to **{value}**.",
    },
    "set.max_caster_slots": {
        "de": "Max. Caster-Plätze wurde auf **{value}** gesetzt.",
        "en": "Max caster slots set to **{value}**.",
    },
    "set.max_squads_per_user": {
        "de": "Max. Squads pro Spieler wurde auf **{value}** gesetzt.",
        "en": "Max squads per user set to **{value}**.",
    },
    "set.caster_registration": {
        "de": "Caster-Registrierung wurde **{state}**.",
        "en": "Caster registration has been **{state}**.",
    },
    "set.caster_enabled": {
        "de": "aktiviert",
        "en": "enabled",
    },
    "set.caster_disabled": {
        "de": "deaktiviert",
        "en": "disabled",
    },
    "set.countdown_seconds": {
        "de": "Countdown vor Registrierungsstart wurde auf **{value}** Sekunden gesetzt.",
        "en": "Countdown before registration start set to **{value}** seconds.",
    },
    "set.current_settings": {
        "de": "**Aktuelle Server-Einstellungen**",
        "en": "**Current server settings**",
    },
    "set.value_too_low": {
        "de": "Der Wert muss mindestens {min} sein.",
        "en": "The value must be at least {min}.",
    },

    # ── Event channel ─────────────────────────────────────────────────────
    "channel.set": {
        "de": "Dieser Kanal wurde als Event-Kanal festgelegt.",
        "en": "This channel has been set as the event channel.",
    },
    "channel.already_has_event": {
        "de": "In diesem Kanal gibt es bereits ein aktives Event.",
        "en": "There is already an active event in this channel.",
    },
    "channel.not_set": {
        "de": "Es wurde noch kein Event-Kanal gesetzt. Verwende `/set_channel`.",
        "en": "No event channel has been set yet. Use `/set_channel`.",
    },

    # ── Event creation ────────────────────────────────────────────────────
    "event.create_title": {
        "de": "Neues Event erstellen",
        "en": "Create new event",
    },
    "event.config_title": {
        "de": "Server-Konfiguration",
        "en": "Server Configuration",
    },
    "event.server_max_label": {
        "de": "Server Max Spieler",
        "en": "Server Max Players",
    },
    "event.max_casters_label": {
        "de": "Max Caster (0 = deaktiviert)",
        "en": "Max Casters (0 = disabled)",
    },
    "event.squad_sizes_label": {
        "de": "Squad-Größen (Inf / Fahr / Heli)",
        "en": "Squad Sizes (Inf / Veh / Heli)",
    },
    "event.max_vehicles_label": {
        "de": "Max Fahrzeug-Squads",
        "en": "Max Vehicle Squads",
    },
    "event.max_helis_label": {
        "de": "Max Heli-Squads",
        "en": "Max Heli Squads",
    },
    "event.config_prompt": {
        "de": "Passe die Server-Konfiguration an:",
        "en": "Customize server configuration:",
    },
    "event.config_continue": {
        "de": "Weiter",
        "en": "Continue",
    },
    "event.invalid_squad_sizes": {
        "de": "Ungültiges Format. Verwende: Zahl / Zahl / Zahl (z.B. 6 / 2 / 1)",
        "en": "Invalid format. Use: Number / Number / Number (e.g. 6 / 2 / 1)",
    },
    "event.name_label": {
        "de": "Event-Name",
        "en": "Event name",
    },
    "event.date_label": {
        "de": "Datum (TT.MM.JJJJ)",
        "en": "Date (DD.MM.YYYY)",
    },
    "event.time_label": {
        "de": "Uhrzeit (HH:MM)",
        "en": "Time (HH:MM)",
    },
    "event.description_label": {
        "de": "Beschreibung (optional)",
        "en": "Description (optional)",
    },
    "event.created": {
        "de": "Event **{name}** wurde erfolgreich erstellt! {reg_info}",
        "en": "Event **{name}** created successfully! {reg_info}",
    },
    "event.already_exists_in_channel": {
        "de": "In diesem Kanal existiert bereits ein aktives Event. Bitte lösche es zuerst.",
        "en": "An active event already exists in this channel. Please delete it first.",
    },
    "event.invalid_date": {
        "de": "Ungültiges Datumsformat. Bitte verwende TT.MM.JJJJ.",
        "en": "Invalid date format. Please use DD.MM.YYYY.",
    },
    "event.invalid_time": {
        "de": "Ungültige Uhrzeit. Format: HH:MM (z.B. 20:00)",
        "en": "Invalid time. Format: HH:MM (e.g. 20:00)",
    },

    # ── Event deletion ────────────────────────────────────────────────────
    "event.delete_confirm": {
        "de": "Bist du sicher, dass du das Event **{name}** löschen möchtest?\nAlle Anmeldungen werden gelöscht.",
        "en": "Are you sure you want to delete the event **{name}**?\nAll registrations will be deleted.",
    },
    "event.delete_confirm_title": {
        "de": "Event wirklich löschen?",
        "en": "Really delete event?",
    },
    "event.delete_button": {
        "de": "Ja, Event löschen",
        "en": "Yes, delete event",
    },
    "event.deleted": {
        "de": "Das Event **{name}** wurde gelöscht.",
        "en": "The event **{name}** has been deleted.",
    },
    "event.deleted_title": {
        "de": "(Gelöscht)",
        "en": "(Deleted)",
    },
    "event.nothing_to_delete": {
        "de": "Es gibt kein aktives Event zum Löschen in diesem Kanal.",
        "en": "There is no active event to delete in this channel.",
    },

    # ── Event expiry ──────────────────────────────────────────────────────
    "event.expired_log": {
        "de": "Event '{name}' ist abgelaufen und wurde automatisch entfernt.",
        "en": "Event '{name}' has expired and was automatically removed.",
    },
    "event.summary_title": {
        "de": "Zusammenfassung: {name}",
        "en": "Summary: {name}",
    },
    "event.summary_date": {
        "de": "Datum",
        "en": "Date",
    },
    "event.summary_squads": {
        "de": "Squads",
        "en": "Squads",
    },
    "event.summary_casters": {
        "de": "Caster",
        "en": "Casters",
    },
    "event.summary_waitlist": {
        "de": "Warteliste",
        "en": "Waitlist",
    },
    "event.summary_players": {
        "de": "Spieler",
        "en": "Players",
    },
    "event.summary_slots_used": {
        "de": "{used}/{max} Spielerplätze belegt",
        "en": "{used}/{max} player slots used",
    },

    # ── Registration ──────────────────────────────────────────────────────
    "reg.open": {
        "de": "Offen",
        "en": "Open",
    },
    "reg.closed": {
        "de": "Geschlossen",
        "en": "Closed",
    },
    "reg.not_open_yet": {
        "de": "Noch nicht geöffnet",
        "en": "Not open yet",
    },
    "reg.opens_at": {
        "de": "Öffnet <t:{ts}:f> (<t:{ts}:R>)",
        "en": "Opens <t:{ts}:f> (<t:{ts}:R>)",
    },
    "reg.closed_message": {
        "de": "Die Anmeldungen für dieses Event sind geschlossen.",
        "en": "Registration for this event is closed.",
    },
    "reg.not_open_message": {
        "de": "Die Registrierung ist noch nicht geöffnet.",
        "en": "Registration is not open yet.",
    },
    "reg.event_started": {
        "de": "Das Event hat bereits begonnen. Eine Anmeldung ist nicht mehr möglich.",
        "en": "The event has already started. Registration is no longer possible.",
    },
    "reg.opened_announcement": {
        "de": "**Die Registrierung für {name} ist jetzt geöffnet!**\nMeldet eure Squads an!",
        "en": "**Registration for {name} is now open!**\nRegister your squads!",
    },
    "reg.opens_soon": {
        "de": "**Die Anmeldung für {name} öffnet <t:{ts}:R>!**\nStart: <t:{ts}:f>",
        "en": "**Registration for {name} opens <t:{ts}:R>!**\nStart: <t:{ts}:f>",
    },
    "reg.opened_now": {
        "de": "Registrierung ist sofort geöffnet.",
        "en": "Registration is open immediately.",
    },
    "reg.opens_at_info": {
        "de": "Registrierung öffnet <t:{ts}:f> (<t:{ts}:R>).",
        "en": "Registration opens <t:{ts}:f> (<t:{ts}:R>).",
    },
    "reg.manually_opened": {
        "de": "Die Registrierung für '{name}' wurde geöffnet!",
        "en": "Registration for '{name}' has been opened!",
    },
    "reg.already_open": {
        "de": "Die Registrierung ist bereits geöffnet.",
        "en": "Registration is already open.",
    },
    "reg.manually_closed": {
        "de": "Die Anmeldungen für '{name}' wurden geschlossen.",
        "en": "Registration for '{name}' has been closed.",
    },

    # ── Squad registration ────────────────────────────────────────────────
    "squad.register_title": {
        "de": "Squad anmelden",
        "en": "Register squad",
    },
    "squad.step_1_title": {
        "de": "Squad anmelden - Schritt 1/2",
        "en": "Register squad - Step 1/2",
    },
    "squad.step_1_desc": {
        "de": "Wähle den Squad-Typ und Spielstil:",
        "en": "Choose squad type and playstyle:",
    },
    "squad.type_select": {
        "de": "Squad-Typ wählen...",
        "en": "Choose squad type...",
    },
    "squad.playstyle_select": {
        "de": "Spielstil wählen...",
        "en": "Choose playstyle...",
    },
    "squad.type_infantry": {
        "de": "⚔️ Infanterie ({size} Spieler)",
        "en": "⚔️ Infantry ({size} players)",
    },
    "squad.type_vehicle": {
        "de": "🛺 Fahrzeug ({size} Spieler)",
        "en": "🛺 Vehicle ({size} players)",
    },
    "squad.type_heli": {
        "de": "🚁 Heli ({size} Spieler)",
        "en": "🚁 Heli ({size} players)",
    },
    "squad.playstyle_casual": {
        "de": "Casual",
        "en": "Casual",
    },
    "squad.playstyle_normal": {
        "de": "Normal",
        "en": "Normal",
    },
    "squad.playstyle_focused": {
        "de": "Focused",
        "en": "Focused",
    },
    "squad.name_label": {
        "de": "Squad-Name",
        "en": "Squad name",
    },
    "squad.name_placeholder": {
        "de": "Gib den Namen deines Squads ein",
        "en": "Enter your squad name",
    },
    "squad.selected_type": {
        "de": "**Typ:** {label}",
        "en": "**Type:** {label}",
    },
    "squad.selected_playstyle": {
        "de": "**Spielstil:** {label}",
        "en": "**Playstyle:** {label}",
    },
    "squad.continue": {
        "de": "Weiter",
        "en": "Continue",
    },
    "squad.registered": {
        "de": "Squad **{name}** ({type}, {size} Spieler, {playstyle}) wurde erfolgreich angemeldet! {info}",
        "en": "Squad **{name}** ({type}, {size} players, {playstyle}) registered successfully! {info}",
    },
    "squad.waitlisted": {
        "de": "Nicht genügend Plätze! Squad **{name}** ({type}, {size} Spieler, {playstyle}) wurde auf die Warteliste gesetzt (Position {pos}). {info}",
        "en": "Not enough slots! Squad **{name}** ({type}, {size} players, {playstyle}) has been waitlisted (position {pos}). {info}",
    },
    "squad.duplicate_name": {
        "de": "Ein Squad mit dem Namen '{name}' existiert bereits.",
        "en": "A squad with the name '{name}' already exists.",
    },
    "squad.max_reached": {
        "de": "Du hast bereits {current}/{max} Squads angemeldet.",
        "en": "You already have {current}/{max} squads registered.",
    },
    "squad.already_assigned": {
        "de": "Du bist bereits dem Squad '{name}' zugewiesen.",
        "en": "You are already assigned to squad '{name}'.",
    },
    "squad.your_squads_info": {
        "de": "(Deine Squads: {current}/{max})",
        "en": "(Your squads: {current}/{max})",
    },
    "squad.unregistered": {
        "de": "Squad **{name}** wurde abgemeldet.",
        "en": "Squad **{name}** has been unregistered.",
    },
    "squad.not_found": {
        "de": "Squad '{name}' ist weder angemeldet noch auf der Warteliste.",
        "en": "Squad '{name}' is neither registered nor on the waitlist.",
    },
    "squad.moved_from_waitlist": {
        "de": "Dein Squad **{name}** ist von der Warteliste ins Event nachgerückt!",
        "en": "Your squad **{name}** has moved from the waitlist into the event!",
    },
    "squad.unregister_confirm": {
        "de": "Bist du sicher, dass du dein Squad **{name}** abmelden möchtest?\n\nDiese Aktion kann nicht rückgängig gemacht werden!",
        "en": "Are you sure you want to unregister your squad **{name}**?\n\nThis action cannot be undone!",
    },
    "squad.unregister_title": {
        "de": "Squad wirklich abmelden?",
        "en": "Really unregister squad?",
    },
    "squad.unregister_button": {
        "de": "Ja, Squad abmelden",
        "en": "Yes, unregister squad",
    },
    "squad.pick_to_unregister": {
        "de": "Wähle das Squad, das du abmelden möchtest:",
        "en": "Choose the squad you want to unregister:",
    },
    "squad.no_role": {
        "de": "Du hast nicht die erforderliche Rolle, um Squads anzumelden.",
        "en": "You don't have the required role to register squads.",
    },

    # ── Caster registration ───────────────────────────────────────────────
    "caster.register": {
        "de": "Als Caster anmelden",
        "en": "Register as caster",
    },
    "caster.registered": {
        "de": "Du wurdest erfolgreich als Caster angemeldet!",
        "en": "You have been registered as a caster!",
    },
    "caster.waitlisted": {
        "de": "Beide Caster-Plätze sind belegt. Du wurdest auf die Caster-Warteliste gesetzt (Position {pos}).",
        "en": "All caster slots are full. You have been waitlisted (position {pos}).",
    },
    "caster.already_registered": {
        "de": "Du bist bereits als Caster angemeldet.",
        "en": "You are already registered as a caster.",
    },
    "caster.unregistered": {
        "de": "Du wurdest als Caster abgemeldet.",
        "en": "You have been unregistered as a caster.",
    },
    "caster.not_registered": {
        "de": "Du bist nicht als Caster angemeldet.",
        "en": "You are not registered as a caster.",
    },
    "caster.disabled": {
        "de": "Caster-Anmeldung ist deaktiviert.",
        "en": "Caster registration is disabled.",
    },
    "caster.moved_from_waitlist": {
        "de": "Du bist von der Caster-Warteliste nachgerückt und jetzt als Caster angemeldet!",
        "en": "You've moved up from the caster waitlist and are now registered as a caster!",
    },
    "caster.unregister_confirm": {
        "de": "Bist du sicher, dass du dich als Caster abmelden möchtest?",
        "en": "Are you sure you want to unregister as a caster?",
    },
    "caster.unregister_title": {
        "de": "Caster wirklich abmelden?",
        "en": "Really unregister as caster?",
    },
    "caster.no_role": {
        "de": "Du hast nicht die erforderliche Rolle, um dich als Caster anzumelden.",
        "en": "You don't have the required role to register as a caster.",
    },

    # ── Event embed / display ─────────────────────────────────────────────
    "embed.title": {
        "de": "Event: {name}",
        "en": "Event: {name}",
    },
    "embed.deleted_title": {
        "de": "Event: {name} (Gelöscht)",
        "en": "Event: {name} (Deleted)",
    },
    "embed.no_description": {
        "de": "Keine Beschreibung verfügbar",
        "en": "No description available",
    },
    "embed.event_start": {
        "de": "📅 Event-Start",
        "en": "📅 Event start",
    },
    "embed.registration": {
        "de": "📋 Registrierung",
        "en": "📋 Registration",
    },
    "embed.reminder": {
        "de": "🔔 Erinnerung",
        "en": "🔔 Reminder",
    },
    "embed.reminder_value": {
        "de": "{minutes} Min. vor Start",
        "en": "{minutes} min before start",
    },
    "embed.reminder_sent": {
        "de": "{minutes} Min. vorher (gesendet)",
        "en": "{minutes} min before (sent)",
    },
    "embed.server_overview": {
        "de": "🖥️ Server",
        "en": "🖥️ Server",
    },
    "embed.server_overview_value": {
        "de": "{cap} Plätze ({free} frei)\nUngenutzt: {unused}",
        "en": "{cap} slots ({free} free)\nUnused: {unused}",
    },
    "embed.max_per_user_label": {
        "de": "👤 Max Squads pro Spieler: {count}",
        "en": "👤 Max squads per user: {count}",
    },
    "embed.no_entries": {
        "de": "-",
        "en": "-",
    },
    "embed.caster_overview_compact": {
        "de": "🎙️ Caster ({count}/{max})",
        "en": "🎙️ Casters ({count}/{max})",
    },
    "embed.type_infantry": {
        "de": "⚔️ Infanterie",
        "en": "⚔️ Infantry",
    },
    "embed.type_vehicle": {
        "de": "🛺 Fahrzeug",
        "en": "🛺 Vehicle",
    },
    "embed.type_heli": {
        "de": "🚁 Heli",
        "en": "🚁 Heli",
    },
    "embed.squads_label": {
        "de": "Squads",
        "en": "Squads",
    },
    "embed.waitlist_label": {
        "de": "⏳ Warteliste ({count})",
        "en": "⏳ Waitlist ({count})",
    },
    "embed.caster_waitlist_label": {
        "de": "⏳ Caster-Warteliste ({count})",
        "en": "⏳ Caster waitlist ({count})",
    },
    "embed.footer": {
        "de": "Nutze die Buttons unten, um dich anzumelden.",
        "en": "Use the buttons below to register.",
    },

    # ── Buttons ───────────────────────────────────────────────────────────
    "button.register_squad": {
        "de": "Squad anmelden",
        "en": "Register squad",
    },
    "button.register_caster": {
        "de": "Als Caster anmelden",
        "en": "Register as caster",
    },
    "button.my_info": {
        "de": "Mein Squad/Caster",
        "en": "My squad/caster",
    },
    "button.unregister": {
        "de": "Abmelden",
        "en": "Unregister",
    },
    "button.admin": {
        "de": "Admin",
        "en": "Admin",
    },

    # ── Info ──────────────────────────────────────────────────────────────
    "info.no_assignment": {
        "de": "Du bist aktuell keinem Squad und keinem Caster-Slot zugewiesen.",
        "en": "You are not currently assigned to any squad or caster slot.",
    },
    "info.caster_assigned": {
        "de": "Du bist als **Caster** für dieses Event angemeldet.",
        "en": "You are registered as a **caster** for this event.",
    },
    "info.caster_waitlisted": {
        "de": "Du stehst auf der **Caster-Warteliste**.",
        "en": "You are on the **caster waitlist**.",
    },
    "info.not_registered": {
        "de": "Du bist nicht angemeldet.",
        "en": "You are not registered.",
    },

    # ── Admin ─────────────────────────────────────────────────────────────
    "admin.title": {
        "de": "Admin-Aktionen",
        "en": "Admin actions",
    },
    "admin.add_squad": {
        "de": "Squad hinzufügen",
        "en": "Add squad",
    },
    "admin.add_caster": {
        "de": "Caster hinzufügen",
        "en": "Add caster",
    },
    "admin.remove_squad": {
        "de": "Squad entfernen",
        "en": "Remove squad",
    },
    "admin.remove_caster": {
        "de": "Caster entfernen",
        "en": "Remove caster",
    },
    "admin.edit_event": {
        "de": "Event bearbeiten",
        "en": "Edit event",
    },
    "admin.delete_event": {
        "de": "Event löschen",
        "en": "Delete event",
    },
    "admin.no_squads": {
        "de": "Keine Squads vorhanden.",
        "en": "No squads available.",
    },
    "admin.no_casters": {
        "de": "Keine Caster vorhanden.",
        "en": "No casters available.",
    },
    "admin.select_rep_user": {
        "de": "Vertreter auswählen",
        "en": "Select representative",
    },
    "admin.selected_rep_user": {
        "de": "👤 Vertreter: **{user}**",
        "en": "👤 Representative: **{user}**",
    },
    "admin.select_squad_remove": {
        "de": "Wähle das Squad, das entfernt werden soll:",
        "en": "Select the squad to remove:",
    },
    "admin.select_caster_remove": {
        "de": "Wähle den Caster, der entfernt werden soll:",
        "en": "Select the caster to remove:",
    },

    # ── Log ───────────────────────────────────────────────────────────────
    "log.event_created": {
        "de": "Event erstellt: '{name}' am {date} um {time} durch {user}. {reg_info}",
        "en": "Event created: '{name}' on {date} at {time} by {user}. {reg_info}",
    },
    "log.event_deleted": {
        "de": "Event gelöscht: {user} hat das Event '{name}' gelöscht",
        "en": "Event deleted: {user} deleted the event '{name}'",
    },
    "log.event_expired": {
        "de": "Event '{name}' ist automatisch abgelaufen.",
        "en": "Event '{name}' expired automatically.",
    },
    "log.squad_registered": {
        "de": "Squad angemeldet: {user} hat Squad '{squad}' ({type}, {size} Spieler, {playstyle}) angemeldet",
        "en": "Squad registered: {user} registered squad '{squad}' ({type}, {size} players, {playstyle})",
    },
    "log.squad_waitlisted": {
        "de": "Squad auf Warteliste: {user} hat Squad '{squad}' auf Warteliste gesetzt",
        "en": "Squad waitlisted: {user} put squad '{squad}' on waitlist",
    },
    "log.squad_unregistered": {
        "de": "Squad abgemeldet: {user} hat Squad '{squad}' abgemeldet (freigegebene Slots: {freed})",
        "en": "Squad unregistered: {user} unregistered squad '{squad}' (freed slots: {freed})",
    },
    "log.squad_moved": {
        "de": "Squad nachgerückt: '{squad}' ({size} Spieler) von der Warteliste ins Event",
        "en": "Squad promoted: '{squad}' ({size} players) moved from waitlist into event",
    },
    "log.caster_registered": {
        "de": "Caster angemeldet: {user} ({uid})",
        "en": "Caster registered: {user} ({uid})",
    },
    "log.caster_unregistered": {
        "de": "Caster abgemeldet: {user} ({uid})",
        "en": "Caster unregistered: {user} ({uid})",
    },
    "log.caster_moved": {
        "de": "Caster nachgerückt: {name} ({uid})",
        "en": "Caster promoted: {name} ({uid})",
    },
    "log.reg_opened": {
        "de": "Registrierung geöffnet für Event '{name}'",
        "en": "Registration opened for event '{name}'",
    },
    "log.reg_closed": {
        "de": "Event geschlossen: {user} hat die Anmeldungen für '{name}' geschlossen",
        "en": "Event closed: {user} closed registration for '{name}'",
    },
    "log.channel_set": {
        "de": "Event-Channel gesetzt: {user} hat Channel '#{channel}' festgelegt",
        "en": "Event channel set: {user} set channel '#{channel}'",
    },
    "log.bot_started": {
        "de": "**Event-Bot gestartet** als `{bot_name}`",
        "en": "**Event Bot started** as `{bot_name}`",
    },

    # ── Edit flow ─────────────────────────────────────────────────────────
    "edit.title": {
        "de": "Event bearbeiten",
        "en": "Edit event",
    },
    "edit.select_property": {
        "de": "Gib die Nummer der Eigenschaft ein, die du ändern möchtest:",
        "en": "Enter the number of the property you want to change:",
    },
    "edit.footer_hint": {
        "de": "Gib eine Zahl ein · 'abbrechen' zum Zurückkehren",
        "en": "Enter a number · 'cancel' to go back",
    },
    "edit.cancel_word": {
        "de": "abbrechen",
        "en": "cancel",
    },
    "edit.not_set": {
        "de": "Nicht gesetzt",
        "en": "Not set",
    },
    "edit.current_value": {
        "de": "Aktueller Wert: `{value}`",
        "en": "Current value: `{value}`",
    },
    "edit.enter_new_value": {
        "de": "Gib den neuen Wert ein:",
        "en": "Enter the new value:",
    },
    "edit.invalid_number": {
        "de": "Ungültige Eingabe. Bitte gib eine Zahl zwischen 1 und {max} ein.",
        "en": "Invalid input. Please enter a number between 1 and {max}.",
    },
    "edit.confirm_change": {
        "de": "Änderung bestätigen?",
        "en": "Confirm change?",
    },
    "edit.old_value": {
        "de": "Alter Wert",
        "en": "Old value",
    },
    "edit.new_value": {
        "de": "Neuer Wert",
        "en": "New value",
    },
    "edit.applied": {
        "de": "Änderung angewendet!",
        "en": "Change applied!",
    },
    "edit.edit_more_question": {
        "de": "Möchtest du eine weitere Eigenschaft ändern?",
        "en": "Would you like to change another property?",
    },
    "edit.yes_more": {
        "de": "Ja, weitere Eigenschaft",
        "en": "Yes, another property",
    },
    "edit.no_done": {
        "de": "Nein, fertig",
        "en": "No, done",
    },
    "edit.finished": {
        "de": "Bearbeitung abgeschlossen.",
        "en": "Editing complete.",
    },
    "edit.dm_sent": {
        "de": "Ich habe dir eine Direktnachricht geschickt. Bitte bearbeite das Event dort.",
        "en": "I sent you a direct message. Please edit the event there.",
    },
    "edit.dm_blocked": {
        "de": "Ich kann dir keine Direktnachricht senden. Bitte aktiviere DMs von Server-Mitgliedern.",
        "en": "I cannot send you a direct message. Please enable DMs from server members.",
    },
    "edit.active_session": {
        "de": "Du hast bereits eine aktive Bearbeitungssitzung in deinen DMs.",
        "en": "You already have an active editing session in your DMs.",
    },
    "edit.property.name": {
        "de": "1. Event-Name",
        "en": "1. Event name",
    },
    "edit.property.date": {
        "de": "2. Datum (TT.MM.JJJJ)",
        "en": "2. Date (DD.MM.YYYY)",
    },
    "edit.property.time": {
        "de": "3. Uhrzeit (HH:MM)",
        "en": "3. Time (HH:MM)",
    },
    "edit.property.description": {
        "de": "4. Beschreibung",
        "en": "4. Description",
    },
    "edit.property.server_max": {
        "de": "5. Server max. Spieler",
        "en": "5. Server max players",
    },
    "edit.property.max_casters": {
        "de": "6. Max. Caster-Plätze",
        "en": "6. Max caster slots",
    },
    "edit.property.max_vehicles": {
        "de": "7. Max. Fahrzeug-Squads",
        "en": "7. Max vehicle squads",
    },
    "edit.property.max_helis": {
        "de": "8. Max. Heli-Squads",
        "en": "8. Max heli squads",
    },
    "edit.property.infantry_size": {
        "de": "9. Infanterie-Squadgröße",
        "en": "9. Infantry squad size",
    },
    "edit.property.vehicle_size": {
        "de": "10. Fahrzeug-Squadgröße",
        "en": "10. Vehicle squad size",
    },
    "edit.property.heli_size": {
        "de": "11. Heli-Squadgröße",
        "en": "11. Heli squad size",
    },
    "edit.property.max_squads_user": {
        "de": "12. Max. Squads pro Spieler",
        "en": "12. Max squads per player",
    },
    "edit.property.reminder": {
        "de": "13. Erinnerung (Min., 0=aus)",
        "en": "13. Reminder (min, 0=off)",
    },
    "edit.property.reg_start": {
        "de": "14. Registrierungsstart",
        "en": "14. Registration start",
    },
    "edit.property.image": {
        "de": "15. Event-Bild (URL)",
        "en": "15. Event image (URL)",
    },
    "edit.image_hint": {
        "de": "Sende eine HTTPS-URL oder lade ein Bild hoch. Sende 'leer' zum Entfernen.",
        "en": "Send an HTTPS URL or upload an image. Send 'empty' to remove.",
    },
    "edit.invalid_url": {
        "de": "Ungültige URL. Bitte sende eine gültige HTTPS-URL oder lade ein Bild hoch.",
        "en": "Invalid URL. Please send a valid HTTPS URL or upload an image.",
    },
    "edit.invalid_date": {
        "de": "Ungültiges Datum. Bitte verwende das Format TT.MM.JJJJ.",
        "en": "Invalid date. Please use the format DD.MM.YYYY.",
    },
    "edit.invalid_time": {
        "de": "Ungültige Uhrzeit. Bitte verwende das Format HH:MM.",
        "en": "Invalid time. Please use the format HH:MM.",
    },
    "edit.invalid_integer": {
        "de": "Ungültige Eingabe. Bitte gib eine positive ganze Zahl ein.",
        "en": "Invalid input. Please enter a positive integer.",
    },
    "edit.recalculated": {
        "de": "Spieler-Slots neu berechnet: {slots}",
        "en": "Player slots recalculated: {slots}",
    },
    "edit.timeout": {
        "de": "Ich bin mir nicht sicher, wohin du gegangen bist. Wir können es später erneut versuchen.",
        "en": "I'm not sure where you went. We can try again later.",
    },
    "edit.cancel_hint": {
        "de": "'abbrechen' zum Zurückkehren",
        "en": "'cancel' to go back",
    },
    "edit.confirm_prompt": {
        "de": "1 Ja\n2 Nein",
        "en": "1 Yes\n2 No",
    },
    "edit.edit_more_prompt": {
        "de": "1 Nein, ich bin fertig\n2 Ja, ich möchte weiter bearbeiten",
        "en": "1 No, I'm done\n2 Yes, I want to continue editing",
    },
    "edit.updated": {
        "de": "Das Event wurde aktualisiert! [Klicke hier um das Event anzusehen.]({link})",
        "en": "The event has been updated! [Click here to view the event.]({link})",
    },
    "edit.reg_start_hint": {
        "de": "Format: TT.MM.JJJJ HH:MM, oder 'sofort'/'now', oder 'leer'/'empty' zum Entfernen",
        "en": "Format: DD.MM.YYYY HH:MM, or 'now'/'sofort', or 'empty'/'leer' to remove",
    },
    "edit.description_hint": {
        "de": "Sende die neue Beschreibung, oder 'leer'/'empty' zum Entfernen.",
        "en": "Send the new description, or 'empty'/'leer' to remove.",
    },
    "edit.image_removed": {
        "de": "Event-Bild entfernt.",
        "en": "Event image removed.",
    },
    "edit.group.general": {
        "de": "Allgemein",
        "en": "General",
    },
    "edit.group.squad_config": {
        "de": "Squad-Konfiguration",
        "en": "Squad configuration",
    },
    "edit.group.extras": {
        "de": "Registrierung & Extras",
        "en": "Registration & extras",
    },
    "log.event_edited": {
        "de": "Event bearbeitet: {user} hat '{property}' geändert (Event: {name})",
        "en": "Event edited: {user} changed '{property}' (Event: {name})",
    },

    # ── Wizard / creation flow ────────────────────────────────────────────
    "wizard.server_capacity": {
        "de": "Server-Kapazität (Spieler)",
        "en": "Server capacity (players)",
    },
    "wizard.squad_sizes": {
        "de": "Squad-Größen (Inf./Fahr./Heli)",
        "en": "Squad sizes (Inf./Veh./Heli)",
    },
    "wizard.max_special_squads": {
        "de": "Max. Fahrzeug-Squads / Max. Heli-Squads",
        "en": "Max vehicle squads / Max heli squads",
    },
    "wizard.max_casters": {
        "de": "Max. Caster-Plätze",
        "en": "Max caster slots",
    },
    "wizard.reg_start": {
        "de": "Registrierungsstart",
        "en": "Registration start",
    },
    "wizard.reg_start_hint": {
        "de": "Leer = 15. des Monats 15:55, oder 'sofort'",
        "en": "Empty = 15th of month 15:55, or 'now'",
    },
    "wizard.immediately": {
        "de": "sofort",
        "en": "now",
    },
    "wizard.reminder_title": {
        "de": "Event-Erinnerung (optional)",
        "en": "Event reminder (optional)",
    },
    "wizard.reminder_none": {
        "de": "Keine Erinnerung",
        "en": "No reminder",
    },
    "wizard.reminder_minutes": {
        "de": "{min} Minuten vorher",
        "en": "{min} minutes before",
    },
    "wizard.squad_rep_title": {
        "de": "Squad-Rep Rolle (optional)",
        "en": "Squad rep role (optional)",
    },
    "wizard.squad_rep_desc": {
        "de": "Wähle die Rolle, die Squads anmelden darf:",
        "en": "Select the role that may register squads:",
    },
    "wizard.community_rep_title": {
        "de": "Community-Rep (optional)",
        "en": "Community rep (optional)",
    },
    "wizard.caster_role_title": {
        "de": "Caster-Rollen (optional)",
        "en": "Caster roles (optional)",
    },
    "wizard.caster_early_title": {
        "de": "Caster Vorab-Zugang (optional)",
        "en": "Caster early access (optional)",
    },
    "wizard.confirmation_title": {
        "de": "Event-Zusammenfassung — Bitte bestätigen:",
        "en": "Event summary — Please confirm:",
    },
    "wizard.creating": {
        "de": "Event wird erstellt...",
        "en": "Creating event...",
    },
    "wizard.event_cancelled": {
        "de": "Event-Erstellung abgebrochen.",
        "en": "Event creation cancelled.",
    },
    "wizard.summary_name": {
        "de": "Event-Name",
        "en": "Event name",
    },
    "wizard.summary_datetime": {
        "de": "Datum & Uhrzeit",
        "en": "Date & time",
    },
    "wizard.summary_description": {
        "de": "Beschreibung",
        "en": "Description",
    },
    "wizard.summary_registration": {
        "de": "Registrierung",
        "en": "Registration",
    },
    "wizard.summary_reg_immediate": {
        "de": "Sofort geöffnet",
        "en": "Opens immediately",
    },
    "wizard.summary_reg_at": {
        "de": "Öffnet <t:{ts}:f>",
        "en": "Opens <t:{ts}:f>",
    },
    "wizard.summary_roles": {
        "de": "Rollen-Konfiguration",
        "en": "Role configuration",
    },
    "wizard.summary_squad_roles": {
        "de": "Squad-Rep Rollen/Benutzer",
        "en": "Squad rep roles/users",
    },
    "wizard.summary_community_roles": {
        "de": "Community-Rep Rollen/Benutzer",
        "en": "Community rep roles/users",
    },
    "wizard.summary_caster_roles": {
        "de": "Caster-Rollen/Benutzer",
        "en": "Caster roles/users",
    },
    "wizard.summary_caster_early": {
        "de": "Caster Vorab-Zugang",
        "en": "Caster early access",
    },
    "wizard.summary_server": {
        "de": "Server-Einstellungen",
        "en": "Server settings",
    },
    "wizard.summary_none": {
        "de": "Keine",
        "en": "None",
    },
    "wizard.reminder_title": {
        "de": "Event-Erinnerung",
        "en": "Event Reminder",
    },
    "wizard.reminder_desc": {
        "de": "Wähle optional eine Erinnerung, die vor dem Event-Start gesendet wird.",
        "en": "Optionally select a reminder to be sent before the event starts.",
    },
    "wizard.reminder_placeholder": {
        "de": "Erinnerung auswählen...",
        "en": "Select reminder...",
    },
    "wizard.reminder_none": {
        "de": "Keine Erinnerung",
        "en": "No reminder",
    },
    "wizard.reminder_15": {
        "de": "15 Minuten vorher",
        "en": "15 minutes before",
    },
    "wizard.reminder_30": {
        "de": "30 Minuten vorher",
        "en": "30 minutes before",
    },
    "wizard.reminder_60": {
        "de": "1 Stunde vorher",
        "en": "1 hour before",
    },
    "wizard.reminder_120": {
        "de": "2 Stunden vorher",
        "en": "2 hours before",
    },
    "wizard.reminder_240": {
        "de": "4 Stunden vorher",
        "en": "4 hours before",
    },
    "wizard.reminder_480": {
        "de": "8 Stunden vorher",
        "en": "8 hours before",
    },
    "wizard.reminder_1440": {
        "de": "1 Tag vorher",
        "en": "1 day before",
    },
    "wizard.summary_reminder": {
        "de": "Erinnerung",
        "en": "Reminder",
    },
    "wizard.timing_title": {
        "de": "Erinnerung & Countdown",
        "en": "Reminder & Countdown",
    },
    "wizard.timing_desc": {
        "de": "Konfiguriere optionale Erinnerung und Countdown-Nachricht.",
        "en": "Configure optional reminder and countdown message.",
    },
    "wizard.countdown_placeholder": {
        "de": "Countdown auswählen...",
        "en": "Select countdown...",
    },
    "wizard.countdown_none": {
        "de": "Kein Countdown",
        "en": "No countdown",
    },
    "wizard.countdown_10s": {
        "de": "10 Sekunden vorher",
        "en": "10 seconds before",
    },
    "wizard.countdown_60s": {
        "de": "1 Minute vorher",
        "en": "1 minute before",
    },
    "wizard.countdown_300s": {
        "de": "5 Minuten vorher",
        "en": "5 minutes before",
    },
    "wizard.countdown_600s": {
        "de": "10 Minuten vorher",
        "en": "10 minutes before",
    },
    "wizard.countdown_900s": {
        "de": "15 Minuten vorher",
        "en": "15 minutes before",
    },
    "wizard.countdown_1800s": {
        "de": "30 Minuten vorher",
        "en": "30 minutes before",
    },
    "wizard.countdown_3600s": {
        "de": "1 Stunde vorher",
        "en": "1 hour before",
    },
    "wizard.countdown_7200s": {
        "de": "2 Stunden vorher",
        "en": "2 hours before",
    },
    "wizard.countdown_14400s": {
        "de": "4 Stunden vorher",
        "en": "4 hours before",
    },
    "wizard.countdown_28800s": {
        "de": "8 Stunden vorher",
        "en": "8 hours before",
    },
    "wizard.summary_countdown": {
        "de": "Countdown",
        "en": "Countdown",
    },
    "wizard.ping_select_title": {
        "de": "Rollen/Benutzer bei Öffnung pingen?",
        "en": "Ping roles/users on open?",
    },
    "wizard.ping_yes": {
        "de": "Ja — Rollen/Benutzer benachrichtigen",
        "en": "Yes — Notify roles/users",
    },
    "wizard.ping_no": {
        "de": "Nein — Keine Benachrichtigung",
        "en": "No — No notification",
    },
    "wizard.summary_ping": {
        "de": "Ping bei Öffnung",
        "en": "Ping on open",
    },
    "wizard.summary_ping_yes": {
        "de": "Ja",
        "en": "Yes",
    },
    "wizard.summary_ping_no": {
        "de": "Nein",
        "en": "No",
    },
    "wizard.squad_limit_title": {
        "de": "Squad-Limit pro Spieler (optional)",
        "en": "Squad Limit per User (optional)",
    },
    "wizard.squad_limit_desc": {
        "de": "Wie viele Squads darf ein Spieler maximal anmelden? Standard: {default}",
        "en": "How many squads can a user register at most? Default: {default}",
    },
    "wizard.squad_limit_placeholder": {
        "de": "Max. Squads pro Spieler",
        "en": "Max squads per user",
    },
    "ping.reg_closed": {
        "de": "**Die Registrierung für {name} ist geschlossen.**",
        "en": "**Registration for {name} is closed.**",
    },

    # ── Export ────────────────────────────────────────────────────────────
    "export.csv_header": {
        "de": "Hier ist die exportierte Squad-Liste für {name}:",
        "en": "Here is the exported squad list for {name}:",
    },

    # ── Messages clear ────────────────────────────────────────────────────
    "clear.confirm_title": {
        "de": "Nachrichten löschen?",
        "en": "Delete messages?",
    },
    "clear.confirm_desc": {
        "de": "**{count} Nachrichten** löschen?{reason}\n\nNicht rückgängig machbar!",
        "en": "Delete **{count} messages**?{reason}\n\nThis cannot be undone!",
    },
    "clear.confirm_button": {
        "de": "Ja, löschen",
        "en": "Yes, delete",
    },
    "clear.deleted": {
        "de": "{count} Nachrichten gelöscht.",
        "en": "{count} messages deleted.",
    },
    "clear.range_error": {
        "de": "Anzahl muss zwischen 1 und 100 liegen.",
        "en": "Count must be between 1 and 100.",
    },

    # ── Help ──────────────────────────────────────────────────────────────
    "help.title": {
        "de": "Event-Bot Hilfe",
        "en": "Event Bot Help",
    },
    "help.admin_title": {
        "de": "Admin-Befehle für Event-Management",
        "en": "Admin commands for event management",
    },

    # ── Settings display ──────────────────────────────────────────────────
    "settings.title": {
        "de": "Server-Einstellungen",
        "en": "Server settings",
    },
    "settings.organizer_role": {
        "de": "Organisator-Rolle",
        "en": "Organizer role",
    },
    "settings.log_channel": {
        "de": "Log-Kanal",
        "en": "Log channel",
    },
    "settings.language": {
        "de": "Sprache",
        "en": "Language",
    },
    "settings.server_max_players": {
        "de": "Server-Kapazität",
        "en": "Server capacity",
    },
    "settings.infantry_squad_size": {
        "de": "Infanterie-Squadgröße",
        "en": "Infantry squad size",
    },
    "settings.vehicle_squad_size": {
        "de": "Fahrzeug-Squadgröße",
        "en": "Vehicle squad size",
    },
    "settings.heli_squad_size": {
        "de": "Heli-Squadgröße",
        "en": "Heli squad size",
    },
    "settings.max_vehicle_squads": {
        "de": "Max. Fahrzeug-Squads",
        "en": "Max vehicle squads",
    },
    "settings.max_heli_squads": {
        "de": "Max. Heli-Squads",
        "en": "Max heli squads",
    },
    "settings.max_caster_slots": {
        "de": "Max. Caster-Plätze",
        "en": "Max caster slots",
    },
    "settings.max_squads_per_user": {
        "de": "Max. Squads pro Spieler",
        "en": "Max squads per user",
    },
    "settings.caster_registration": {
        "de": "Caster-Registrierung",
        "en": "Caster registration",
    },
    "settings.countdown_seconds": {
        "de": "Countdown-Sekunden",
        "en": "Countdown seconds",
    },
    "settings.not_set": {
        "de": "Nicht gesetzt",
        "en": "Not set",
    },

    # ── Reminder ─────────────────────────────────────────────────────────
    "reminder.set": {
        "de": "Erinnerung auf **{minutes} Minuten** vor Event-Start gesetzt.",
        "en": "Reminder set to **{minutes} minutes** before event start.",
    },
    "reminder.disabled": {
        "de": "Event-Erinnerung deaktiviert.",
        "en": "Event reminder disabled.",
    },
    "log.reminder_set": {
        "de": "Erinnerung gesetzt: {user} hat {minutes} Min. vor Event-Start gesetzt",
        "en": "Reminder set: {user} set {minutes} min before event start",
    },

    # ── Role management ──────────────────────────────────────────────────
    "roles.updated": {
        "de": "Event-Rollen aktualisiert:",
        "en": "Event roles updated:",
    },
    "roles.no_changes": {
        "de": "Keine Änderungen — die ausgewählten Rollen sind bereits gesetzt.",
        "en": "No changes — the selected roles are already set.",
    },
    "roles.cleared": {
        "de": "Event-Rollen gelöscht: {role_type}",
        "en": "Event roles cleared: {role_type}",
    },
    "roles.cleared_all": {
        "de": "Alle Event-Rollen gelöscht.",
        "en": "All event roles cleared.",
    },
    "roles.no_roles": {
        "de": "Keine Rollen zum Löschen vorhanden.",
        "en": "No roles to clear.",
    },
    "log.roles_updated": {
        "de": "Event-Rollen aktualisiert von {user}: {changes}",
        "en": "Event roles updated by {user}: {changes}",
    },
    "log.roles_cleared": {
        "de": "Event-Rollen gelöscht von {user}: {role_type}",
        "en": "Event roles cleared by {user}: {role_type}",
    },

    # ── Admin squad management ───────────────────────────────────────────
    "admin.squad_added": {
        "de": "Squad **{name}** ({type}, {size} Spieler, {playstyle}) hinzugefügt. Status: {status}",
        "en": "Squad **{name}** ({type}, {size} players, {playstyle}) added. Status: {status}",
    },
    "admin.squad_added_waitlist": {
        "de": "Angemeldet",
        "en": "Registered",
    },
    "admin.squad_added_registered": {
        "de": "Warteliste (Position {pos})",
        "en": "Waitlist (position {pos})",
    },
    "admin.squad_edited": {
        "de": "Squad **{name}** Größe geändert: {old} → {new}",
        "en": "Squad **{name}** size changed: {old} → {new}",
    },
    "admin.squad_removed": {
        "de": "Squad **{name}** wurde entfernt ({freed} Slots freigegeben).",
        "en": "Squad **{name}** has been removed ({freed} slots freed).",
    },
    "admin.squad_not_found": {
        "de": "Squad '{name}' nicht gefunden (weder angemeldet noch auf der Warteliste).",
        "en": "Squad '{name}' not found (not registered or waitlisted).",
    },
    "admin.waitlist_title": {
        "de": "Warteliste — {name}",
        "en": "Waitlist — {name}",
    },
    "admin.waitlist_empty": {
        "de": "Die Warteliste ist leer.",
        "en": "The waitlist is empty.",
    },
    "admin.waitlist_squad_entry": {
        "de": "**{pos}.** {name} ({type}, {size} Spieler, {playstyle})",
        "en": "**{pos}.** {name} ({type}, {size} players, {playstyle})",
    },
    "admin.waitlist_caster_entry": {
        "de": "**{pos}.** {name} (<@{uid}>)",
        "en": "**{pos}.** {name} (<@{uid}>)",
    },
    "admin.assignments_title": {
        "de": "Benutzer-Zuweisungen",
        "en": "User Assignments",
    },
    "admin.assignments_empty": {
        "de": "Keine Zuweisungen vorhanden.",
        "en": "No assignments found.",
    },
    "admin.assignment_reset": {
        "de": "Zuweisung von {user} wurde zurückgesetzt (war: {squads}).",
        "en": "Assignment for {user} has been reset (was: {squads}).",
    },
    "admin.user_not_assigned": {
        "de": "Dieser Benutzer hat keine aktive Zuweisung.",
        "en": "This user has no active assignment.",
    },
    "admin.duplicate_squad": {
        "de": "Ein Squad mit dem Namen '{name}' existiert bereits.",
        "en": "A squad with the name '{name}' already exists.",
    },
    "admin.invalid_size": {
        "de": "Ungültige Größe. Muss mindestens 1 sein.",
        "en": "Invalid size. Must be at least 1.",
    },
    "log.admin_squad_added": {
        "de": "Admin: {user} hat Squad '{squad}' ({type}, {size}, {playstyle}) hinzugefügt",
        "en": "Admin: {user} added squad '{squad}' ({type}, {size}, {playstyle})",
    },
    "log.admin_squad_edited": {
        "de": "Admin: {user} hat Squad '{squad}' Größe {old}→{new} geändert",
        "en": "Admin: {user} changed squad '{squad}' size {old}→{new}",
    },
    "log.admin_squad_removed": {
        "de": "Admin: {user} hat Squad '{squad}' entfernt",
        "en": "Admin: {user} removed squad '{squad}'",
    },
    "log.admin_assignment_reset": {
        "de": "Admin: {user} hat Zuweisung von {target} zurückgesetzt",
        "en": "Admin: {user} reset assignment for {target}",
    },

    # ── Role gating ──────────────────────────────────────────────────────
    "gate.squad_denied": {
        "de": "Du hast nicht die erforderliche Rolle oder Berechtigung, um Squads anzumelden.",
        "en": "You do not have the required role or permission to register squads.",
    },
    "gate.caster_denied": {
        "de": "Du hast nicht die erforderliche Rolle oder Berechtigung, um dich als Caster anzumelden.",
        "en": "You do not have the required role or permission to register as a caster.",
    },

    # ── Post-creation wizard ─────────────────────────────────────────────
    "wizard.squad_roles_title": {
        "de": "Rollen-Konfiguration — Schritt 1/2: Squad-Rollen",
        "en": "Role Configuration — Step 1/2: Squad Roles",
    },
    "wizard.squad_roles_desc": {
        "de": "Wähle optional Rollen/Benutzer, die Squads anmelden dürfen und Vorab-Zugang erhalten.\nÜberspringe diesen Schritt, wenn jeder Squads anmelden darf.",
        "en": "Optionally select roles/users who can register squads and get early access.\nSkip this step if anyone should be allowed to register squads.",
    },
    "wizard.caster_roles_title": {
        "de": "Rollen-Konfiguration — Schritt 2/2: Caster-Rollen",
        "en": "Role Configuration — Step 2/2: Caster Roles",
    },
    "wizard.caster_roles_desc": {
        "de": "Wähle optional Rollen/Benutzer, die sich als Caster anmelden dürfen und Vorab-Zugang erhalten.\nÜberspringe diesen Schritt, wenn jeder sich als Caster anmelden darf.",
        "en": "Optionally select roles/users who can register as casters and get early access.\nSkip this step if anyone should be allowed to register as a caster.",
    },
    "wizard.continue": {
        "de": "Weiter →",
        "en": "Continue →",
    },
    "wizard.complete": {
        "de": "Rollen-Konfiguration abgeschlossen!",
        "en": "Role configuration complete!",
    },

    # ── Admin caster ─────────────────────────────────────────────────────
    "admin.caster_added": {
        "de": "**{user}** wurde als Caster hinzugefügt.",
        "en": "**{user}** has been added as a caster.",
    },
    "admin.caster_added_waitlist": {
        "de": "Alle Caster-Plätze sind belegt. **{user}** wurde auf die Caster-Warteliste gesetzt (Position {pos}).",
        "en": "All caster slots are full. **{user}** has been added to the caster waitlist (position {pos}).",
    },
    "admin.caster_already_registered": {
        "de": "**{user}** ist bereits als Caster angemeldet.",
        "en": "**{user}** is already registered as a caster.",
    },
    "log.admin_caster_added": {
        "de": "Admin: {admin} hat {user} als Caster hinzugefügt",
        "en": "Admin: {admin} added {user} as caster",
    },
    "admin.select_caster_add": {
        "de": "Wähle den Benutzer, der als Caster hinzugefügt werden soll:",
        "en": "Select the user to add as caster:",
    },
    "admin.caster_removed": {
        "de": "**{name}** wurde als Caster entfernt.",
        "en": "**{name}** has been removed as caster.",
    },
    "admin.caster_not_found": {
        "de": "Dieser Caster wurde nicht gefunden (möglicherweise bereits entfernt).",
        "en": "This caster was not found (may have already been removed).",
    },
    "log.admin_caster_removed": {
        "de": "Admin: {admin} hat Caster {name} entfernt",
        "en": "Admin: {admin} removed caster {name}",
    },
}


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Get a translated string.

    Parameters
    ----------
    key : str
        Dotted key into the translation table, e.g. ``"squad.registered"``.
    lang : str | None
        Two-letter language code (``"de"`` or ``"en"``).  Falls back to
        ``DEFAULT_LANGUAGE`` if *None* or unsupported.
    **kwargs
        Format variables substituted into the string via :meth:`str.format`.
    """
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    entry = _STRINGS.get(key)
    if entry is None:
        return f"[missing: {key}]"

    text = entry.get(lang)
    if text is None:
        text = entry.get(DEFAULT_LANGUAGE, f"[missing: {key}/{lang}]")

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass  # Return unformatted rather than crash

    return text


def get_language_name(code: str) -> str:
    """Return human-readable language name."""
    return {"de": "Deutsch", "en": "English"}.get(code, code)
