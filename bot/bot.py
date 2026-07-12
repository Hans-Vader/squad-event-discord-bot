#!/usr/bin/env python3
"""
Event Registration Bot — Multi-guild, multi-event, language-configurable.

Architecture:
- Per-guild settings stored in SQLite (organizer role, defaults, language)
- Events are channel-bound: one active event per channel, multiple channels per guild
- All configuration via /setup (initial) and /set_* commands (ongoing)
- Discord administrators can always configure the bot
- Organizer role can manage events
"""

import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional
import logging
import sys
import csv
import io
import re

from config import TOKEN, ADMIN_IDS, REGISTRATION_CHECK_INTERVAL, REGISTRATION_CHECK_INTERVAL_FAST, REGISTRATION_CRITICAL_WINDOW
from database import (
    init_db, get_guild_settings, save_guild_settings, guild_is_configured,
    get_guild_language, get_event_by_channel, get_all_active_events,
    get_all_active_events_global, save_event, create_event, delete_event,
    expire_event, channel_has_active_event, build_default_event,
    clone_event_for_recurrence,
    DEFAULT_GUILD_SETTINGS,
)
from utils import (
    has_organizer_role, is_guild_admin, has_role, parse_date,
    parse_registration_start, compute_reg_start_15th, generate_squad_id,
    compute_next_occurrence, compute_event_start, compute_event_end,
    validate_recurrence_fits,
    format_event_details, build_event_summary_embed,
    send_to_log_channel, set_log_channel, get_log_channel,
    export_log_file, clear_log_file, logger,
    resolve_event_defaults, role_label,
    _player_register, _player_unregister, _player_remove_from_waitlist,
    _player_waitlist_type, _player_self_unregister,
    _add_tentative, _remove_tentative, _player_tentative_entry, _player_tentative_type,
    _add_declined, _remove_declined, _player_declined_entry,
    _player_current_assignment, _select_tentative,
    consolidate_all_player_squads,
    build_event_ics, _ics_slug,
    infantry_unused_pool, infantry_size_options, dont_waste_slots_active,
)
from i18n import t, SUPPORTED_LANGUAGES, get_language_name

# ---------------------------------------------------------------------------
# Check token
# ---------------------------------------------------------------------------
if not TOKEN:
    logger.critical("No Discord bot token found. Set DISCORD_BOT_TOKEN in .env")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Intents & bot
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True


class EventBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        try:
            self.add_view(EventActionView())
            # Also register the player-mode layout so its extra custom_id
            # (event_tentative) keeps dispatching on persisted messages across
            # restarts. Both views are stateless and route identically via
            # interaction_check, so overlapping custom_ids are harmless.
            self.add_view(EventActionView(mode="player"))
            logger.info("Persistent EventActionView registered")
        except Exception as e:
            logger.error(f"Failed to register persistent view: {e}", exc_info=True)
        try:
            await self.tree.sync()
            logger.info("Slash commands synced")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}", exc_info=True)


bot = EventBot()

# ---------------------------------------------------------------------------
# Per-guild in-memory state (loaded from DB on demand)
# ---------------------------------------------------------------------------
# Locks per guild to protect concurrent state mutations
_guild_locks: dict[int, asyncio.Lock] = {}
# Track active DM edit sessions: user_id ->
# {guild_id, channel_id, db_id, lang, dm_message, active_view, last_activity}
_active_edit_sessions: dict[int, dict] = {}
# A session whose view's on_timeout never fired is considered stuck after this
# many seconds, so a new /edit can reclaim it instead of being blocked forever.
SESSION_STALE_AFTER_SECONDS = 660
# Debounced display update tasks per (guild_id, channel_id)
_display_update_tasks: dict[tuple[int, int], asyncio.Task] = {}

# Data-driven table for the DM edit flow: (number, event_key, i18n_label, value_type, side_effect)
_EDIT_PROPERTIES = [
    (1,  "name",                   "edit.property.name",            "string",          None),
    (2,  "date",                   "edit.property.date",            "date",            None),
    (3,  "time",                   "edit.property.time",            "time",            None),
    (4,  "description",            "edit.property.description",     "string_nullable", None),
    (5,  "server_max_players",     "edit.property.server_max",      "int",             "recalc_slots"),
    (6,  "max_caster_slots",       "edit.property.max_casters",     "int_zero",        "recalc_slots"),
    (7,  "max_vehicle_squads",     "edit.property.max_vehicles",    "int_zero",        None),
    (8,  "max_heli_squads",        "edit.property.max_helis",       "int_zero",        None),
    (9,  "infantry_squad_size",    "edit.property.infantry_size",   "int",             None),
    (10, "vehicle_squad_size",     "edit.property.vehicle_size",    "int",             None),
    (11, "heli_squad_size",        "edit.property.heli_size",       "int",             None),
    (12, "max_squads_per_user",    "edit.property.max_squads_user", "int",             None),
    (13, "event_reminder_minutes", "edit.property.reminder",        "int_nullable",    None),
    (14, "registration_start_time","edit.property.reg_start",       "reg_start",       None),
    (15, "embed_image_url",        "edit.property.image",           "image",           None),
    (16, "recurrence",             "edit.property.recurrence",      "recurrence",      None),
    (17, "duration_minutes",       "edit.property.duration",        "duration",        None),
    (18, "spawn_offset_minutes",   "edit.property.spawn_offset",    "spawn_offset",    None),
    (19, "playstyle_enabled",      "edit.property.playstyle_enabled","bool",           None),
    (20, "community_rep_cap_percent",    "edit.property.early_pct_cap",   "percent",     None),
    (21, "early_access_squads_per_role", "edit.property.early_squad_cap", "squad_count", None),
    (22, "player_roles_enabled",   "edit.property.player_roles_enabled","bool",         None),
    (23, "dont_waste_slots",       "edit.property.dont_waste_slots",    "bool",         None),
]


def _get_guild_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _guild_locks:
        _guild_locks[guild_id] = asyncio.Lock()
    return _guild_locks[guild_id]


# ---------------------------------------------------------------------------
# Guild-defaults property table (used by GuildEditTarget / /config_defaults)
# ---------------------------------------------------------------------------
# (num, key, label_key, vtype, special)  — special always None for guild defaults
_GUILD_EDIT_PROPERTIES = [
    (1,  "server_max_players",             "config_defaults.prop.server_max_players",           "int",      None),
    (2,  "max_caster_slots",               "config_defaults.prop.max_caster_slots",              "int_zero", None),
    (3,  "max_vehicle_squads",             "config_defaults.prop.max_vehicle_squads",            "int_zero", None),
    (4,  "max_heli_squads",                "config_defaults.prop.max_heli_squads",               "int_zero", None),
    (5,  "infantry_squad_size",            "config_defaults.prop.infantry_squad_size",           "int",      None),
    (6,  "vehicle_squad_size",             "config_defaults.prop.vehicle_squad_size",            "int",      None),
    (7,  "heli_squad_size",                "config_defaults.prop.heli_squad_size",               "int",      None),
    (8,  "max_squads_per_user",            "config_defaults.prop.max_squads_per_user",           "int",      None),
    (9,  "caster_registration_enabled",    "config_defaults.prop.caster_registration_enabled",  "bool",     None),
    (10, "registration_countdown_seconds", "config_defaults.prop.registration_countdown_seconds","int_zero", None),
]


# ---------------------------------------------------------------------------
# EditTarget abstraction — makes the DM editor target-aware
# ---------------------------------------------------------------------------

class EditTarget:
    """Abstract base for event vs. guild-defaults targets."""
    kind = ""

    def properties(self):
        raise NotImplementedError

    def load(self, guild_id, channel_id):
        """Return the dict to display/edit, or None if unavailable."""
        raise NotImplementedError

    def overview_embed(self, obj, lang, updated_note=None):
        raise NotImplementedError

    async def persist(self, guild_id, channel_id, prop, new_value, lang, editor_name):
        """Persist one edit. Returns ("ok", payload) | ("gone", None) | ("error", text)."""
        raise NotImplementedError

    def finish_text(self, guild_id, channel_id, lang):
        """Return the Done-message text (may include a markdown link)."""
        raise NotImplementedError


class EventEditTarget(EditTarget):
    """Delegates entirely to the existing event helpers — no logic moved."""
    kind = "event"

    def properties(self):
        return _EDIT_PROPERTIES

    def load(self, guild_id, channel_id):
        event, _ua, _db = _get_channel_event(guild_id, channel_id)
        return event

    def overview_embed(self, obj, lang, updated_note=None):
        return _build_edit_main_embed(obj, lang, updated_note=updated_note)

    async def persist(self, guild_id, channel_id, prop, new_value, lang, editor_name):
        return await _persist_event_edit(guild_id, channel_id, prop, new_value, lang, editor_name)

    def finish_text(self, guild_id, channel_id, lang):
        text = t("edit.finished", lang)
        event, _ua, _db = _get_channel_event(guild_id, channel_id)
        link = _build_event_message_link(event, channel_id, guild_id) if event else None
        if link:
            text = f"{text} [{t('edit.event_link', lang)}]({link})"
        return text


class GuildEditTarget(EditTarget):
    """Targets guild-wide default settings."""
    kind = "guild"

    def properties(self):
        return _GUILD_EDIT_PROPERTIES

    def load(self, guild_id, channel_id):
        return get_guild_settings(guild_id) or dict(DEFAULT_GUILD_SETTINGS)

    def overview_embed(self, obj, lang, updated_note=None):
        return _build_guild_main_embed(obj, lang, updated_note=updated_note)

    async def persist(self, guild_id, channel_id, prop, new_value, lang, editor_name):
        return await _persist_guild_edit(guild_id, prop, new_value, lang, editor_name)

    def finish_text(self, guild_id, channel_id, lang):
        text = t("config_defaults.finished", lang)
        link = f"https://discord.com/channels/{guild_id}/{channel_id}"
        text = f"{text} [{t('config_defaults.channel_link', lang)}]({link})"
        return text


_EVENT_TARGET = EventEditTarget()
_GUILD_TARGET = GuildEditTarget()


def _session_target(user_id):
    """Return the EditTarget for this user's active session. Defaults to event target."""
    s = _active_edit_sessions.get(user_id)
    return (s.get("target") if s else None) or _EVENT_TARGET


def _find_prop_in(table, key):
    """Return the property tuple for `key` in the given table, or None."""
    return next((p for p in table if p[1] == key), None)


def is_player_mode(event) -> bool:
    """True if the given event dict is configured in player mode."""
    return bool(event) and event.get("mode") == "player"


async def _dispatch_player_register(interaction, guild_id: int, channel_id: int, lang: str):
    """Send the player-mode type picker as an ephemeral response. Entry point
    for the Squad button. When the user is currently tentative, the picker is
    pre-filled with their tentative type+role (carried over on the upgrade to a
    firm registration); a successful register then clears the tentative entry."""
    user_id = str(interaction.user.id)
    event, _, _ = _get_channel_event(guild_id, channel_id)
    tent = _player_tentative_entry(event, user_id) if event else None
    if tent:
        view = PlayerTypePickerView(guild_id, channel_id,
                                    initial_type=tent.get("type"),
                                    initial_roles=list(tent.get("roles", [])))
    else:
        view = PlayerTypePickerView(guild_id, channel_id)
    await interaction.response.send_message(
        f"**{t('player.pick_type_title', lang)}**\n{t('player.pick_type_desc', lang)}",
        view=view, ephemeral=True)


async def _dispatch_player_unregister(interaction, guild_id: int, channel_id: int,
                                      lang: str, user_assignments: dict):
    """Show a confirmation dialog for player-mode self-unregister. Entry point
    for the Unregister button. Works for seated players and for players who
    only hold a waitlist spot."""
    user_id = str(interaction.user.id)
    if user_id in (user_assignments or {}):
        squad_names = user_assignments.get(user_id, [])
        squad_name = squad_names[0] if squad_names else "?"
        embed = discord.Embed(
            title=t("player.unregister_confirm_title", lang),
            description=t("player.unregister_confirm", lang, squad=squad_name),
            color=discord.Color.red())
        view = PlayerUnregisterConfirmView(guild_id, channel_id, squad_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    # Not seated — a waitlisted player can still unregister themselves.
    event, _, _ = _get_channel_event(guild_id, channel_id)
    wl_type = _player_waitlist_type(event, user_id) if event else None
    if wl_type is not None:
        type_label = t(f"embed.type_{wl_type}", lang) if wl_type in SQUAD_TYPES else wl_type
        embed = discord.Embed(
            title=t("player.unregister_confirm_title", lang),
            description=t("player.unregister_waitlist_confirm", lang, type=type_label),
            color=discord.Color.red())
        view = PlayerUnregisterConfirmView(guild_id, channel_id, None)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    # Not seated or waitlisted — a tentative player can also withdraw.
    if event and _player_tentative_type(event, user_id) is not None:
        embed = discord.Embed(
            title=t("player.unregister_confirm_title", lang),
            description=t("player.tentative_unregister_confirm", lang),
            color=discord.Color.red())
        view = PlayerUnregisterConfirmView(guild_id, channel_id, None)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    # Not seated, waitlisted or tentative — the Unregister button's second action:
    # toggle an explicit "declined" (not attending) mark.
    await player_decline(interaction, guild_id, channel_id)


async def _dispatch_player_tentative(interaction, guild_id: int, channel_id: int, lang: str):
    """Player-mode tentative entry point (Vorläufig button).

    - Firmly seated → confirm switch (frees the seat, carries over type+role).
    - On a waitlist → confirm switch (frees the waitlist spot).
    - Already tentative → re-open the picker pre-filled to change the selection.
    - Otherwise → fresh tentative type picker.
    """
    user_id = str(interaction.user.id)
    event, user_assignments, _ = _get_channel_event(guild_id, channel_id)

    if user_id in (user_assignments or {}):
        squad_names = user_assignments.get(user_id, [])
        squad_name = squad_names[0] if squad_names else "?"
        embed = discord.Embed(
            title=t("player.tentative_switch_title", lang),
            description=t("player.tentative_switch_confirm", lang, squad=squad_name),
            color=discord.Color.orange())
        view = PlayerTentativeSwitchConfirmView(guild_id, channel_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    wl_type = _player_waitlist_type(event, user_id) if event else None
    if wl_type is not None:
        type_label = t(f"embed.type_{wl_type}", lang) if wl_type in SQUAD_TYPES else wl_type
        embed = discord.Embed(
            title=t("player.tentative_switch_title", lang),
            description=t("player.tentative_switch_waitlist_confirm", lang, type=type_label),
            color=discord.Color.orange())
        view = PlayerTentativeSwitchConfirmView(guild_id, channel_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    tent = _player_tentative_entry(event, user_id) if event else None
    if tent:
        view = PlayerTypePickerView(guild_id, channel_id, tentative=True,
                                    initial_type=tent.get("type"),
                                    initial_roles=list(tent.get("roles", [])))
    else:
        view = PlayerTypePickerView(guild_id, channel_id, tentative=True)
    await interaction.response.send_message(
        f"**{t('player.pick_type_title', lang)}**\n{t('player.pick_type_desc', lang)}",
        view=view, ephemeral=True)


# ---------------------------------------------------------------------------
# Helper: get guild language
# ---------------------------------------------------------------------------
def _lang(interaction_or_guild) -> str:
    """Get language for the guild from an interaction or guild object."""
    if hasattr(interaction_or_guild, "guild") and interaction_or_guild.guild:
        return get_guild_language(interaction_or_guild.guild.id)
    if hasattr(interaction_or_guild, "id"):
        return get_guild_language(interaction_or_guild.id)
    return "de"


def _guild_id(interaction: discord.Interaction) -> int:
    return interaction.guild.id if interaction.guild else 0


# ---------------------------------------------------------------------------
# Helper: get event for the current channel
# ---------------------------------------------------------------------------
def _get_channel_event(guild_id: int, channel_id: int):
    """Load event + assignments from DB for this channel. Returns (event_dict, user_assignments, db_id) or (None, None, None)."""
    row = get_event_by_channel(guild_id, channel_id)
    if row is None:
        return None, None, None
    event = row["event"]
    if not event or not event.get("name"):
        return None, None, None
    # Ensure all expected keys exist
    _ensure_event_keys(event)
    return event, row["user_assignments"], row["db_id"]


def _ensure_event_keys(event: dict):
    """Backfill missing keys on an event dict."""
    defaults = {
        "squads": {}, "casters": {}, "waitlist": [],
        "infantry_waitlist": [], "vehicle_waitlist": [], "heli_waitlist": [],
        "caster_waitlist": [], "tentative": [], "declined": [],
        "max_player_slots": 98, "player_slots_used": 0,
        "max_caster_slots": 2, "caster_slots_used": 0,
        "registration_open": False, "is_closed": False,
        "event_message_id": None, "ping_role_ids": [],
        "squad_rep_role_ids": [], "squad_rep_user_ids": [],
        "community_rep_role_ids": [], "community_rep_user_ids": [],
        "caster_role_ids": [], "caster_user_ids": [],
        "caster_community_role_ids": [], "caster_community_user_ids": [],
        "streamer_role_ids": [], "streamer_user_ids": [],
        "countdown_seconds": None, "countdown_sent": False, "announcement_sent": False,
        "event_reminder_sent": False,
        "ping_on_open": False, "ping_message_ids": [],
        "embed_image_url": None, "event_reminder_minutes": None,
        "recurrence": {"type": "never"},
        "duration_minutes": 120, "spawn_offset_minutes": 5,
        "mode": "rep",
        "dont_waste_slots": False,
        "playstyle_enabled": True,
        "player_roles_enabled": True,
        "community_rep_cap_percent": None,
        "early_access_squads_per_role": None,
    }
    for key, default in defaults.items():
        if key not in event:
            event[key] = default

    # Migrate old shared waitlist to per-type waitlists
    if event.get("waitlist"):
        for entry in event["waitlist"]:
            key = _waitlist_key(entry[1])
            event[key].append(entry)
        event["waitlist"] = []

# ---------------------------------------------------------------------------
# Helper: user assignments
# ---------------------------------------------------------------------------
def get_user_assignments(user_assignments: dict, user_id: str) -> list:
    val = user_assignments.get(str(user_id))
    if val is None:
        return []
    return list(val)


def add_user_assignment(user_assignments: dict, user_id: str, assignment: str):
    uid = str(user_id)
    current = get_user_assignments(user_assignments, uid)
    if not any(a.lower() == assignment.lower() for a in current):
        current.append(assignment)
    user_assignments[uid] = current


def remove_user_assignment(user_assignments: dict, user_id: str, assignment: str):
    uid = str(user_id)
    current = get_user_assignments(user_assignments, uid)
    current = [a for a in current if a.lower() != assignment.lower()]
    if current:
        user_assignments[uid] = current
    elif uid in user_assignments:
        del user_assignments[uid]


def user_has_caster(user_assignments: dict, user_id: str) -> bool:
    return "__caster__" in get_user_assignments(user_assignments, str(user_id))


def get_user_squad_ids(user_assignments: dict, user_id: str) -> list:
    return [a for a in get_user_assignments(user_assignments, str(user_id)) if a != "__caster__"]


def _resolve_squad_name(event, squad_id):
    """Resolve a squad_id to its display name."""
    data = event.get("squads", {}).get(squad_id)
    if data:
        return data.get("name", squad_id)
    for st in ("infantry", "vehicle", "heli"):
        for entry in event.get(f"{st}_waitlist", []):
            if len(entry) > 4 and entry[4] == squad_id:
                return entry[0]
    return squad_id


def _resolve_squad_meta(event, squad_id):
    """Resolve a squad_id to its ``(name, type, size)`` for display.

    Looks in the active squads first, then the per-type waitlists (whose entries
    are ``(name, type, playstyle, size, squad_id, rep_name)`` tuples). Falls back
    to the raw id with ``None`` type/size when the squad can't be found.
    """
    data = event.get("squads", {}).get(squad_id)
    if data:
        return data.get("name", squad_id), data.get("type"), data.get("size")
    for st in ("infantry", "vehicle", "heli"):
        for entry in event.get(f"{st}_waitlist", []):
            if len(entry) > 4 and entry[4] == squad_id:
                return entry[0], entry[1], entry[3]
    return squad_id, None, None


# ---------------------------------------------------------------------------
# Helper: permission checks
# ---------------------------------------------------------------------------
async def check_guild_configured(interaction: discord.Interaction) -> bool:
    """Check if guild is configured. Sends error if not. Returns True if OK."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return False
    if not guild_is_configured(interaction.guild.id):
        lang = _lang(interaction)
        await interaction.response.send_message(t("setup.not_configured", lang), ephemeral=True)
        return False
    return True


async def check_organizer(interaction: discord.Interaction) -> bool:
    """Check if user has organizer role. Sends error if not. Returns True if OK."""
    if not await check_guild_configured(interaction):
        return False
    settings = get_guild_settings(interaction.guild.id)
    lang = _lang(interaction)
    if not has_organizer_role(interaction.user, settings["organizer_role_id"]):
        await interaction.response.send_message(t("general.requires_organizer", lang), ephemeral=True)
        return False
    return True


async def check_admin(interaction: discord.Interaction) -> bool:
    """Check if user is Discord admin. Sends error if not."""
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return False
    lang = _lang(interaction)
    if not is_guild_admin(interaction.user):
        await interaction.response.send_message(t("general.requires_admin", lang), ephemeral=True)
        return False
    return True


# ---------------------------------------------------------------------------
# Helper: send feedback
# ---------------------------------------------------------------------------
async def send_feedback(interaction, message, ephemeral=True, embed=None, view=None):
    done = False
    try:
        done = interaction.response.is_done()
    except Exception:
        pass

    # Smooth transition: confirm dialogs opt in (set interaction.extras["edit_feedback"] = True in
    # their _confirm callback) to have this success/error text REPLACE the dialog message in place
    # instead of appending a new ephemeral. embed=None clears the red confirm embed, view=None drops
    # the Confirm/Cancel buttons — collapsing "Are you sure?" → "✅ done" into a single message.
    extras = getattr(interaction, "extras", None)
    if isinstance(extras, dict) and extras.get("edit_feedback"):
        try:
            if done:  # _confirm defer()s first → deferred message update → edits the dialog message
                await interaction.edit_original_response(content=message, embed=embed, view=view)
            else:
                await interaction.response.edit_message(content=message, embed=embed, view=view)
            return True
        except Exception as e:
            logger.error(f"Error editing feedback, falling back to new message: {e}")

    try:
        kwargs = {"ephemeral": ephemeral}
        if embed:
            kwargs["embed"] = embed
        if view:
            kwargs["view"] = view

        if done:
            await interaction.followup.send(message, **kwargs)
        else:
            await interaction.response.send_message(message, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error sending feedback: {e}")
        try:
            kwargs = {"ephemeral": ephemeral}
            if embed:
                kwargs["embed"] = embed
            if view:
                kwargs["view"] = view
            await interaction.followup.send(message, **kwargs)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Helper: registration checks
# ---------------------------------------------------------------------------
def check_registration_open(event, user=None, registration_type=None):
    """Check if registration is open. Returns (is_open, message_key_or_text)."""
    is_closed = event.get("is_closed", False)
    is_open = event.get("registration_open", False)

    # Block if event already started
    date_str = event.get("date", "")
    time_str = event.get("time", "")
    if date_str and time_str:
        try:
            event_dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
            if datetime.now() >= event_dt:
                return False, "reg.event_started"
        except ValueError:
            pass

    # Early access checks
    if not is_closed and not is_open and user is not None:
        if registration_type == "squad":
            for rid in event.get("community_rep_role_ids", []):
                if has_role(user, rid):
                    return True, None
            if str(user.id) in event.get("community_rep_user_ids", []):
                return True, None
        if registration_type == "caster":
            for rid in event.get("caster_community_role_ids", []):
                if has_role(user, rid):
                    return True, None
            if str(user.id) in event.get("caster_community_user_ids", []):
                return True, None

    # Inline open: if start_time has passed but background loop hasn't caught up yet
    if not is_open and not is_closed:
        start_time = event.get("registration_start_time")
        if start_time and isinstance(start_time, datetime) and datetime.now() >= start_time:
            event["registration_open"] = True
            is_open = True

    if is_closed:
        return False, "reg.closed_message"
    if not is_open:
        start_time = event.get("registration_start_time")
        if start_time and isinstance(start_time, datetime):
            ts = int(start_time.timestamp())
            return False, f"reg.opens_at:{ts}"
        return False, "reg.not_open_message"
    return True, None


def check_role_gate(event, user, registration_type):
    """Check if user is allowed by role/user gate. Returns (allowed, message_key)."""
    if registration_type == "squad":
        role_ids = list(event.get("squad_rep_role_ids", [])) + list(event.get("community_rep_role_ids", []))
        user_ids = list(event.get("squad_rep_user_ids", [])) + list(event.get("community_rep_user_ids", []))
        deny_key = "gate.squad_denied"
    elif registration_type == "caster":
        role_ids = list(event.get("caster_role_ids", [])) + list(event.get("caster_community_role_ids", []))
        user_ids = list(event.get("caster_user_ids", [])) + list(event.get("caster_community_user_ids", []))
        deny_key = "gate.caster_denied"
    else:
        return True, None

    # No gate configured → anyone can register
    if not role_ids and not user_ids:
        return True, None

    # Check user ID
    if str(user.id) in user_ids:
        return True, None

    # Check roles
    for rid in role_ids:
        if has_role(user, rid):
            return True, None

    return False, deny_key


# ---------------------------------------------------------------------------
# Per-register-type registration limits (seat % + early-access squads/role)
# ---------------------------------------------------------------------------
def _member_register_type(member, event):
    """Classify a member by registration role group. Roles only, early-access first.

    Plain role membership (NOT has_role) so admins are classified by their actual
    roles rather than bypassing into every group.
    """
    if member is None:
        return None
    held = {r.id for r in getattr(member, "roles", [])}
    if held & set(event.get("community_rep_role_ids", [])):
        return "community_rep"
    if held & set(event.get("squad_rep_role_ids", [])):
        return "squad_rep"
    return None


def _exempt_from_user_squad_limit(event, member) -> bool:
    """Whether a member skips the per-user squad limit (max_squads_per_user, #12).

    During the early-access window, early-access members are governed by the
    per-role squad cap instead of the per-user limit. Once registration opens the
    per-role cap lifts and #12 applies to them like everyone else.
    """
    if event.get("registration_open"):
        return False
    return _member_register_type(member, event) == "community_rep"


def _seat_cap_slots(event, group):
    """Max player slots a register-type group may consume, or None if uncapped.

    Only early access (community_rep) has a seat-% cap; regular registration has none.
    """
    if group != "community_rep":
        return None
    pct = event.get("community_rep_cap_percent")
    if pct is None:
        return None
    return int(pct) * int(event.get("max_player_slots", 0)) // 100


def _squad_rep_map(user_assignments):
    """Reverse map squad_id → rep user_id from user_assignments."""
    rep_of = {}
    for uid, sids in (user_assignments or {}).items():
        for sid in sids:
            rep_of[sid] = uid
    return rep_of


def _group_seats_used(event, user_assignments, guild, group):
    """Player seats currently consumed by registrants of `group` (both modes)."""
    if guild is None:
        return 0
    used = 0
    if is_player_mode(event):
        for squad in event.get("squads", {}).values():
            for m in squad.get("members", []):
                member = guild.get_member(int(m["user_id"]))
                if member and _member_register_type(member, event) == group:
                    used += 1
    else:
        rep_of = _squad_rep_map(user_assignments)
        for sid, squad in event.get("squads", {}).items():
            uid = rep_of.get(sid)
            if uid is None:
                continue
            member = guild.get_member(int(uid))
            if member and _member_register_type(member, event) == group:
                used += squad.get("size", 0)
    return used


def _early_access_role_squad_counts(event, user_assignments, guild):
    """Per early-access role: how many registered squads its holders have (rep mode)."""
    counts = {rid: 0 for rid in event.get("community_rep_role_ids", [])}
    if guild is None or not counts:
        return counts
    rep_of = _squad_rep_map(user_assignments)
    for sid in event.get("squads", {}):
        uid = rep_of.get(sid)
        if uid is None:
            continue
        member = guild.get_member(int(uid))
        if not member:
            continue
        held = {r.id for r in getattr(member, "roles", [])}
        for rid in counts:
            if rid in held:
                counts[rid] += 1
    return counts


def _seat_cap_usage(event, user_assignments, guild, member):
    """Current early-access seat usage as a '12%/50%' string, or None if no seat-%
    cap applies to this member (not early-access / open / unset)."""
    if event.get("registration_open"):
        return None
    group = _member_register_type(member, event)
    if group != "community_rep":
        return None
    pct = event.get("community_rep_cap_percent")
    if pct is None:
        return None
    max_slots = int(event.get("max_player_slots", 0)) or 0
    used = _group_seats_used(event, user_assignments, guild, group)
    used_pct = round(used / max_slots * 100) if max_slots else 0
    return f"{used_pct}%/{int(pct)}%"


def _squad_role_cap_usage(event, user_assignments, guild, member):
    """Current early-access per-role squad usage as a '3/5' string (the member's
    most-used early-access role), or None if no per-role cap applies."""
    if event.get("registration_open"):
        return None
    if _member_register_type(member, event) != "community_rep":
        return None
    limit = event.get("early_access_squads_per_role")
    if limit is None:
        return None
    counts = _early_access_role_squad_counts(event, user_assignments, guild)
    held = {r.id for r in getattr(member, "roles", [])}
    max_count = max((counts.get(rid, 0) for rid in event.get("community_rep_role_ids", [])
                     if rid in held), default=0)
    return f"{max_count}/{int(limit)}"


def _check_seat_cap(event, user_assignments, guild, member, added_seats):
    """Early-access seat-% cap only. Returns (allowed, message_key_or_None, usage).

    Needs the squad size (added_seats), so it's checked once the squad type is
    known. Lifted once registration is open. `usage` is the current '12%/50%'
    string on block (else None).
    """
    if event.get("registration_open"):
        return True, None, None
    group = _member_register_type(member, event)
    if group is None:
        return True, None, None
    cap = _seat_cap_slots(event, group)
    if cap is None:
        return True, None, None
    used = _group_seats_used(event, user_assignments, guild, group)
    if used + added_seats > cap:
        return False, "gate.seat_cap_reached", _seat_cap_usage(event, user_assignments, guild, member)
    return True, None, None


def _check_squad_count_cap(event, user_assignments, guild, member, mode):
    """Early-access per-role squad-count cap only (rep mode). Returns
    (allowed, key, usage).

    Count-based (size-independent), so it can be checked as early as the button
    press. Counts toward EACH early-access role the member holds. Lifted once
    registration is open. `usage` is the current '3/5' string on block (else None).
    """
    if event.get("registration_open"):
        return True, None, None
    if mode != "rep" or _member_register_type(member, event) != "community_rep":
        return True, None, None
    limit = event.get("early_access_squads_per_role")
    if limit is None:
        return True, None, None
    counts = _early_access_role_squad_counts(event, user_assignments, guild)
    held = {r.id for r in getattr(member, "roles", [])}
    for rid in event.get("community_rep_role_ids", []):
        if rid in held and counts.get(rid, 0) + 1 > limit:
            return False, "gate.squad_role_cap_reached", _squad_role_cap_usage(event, user_assignments, guild, member)
    return True, None, None


def _check_registration_limits(event, user_assignments, guild, member, added_seats, mode):
    """Full early-access cap check (seat-% + per-role squad count) — final authority
    used at registration time. Returns (allowed, message_key_or_None, usage)."""
    ok, key, usage = _check_seat_cap(event, user_assignments, guild, member, added_seats)
    if not ok:
        return ok, key, usage
    return _check_squad_count_cap(event, user_assignments, guild, member, mode)


def _resolve_reg_message(msg_key: str, lang: str) -> str:
    """Resolve a registration check message key to translated text."""
    if msg_key is None:
        return ""
    if msg_key.startswith("reg.opens_at:"):
        ts = msg_key.split(":")[1]
        return t("reg.opens_at", lang, ts=ts)
    return t(msg_key, lang)


# ---------------------------------------------------------------------------
# Helper: squad type config
# ---------------------------------------------------------------------------
def _get_squad_sizes(event: dict) -> dict:
    return {
        "infantry": event.get("infantry_squad_size", 6),
        "vehicle": event.get("vehicle_squad_size", 2),
        "heli": event.get("heli_squad_size", 1),
    }


def _get_max_infantry_squads(event: dict) -> int:
    server_cap = event.get("server_max_players", 100)
    max_casters = event.get("max_caster_slots", 2)
    max_vehicles = event.get("max_vehicle_squads", 6)
    max_helis = event.get("max_heli_squads", 2)
    veh_size = event.get("vehicle_squad_size", 2)
    heli_size = event.get("heli_squad_size", 1)
    inf_size = event.get("infantry_squad_size", 6)
    remaining = server_cap - max_casters - (max_vehicles * veh_size) - (max_helis * heli_size)
    return remaining // inf_size if inf_size > 0 else 0


def _count_registered_squads_of_type(event: dict, squad_type: str) -> int:
    """Count registered (not waitlisted) squads of the given type."""
    return sum(1 for d in event.get("squads", {}).values() if d.get("type") == squad_type)


def _get_max_squads_for_type(event: dict, squad_type: str) -> int:
    """Return the max squad count for the given type."""
    if squad_type == "vehicle":
        return event.get("max_vehicle_squads", 6)
    elif squad_type == "heli":
        return event.get("max_heli_squads", 2)
    return _get_max_infantry_squads(event)


def _is_squad_type_full(event: dict, squad_type: str) -> bool:
    """Check if a squad type has reached its registration limit."""
    return _count_registered_squads_of_type(event, squad_type) >= _get_max_squads_for_type(event, squad_type)


def _squad_slot_reserved(event: dict, squad_type: str, size: int) -> bool:
    """True when a base-size infantry registration would take the squad slot
    reserved for an incomplete oversized pair's mirror (don't-waste mode).
    Sizes other than the current base (e.g. stale waitlist entries after a
    squad-size edit) are never blocked by the reservation."""
    if squad_type != "infantry" or not event.get("dont_waste_slots"):
        return False
    if size != _get_squad_sizes(event)["infantry"]:
        return False
    return dict(infantry_size_options(event)).get(size, 0) <= 0


SQUAD_TYPES = ("infantry", "vehicle", "heli")

ROLES_BY_TYPE = {
    "infantry": [
        "Squad Leader", "Medic", "Rifleman", "Automatic Rifleman",
        "Machine Gunner", "Combat Engineer", "Light Anti Tank",
        "Heavy Anti Tank", "Grenadier", "Marksman", "Scout",
        "Logi driver", "Mortar",
    ],
    "vehicle": ["Driver", "Gunner", "Commander"],
    "heli":    ["Pilot", "Spotter", "Gunner"],
}


def _parse_squad_type_value(value: str) -> tuple:
    """Split a squad-type select value into (squad_type, requested_size).
    Base options use the plain type ("infantry"); oversized infantry options
    encode their size as "infantry:<size>"."""
    if ":" in value:
        squad_type, size = value.split(":", 1)
        return squad_type, int(size)
    return value, None


def _squad_type_options(event: dict, lang: str) -> list:
    """Squad-type SelectOption list for a registration dropdown. Vehicle and
    Heli are omitted when their `max_*_squads` is 0; Infantry is always shown.
    With "don't waste slots" mode active, one option per offerable infantry
    size is shown (oversized values encoded as "infantry:<size>")."""
    sizes = _get_squad_sizes(event) if event else {"infantry": 6, "vehicle": 2, "heli": 1}
    opts = [discord.SelectOption(
        label=t("squad.type_infantry", lang, size=sizes["infantry"]), value="infantry")]
    if event:
        oversized = [(s, r) for s, r in infantry_size_options(event) if s != sizes["infantry"]]
        # Discord caps selects at 25 options; keep room for base + vehicle + heli.
        for size, remaining in oversized[:22]:
            opts.append(discord.SelectOption(
                label=t("squad.type_infantry_sized", lang, size=size, count=remaining),
                value=f"infantry:{size}"))
    if event and event.get("max_vehicle_squads", 0) > 0:
        opts.append(discord.SelectOption(
            label=t("squad.type_vehicle", lang, size=sizes["vehicle"]), value="vehicle"))
    if event and event.get("max_heli_squads", 0) > 0:
        opts.append(discord.SelectOption(
            label=t("squad.type_heli", lang, size=sizes["heli"]), value="heli"))
    return opts


def _waitlist_key(squad_type: str) -> str:
    """Return the event dict key for a squad type's waitlist."""
    return f"{squad_type}_waitlist"


def _all_squad_waitlist_entries(event: dict) -> list:
    """Return a combined list of all per-type waitlist entries."""
    result = []
    for st in SQUAD_TYPES:
        result.extend(event.get(_waitlist_key(st), []))
    return result


def _any_squad_waitlist(event: dict) -> bool:
    """Return True if any squad waitlist is non-empty."""
    return any(event.get(_waitlist_key(st)) for st in SQUAD_TYPES)


def _build_ping_text(event):
    role_ids = set()
    user_ids = set()
    for rid in event.get("ping_role_ids", []):
        role_ids.add(rid)
    for rid in event.get("squad_rep_role_ids", []):
        role_ids.add(rid)
    for uid in event.get("squad_rep_user_ids", []):
        user_ids.add(uid)
    for rid in event.get("caster_role_ids", []):
        role_ids.add(rid)
    for uid in event.get("caster_user_ids", []):
        user_ids.add(uid)
    mentions = [f"<@&{rid}>" for rid in role_ids] + [f"<@{uid}>" for uid in user_ids]
    return (" ".join(mentions) + " ") if mentions else ""


def _build_registered_users_ping_text(user_assignments):
    """Ping prefix mentioning every user currently registered for the event.

    Iterates user_assignments keys — these are the user IDs of squad members
    (rep-mode reps and player-mode players) and casters (whose assignment
    list contains the "__caster__" marker). Waitlisted users are not in
    this dict and therefore not pinged. Returns "" if empty.
    """
    if not user_assignments:
        return ""
    seen = set()
    mentions = []
    for uid in user_assignments.keys():
        uid_str = str(uid)
        if uid_str in seen:
            continue
        seen.add(uid_str)
        mentions.append(f"<@{uid_str}>")
    return (" ".join(mentions) + " ") if mentions else ""


def _build_event_message_link(event, channel_id, guild_id):
    msg_id = event.get("event_message_id")
    if not msg_id or not channel_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"


# ---------------------------------------------------------------------------
# Display update (debounced)
# ---------------------------------------------------------------------------
async def _do_display_update(guild_id: int, channel_id: int):
    try:
        await asyncio.sleep(2)
        event, _, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            return
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                return
        settings = get_guild_settings(guild_id) or DEFAULT_GUILD_SETTINGS
        lang = settings.get("language", "de")
        caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
        await send_event_details(channel, event, db_id, lang, caster_enabled)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in display update: {e}")


async def update_event_displays(guild_id: int, channel_id: int):
    key = (guild_id, channel_id)
    task = _display_update_tasks.get(key)
    if task and not task.done():
        task.cancel()
    _display_update_tasks[key] = asyncio.create_task(_do_display_update(guild_id, channel_id))


async def send_event_details(channel, event, db_id, lang="de", caster_enabled=True):
    """Send or edit event embed in channel."""
    try:
        embed = format_event_details(event, lang, caster_enabled)
        start_dt = compute_event_start(event)
        event_started = start_dt is not None and datetime.now() >= start_dt
        view = EventActionView(
            lang,
            mode=event.get("mode", "rep"),
            is_closed=event.get("is_closed", False),
            event_started=event_started,
        )

        if not isinstance(embed, discord.Embed):
            await channel.send(str(embed), view=view)
            return

        msg_id = event.get("event_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        msg = await channel.send(embed=embed, view=view)
        event["event_message_id"] = msg.id
        # Need to get user_assignments to save
        row = get_event_by_channel(channel.guild.id, channel.id)
        if row:
            save_event(db_id, event, row["user_assignments"])
    except Exception as e:
        logger.error(f"Error sending event details: {e}")


# ---------------------------------------------------------------------------
# Core: squad registration
# ---------------------------------------------------------------------------
async def register_squad(interaction, guild_id, channel_id, squad_name, squad_type, playstyle,
                         requested_size=None):
    """Register a squad. Uses guild lock for thread safety.

    `requested_size` carries an oversized infantry pick from the "don't waste
    slots" select; it is re-validated under the lock because the offerable
    sizes may have changed between the select and the modal submit."""
    lock = _get_guild_lock(guild_id)
    settings = get_guild_settings(guild_id) or DEFAULT_GUILD_SETTINGS
    lang = settings.get("language", "de")
    caster_enabled = settings.get("caster_registration_enabled", True)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False

        is_open, msg_key = check_registration_open(event, user=interaction.user, registration_type="squad")
        if not is_open:
            await send_feedback(interaction, _resolve_reg_message(msg_key, lang), ephemeral=True)
            return False

        allowed, gate_key = check_role_gate(event, interaction.user, "squad")
        if not allowed:
            await send_feedback(interaction, t(gate_key, lang), ephemeral=True)
            return False

        user_id = str(interaction.user.id)
        max_squads = event.get("max_squads_per_user", 1)
        is_ea_exempt = _exempt_from_user_squad_limit(event, interaction.user)
        if not is_ea_exempt:
            current_squads = get_user_squad_ids(user_assignments, user_id)
            if len(current_squads) >= max_squads:
                if max_squads == 1 and current_squads:
                    await send_feedback(interaction, t("squad.already_assigned", lang, name=_resolve_squad_name(event, current_squads[0])), ephemeral=True)
                else:
                    await send_feedback(interaction, t("squad.max_reached", lang, current=len(current_squads), max=max_squads), ephemeral=True)
                return False

        sizes = _get_squad_sizes(event)
        size = sizes.get(squad_type, sizes["infantry"])
        squad_id = generate_squad_id(squad_name, len(event.get("squads", {})))
        available = event["max_player_slots"] - event["player_slots_used"]
        rep_name = interaction.user.display_name

        type_full = _is_squad_type_full(event, squad_type)
        mirror_reserved = False
        if squad_type == "infantry" and requested_size is not None and requested_size != size:
            # Oversized pick: never waitlist or silently resize — the slot
            # either still exists (infantry_size_options self-gates on the
            # toggle, so a mid-dialog config change also lands here) or the
            # user has to pick again.
            if (dict(infantry_size_options(event)).get(requested_size, 0) <= 0
                    or requested_size > available):
                await send_feedback(interaction, t("squad.size_unavailable", lang), ephemeral=True)
                return False
            size = requested_size
        elif not type_full and _squad_slot_reserved(event, squad_type, size):
            type_full = True
            mirror_reserved = True

        ok_lim, lim_key, lim_usage = _check_registration_limits(
            event, user_assignments, interaction.guild, interaction.user, size, "rep")
        if not ok_lim:
            await send_feedback(interaction, t(lim_key, lang, usage=lim_usage), ephemeral=True)
            return False

        wl_key = _waitlist_key(squad_type)
        if type_full:
            event[wl_key].append((squad_name, squad_type, playstyle, size, squad_id, rep_name))
            add_user_assignment(user_assignments, user_id, squad_id)
            save_event(db_id, event, user_assignments)
            result = "type_full_waitlisted"
            wl_pos = len(event[wl_key])
        elif size <= available:
            event["squads"][squad_id] = {
                "name": squad_name, "type": squad_type, "playstyle": playstyle,
                "size": size, "rep_name": rep_name,
            }
            event["player_slots_used"] += size
            add_user_assignment(user_assignments, user_id, squad_id)
            save_event(db_id, event, user_assignments)
            result = "registered"
            wl_pos = None
        else:
            event[wl_key].append((squad_name, squad_type, playstyle, size, squad_id, rep_name))
            add_user_assignment(user_assignments, user_id, squad_id)
            save_event(db_id, event, user_assignments)
            result = "waitlisted"
            wl_pos = len(event[wl_key])

    type_label = t(f"squad.label_{squad_type}", lang) if squad_type in SQUAD_TYPES else squad_type
    if is_ea_exempt:
        # Early-access member: show their early-access cap usage (post-registration),
        # not the per-user #12 count they're exempt from.
        parts = []
        seat_usage = _seat_cap_usage(event, user_assignments, interaction.guild, interaction.user)
        if seat_usage:
            parts.append(t("squad.cap_info_seat", lang, usage=seat_usage))
        squad_usage = _squad_role_cap_usage(event, user_assignments, interaction.guild, interaction.user)
        if squad_usage:
            parts.append(t("squad.cap_info_squads", lang, usage=squad_usage))
        squad_info = ("(" + " · ".join(parts) + ")") if parts else ""
    else:
        user_squads_now = len(get_user_squad_ids(user_assignments, user_id))
        squad_info = t("squad.your_squads_info", lang, current=user_squads_now, max=max_squads)
    playstyle_enabled = event.get("playstyle_enabled", True)

    if result == "registered":
        msg_key = "squad.registered" if playstyle_enabled else "squad.registered_no_playstyle"
        await send_feedback(interaction,
            t(msg_key, lang, name=squad_name, type=type_label, size=size, playstyle=playstyle, info=squad_info),
            ephemeral=True)
        await send_to_log_channel(
            t("log.squad_registered", lang, user=interaction.user.name, squad=squad_name, type=type_label, size=size, playstyle=playstyle),
            guild=interaction.guild)
    elif result == "type_full_waitlisted":
        if mirror_reserved:
            # Not actually full — the last slot is held for an oversized pair's
            # mirror, so don't claim "all slots taken".
            msg_key = "squad.waitlisted_mirror"
        else:
            msg_key = "squad.type_full" if playstyle_enabled else "squad.type_full_no_playstyle"
        await send_feedback(interaction,
            t(msg_key, lang, name=squad_name, type=type_label, size=size, playstyle=playstyle, pos=wl_pos, info=squad_info),
            ephemeral=True)
        await send_to_log_channel(
            t("log.squad_type_full_waitlisted", lang, user=interaction.user.name, squad=squad_name, type=type_label),
            guild=interaction.guild)
    else:
        msg_key = "squad.waitlisted" if playstyle_enabled else "squad.waitlisted_no_playstyle"
        await send_feedback(interaction,
            t(msg_key, lang, name=squad_name, type=type_label, size=size, playstyle=playstyle, pos=wl_pos, info=squad_info),
            ephemeral=True)
        await send_to_log_channel(
            t("log.squad_waitlisted", lang, user=interaction.user.name, squad=squad_name),
            guild=interaction.guild)

    await update_event_displays(guild_id, channel_id)
    return True


# ---------------------------------------------------------------------------
# Core: player-mode registration
# ---------------------------------------------------------------------------
async def player_register(interaction, guild_id, channel_id, squad_type, target_user=None, roles=None):
    """Register a single player into an auto-managed squad (player mode)."""
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)
    user = target_user or interaction.user
    user_id = str(user.id)
    display_name = user.display_name

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False

        if not is_player_mode(event):
            await send_feedback(interaction, t("player.not_player_mode", lang), ephemeral=True)
            return False

        ok_lim, lim_key, lim_usage = _check_registration_limits(
            event, user_assignments, interaction.guild, user, 1, "player")
        if not ok_lim:
            await send_feedback(interaction, t(lim_key, lang, usage=lim_usage), ephemeral=True)
            return False

        squad_name, status = _player_register(event, user_assignments, user_id, display_name, squad_type, roles)
        if status in ("registered", "waitlisted"):
            # A firm sign-up (or waitlist spot) supersedes any tentative entry.
            _remove_tentative(event, user_id)
            save_event(db_id, event, user_assignments)

    type_label = t(f"embed.type_{squad_type}", lang) if squad_type in SQUAD_TYPES else squad_type
    role_labels = [role_label(r, lang) for r in (roles or [])]
    role_suffix = (", " + ", ".join(role_labels)) if role_labels else ""

    if status == "already_registered":
        await send_feedback(interaction, t("player.already_registered", lang), ephemeral=True)
        return False
    if status == "invalid_type":
        await send_feedback(interaction, t("player.invalid_type", lang), ephemeral=True)
        return False
    if status == "registered":
        await send_feedback(interaction,
            t("player.registered", lang, squad=squad_name, type=type_label, role_suffix=role_suffix), ephemeral=True)
        await send_to_log_channel(
            t("log.player_registered", lang, user=user.name, type=type_label, squad=squad_name, role_suffix=role_suffix),
            guild=interaction.guild)
    else:  # waitlisted
        await send_feedback(interaction,
            t("player.waitlisted", lang, type=type_label), ephemeral=True)
        await send_to_log_channel(
            t("log.player_waitlisted", lang, user=user.name, type=type_label),
            guild=interaction.guild)

    await update_event_displays(guild_id, channel_id)
    return True


async def player_register_tentative(interaction, guild_id, channel_id, squad_type, roles=None):
    """Sign a player up tentatively ("Vorläufig"). No real seat is consumed and
    seat-limit checks are skipped; exactly one tentative entry per user."""
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)
    user = interaction.user
    user_id = str(user.id)
    display_name = user.display_name

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False
        if not is_player_mode(event):
            await send_feedback(interaction, t("player.not_player_mode", lang), ephemeral=True)
            return False
        if _add_tentative(event, user_id, display_name, squad_type, roles) != "tentative":
            await send_feedback(interaction, t("player.invalid_type", lang), ephemeral=True)
            return False
        save_event(db_id, event, user_assignments)

    type_label = t(f"embed.type_{squad_type}", lang) if squad_type in SQUAD_TYPES else squad_type
    role_labels = [role_label(r, lang) for r in (roles or [])]
    role_suffix = (", " + ", ".join(role_labels)) if role_labels else ""
    await send_feedback(interaction,
        t("player.tentative_registered", lang, type=type_label, role_suffix=role_suffix), ephemeral=True)
    await send_to_log_channel(
        t("log.player_tentative", lang, user=user.name, type=type_label, role_suffix=role_suffix),
        guild=interaction.guild)
    await update_event_displays(guild_id, channel_id)
    return True


async def player_decline(interaction, guild_id, channel_id):
    """Toggle the caller's "declined" (not attending) mark — the Unregister
    button's second action, reached when the user holds no seat/waitlist/tentative
    spot. First click marks them declined, a second click clears it. Non-destructive,
    so no confirmation dialog."""
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)
    user = interaction.user
    user_id = str(user.id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False
        if not is_player_mode(event):
            await send_feedback(interaction, t("player.not_player_mode", lang), ephemeral=True)
            return False

        if _player_declined_entry(event, user_id):
            _remove_declined(event, user_id)
            removed = True
        else:
            # Guard against a TOCTOU: an admin may have seated the user between the
            # button click and now — never leave them seated AND declined.
            if (user_id in (user_assignments or {})
                    or _player_waitlist_type(event, user_id) is not None
                    or _player_tentative_entry(event, user_id)):
                await send_feedback(interaction, t("player.already_registered", lang), ephemeral=True)
                return False
            _add_declined(event, user_id, user.display_name)
            removed = False
        save_event(db_id, event, user_assignments)

    await send_feedback(interaction,
        t("player.declined_removed" if removed else "player.declined_added", lang), ephemeral=True)
    await send_to_log_channel(
        t("log.player_declined_removed" if removed else "log.player_declined", lang, user=user.name),
        guild=interaction.guild)
    await update_event_displays(guild_id, channel_id)
    return True


async def player_switch_to_tentative(interaction, guild_id, channel_id):
    """Move a firmly-registered (or waitlisted) player to tentative: free their
    seat / waitlist spot and re-add them as tentative, carrying over their squad
    type and roles. Promotes any waitlisted player into the freed seat."""
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)
    user = interaction.user
    user_id = str(user.id)
    display_name = user.display_name

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False
        if not is_player_mode(event):
            await send_feedback(interaction, t("player.not_player_mode", lang), ephemeral=True)
            return False

        # Capture type + roles BEFORE removing the seat/waitlist entry.
        squad_type, roles = _player_current_assignment(event, user_assignments, user_id)
        if squad_type is None:
            await send_feedback(interaction, t("player.not_registered", lang), ephemeral=True)
            return False

        _status, _name, promoted = _player_self_unregister(event, user_assignments, user_id)
        _add_tentative(event, user_id, display_name, squad_type, roles)
        save_event(db_id, event, user_assignments)

    type_label = t(f"embed.type_{squad_type}", lang) if squad_type in SQUAD_TYPES else squad_type
    role_labels = [role_label(r, lang) for r in (roles or [])]
    role_suffix = (", " + ", ".join(role_labels)) if role_labels else ""
    await send_feedback(interaction,
        t("player.tentative_switched", lang, type=type_label, role_suffix=role_suffix), ephemeral=True)
    await send_to_log_channel(
        t("log.player_tentative", lang, user=user.name, type=type_label, role_suffix=role_suffix),
        guild=interaction.guild)
    await _notify_promoted_players(interaction.guild, guild_id, channel_id, lang, promoted, event)
    await update_event_displays(guild_id, channel_id)
    return True


async def player_unregister(interaction, guild_id, channel_id, target_user=None):
    """Unregister a single player (player mode) — from their squad, their
    waitlist spot, or their tentative sign-up."""
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)
    user = target_user or interaction.user
    user_id = str(user.id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False

        if not is_player_mode(event):
            await send_feedback(interaction, t("player.not_player_mode", lang), ephemeral=True)
            return False

        status, name_or_type, promoted = _player_self_unregister(event, user_assignments, user_id)
        save_event(db_id, event, user_assignments)

    if status is None:
        await send_feedback(interaction, t("player.not_registered", lang), ephemeral=True)
        return False

    if status == "waitlist":
        type_label = t(f"embed.type_{name_or_type}", lang) if name_or_type in SQUAD_TYPES else name_or_type
        await send_feedback(interaction, t("player.waitlist_unregistered", lang, type=type_label), ephemeral=True)
        await send_to_log_channel(
            t("log.player_waitlist_removed", lang, user=user.name, type=type_label),
            guild=interaction.guild)
        await update_event_displays(guild_id, channel_id)
        return True

    if status == "tentative":
        await send_feedback(interaction, t("player.tentative_removed", lang), ephemeral=True)
        await send_to_log_channel(
            t("log.player_tentative_removed", lang, user=user.name),
            guild=interaction.guild)
        await update_event_displays(guild_id, channel_id)
        return True

    squad_name = name_or_type
    await send_feedback(interaction, t("player.unregistered", lang, squad=squad_name or "?"), ephemeral=True)
    await send_to_log_channel(
        t("log.player_unregistered", lang, user=user.name, squad=squad_name or "?"),
        guild=interaction.guild)
    await _notify_promoted_players(interaction.guild, guild_id, channel_id, lang, promoted, event)
    await update_event_displays(guild_id, channel_id)
    return True


async def _notify_promoted_players(guild, guild_id, channel_id, lang, promoted, event):
    """DM each promoted player and write a log-channel line per promotion.

    Mirrors rep-mode waitlist-promotion notifications.
    """
    if not promoted:
        return
    link = _build_event_message_link(event, channel_id, guild_id)
    for uid, name, squad_name in promoted:
        dm_msg = t("player.moved_from_waitlist", lang, squad=squad_name)
        if link:
            dm_msg += f"\n[→ Event]({link})"
        try:
            target = await bot.fetch_user(int(uid))
            if target is not None:
                await target.send(dm_msg)
        except Exception as e:
            logger.warning(f"Could not DM promoted player {uid}: {e}")
        await send_to_log_channel(
            t("log.player_moved", lang, name=name, squad=squad_name),
            guild=guild)


# ---------------------------------------------------------------------------
# Core: squad unregistration
# ---------------------------------------------------------------------------
async def unregister_squad(interaction, guild_id, channel_id, squad_id, is_admin=False):
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return None

        freed_slots = 0
        display_name = _resolve_squad_name(event, squad_id)

        found_in_event = squad_id in event.get("squads", {})

        found_in_waitlist = None  # (wl_key, index) or None
        if not found_in_event:
            for st in SQUAD_TYPES:
                wl_key = _waitlist_key(st)
                for i, entry in enumerate(event.get(wl_key, [])):
                    if len(entry) > 4 and entry[4] == squad_id:
                        found_in_waitlist = (wl_key, i)
                        break
                if found_in_waitlist:
                    break

        if not found_in_event and found_in_waitlist is None:
            await send_feedback(interaction, t("squad.not_found", lang, name=display_name), ephemeral=True)
            return None

        freed_type = None
        if found_in_event:
            squad_data = event["squads"].pop(squad_id)
            freed_slots = squad_data.get("size", 0)
            freed_type = squad_data.get("type")
            event["player_slots_used"] = max(0, event["player_slots_used"] - freed_slots)

        elif found_in_waitlist is not None:
            wl_key, wl_idx = found_in_waitlist
            event[wl_key].pop(wl_idx)

        for uid in list(user_assignments.keys()):
            assignments = get_user_assignments(user_assignments, uid)
            if squad_id in assignments:
                remove_user_assignment(user_assignments, uid, squad_id)

        save_event(db_id, event, user_assignments)

        if freed_slots > 0:
            await _process_squad_waitlist(event, user_assignments, db_id, guild_id, channel_id, freed_slots, freed_type=freed_type)

    await send_feedback(interaction, t("squad.unregistered", lang, name=display_name), ephemeral=True)
    await send_to_log_channel(
        t("log.squad_unregistered", lang, user=interaction.user.name, squad=display_name, freed=freed_slots),
        guild=interaction.guild)
    await update_event_displays(guild_id, channel_id)
    return freed_slots


async def _process_squad_waitlist(event, user_assignments, db_id, guild_id, channel_id, free_slots, freed_type=None):
    """Move waiting squads into event if they fit."""
    if free_slots <= 0 or not _any_squad_waitlist(event):
        return

    # Prioritize the freed type's waitlist
    ordered_types = list(SQUAD_TYPES)
    if freed_type and freed_type in ordered_types:
        ordered_types.remove(freed_type)
        ordered_types.insert(0, freed_type)

    moved = []
    remaining = free_slots

    for st in ordered_types:
        wl_key = _waitlist_key(st)
        wl = event.get(wl_key, [])
        to_remove = []
        for i, entry in enumerate(wl):
            if remaining <= 0:
                break
            squad_name, squad_type, playstyle, size, squad_id, *_rest = entry
            rep_name = _rest[0] if _rest else None
            type_full = (_is_squad_type_full(event, squad_type)
                         or _squad_slot_reserved(event, squad_type, size))
            if size <= remaining and not type_full:
                squad_data = {"name": squad_name, "type": squad_type, "playstyle": playstyle, "size": size}
                if rep_name:
                    squad_data["rep_name"] = rep_name
                event["squads"][squad_id] = squad_data
                event["player_slots_used"] += size
                remaining -= size
                to_remove.append(i)
                moved.append((squad_name, squad_id, size))
        for i in sorted(to_remove, reverse=True):
            event[wl_key].pop(i)

    if moved:
        save_event(db_id, event, user_assignments)
        lang = get_guild_language(guild_id)
        for squad_name, squad_id, size in moved:
            link = _build_event_message_link(event, channel_id, guild_id)
            dm_msg = t("squad.moved_from_waitlist", lang, name=squad_name)
            if link:
                dm_msg += f"\n[→ Event]({link})"
            await _send_squad_dm(user_assignments, squad_id, dm_msg)
            await send_to_log_channel(
                t("log.squad_moved", lang, squad=squad_name, size=size),
                guild_id=guild_id)


async def _send_squad_dm(user_assignments, squad_id, message):
    leader_id = None
    for uid in user_assignments:
        if squad_id in get_user_assignments(user_assignments, uid):
            leader_id = uid
            break
    if leader_id:
        try:
            user = await bot.fetch_user(int(leader_id))
            if user:
                await user.send(message)
        except Exception as e:
            logger.warning(f"Could not DM user {leader_id}: {e}")


# ---------------------------------------------------------------------------
# Core: caster registration
# ---------------------------------------------------------------------------
async def register_caster(interaction, guild_id, channel_id):
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False

        is_open, msg_key = check_registration_open(event, user=interaction.user, registration_type="caster")
        if not is_open:
            await send_feedback(interaction, _resolve_reg_message(msg_key, lang), ephemeral=True)
            return False

        allowed, gate_key = check_role_gate(event, interaction.user, "caster")
        if not allowed:
            await send_feedback(interaction, t(gate_key, lang), ephemeral=True)
            return False

        user_id = str(interaction.user.id)
        if user_has_caster(user_assignments, user_id):
            await send_feedback(interaction, t("caster.already_registered", lang), ephemeral=True)
            return False

        display_name = interaction.user.display_name

        if event["caster_slots_used"] < event["max_caster_slots"]:
            event["casters"][user_id] = {"name": display_name, "id": user_id}
            event["caster_slots_used"] += 1
            add_user_assignment(user_assignments, user_id, "__caster__")
            save_event(db_id, event, user_assignments)
            result = "registered"
        else:
            event["caster_waitlist"].append((user_id, display_name))
            add_user_assignment(user_assignments, user_id, "__caster__")
            save_event(db_id, event, user_assignments)
            result = "waitlisted"
            wl_pos = len(event["caster_waitlist"])

    if result == "registered":
        await send_feedback(interaction, t("caster.registered", lang), ephemeral=True)
        await send_to_log_channel(t("log.caster_registered", lang, user=interaction.user.name, uid=user_id), guild=interaction.guild)
    else:
        await send_feedback(interaction, t("caster.waitlisted", lang, pos=wl_pos), ephemeral=True)

    await update_event_displays(guild_id, channel_id)
    return True


async def unregister_caster(interaction, guild_id, channel_id):
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return False

        user_id = str(interaction.user.id)

        if user_id in event["casters"]:
            del event["casters"][user_id]
            event["caster_slots_used"] = max(0, event["caster_slots_used"] - 1)
            remove_user_assignment(user_assignments, user_id, "__caster__")
            save_event(db_id, event, user_assignments)
            await _process_caster_waitlist(event, user_assignments, db_id, guild_id, channel_id)
        elif any(uid == user_id for uid, _ in event["caster_waitlist"]):
            event["caster_waitlist"] = [(uid, name) for uid, name in event["caster_waitlist"] if uid != user_id]
            remove_user_assignment(user_assignments, user_id, "__caster__")
            save_event(db_id, event, user_assignments)
        else:
            await send_feedback(interaction, t("caster.not_registered", lang), ephemeral=True)
            return False

    await send_feedback(interaction, t("caster.unregistered", lang), ephemeral=True)
    await send_to_log_channel(t("log.caster_unregistered", lang, user=interaction.user.name, uid=user_id), guild=interaction.guild)
    await update_event_displays(guild_id, channel_id)
    return True


async def _process_caster_waitlist(event, user_assignments, db_id, guild_id, channel_id):
    lang = get_guild_language(guild_id)
    while event["caster_slots_used"] < event["max_caster_slots"] and event["caster_waitlist"]:
        user_id, display_name = event["caster_waitlist"].pop(0)
        event["casters"][user_id] = {"name": display_name, "id": user_id}
        event["caster_slots_used"] += 1
        save_event(db_id, event, user_assignments)

        try:
            user = await bot.fetch_user(int(user_id))
            if user:
                dm_msg = t("caster.moved_from_waitlist", lang)
                link = _build_event_message_link(event, channel_id, guild_id)
                if link:
                    dm_msg += f"\n[→ Event]({link})"
                await user.send(dm_msg)
        except Exception as e:
            logger.error(f"Could not DM caster {user_id}: {e}")

        await send_to_log_channel(t("log.caster_moved", lang, name=display_name, uid=user_id), guild_id=guild_id)


# ############################# #
# UI COMPONENTS                 #
# ############################# #

class BaseView(ui.View):
    def __init__(self, timeout=900, title="Interaction"):
        super().__init__(timeout=timeout)
        self.has_responded = False
        self.message = None
        self.timeout_title = title

    async def on_timeout(self):
        try:
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass
        except Exception:
            pass

    def check_response(self, interaction, store_msg=True):
        if store_msg and interaction.message:
            self.message = interaction.message
        if self.has_responded:
            return True
        self.has_responded = True
        return False


class BaseConfirmationView(BaseView):
    def __init__(self, timeout=3600, title="Confirmation"):
        super().__init__(timeout=timeout, title=title)

    def _edit_in_place(self, interaction):
        """Call at the top of a _confirm callback: make the result text REPLACE this dialog message
        (send_feedback honours interaction.extras["edit_feedback"]) instead of appending a new
        ephemeral, and stop() the view so on_timeout can't re-attach the buttons onto the result."""
        try:
            interaction.extras["edit_feedback"] = True
        except Exception:
            pass
        self.stop()


class EventActionView(ui.View):
    """Persistent view with event action buttons."""
    def __init__(self, lang="de", mode: str = "rep", is_closed: bool = False, event_started: bool = False):
        super().__init__(timeout=None)

        reg_disabled = is_closed or event_started
        if mode == "player":
            self.add_item(ui.Button(
                label=t("button.join", lang), style=discord.ButtonStyle.success,
                custom_id="event_register_squad", emoji="🪖",
                disabled=reg_disabled,
            ))
            self.add_item(ui.Button(
                label=t("button.tentative", lang), style=discord.ButtonStyle.primary,
                custom_id="event_tentative", emoji="🤔",
                disabled=reg_disabled,
            ))
        else:
            self.add_item(ui.Button(
                label=t("button.register_squad", lang), style=discord.ButtonStyle.success,
                custom_id="event_register_squad", emoji="🪖",
                disabled=reg_disabled,
            ))
            self.add_item(ui.Button(
                label=t("button.register_caster", lang), style=discord.ButtonStyle.primary,
                custom_id="event_register_caster", emoji="🎙️",
                disabled=reg_disabled,
            ))
        # Unregister stays enabled when merely closed, so members who registered while open can
        # always withdraw — but it's disabled once the event itself has started.
        self.add_item(ui.Button(
            label=t("button.unregister", lang), style=discord.ButtonStyle.danger,
            custom_id="event_unregister", emoji="❌",
            disabled=event_started,
        ))
        self.add_item(ui.Button(
            label=t("button.ics", lang), style=discord.ButtonStyle.secondary,
            custom_id="event_ics", emoji="📅",
        ))
        self.add_item(ui.Button(
            label=t("button.admin", lang), style=discord.ButtonStyle.secondary,
            custom_id="event_admin", emoji="⚙️",
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id == "event_register_squad":
            await self._register_squad(interaction)
        elif custom_id == "event_tentative":
            await self._register_tentative(interaction)
        elif custom_id == "event_register_caster":
            await self._register_caster(interaction)
        elif custom_id == "event_unregister":
            await self._unregister(interaction)
        elif custom_id == "event_admin":
            await self._admin(interaction)
        elif custom_id == "event_ics":
            await self._ics(interaction)
        return False

    async def _register_squad(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        event, user_assignments, _ = _get_channel_event(gid, cid)
        lang = _lang(interaction)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return

        is_open, msg_key = check_registration_open(event, user=interaction.user, registration_type="squad")
        if not is_open:
            await interaction.response.send_message(_resolve_reg_message(msg_key, lang), ephemeral=True)
            return

        allowed, gate_key = check_role_gate(event, interaction.user, "squad")
        if not allowed:
            await interaction.response.send_message(t(gate_key, lang), ephemeral=True)
            return

        if is_player_mode(event):
            await _dispatch_player_register(interaction, gid, cid, lang)
            return

        user_id = str(interaction.user.id)
        if not _exempt_from_user_squad_limit(event, interaction.user):
            max_squads = event.get("max_squads_per_user", 1)
            current = get_user_squad_ids(user_assignments, user_id)
            if len(current) >= max_squads:
                if max_squads == 1 and current:
                    await interaction.response.send_message(t("squad.already_assigned", lang, name=_resolve_squad_name(event, current[0])), ephemeral=True)
                else:
                    await interaction.response.send_message(t("squad.max_reached", lang, current=len(current), max=max_squads), ephemeral=True)
                return

        # Count-based caps (early-access per-role squad cap) are size-independent, so
        # reject right here on button press. The seat-% cap needs the squad size and
        # is checked once the type is picked (SquadRegistrationView); the precise full
        # check still runs in register_squad (race safety).
        ok_lim, lim_key, lim_usage = _check_squad_count_cap(
            event, user_assignments, interaction.guild, interaction.user, "rep")
        if not ok_lim:
            await interaction.response.send_message(t(lim_key, lang, usage=lim_usage), ephemeral=True)
            return

        settings = get_guild_settings(gid) or DEFAULT_GUILD_SETTINGS
        view = SquadRegistrationView(gid, cid, event)
        desc_key = "squad.step_1_desc" if event.get("playstyle_enabled", True) else "squad.step_1_desc_no_playstyle"
        await interaction.response.send_message(
            f"**{t('squad.step_1_title', lang)}**\n{t(desc_key, lang)}",
            view=view, ephemeral=True)

    async def _register_tentative(self, interaction: discord.Interaction):
        """Player mode: sign up as tentative ("maybe"). Mirrors the squad-button
        guards (registration open + role gate), but skips the seat-limit check
        since a tentative player occupies no real seat."""
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        event, _, _ = _get_channel_event(gid, cid)
        lang = _lang(interaction)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        if not is_player_mode(event):
            await interaction.response.send_message(t("player.not_player_mode", lang), ephemeral=True)
            return

        is_open, msg_key = check_registration_open(event, user=interaction.user, registration_type="squad")
        if not is_open:
            await interaction.response.send_message(_resolve_reg_message(msg_key, lang), ephemeral=True)
            return

        allowed, gate_key = check_role_gate(event, interaction.user, "squad")
        if not allowed:
            await interaction.response.send_message(t(gate_key, lang), ephemeral=True)
            return

        await _dispatch_player_tentative(interaction, gid, cid, lang)

    async def _register_caster(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        settings = get_guild_settings(gid) or DEFAULT_GUILD_SETTINGS
        lang = settings.get("language", "de")

        event, user_assignments, _ = _get_channel_event(gid, cid)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return

        if is_player_mode(event):
            await interaction.response.send_message(t("caster.disabled", lang), ephemeral=True)
            return

        if not settings.get("caster_registration_enabled", True) or event.get("max_caster_slots", 2) == 0:
            await interaction.response.send_message(t("caster.disabled", lang), ephemeral=True)
            return

        if user_has_caster(user_assignments, str(interaction.user.id)):
            await interaction.response.send_message(t("caster.already_registered", lang), ephemeral=True)
            return

        is_open, msg_key = check_registration_open(event, user=interaction.user, registration_type="caster")
        if not is_open:
            await interaction.response.send_message(_resolve_reg_message(msg_key, lang), ephemeral=True)
            return

        allowed, gate_key = check_role_gate(event, interaction.user, "caster")
        if not allowed:
            await interaction.response.send_message(t(gate_key, lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await register_caster(interaction, gid, cid)

    async def _unregister(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        lang = _lang(interaction)
        event, user_assignments, _ = _get_channel_event(gid, cid)
        if is_player_mode(event):
            await _dispatch_player_unregister(interaction, gid, cid, lang, user_assignments or {})
            return

        user_id = str(interaction.user.id)
        assignments = get_user_assignments(user_assignments or {}, user_id)

        if not assignments:
            await interaction.response.send_message(t("info.not_registered", lang), ephemeral=True)
            return

        if "__caster__" in assignments:
            embed = discord.Embed(
                title=t("caster.unregister_title", lang),
                description=t("caster.unregister_confirm", lang),
                color=discord.Color.red())
            view = CasterUnregisterConfirmView(gid, cid)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        elif len(assignments) == 1:
            embed, view = _build_squad_unregister_confirm(event, gid, cid, assignments[0], lang)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            options = []
            for sn in assignments:
                if sn == "__caster__":
                    continue
                if event:
                    name, stype, size = _resolve_squad_meta(event, sn)
                else:
                    name, stype, size = sn, None, None
                # Secondary line in the dropdown, e.g. "⚔️ Infantry (6 players)".
                desc = t(f"squad.type_{stype}", lang, size=size) if stype in SQUAD_TYPES else None
                options.append(discord.SelectOption(label=name, description=desc, value=sn))
            view = UserSquadUnregisterSelector(gid, cid, options)
            await interaction.response.send_message(t("squad.pick_to_unregister", lang), view=view, ephemeral=True)

    async def _admin(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        settings = get_guild_settings(gid)
        lang = _lang(interaction)
        if not settings or not has_organizer_role(interaction.user, settings["organizer_role_id"]):
            await interaction.followup.send(t("general.requires_organizer", lang), ephemeral=True)
            return

        event, _, _ = _get_channel_event(gid, interaction.channel_id)
        if not event:
            await interaction.followup.send(t("general.no_active_event", lang), ephemeral=True)
            return

        embed = discord.Embed(title=t("admin.title", lang), color=discord.Color.dark_red())
        view = AdminActionView(gid, interaction.channel_id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _ics(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        lang = _lang(interaction)
        event, _, _ = _get_channel_event(gid, cid)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        msg_id = event.get("event_message_id")
        jump_url = f"https://discord.com/channels/{gid}/{cid}/{msg_id}" if msg_id else None
        try:
            ics_bytes = build_event_ics(event, gid, cid, jump_url)
        except ValueError:
            await interaction.response.send_message(t("ics.error.invalid_datetime", lang), ephemeral=True)
            return
        filename_stem = _ics_slug(event.get("name", "")) or "event"
        date_str = event.get("date", "").replace(".", "-") or "event"
        filename = f"{filename_stem}_{date_str}.ics"
        file = discord.File(fp=io.BytesIO(ics_bytes), filename=filename)
        await interaction.response.send_message(
            t("ics.delivered", lang, name=event.get("name", "")),
            file=file, ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Squad registration flow views
# ---------------------------------------------------------------------------

class PlayerTypePickerView(BaseView):
    """Player mode: type picker + optional multi-select role dropdown, then a
    Continue button that submits the registration.

    `tentative=True` submits a tentative ("Vorläufig") sign-up instead of a firm
    one. `initial_type`/`initial_roles` pre-fill the picker — used to carry over
    an existing tentative selection when switching tentative ↔ firm.
    """
    def __init__(self, guild_id, channel_id, *, tentative: bool = False,
                 initial_type=None, initial_roles=None):
        super().__init__(timeout=300, title="Player Registration")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.tentative = tentative
        self.selected_type = initial_type
        lang = get_guild_language(guild_id)
        event, _, _ = _get_channel_event(guild_id, channel_id)
        # In-squad roles are opt-out per event; when disabled there's no role
        # dropdown and registrations carry no roles.
        self.roles_enabled = bool(event.get("player_roles_enabled", True)) if event else True
        self.selected_roles: list = list(initial_roles or []) if self.roles_enabled else []

        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=_squad_type_options(event, lang),
            custom_id="player_type_select", row=0)
        self.type_select.callback = self._on_type
        self.add_item(self.type_select)

        self.role_select = None
        if self.roles_enabled:
            self.role_select = ui.Select(
                placeholder=t("player.role_select_placeholder", lang),
                options=[discord.SelectOption(label="—", value="__placeholder__")],
                custom_id="player_role_select",
                min_values=0, max_values=1,
                disabled=True, row=1)
            self.role_select.callback = self._on_role
            self.add_item(self.role_select)

        self.continue_button = ui.Button(
            label=t("squad.continue", lang),
            style=discord.ButtonStyle.success,
            disabled=True, row=2)
        self.continue_button.callback = self._on_continue
        self.add_item(self.continue_button)

        if self.selected_type:
            self._apply_type(lang)

    def _apply_type(self, lang):
        """Reflect `self.selected_type`/`self.selected_roles` onto the selects:
        mark the chosen type, populate role options (pre-selecting chosen roles)
        when roles are enabled, and enable the Continue button."""
        for opt in self.type_select.options:
            opt.default = (opt.value == self.selected_type)
        if self.roles_enabled and self.role_select is not None:
            role_opts = [discord.SelectOption(label=role_label(r, lang), value=r,
                                              default=(r in self.selected_roles))
                         for r in ROLES_BY_TYPE.get(self.selected_type, [])]
            self.role_select.options = role_opts or [discord.SelectOption(label="—", value="__placeholder__")]
            self.role_select.disabled = not role_opts
            self.role_select.min_values = 0
            self.role_select.max_values = max(1, len(role_opts))
            self.role_select.placeholder = t("player.role_select_placeholder", lang)
        self.continue_button.disabled = False

    async def _on_type(self, interaction: discord.Interaction):
        self.selected_type = self.type_select.values[0]
        self.selected_roles = []
        self._apply_type(get_guild_language(self.guild_id))
        await interaction.response.edit_message(view=self)

    async def _on_role(self, interaction: discord.Interaction):
        self.selected_roles = [v for v in self.role_select.values if v != "__placeholder__"]
        for opt in self.role_select.options:
            opt.default = (opt.value in self.selected_roles)
        await interaction.response.edit_message(view=self)

    async def _on_continue(self, interaction: discord.Interaction):
        if not self.selected_type:
            return
        if self.tentative:
            await player_register_tentative(interaction, self.guild_id, self.channel_id,
                                            self.selected_type, roles=self.selected_roles)
        else:
            await player_register(interaction, self.guild_id, self.channel_id,
                                  self.selected_type, roles=self.selected_roles)


class SquadRegistrationView(BaseView):
    def __init__(self, guild_id, channel_id, event):
        super().__init__(timeout=300, title="Squad Registration")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_type = None
        self.playstyle_enabled = bool(event.get("playstyle_enabled", True))
        self.selected_playstyle = None if self.playstyle_enabled else "Normal"
        self.event = event
        self._type_fits = True  # set False if the picked type exceeds the early-access seat-% cap

        sizes = _get_squad_sizes(event)
        lang = get_guild_language(guild_id)

        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=_squad_type_options(event, lang),
            custom_id="squad_type_select", row=0)
        self.type_select.callback = lambda i: self._on_select(i, self.type_select, 'selected_type')
        self.add_item(self.type_select)

        if self.playstyle_enabled:
            self.playstyle_select = ui.Select(
                placeholder=t("squad.playstyle_select", lang),
                options=[
                    discord.SelectOption(label="Casual", value="Casual"),
                    discord.SelectOption(label="Normal", value="Normal"),
                    discord.SelectOption(label="Focused", value="Focused"),
                ],
                custom_id="squad_playstyle_select", row=1)
            self.playstyle_select.callback = lambda i: self._on_select(i, self.playstyle_select, 'selected_playstyle')
            self.add_item(self.playstyle_select)
        else:
            self.playstyle_select = None

        self.continue_button = ui.Button(label=t("squad.continue", lang), style=discord.ButtonStyle.success, disabled=True, row=2)
        self.continue_button.callback = self._continue
        self.add_item(self.continue_button)

    def _ready(self):
        if self.playstyle_enabled:
            return bool(self.selected_type and self.selected_playstyle)
        return bool(self.selected_type)

    def _build_status_content(self):
        lang = get_guild_language(self.guild_id)
        sizes = _get_squad_sizes(self.event)
        desc_key = "squad.step_1_desc" if self.playstyle_enabled else "squad.step_1_desc_no_playstyle"
        lines = [f"**{t('squad.step_1_title', lang)}**", t(desc_key, lang)]
        if self.selected_type:
            stype, req_size = _parse_squad_type_value(self.selected_type)
            type_label = t(f"squad.type_{stype}", lang, size=req_size or sizes.get(stype, "?"))
            lines.append(t("squad.selected_type", lang, label=type_label))
        if self.playstyle_enabled and self.selected_playstyle:
            lines.append(t("squad.selected_playstyle", lang, label=self.selected_playstyle))
        return "\n".join(lines)

    async def _on_select(self, interaction, select, attr):
        setattr(self, attr, select.values[0])
        for opt in select.options:
            opt.default = opt.value == select.values[0]

        content = self._build_status_content()
        # The early-access seat-% cap depends on the squad size, so check it the
        # moment the type is selected. If this type won't fit, warn and keep
        # Continue disabled so the user can pick a smaller type.
        if attr == "selected_type":
            lang = get_guild_language(self.guild_id)
            event, user_assignments, _ = _get_channel_event(self.guild_id, self.channel_id)
            self._type_fits = True
            if event:
                stype, req_size = _parse_squad_type_value(self.selected_type)
                size = req_size or _get_squad_sizes(event).get(stype, 1)
                ok, key, usage = _check_seat_cap(event, user_assignments, interaction.guild,
                                                 interaction.user, size)
                if not ok:
                    self._type_fits = False
                    content += f"\n⚠️ {t(key, lang, usage=usage)}"

        self.continue_button.disabled = not (self._ready() and self._type_fits)
        await interaction.response.edit_message(content=content, view=self)

    async def _continue(self, interaction):
        if not self._ready():
            return
        stype, req_size = _parse_squad_type_value(self.selected_type)
        modal = SquadNameModal(self.guild_id, self.channel_id, stype, self.selected_playstyle,
                               requested_size=req_size)
        await interaction.response.send_modal(modal)


class SquadNameModal(ui.Modal):
    def __init__(self, guild_id, channel_id, squad_type, playstyle, requested_size=None):
        lang = get_guild_language(guild_id)
        super().__init__(title=t("squad.register_title", lang))
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_type = squad_type
        self.playstyle = playstyle
        self.requested_size = requested_size

        self.squad_name = ui.TextInput(
            label=t("squad.name_label", lang),
            placeholder=t("squad.name_placeholder", lang),
            required=True, min_length=2, max_length=30)
        self.add_item(self.squad_name)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await register_squad(interaction, self.guild_id, self.channel_id,
                             self.squad_name.value.strip(), self.squad_type, self.playstyle,
                             requested_size=self.requested_size)


# ---------------------------------------------------------------------------
# Unregister confirm views
# ---------------------------------------------------------------------------

class SquadUnregisterConfirmView(BaseConfirmationView):
    def __init__(self, guild_id, channel_id, squad_name):
        super().__init__(title="Unregister")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_name = squad_name

        lang = get_guild_language(guild_id)
        confirm_btn = ui.Button(label=t("squad.unregister_button", lang), style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        await unregister_squad(interaction, self.guild_id, self.channel_id, self.squad_name)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


def _build_squad_unregister_confirm(event, guild_id, channel_id, squad_id, lang):
    """Build the red 'are you sure?' embed and Confirm/Cancel view shown before a
    squad is unregistered. Shared by the single-squad path and the multi-squad
    dropdown so both ask for confirmation identically."""
    display_name = _resolve_squad_name(event, squad_id) if event else squad_id
    embed = discord.Embed(
        title=t("squad.unregister_title", lang),
        description=t("squad.unregister_confirm", lang, name=display_name),
        color=discord.Color.red())
    return embed, SquadUnregisterConfirmView(guild_id, channel_id, squad_id)


class PlayerUnregisterConfirmView(BaseConfirmationView):
    """Confirmation dialog for a user unregistering themselves in player mode."""
    def __init__(self, guild_id, channel_id, squad_name):
        super().__init__(title="Unregister Player")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_name = squad_name
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("squad.unregister_button", lang), style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        await player_unregister(interaction, self.guild_id, self.channel_id)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


class PlayerTentativeSwitchConfirmView(BaseConfirmationView):
    """Confirm switching a firm / waitlisted player to tentative — their seat or
    waitlist spot is freed; squad type and role are carried over."""
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Switch to tentative")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("general.confirm", lang), style=discord.ButtonStyle.primary)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        await player_switch_to_tentative(interaction, self.guild_id, self.channel_id)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), embed=None, view=None)


def _tentative_gather(guild_id, channel_id):
    """Return (event, lang, [tentative entries]) or (None, lang, []) if gone."""
    lang = get_guild_language(guild_id)
    event, _, _ = _get_channel_event(guild_id, channel_id)
    if not event:
        return None, lang, []
    return event, lang, list(event.get("tentative", []))


async def _tentative_notify_thread(interaction, guild_id, channel_id, private: bool,
                                   recipient_ids=None):
    """Create a thread and ping the chosen tentative players in it.

    `recipient_ids is None` notifies everyone; otherwise only those user ids.
    Public threads are attached directly to the event message; private threads
    are created on the channel and the organizer who triggered this is added.
    Mentioned tentative players are pulled into the thread by the mention.
    """
    event, lang, entries = _tentative_gather(guild_id, channel_id)
    if not event:
        await interaction.followup.send(t("general.no_active_event", lang), ephemeral=True)
        return
    entries = _select_tentative(entries, recipient_ids)
    if not entries:
        await interaction.followup.send(t("tentative.none", lang), ephemeral=True)
        return
    link = _build_event_message_link(event, channel_id, guild_id) or ""
    mentions = " ".join(f"<@{e.get('user_id')}>" for e in entries if e.get("user_id"))
    text = t("tentative.thread_text", lang, mentions=mentions, name=event.get("name", ""), url=link)
    thread_name = t("tentative.thread_name", lang, name=event.get("name", ""))[:100]
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if private:
            thread = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.private_thread)
            # Add the organizer who triggered the notification to the private thread.
            try:
                await thread.add_user(interaction.user)
            except Exception as e:
                logger.info(f"Could not add organizer to private tentative thread: {e}")
        else:
            # Public thread attached to the event message when it still exists.
            msg_id = event.get("event_message_id")
            msg = None
            if msg_id:
                try:
                    msg = await channel.fetch_message(int(msg_id))
                except Exception:
                    msg = None
            if msg is not None:
                thread = await msg.create_thread(name=thread_name)
            else:
                thread = await channel.create_thread(
                    name=thread_name, type=discord.ChannelType.public_thread)
        await thread.send(text, allowed_mentions=discord.AllowedMentions(users=True))
    except Exception as e:
        logger.warning(f"Tentative thread notify failed: {e}")
        await interaction.followup.send(t("tentative.notify_error", lang, error=str(e)), ephemeral=True)
        return
    await interaction.followup.send(
        t("tentative.notify_thread_done", lang, count=len(entries), thread=thread.mention),
        ephemeral=True)
    await send_to_log_channel(
        t("log.tentative_notified_thread", lang, count=len(entries), name=event.get("name", "")),
        guild=interaction.guild)


async def _tentative_notify_dm(interaction, guild_id, channel_id, recipient_ids=None):
    """DM the chosen tentative players, asking them to confirm via the event
    buttons. `recipient_ids is None` DMs everyone; otherwise only those ids."""
    event, lang, entries = _tentative_gather(guild_id, channel_id)
    if not event:
        await interaction.followup.send(t("general.no_active_event", lang), ephemeral=True)
        return
    entries = _select_tentative(entries, recipient_ids)
    if not entries:
        await interaction.followup.send(t("tentative.none", lang), ephemeral=True)
        return
    link = _build_event_message_link(event, channel_id, guild_id) or ""
    dm_text = t("tentative.dm_text", lang, name=event.get("name", ""), url=link)
    ok = failed = 0
    for entry in entries:
        uid = entry.get("user_id")
        if not uid:
            continue
        try:
            target = await bot.fetch_user(int(uid))
            await target.send(dm_text)
            ok += 1
        except Exception as e:
            failed += 1
            logger.info(f"Tentative DM to {uid} failed: {e}")
    failed_suffix = t("tentative.notify_dm_failed_suffix", lang, n=failed) if failed else ""
    await interaction.followup.send(
        t("tentative.notify_dm_done", lang, ok=ok, failed_suffix=failed_suffix), ephemeral=True)
    await send_to_log_channel(
        t("log.tentative_notified_dm", lang, ok=ok, failed=failed, name=event.get("name", "")),
        guild=interaction.guild)


class TentativeSelectUsersView(BaseView):
    """First step of the notify flow: pick which tentative players to ask — a
    multi-select of the current tentatives, or an "Ask all" button."""
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=300, title="Select tentatives")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)
        event, _, _ = _get_channel_event(guild_id, channel_id)

        type_abbrev = {"infantry": "Inf", "vehicle": "Veh", "heli": "Heli"}
        options = []
        for e in (event or {}).get("tentative", [])[:25]:
            uid = str(e.get("user_id", ""))
            if not uid:
                continue
            abbr = type_abbrev.get(e.get("type"), "?")
            options.append(discord.SelectOption(
                label=f"[{abbr}] {e.get('name', '?')}"[:100], value=uid))

        # Defensive: the admin entry only opens this view when tentatives exist,
        # but a select needs at least one option to be valid.
        if options:
            self.user_select = ui.Select(
                placeholder=t("tentative.select_users_placeholder", lang),
                options=options, min_values=1, max_values=len(options), row=0)
            self.user_select.callback = self._on_select
            self.add_item(self.user_select)

        all_btn = ui.Button(label=t("tentative.notify_all_button", lang),
                            style=discord.ButtonStyle.primary, row=1)
        all_btn.callback = self._all
        self.add_item(all_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang),
                               style=discord.ButtonStyle.secondary, row=1)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _advance(self, interaction, recipient_ids):
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(
            content=t("tentative.notify_choose", lang),
            view=TentativeNotifyView(self.guild_id, self.channel_id, recipient_ids=recipient_ids))

    async def _on_select(self, interaction):
        await self._advance(interaction, list(self.user_select.values))

    async def _all(self, interaction):
        if self.check_response(interaction):
            return
        await self._advance(interaction, None)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


class TentativeNotifyView(BaseView):
    """Organizer chooser: notify the chosen tentative players via a thread or DM.
    Picking "thread" opens a follow-up asking for a public or private thread.
    `recipient_ids is None` means everyone; otherwise the selected user ids."""
    def __init__(self, guild_id, channel_id, recipient_ids=None):
        super().__init__(timeout=300, title="Notify tentatives")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.recipient_ids = recipient_ids
        lang = get_guild_language(guild_id)

        thread_btn = ui.Button(label=t("tentative.notify_thread_button", lang),
                               style=discord.ButtonStyle.primary)
        thread_btn.callback = self._choose_thread
        self.add_item(thread_btn)
        dm_btn = ui.Button(label=t("tentative.notify_dm_button", lang),
                           style=discord.ButtonStyle.secondary)
        dm_btn.callback = self._notify_dm
        self.add_item(dm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _choose_thread(self, interaction):
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(
            content=t("tentative.thread_type_choose", lang),
            view=TentativeThreadTypeView(self.guild_id, self.channel_id, self.recipient_ids))

    async def _notify_dm(self, interaction):
        if self.check_response(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await _tentative_notify_dm(interaction, self.guild_id, self.channel_id, self.recipient_ids)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


class TentativeThreadTypeView(BaseView):
    """Second step of the thread-notify flow: public or private thread."""
    def __init__(self, guild_id, channel_id, recipient_ids=None):
        super().__init__(timeout=300, title="Thread type")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.recipient_ids = recipient_ids
        lang = get_guild_language(guild_id)

        public_btn = ui.Button(label=t("tentative.notify_thread_public_button", lang),
                               style=discord.ButtonStyle.primary)
        public_btn.callback = self._public
        self.add_item(public_btn)
        private_btn = ui.Button(label=t("tentative.notify_thread_private_button", lang),
                                style=discord.ButtonStyle.secondary)
        private_btn.callback = self._private
        self.add_item(private_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _public(self, interaction):
        if self.check_response(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await _tentative_notify_thread(interaction, self.guild_id, self.channel_id,
                                       private=False, recipient_ids=self.recipient_ids)

    async def _private(self, interaction):
        if self.check_response(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await _tentative_notify_thread(interaction, self.guild_id, self.channel_id,
                                       private=True, recipient_ids=self.recipient_ids)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


class CasterUnregisterConfirmView(BaseConfirmationView):
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Unregister Caster")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("general.confirm", lang), style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        await unregister_caster(interaction, self.guild_id, self.channel_id)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


class UserSquadUnregisterSelector(BaseView):
    def __init__(self, guild_id, channel_id, options):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.channel_id = channel_id
        select = ui.Select(placeholder="...", options=options)
        select.callback = self._selected
        self.add_item(select)

    async def _selected(self, interaction):
        selected = interaction.data["values"][0]
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        embed, view = _build_squad_unregister_confirm(
            event, self.guild_id, self.channel_id, selected, lang)
        # Replace the dropdown in place with the Confirm/Cancel prompt; the actual
        # removal still happens only in SquadUnregisterConfirmView._confirm.
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ---------------------------------------------------------------------------
# Admin action view
# ---------------------------------------------------------------------------

class AdminActionView(BaseView):
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=3600, title="Admin")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        event, _, _ = _get_channel_event(guild_id, channel_id)
        player_mode = is_player_mode(event)

        if player_mode:
            buttons = [
                ("admin.add_player", discord.ButtonStyle.success, "_add_player", 0),
                ("admin.remove_player", discord.ButtonStyle.danger, "_remove_player", 0),
                ("button.notify_tentative", discord.ButtonStyle.primary, "_notify_tentative", 0),
                ("admin.open_registration", discord.ButtonStyle.success, "_open", 1),
                ("admin.close_registration", discord.ButtonStyle.danger, "_close", 1),
                ("admin.consolidate_squads", discord.ButtonStyle.primary, "_consolidate", 1),
                ("admin.edit_event", discord.ButtonStyle.primary, "_edit", 2),
                ("admin.delete_event", discord.ButtonStyle.danger, "_delete", 2),
            ]
        else:
            buttons = [
                ("admin.add_squad", discord.ButtonStyle.success, "_add_squad", 0),
                ("admin.remove_squad", discord.ButtonStyle.danger, "_remove_squad", 0),
                ("admin.add_caster", discord.ButtonStyle.success, "_add_caster", 1),
                ("admin.remove_caster", discord.ButtonStyle.danger, "_remove_caster", 1),
                ("admin.open_registration", discord.ButtonStyle.success, "_open", 2),
                ("admin.close_registration", discord.ButtonStyle.danger, "_close", 2),
                ("admin.edit_event", discord.ButtonStyle.primary, "_edit", 3),
                ("admin.delete_event", discord.ButtonStyle.danger, "_delete", 3),
            ]

        for label_key, style, cb_name, row in buttons:
            btn = ui.Button(label=t(label_key, lang), style=style, row=row)
            btn.callback = getattr(self, cb_name)
            self.add_item(btn)

    async def _edit(self, interaction):
        lang = get_guild_language(self.guild_id)

        event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(
                t("general.no_active_event", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await start_dm_edit_session(interaction, self.guild_id, self.channel_id, db_id, lang)

    async def _delete(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("event.nothing_to_delete", lang), ephemeral=True)
            return

        embed = discord.Embed(
            title=t("event.delete_confirm_title", lang),
            description=t("event.delete_confirm", lang, name=event["name"]),
            color=discord.Color.red())
        view = DeleteConfirmationView(self.guild_id, self.channel_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _open(self, interaction):
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)

        event, _, _ = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return
        if event.get("registration_open", False):
            await send_feedback(interaction, t("reg.already_open", lang), ephemeral=True)
            return

        # Confirm first — opening may send a ping to configured roles.
        embed = _build_open_confirm_embed(event, lang)
        view = OpenConfirmationView(gid, cid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _close(self, interaction):
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)

        event, _, _ = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return

        embed = discord.Embed(
            title=t("reg.close_confirm_title", lang),
            description=t("reg.close_confirm", lang, name=event["name"]),
            color=discord.Color.orange())
        view = CloseConfirmationView(gid, cid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _consolidate(self, interaction):
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)

        event, _, _ = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return
        if not is_player_mode(event):
            await send_feedback(interaction, t("consolidate.player_mode_only", lang), ephemeral=True)
            return

        # Confirm first — consolidation rearranges squads and removes emptied ones.
        embed = discord.Embed(
            title=t("consolidate.confirm_title", lang),
            description=t("consolidate.confirm", lang, name=event["name"]),
            color=discord.Color.blurple())
        view = ConsolidateConfirmationView(gid, cid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _notify_tentative(self, interaction):
        """Ask the tentative players whether they'll join — via a (public/private)
        pinged thread or via DM. Reached from the admin panel, so already
        organizer-gated by the Admin button."""
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)
        event, _, _ = _get_channel_event(gid, cid)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        if not is_player_mode(event):
            await interaction.response.send_message(t("player.not_player_mode", lang), ephemeral=True)
            return
        if not event.get("tentative"):
            await interaction.response.send_message(t("tentative.none", lang), ephemeral=True)
            return
        view = TentativeSelectUsersView(gid, cid)
        await interaction.response.send_message(t("tentative.select_choose", lang), view=view, ephemeral=True)

    async def _add_squad(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        view = _AdminSquadRegView(self.guild_id, self.channel_id, event)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _add_player(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        view = _AdminPlayerAddView(self.guild_id, self.channel_id)
        await interaction.response.send_message(
            t("admin.pick_player_and_type", lang), view=view, ephemeral=True)

    async def _remove_player(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, user_assignments, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        type_abbrev = {"infantry": "Inf", "vehicle": "Veh", "heli": "Heli"}
        opts = []
        # Registered player members across all squads.
        for squad_name, squad in event.get("squads", {}).items():
            for m in squad.get("members", []):
                opts.append(discord.SelectOption(
                    label=f"{m.get('name', '?')} — {squad_name}",
                    value=m.get("user_id", ""),
                ))
        # Waitlist entries per type — prefixed [WL-Inf]/[WL-Veh]/[WL-Heli] like rep mode.
        for st in SQUAD_TYPES:
            abbr = type_abbrev.get(st, "?")
            for entry in event.get(_waitlist_key(st), []):
                if not isinstance(entry, (tuple, list)) or len(entry) < 6:
                    continue
                player_name = entry[5]
                uid = str(entry[4])
                opts.append(discord.SelectOption(
                    label=f"[WL-{abbr}] {player_name}",
                    value=uid,
                ))
        # Tentative ("Vorläufig") entries — prefixed [Vorl-Inf]/[Vorl-Veh]/[Vorl-Heli].
        for entry in event.get("tentative", []):
            abbr = type_abbrev.get(entry.get("type"), "?")
            uid = str(entry.get("user_id", ""))
            if not uid:
                continue
            opts.append(discord.SelectOption(
                label=f"[Vorl-{abbr}] {entry.get('name', '?')}",
                value=uid,
            ))
        if not opts:
            await interaction.response.send_message(t("embed.no_entries", lang), ephemeral=True)
            return
        view = _AdminPlayerRemoveView(self.guild_id, self.channel_id, opts[:25])
        await interaction.response.send_message(
            t("admin.pick_player_to_remove", lang), view=view, ephemeral=True)

    async def _remove_squad(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        squads = event.get("squads", {})
        type_labels = {
            "infantry": t("embed.type_infantry", lang),
            "vehicle": t("embed.type_vehicle", lang),
            "heli": t("embed.type_heli", lang),
        }
        type_abbrev = {"infantry": "Inf", "vehicle": "Veh", "heli": "Heli"}
        select_groups = []  # [(placeholder, [SelectOption, ...])]
        # Registered squads per type
        for st in SQUAD_TYPES:
            opts = [discord.SelectOption(label=data.get("name", sq_id), value=sq_id)
                    for sq_id, data in squads.items() if data.get("type") == st]
            if opts:
                select_groups.append((type_labels[st], opts[:25]))
        # Combined waitlist across all types
        wl_opts = []
        for entry in _all_squad_waitlist_entries(event):
            abbr = type_abbrev.get(entry[1], "?")
            wl_opts.append(discord.SelectOption(label=f"[WL-{abbr}] {entry[0]}", value=entry[4]))
        if wl_opts:
            wl_label = t("embed.waitlist_label", lang, count=len(wl_opts))
            select_groups.append((wl_label, wl_opts[:25]))
        if not select_groups:
            await interaction.response.send_message(t("embed.no_entries", lang), ephemeral=True)
            return
        view = _AdminRemoveSquadView(self.guild_id, self.channel_id, select_groups)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _add_caster(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        if event.get("max_caster_slots", 2) == 0:
            await interaction.response.send_message(t("caster.disabled", lang), ephemeral=True)
            return
        view = _AdminAddCasterView(self.guild_id, self.channel_id)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _remove_caster(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        casters = event.get("casters", {})
        caster_wl = event.get("caster_waitlist", [])
        options = []
        for uid, data in casters.items():
            options.append(discord.SelectOption(label=data.get("name", "?"), value=uid))
        for uid, name in caster_wl:
            options.append(discord.SelectOption(label=f"[WL] {name}", value=uid))
        if not options:
            await interaction.response.send_message(t("embed.no_entries", lang), ephemeral=True)
            return
        view = _AdminRemoveCasterView(self.guild_id, self.channel_id, options)
        await interaction.response.send_message(view=view, ephemeral=True)


# ---------------------------------------------------------------------------
# Admin squad/caster management views
# ---------------------------------------------------------------------------

class _AdminPlayerAddView(BaseView):
    """Admin: pick one or more users + a squad type + optional in-squad roles; adds them in one submit."""
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=300, title="Admin Add Player")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_users: list = []
        self.selected_type = None
        self.selected_roles: list = []
        lang = get_guild_language(guild_id)

        self.user_select = ui.UserSelect(
            placeholder=t("admin.pick_user", lang),
            min_values=1, max_values=25, row=0)
        self.user_select.callback = self._on_user
        self.add_item(self.user_select)

        event, _, _ = _get_channel_event(guild_id, channel_id)
        self.roles_enabled = bool(event.get("player_roles_enabled", True)) if event else True
        sizes = _get_squad_sizes(event) if event else {"infantry": 6, "vehicle": 2, "heli": 1}
        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=_squad_type_options(event, lang),
            row=1)
        self.type_select.callback = self._on_type
        self.add_item(self.type_select)

        self.role_select = None
        if self.roles_enabled:
            self.role_select = ui.Select(
                placeholder=t("player.role_select_placeholder", lang),
                options=[discord.SelectOption(label="—", value="__placeholder__")],
                min_values=0, max_values=1,
                disabled=True, row=2)
            self.role_select.callback = self._on_role
            self.add_item(self.role_select)

        self.confirm_btn = ui.Button(
            label=t("general.confirm", lang), style=discord.ButtonStyle.success,
            disabled=True, row=3)
        self.confirm_btn.callback = self._confirm
        self.add_item(self.confirm_btn)

    def _update_confirm_state(self):
        self.confirm_btn.disabled = not (self.selected_users and self.selected_type)

    async def _on_user(self, interaction):
        self.selected_users = list(self.user_select.values)
        self._update_confirm_state()
        await interaction.response.edit_message(view=self)

    async def _on_type(self, interaction):
        self.selected_type = self.type_select.values[0]
        self.selected_roles = []
        for opt in self.type_select.options:
            opt.default = (opt.value == self.selected_type)
        lang = get_guild_language(self.guild_id)
        if self.roles_enabled and self.role_select is not None:
            role_opts = [discord.SelectOption(label=role_label(r, lang), value=r)
                         for r in ROLES_BY_TYPE.get(self.selected_type, [])]
            self.role_select.options = role_opts or [discord.SelectOption(label="—", value="__placeholder__")]
            self.role_select.disabled = not role_opts
            self.role_select.min_values = 0
            self.role_select.max_values = max(1, len(role_opts))
            self.role_select.placeholder = t("player.role_select_placeholder", lang)
        self._update_confirm_state()
        await interaction.response.edit_message(view=self)

    async def _on_role(self, interaction):
        self.selected_roles = [v for v in self.role_select.values if v != "__placeholder__"]
        for opt in self.role_select.options:
            opt.default = (opt.value in self.selected_roles)
        await interaction.response.edit_message(view=self)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        # Disable the whole view so a second click can't re-fire a stale handler.
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        registered: list = []
        waitlisted: list = []
        already: list = []
        lock = _get_guild_lock(self.guild_id)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
            if not event or not is_player_mode(event):
                await interaction.followup.send(t("player.not_player_mode", lang), ephemeral=True)
                self.stop()
                return
            for user in self.selected_users:
                squad_name, status = _player_register(
                    event, user_assignments, user.id, user.display_name,
                    self.selected_type, self.selected_roles)
                if status == "registered":
                    registered.append((user, squad_name))
                elif status == "waitlisted":
                    waitlisted.append(user)
                elif status == "already_registered":
                    already.append(user)
            save_event(db_id, event, user_assignments)

        type_label = t(f"embed.type_{self.selected_type}", lang) if self.selected_type in SQUAD_TYPES else self.selected_type
        role_labels = [role_label(r, lang) for r in self.selected_roles]
        role_suffix = (", " + ", ".join(role_labels)) if role_labels else ""
        parts = []
        if registered:
            parts.append(t("admin.player_add_registered_count", lang, n=len(registered), type=type_label, role_suffix=role_suffix))
        if waitlisted:
            parts.append(t("admin.player_add_waitlisted_count", lang, n=len(waitlisted)))
        if already:
            parts.append(t("admin.player_add_already_count", lang, n=len(already)))
        summary = "\n".join(parts) or t("embed.no_entries", lang)
        await interaction.followup.send(summary, ephemeral=True)

        for user, squad_name in registered:
            await send_to_log_channel(
                t("log.player_registered", lang, user=user.name, type=type_label, squad=squad_name, role_suffix=role_suffix),
                guild=interaction.guild)
        for user in waitlisted:
            await send_to_log_channel(
                t("log.player_waitlisted", lang, user=user.name, type=type_label),
                guild=interaction.guild)

        await update_event_displays(self.guild_id, self.channel_id)
        self.stop()


class _AdminPlayerRemoveView(BaseView):
    """Admin: pick players (squad members or waitlisted), then confirm removal."""
    def __init__(self, guild_id, channel_id, options):
        super().__init__(timeout=300, title="Admin Remove Player")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_ids: list = []
        self._option_labels = {o.value: o.label for o in options}
        lang = get_guild_language(guild_id)

        self.select = ui.Select(
            placeholder=t("admin.pick_player_to_remove", lang),
            options=options,
            min_values=1, max_values=min(25, len(options)) if options else 1)
        self.select.callback = self._on_pick
        self.add_item(self.select)

        self.confirm_btn = ui.Button(
            label=t("squad.unregister_button", lang), style=discord.ButtonStyle.danger,
            disabled=True, row=1)
        self.confirm_btn.callback = self._confirm
        self.add_item(self.confirm_btn)

        self.cancel_btn = ui.Button(
            label=t("general.cancel", lang), style=discord.ButtonStyle.secondary, row=1)
        self.cancel_btn.callback = self._cancel
        self.add_item(self.cancel_btn)

    async def _on_pick(self, interaction):
        self.selected_ids = list(self.select.values)
        # Persist the picked options across re-renders.
        for opt in self.select.options:
            opt.default = opt.value in self.selected_ids
        self.confirm_btn.disabled = not self.selected_ids
        await interaction.response.edit_message(view=self)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)
        self.stop()

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        removed: list = []          # [(user_id, squad_name)]
        waitlist_removed: list = []  # [(user_id, squad_type)]
        tentative_removed: list = []  # [user_id]
        missing: list = []
        all_promoted: list = []
        lock = _get_guild_lock(self.guild_id)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
            if not event or not is_player_mode(event):
                await interaction.followup.send(t("player.not_player_mode", lang), ephemeral=True)
                self.stop()
                return
            for user_id in self.selected_ids:
                ok, squad_name, promoted = _player_unregister(event, user_assignments, user_id)
                if ok:
                    removed.append((user_id, squad_name))
                    all_promoted.extend(promoted)
                    continue
                # Not in a squad — try the waitlist.
                wl_type = _player_remove_from_waitlist(event, user_id)
                if wl_type is not None:
                    waitlist_removed.append((user_id, wl_type))
                    continue
                # Not waitlisted — try a tentative sign-up.
                if _remove_tentative(event, user_id) is not None:
                    tentative_removed.append(user_id)
                else:
                    missing.append(user_id)
            save_event(db_id, event, user_assignments)

        parts = []
        if removed:
            parts.append(t("admin.player_remove_count", lang, n=len(removed)))
        if waitlist_removed:
            parts.append(t("admin.player_remove_waitlist_count", lang, n=len(waitlist_removed)))
        if tentative_removed:
            parts.append(t("admin.player_remove_tentative_count", lang, n=len(tentative_removed)))
        if missing:
            parts.append(t("admin.player_remove_missing_count", lang, n=len(missing)))
        summary = "\n".join(parts) or t("embed.no_entries", lang)
        await interaction.followup.send(summary, ephemeral=True)

        for user_id, squad_name in removed:
            await send_to_log_channel(
                t("log.player_unregistered", lang, user=user_id, squad=squad_name or "?"),
                guild=interaction.guild)
        for user_id, squad_type in waitlist_removed:
            type_label = t(f"embed.type_{squad_type}", lang) if squad_type in SQUAD_TYPES else squad_type
            await send_to_log_channel(
                t("log.player_waitlist_removed", lang, user=user_id, type=type_label),
                guild=interaction.guild)
        for user_id in tentative_removed:
            await send_to_log_channel(
                t("log.player_tentative_removed", lang, user=user_id),
                guild=interaction.guild)

        await _notify_promoted_players(
            interaction.guild, self.guild_id, self.channel_id, lang, all_promoted, event)
        await update_event_displays(self.guild_id, self.channel_id)
        self.stop()


class _AdminSquadRegView(BaseView):
    """Admin add-squad: type select + playstyle select + continue → name modal."""
    def __init__(self, guild_id, channel_id, event):
        super().__init__(timeout=300, title="Admin Add Squad")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.playstyle_enabled = bool(event.get("playstyle_enabled", True))
        self.selected_type = None
        self.selected_playstyle = None if self.playstyle_enabled else "Normal"
        self.selected_user = None

        sizes = _get_squad_sizes(event)
        lang = get_guild_language(guild_id)

        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=_squad_type_options(event, lang),
            row=0)
        self.type_select.callback = lambda i: self._on_select(i, self.type_select, 'selected_type')
        self.add_item(self.type_select)

        if self.playstyle_enabled:
            self.playstyle_select = ui.Select(
                placeholder=t("squad.playstyle_select", lang),
                options=[
                    discord.SelectOption(label="Casual", value="Casual"),
                    discord.SelectOption(label="Normal", value="Normal"),
                    discord.SelectOption(label="Focused", value="Focused"),
                ], row=1)
            self.playstyle_select.callback = lambda i: self._on_select(i, self.playstyle_select, 'selected_playstyle')
            self.add_item(self.playstyle_select)
        else:
            self.playstyle_select = None

        self.user_select = ui.UserSelect(
            placeholder=t("admin.select_rep_user", lang), min_values=1, max_values=1, row=2)
        self.user_select.callback = self._user_selected
        self.add_item(self.user_select)

        self.continue_button = ui.Button(
            label=t("squad.continue", lang), style=discord.ButtonStyle.success, disabled=True, row=3)
        self.continue_button.callback = self._continue
        self.add_item(self.continue_button)

    def _build_status(self):
        lang = get_guild_language(self.guild_id)
        sizes = _get_squad_sizes(self.event)
        desc_key = "squad.step_1_desc" if self.playstyle_enabled else "squad.step_1_desc_no_playstyle"
        lines = [f"**{t('squad.step_1_title', lang)}**", t(desc_key, lang)]
        if self.selected_type:
            stype, req_size = _parse_squad_type_value(self.selected_type)
            type_label = t(f"squad.type_{stype}", lang, size=req_size or sizes.get(stype, "?"))
            lines.append(t("squad.selected_type", lang, label=type_label))
        if self.playstyle_enabled and self.selected_playstyle:
            lines.append(t("squad.selected_playstyle", lang, label=self.selected_playstyle))
        if self.selected_user:
            lines.append(t("admin.selected_rep_user", lang, user=self.selected_user.display_name))
        return "\n".join(lines)

    def _all_selected(self):
        if self.playstyle_enabled:
            return self.selected_type and self.selected_playstyle and self.selected_user
        return self.selected_type and self.selected_user

    async def _on_select(self, interaction, select, attr):
        setattr(self, attr, select.values[0])
        for opt in select.options:
            opt.default = opt.value == select.values[0]
        self.continue_button.disabled = not self._all_selected()
        await interaction.response.edit_message(content=self._build_status(), view=self)

    async def _user_selected(self, interaction):
        self.selected_user = self.user_select.values[0]
        self.continue_button.disabled = not self._all_selected()
        await interaction.response.edit_message(content=self._build_status(), view=self)

    async def _continue(self, interaction):
        if not self._all_selected():
            return
        stype, req_size = _parse_squad_type_value(self.selected_type)
        modal = _AdminSquadNameModal(self.guild_id, self.channel_id, stype, self.selected_playstyle,
                                     self.selected_user, requested_size=req_size)
        await interaction.response.send_modal(modal)


class _AdminSquadNameModal(ui.Modal):
    """Admin add-squad step 2: enter squad name and register."""
    def __init__(self, guild_id, channel_id, squad_type, playstyle, rep_user, requested_size=None):
        lang = get_guild_language(guild_id)
        super().__init__(title=t("squad.register_title", lang))
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_type = squad_type
        self.playstyle = playstyle
        self.rep_user = rep_user
        self.requested_size = requested_size
        self.squad_name = ui.TextInput(
            label=t("squad.name_label", lang),
            placeholder=t("squad.name_placeholder", lang),
            required=True, min_length=2, max_length=30)
        self.add_item(self.squad_name)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)
        squad_name = self.squad_name.value.strip()

        lock = _get_guild_lock(gid)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(gid, cid)
            if not event:
                await interaction.followup.send(t("general.no_active_event", lang), ephemeral=True)
                return

            sizes = _get_squad_sizes(event)
            size = sizes.get(self.squad_type, sizes["infantry"])
            squad_id = generate_squad_id(squad_name, len(event.get("squads", {})))
            available = event["max_player_slots"] - event["player_slots_used"]

            rep_name = self.rep_user.display_name
            rep_uid = str(self.rep_user.id)

            type_full = _is_squad_type_full(event, self.squad_type)
            if self.squad_type == "infantry" and self.requested_size is not None and self.requested_size != size:
                if (dict(infantry_size_options(event)).get(self.requested_size, 0) <= 0
                        or self.requested_size > available):
                    await interaction.followup.send(t("squad.size_unavailable", lang), ephemeral=True)
                    return
                size = self.requested_size
            elif not type_full and _squad_slot_reserved(event, self.squad_type, size):
                type_full = True

            wl_key = _waitlist_key(self.squad_type)
            if type_full:
                event[wl_key].append((squad_name, self.squad_type, self.playstyle, size, squad_id, rep_name))
                wl_pos = len(event[wl_key])
                status = t("admin.squad_type_full_waitlist", lang, type=self.squad_type)
            elif size <= available:
                event["squads"][squad_id] = {
                    "name": squad_name, "type": self.squad_type, "playstyle": self.playstyle,
                    "size": size, "rep_name": rep_name,
                }
                event["player_slots_used"] += size
                status = t("admin.squad_added_registered", lang)
            else:
                event[wl_key].append((squad_name, self.squad_type, self.playstyle, size, squad_id, rep_name))
                wl_pos = len(event[wl_key])
                status = t("admin.squad_added_waitlist", lang, pos=wl_pos)

            add_user_assignment(user_assignments, rep_uid, squad_id)
            save_event(db_id, event, user_assignments)

        type_label = t(f"squad.label_{self.squad_type}", lang) if self.squad_type in SQUAD_TYPES else self.squad_type
        msg_key = "admin.squad_added" if event.get("playstyle_enabled", True) else "admin.squad_added_no_playstyle"
        await interaction.followup.send(
            t(msg_key, lang, name=squad_name, type=type_label, size=size, playstyle=self.playstyle, status=status),
            ephemeral=True)
        await send_to_log_channel(
            t("log.admin_squad_added", lang, user=interaction.user.name, squad=squad_name, type=type_label, size=size, playstyle=self.playstyle),
            guild=interaction.guild)
        await update_event_displays(gid, cid)


class _AdminRemoveSquadView(BaseView):
    """Admin remove-squad: per-type select menus for registered + combined waitlist."""
    def __init__(self, guild_id, channel_id, select_groups):
        super().__init__(timeout=120, title="Remove Squad")
        self.guild_id = guild_id
        self.channel_id = channel_id
        for row, (placeholder, options) in enumerate(select_groups):
            select = ui.Select(placeholder=placeholder, options=options, row=row)
            select.callback = self._selected
            self.add_item(select)

    async def _selected(self, interaction):
        selected = interaction.data["values"][0]
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        display_name = _resolve_squad_name(event, selected) if event else selected
        view = _ConfirmRemoveView(self.guild_id, self.channel_id, selected, "squad", lang, display_name=display_name)
        await interaction.response.send_message(
            t("admin.confirm_remove_squad", lang, name=display_name),
            view=view, ephemeral=True)


class _AdminAddCasterView(BaseView):
    """Admin add-caster: user select to pick a Discord user."""
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=120, title="Add Caster")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user_select = ui.UserSelect(placeholder="Select user", min_values=1, max_values=1, row=0)
        self.user_select.callback = self._user_selected
        self.add_item(self.user_select)

    async def _user_selected(self, interaction):
        selected_user = self.user_select.values[0]
        await interaction.response.defer(ephemeral=True)
        gid = self.guild_id
        cid = self.channel_id
        lang = get_guild_language(gid)

        lock = _get_guild_lock(gid)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(gid, cid)
            if not event:
                await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
                return

            user_id = str(selected_user.id)
            if user_has_caster(user_assignments, user_id):
                await send_feedback(interaction, t("admin.caster_already_registered", lang, user=selected_user.display_name), ephemeral=True)
                return

            display_name = selected_user.display_name

            if event["caster_slots_used"] < event["max_caster_slots"]:
                event["casters"][user_id] = {"name": display_name, "id": user_id}
                event["caster_slots_used"] += 1
                add_user_assignment(user_assignments, user_id, "__caster__")
                save_event(db_id, event, user_assignments)
                await send_feedback(interaction, t("admin.caster_added", lang, user=display_name), ephemeral=True)
            else:
                event["caster_waitlist"].append((user_id, display_name))
                add_user_assignment(user_assignments, user_id, "__caster__")
                save_event(db_id, event, user_assignments)
                wl_pos = len(event["caster_waitlist"])
                await send_feedback(interaction, t("admin.caster_added_waitlist", lang, user=display_name, pos=wl_pos), ephemeral=True)

        await send_to_log_channel(
            t("log.admin_caster_added", lang, admin=interaction.user.name, user=display_name),
            guild=interaction.guild)
        await update_event_displays(gid, cid)


class _AdminRemoveCasterView(BaseView):
    """Admin remove-caster: select menu of all casters + waitlist."""
    def __init__(self, guild_id, channel_id, options):
        super().__init__(timeout=120, title="Remove Caster")
        self.guild_id = guild_id
        self.channel_id = channel_id
        select = ui.Select(placeholder="Select caster", options=options, row=0)
        select.callback = self._selected
        self.add_item(select)

    async def _selected(self, interaction):
        target_uid = interaction.data["values"][0]
        lang = get_guild_language(self.guild_id)
        # Resolve display name from event data
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        caster_name = target_uid
        if event:
            if target_uid in event.get("casters", {}):
                caster_name = event["casters"][target_uid].get("name", target_uid)
            else:
                for uid, name in event.get("caster_waitlist", []):
                    if uid == target_uid:
                        caster_name = name
                        break
        view = _ConfirmRemoveView(self.guild_id, self.channel_id, target_uid, "caster", lang,
                                  display_name=caster_name)
        await interaction.response.send_message(
            t("admin.confirm_remove_caster", lang, name=caster_name),
            view=view, ephemeral=True)


class _ConfirmRemoveView(BaseView):
    """Confirmation prompt before removing a squad or caster."""
    def __init__(self, guild_id, channel_id, target, remove_type, lang, display_name=None):
        super().__init__(timeout=60, title="Confirm Remove")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.target = target  # squad name or caster uid
        self.remove_type = remove_type  # "squad" or "caster"
        self.display_name = display_name or target

        confirm_btn = ui.Button(label=t("general.confirm", lang), style=discord.ButtonStyle.danger, row=0)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary, row=0)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_language(self.guild_id)

        if self.remove_type == "squad":
            result = await unregister_squad(interaction, self.guild_id, self.channel_id, self.target, is_admin=True)
            if result is not None:
                await send_feedback(interaction, t("admin.squad_removed", lang, name=self.display_name, freed=result), ephemeral=True)
        else:
            # Caster removal
            gid, cid = self.guild_id, self.channel_id
            lock = _get_guild_lock(gid)
            async with lock:
                event, user_assignments, db_id = _get_channel_event(gid, cid)
                if not event:
                    await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
                    return

                caster_name = None
                if self.target in event["casters"]:
                    caster_name = event["casters"][self.target]["name"]
                    del event["casters"][self.target]
                    event["caster_slots_used"] = max(0, event["caster_slots_used"] - 1)
                    remove_user_assignment(user_assignments, self.target, "__caster__")
                    save_event(db_id, event, user_assignments)
                    await _process_caster_waitlist(event, user_assignments, db_id, gid, cid)
                else:
                    for i, (uid, name) in enumerate(event.get("caster_waitlist", [])):
                        if uid == self.target:
                            caster_name = name
                            event["caster_waitlist"].pop(i)
                            remove_user_assignment(user_assignments, self.target, "__caster__")
                            save_event(db_id, event, user_assignments)
                            break

            if caster_name is None:
                await send_feedback(interaction, t("admin.caster_not_found", lang), ephemeral=True)
                return

            await send_feedback(interaction, t("admin.caster_removed", lang, name=caster_name), ephemeral=True)
            await send_to_log_channel(
                t("log.admin_caster_removed", lang, admin=interaction.user.name, name=caster_name),
                guild=interaction.guild)
            await update_event_displays(gid, cid)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


# ---------------------------------------------------------------------------
# DM edit session: helpers, views, main loop
# ---------------------------------------------------------------------------

def _event_weekday_index(event):
    """Return 0-6 (Mon..Sun) for the event's date, or None."""
    dt = parse_date(event.get("date", "") or "")
    return dt.weekday() if dt else None


def _event_weekday_name(event, lang):
    """Full localized weekday name for the event's date, falling back to Sunday."""
    idx = _event_weekday_index(event)
    if idx is None:
        idx = 6
    return t(f"edit.recurrence.weekday_full.{idx}", lang)


def _format_recurrence(rec, lang, event=None):
    """Render a recurrence dict as a human-readable one-line string."""
    if not rec or not isinstance(rec, dict):
        return t("edit.recurrence.display.never", lang)
    rtype = rec.get("type", "never")

    if rtype == "never":
        return t("edit.recurrence.display.never", lang)

    if rtype in ("every_minutes", "every_hours", "every_days", "every_weeks"):
        return t(f"edit.recurrence.display.{rtype}", lang, n=rec.get("interval", 1))

    if rtype == "every_month":
        return t("edit.recurrence.display.every_month", lang)

    if rtype in ("first_weekday", "fourth_weekday", "last_weekday"):
        day = _event_weekday_name(event, lang) if event else ""
        return t(f"edit.recurrence.display.{rtype}", lang, day=day)

    if rtype == "specific_date":
        d = rec.get("date", "")
        tstr = rec.get("time")
        display = f"{d} {tstr}" if tstr else d
        return t("edit.recurrence.display.specific_date", lang, date=display)

    if rtype == "specific_weekdays":
        names = [t(f"edit.recurrence.weekday.{i}", lang) for i in rec.get("weekdays", [])]
        return t("edit.recurrence.display.specific_weekdays", lang, days=", ".join(names))

    if rtype == "specific_month_days":
        days = ", ".join(str(d) for d in rec.get("month_days", []))
        return t("edit.recurrence.display.specific_month_days", lang, days=days)

    return t("edit.recurrence.display.never", lang)


_DURATION_PRESETS = [30, 60, 120, 240, 360, 480, 720, 1440]
_DURATION_KEYS = ["30m", "1h", "2h", "4h", "6h", "8h", "12h", "24h"]
_SPAWN_PRESETS = [1, 5, 10, 30, 60, 360, 1440, 10080]
_SPAWN_KEYS = ["1m", "5m", "10m", "30m", "1h", "6h", "1d", "1w"]
# Registration-limit dropdowns. `None` = "no limit". Both fit Discord's 25-option cap.
_PERCENT_PRESETS = [None, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
_COUNT_PRESETS = [None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
# Regular per-user squad limit (#12): required value 1–20, no "no limit".
_REGULAR_SQUAD_PRESETS = list(range(1, 21))


def _format_percent_value(percent, lang):
    """Render a percentage cap; None → 'No limit'."""
    if percent is None:
        return t("limit.none", lang)
    try:
        return t("percent.value", lang, n=int(percent))
    except (TypeError, ValueError):
        return t("limit.none", lang)


def _format_count_value(count, lang):
    """Render a squad-count cap; None → 'No limit'."""
    if count is None:
        return t("limit.none", lang)
    try:
        return str(int(count))
    except (TypeError, ValueError):
        return t("limit.none", lang)


def _format_squads_per_user(count, lang):
    """Context-carrying value for the regular per-user squad dropdown."""
    if count is None:
        return t("limit.none", lang)
    return t("limit.squads_per_user", lang, n=int(count))


def _format_squads_per_role(count, lang):
    """Context-carrying value for the early-access per-role squad dropdown."""
    if count is None:
        return t("limit.none", lang)
    return t("limit.squads_per_role", lang, n=int(count))


def _format_duration_value(minutes, lang):
    """Render duration_minutes as a short label; falls back to '{n} min' for non-preset values."""
    try:
        n = int(minutes)
    except (TypeError, ValueError):
        n = 120
    if n in _DURATION_PRESETS:
        key = _DURATION_KEYS[_DURATION_PRESETS.index(n)]
        return t(f"edit.duration.display.{key}", lang)
    return t("edit.duration.display.custom", lang, n=n)


def _format_spawn_offset_value(minutes, lang):
    """Render spawn_offset_minutes as a short label; falls back to '{n} min' for non-preset values."""
    try:
        n = int(minutes)
    except (TypeError, ValueError):
        n = 5
    if n in _SPAWN_PRESETS:
        key = _SPAWN_KEYS[_SPAWN_PRESETS.index(n)]
        return t(f"edit.spawn_offset.display.{key}", lang)
    return t("edit.spawn_offset.display.custom", lang, n=n)


def _format_property_value(event, key, vtype, lang):
    """Format a property value for display in the edit list."""
    not_set = t("edit.not_set", lang)
    val = event.get(key)
    if vtype == "bool":
        return t("edit.bool.enabled", lang) if val else t("edit.bool.disabled", lang)
    if vtype in ("string", "string_nullable"):
        return str(val) if val else not_set
    if vtype == "date":
        return val if val else not_set
    if vtype == "time":
        return val if val else not_set
    if vtype == "int":
        return str(val) if val is not None else "0"
    if vtype == "int_nullable":
        if val is None or val == 0:
            return not_set
        return str(val)
    if vtype == "reg_start":
        if event.get("registration_open") and not val:
            return t("wizard.summary_reg_immediate", lang)
        if isinstance(val, datetime):
            return val.strftime("%d.%m.%Y %H:%M")
        return not_set
    if vtype == "image":
        return val if val else not_set
    if vtype == "recurrence":
        return _format_recurrence(val, lang, event=event)
    if vtype == "duration":
        return _format_duration_value(val, lang)
    if vtype == "spawn_offset":
        return _format_spawn_offset_value(val, lang)
    if vtype == "percent":
        return _format_percent_value(val, lang)
    if vtype == "squad_count":
        return _format_count_value(val, lang)
    return str(val) if val is not None else not_set


def _validate_edit_value(message, key, vtype, lang):
    """Parse and validate a user reply. Returns (parsed_value, error_i18n_key_or_None)."""
    text = message.content.strip()
    clear_words = {"leer", "empty", "none", ""}

    if vtype == "string":
        if not text:
            return None, "edit.invalid_number"
        return text, None

    if vtype == "string_nullable":
        if text.lower() in clear_words:
            return None, None
        return text, None

    if vtype == "date":
        if not parse_date(text):
            return None, "edit.invalid_date"
        return text, None

    if vtype == "time":
        m = re.match(r"^(\d{1,2}):(\d{2})$", text)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            return None, "edit.invalid_time"
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}", None

    if vtype == "int":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        if val < 1:
            return None, "edit.invalid_integer"
        return val, None

    if vtype == "int_zero":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        if val < 0:
            return None, "edit.invalid_integer"
        return val, None

    if vtype == "int_nullable":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        if val < 0:
            return None, "edit.invalid_integer"
        return val if val > 0 else None, None

    if vtype == "reg_start":
        if text.lower() in clear_words:
            return None, None
        if text.lower() in {"sofort", "now", "jetzt", "immediately"}:
            return "__immediate__", None
        parsed = parse_registration_start(text)
        if parsed is None:
            return None, "edit.invalid_date"
        return parsed, None

    if vtype == "image":
        if message.attachments:
            att = message.attachments[0]
            if att.content_type and att.content_type.startswith("image/"):
                return att.url, None
            return None, "edit.invalid_url"
        if text.lower() in clear_words:
            return None, None
        if text.startswith("https://"):
            return text, None
        return None, "edit.invalid_url"

    if vtype == "bool":
        yes = {"yes", "ja", "y", "j", "true", "1", "on", "an", "aktiviert", "enabled", "enable"}
        no_ = {"no", "nein", "n", "false", "0", "off", "aus", "deaktiviert", "disabled", "disable"}
        lower = text.lower()
        if lower in yes:
            return True, None
        if lower in no_:
            return False, None
        return None, "edit.invalid_bool"

    return text, None


def _parse_int_list(text):
    """Parse comma/whitespace-separated integers. Returns None on any parse error."""
    try:
        return [int(p) for p in re.split(r"[,\s]+", text.strip()) if p]
    except ValueError:
        return None


def _visible_edit_properties(event):
    """Return the editable properties relevant to this event's mode.

    Player-mode events never use playstyle (rep concept); rep-mode events never
    use the player-mode in-squad-role toggle. Each toggle is hidden in the other
    mode.
    """
    if is_player_mode(event):
        return [p for p in _EDIT_PROPERTIES if p[1] != "playstyle_enabled"]
    return [p for p in _EDIT_PROPERTIES if p[1] != "player_roles_enabled"]


# ═══════════════════════════════════════════════════════════════════════════
# View-based DM event editor
#
# A persistent DM message shows a property dropdown + a "Fertig/Done" button.
# Picking a property swaps in a small sub-editor (modal for text/numbers,
# buttons for the bool, a dropdown for presets, a dropdown + modals for
# recurrence, a hybrid listen step for the image). Each edit saves immediately
# and returns to the overview; Done closes the session. Session state lives in
# _active_edit_sessions; every view's on_timeout tears the session down.
# ═══════════════════════════════════════════════════════════════════════════

def _prop_short_label(label_key, lang):
    """Property label without the leading 'NN. ' numbering used in the embed."""
    return t(label_key, lang).split(". ", 1)[-1]


def _validate_edit_text(text, vtype, lang):
    """Parse/validate typed modal input for a scalar vtype.

    Returns (value, error_key_or_None). Mirrors the text branches of
    _validate_edit_value (which still handles the image attachment case).
    """
    text = (text or "").strip()
    clear_words = {"leer", "empty", "none", ""}

    if vtype == "string":
        if not text:
            return None, "edit.required"
        return text, None
    if vtype == "string_nullable":
        if text.lower() in clear_words:
            return None, None
        return text, None
    if vtype == "date":
        if not parse_date(text):
            return None, "edit.invalid_date"
        return text, None
    if vtype == "time":
        m = re.match(r"^(\d{1,2}):(\d{2})$", text)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            return None, "edit.invalid_time"
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}", None
    if vtype == "int":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        return (val, None) if val >= 1 else (None, "edit.invalid_integer")
    if vtype == "int_zero":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        return (val, None) if val >= 0 else (None, "edit.invalid_integer")
    if vtype == "int_nullable":
        try:
            val = int(text)
        except ValueError:
            return None, "edit.invalid_integer"
        if val < 0:
            return None, "edit.invalid_integer"
        return (val if val > 0 else None), None
    if vtype == "reg_start":
        if text.lower() in clear_words:
            return None, None
        if text.lower() in {"sofort", "now", "jetzt", "immediately"}:
            return "__immediate__", None
        parsed = parse_registration_start(text)
        if parsed is None:
            return None, "edit.invalid_date"
        return parsed, None
    return text, None


def _apply_property_change(event, key, vtype, special, new_value, lang):
    """Mutate `event` in place for a confirmed edit. Returns (ok, error_text).

    When ok is False the caller must NOT save — error_text is a ready-to-send,
    localized message. Carries over every invariant from the old edit loop
    (vehicle/heli disable guard, registration-start special cases, slot
    recalculation, recurrence-fits check) and fixes the crash where the old
    code referenced an undefined `dm_channel`.
    """
    if key in ("max_vehicle_squads", "max_heli_squads") and new_value == 0:
        type_key = "vehicle" if key == "max_vehicle_squads" else "heli"
        has_squads = any(s.get("type") == type_key for s in event.get("squads", {}).values())
        has_wl = bool(event.get(f"{type_key}_waitlist", []))
        if has_squads or has_wl:
            return False, t("edit.cannot_disable_type_with_entries", lang,
                            type=t(f"embed.type_{type_key}", lang))

    if key == "registration_start_time":
        if new_value == "__immediate__":
            event["registration_open"] = True
            event["registration_start_time"] = None
        elif new_value is None:
            event["registration_start_time"] = None
        elif isinstance(new_value, datetime) and new_value <= datetime.now():
            event["registration_open"] = True
            event["registration_start_time"] = None
        elif isinstance(new_value, datetime):
            event_dt = parse_date(event.get("date", ""))
            if event_dt and event.get("time"):
                h, m = map(int, event["time"].split(":"))
                event_dt = event_dt.replace(hour=h, minute=m)
            if event_dt and new_value >= event_dt:
                return False, t("event.reg_after_event", lang)
            event["registration_start_time"] = new_value
            event["registration_open"] = False
        else:
            event["registration_start_time"] = new_value
            event["registration_open"] = False
    else:
        if key in ("date", "time", "recurrence", "duration_minutes", "spawn_offset_minutes"):
            # Validate on a probe copy before mutating, so a rejected change
            # never leaks into `event` (the caller relies on this on failure).
            probe = {**event, key: new_value}
            start_dt = compute_event_start(probe)
            end_dt = compute_event_end(probe)
            if start_dt and end_dt:
                ok, reason_key = validate_recurrence_fits(
                    start_dt, end_dt, probe.get("recurrence"),
                    probe.get("spawn_offset_minutes", 5))
                if not ok:
                    # validate_recurrence_fits returns bare keys ("recurrence.error.*");
                    # the localized strings live under the "edit." namespace.
                    return False, t(f"edit.{reason_key}", lang)
        event[key] = new_value

    if special == "recalc_slots":
        event["max_player_slots"] = event["server_max_players"] - event["max_caster_slots"]

    return True, None


# Recurrence dropdown options: value_id -> a ready dict (apply immediately) or a
# string naming the follow-up modal flow.
_RECURRENCE_OPTIONS = [
    ("never", {"type": "never"}),
    ("every_minutes", "interval"),
    ("every_hours", "interval"),
    ("every_days", "interval"),
    ("every_weeks", "interval"),
    ("every_month", {"type": "every_month"}),
    ("first_weekday", {"type": "first_weekday"}),
    ("fourth_weekday", {"type": "fourth_weekday"}),
    ("last_weekday", {"type": "last_weekday"}),
    ("specific_date", "specific_date"),
    ("specific_weekdays", "weekdays"),
    ("specific_month_days", "month_days"),
]
_RECURRENCE_SPEC = dict(_RECURRENCE_OPTIONS)


# ── Session lifecycle ──────────────────────────────────────────────────────

def _close_session(user_id):
    _active_edit_sessions.pop(user_id, None)


def _set_active_view(user_id, view):
    """Mark `view` as the live dialog for this session and bump activity."""
    session = _active_edit_sessions.get(user_id)
    if session is not None:
        session["active_view"] = view
        session["last_activity"] = time.monotonic()


async def _force_close_stale_session(user_id):
    """Tear down a stuck session and disable its old DM dialog (best-effort)."""
    session = _active_edit_sessions.pop(user_id, None)
    if not session:
        return
    dm_msg = session.get("dm_message")
    if dm_msg is not None:
        try:
            await dm_msg.edit(view=None)
        except discord.HTTPException:
            pass


async def _handle_edit_timeout(view, user_id):
    """Shared on_timeout handler for every edit view.

    No-op if the session was already closed (Done pressed) or `view` is a stale
    view the user navigated away from — each navigation supersedes the previous
    view's timer.
    """
    session = _active_edit_sessions.get(user_id)
    if not session or session.get("active_view") is not view:
        return
    _active_edit_sessions.pop(user_id, None)
    lang = session.get("lang", "de")
    dm_msg = session.get("dm_message")
    if dm_msg is None:
        return
    try:
        await dm_msg.edit(view=None)
    except discord.HTTPException:
        pass
    try:
        await dm_msg.channel.send(t("edit.timeout", lang))
    except discord.HTTPException:
        pass


async def _notify_event_gone(interaction, user_id, lang, via_modal=False):
    """Close the session and tell the user the event no longer exists."""
    _close_session(user_id)
    if via_modal:
        try:
            await interaction.response.send_message(
                t("general.no_active_event", lang), ephemeral=True)
        except discord.InteractionResponded:
            pass
    else:
        try:
            await interaction.response.edit_message(
                embed=discord.Embed(description=t("general.no_active_event", lang),
                                    color=discord.Color.red()),
                view=None)
        except discord.HTTPException:
            pass


# ── Overview embed + refresh ───────────────────────────────────────────────

def _build_edit_main_embed(event, lang, updated_note=None):
    """Property overview embed shown at the top of the editor."""
    visible = _visible_edit_properties(event)
    groups = [
        ("edit.group.general", visible[0:4]),
        ("edit.group.squad_config", visible[4:12]),
        ("edit.group.extras", visible[12:]),
    ]
    embed = discord.Embed(
        title=t("edit.title", lang),
        description=t("edit.select_property_v2", lang),
        color=discord.Color.blue(),
    )
    for group_key, props in groups:
        if not props:
            continue
        lines = []
        for num, key, label_key, vtype, special in props:
            current = _format_property_value(event, key, vtype, lang)
            lines.append(f"`{num:>2}.` {_prop_short_label(label_key, lang)}:  `{current}`")
        embed.add_field(name=t(group_key, lang), value="\n".join(lines), inline=False)
    if updated_note:
        embed.add_field(name="​", value=f"✅ {updated_note}", inline=False)
    embed.set_footer(text=t("edit.footer_hint_v2", lang))
    return embed


def _build_guild_main_embed(settings, lang, updated_note=None):
    """Property overview embed for the guild-defaults editor."""
    embed = discord.Embed(
        title=t("config_defaults.title", lang),
        description=t("config_defaults.intro", lang),
        color=discord.Color.blue(),
    )
    lines = []
    for num, key, label_key, vtype, special in _GUILD_EDIT_PROPERTIES:
        current = _format_property_value(settings, key, vtype, lang)
        lines.append(f"`{num:>2}.` {_prop_short_label(label_key, lang)}:  `{current}`")
    embed.add_field(name="​", value="\n".join(lines), inline=False)
    if updated_note:
        embed.add_field(name="​", value=f"✅ {updated_note}", inline=False)
    embed.set_footer(text=t("config_defaults.footer", lang))
    return embed


async def _persist_guild_edit(guild_id, prop, new_value, lang, editor_name):
    """Validate + save one guild-default edit under the guild lock.

    Returns ("ok", None) | ("error", text). Never returns "gone".
    Deliberately skips _apply_property_change and update_event_displays —
    guild defaults are not event invariants.
    """
    num, key, label_key, vtype, special = prop
    lock = _get_guild_lock(guild_id)
    async with lock:
        settings = get_guild_settings(guild_id) or dict(DEFAULT_GUILD_SETTINGS)
        # Min-value validation (mirrors set_defaults_cmd logic)
        if vtype == "int" and isinstance(new_value, int) and new_value < 1:
            return "error", t("set.value_too_low", lang, min=1)
        if vtype == "int_zero" and isinstance(new_value, int) and new_value < 0:
            return "error", t("set.value_too_low", lang, min=0)
        settings[key] = new_value
        save_guild_settings(guild_id, settings)
    guild = bot.get_guild(guild_id)
    if guild:
        await send_to_log_channel(
            t("config_defaults.log_changed", lang,
              user=editor_name,
              property=t(label_key, lang),
              value=str(new_value)),
            guild=guild)
    return "ok", None


async def _refresh_main_view(interaction, user_id, guild_id, channel_id, db_id, lang,
                             updated_note=None, via_modal=False):
    """Re-render the overview (after an edit or cancel) on the session message."""
    target = _session_target(user_id)
    obj = target.load(guild_id, channel_id)
    if target.kind == "event" and not obj:
        await _notify_event_gone(interaction, user_id, lang, via_modal=via_modal)
        return
    embed = target.overview_embed(obj, lang, updated_note=updated_note)
    view = EditMainView(user_id, guild_id, channel_id, db_id, lang)
    _set_active_view(user_id, view)
    if via_modal:
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass
        session = _active_edit_sessions.get(user_id)
        dm_msg = session.get("dm_message") if session else None
        if dm_msg is not None:
            try:
                await dm_msg.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass
    else:
        await interaction.response.edit_message(embed=embed, view=view)


async def _reshow_overview_dm(user_id, guild_id, channel_id, db_id, lang, note=None):
    """Edit the stored session DM message back to the overview (no interaction)."""
    session = _active_edit_sessions.get(user_id)
    dm_msg = session.get("dm_message") if session else None
    if dm_msg is None:
        return
    target = _session_target(user_id)
    obj = target.load(guild_id, channel_id)
    if target.kind == "event" and not obj:
        return
    view = EditMainView(user_id, guild_id, channel_id, db_id, lang)
    _set_active_view(user_id, view)
    try:
        await dm_msg.edit(embed=target.overview_embed(obj, lang, updated_note=note),
                          view=view)
    except discord.HTTPException:
        pass


# ── Persist + apply ────────────────────────────────────────────────────────

async def _persist_event_edit(guild_id, channel_id, prop, new_value, lang, editor_name):
    """Validate + save one property edit under the guild lock.

    Returns ("ok", recalc_slots_or_None) | ("gone", None) | ("error", text).
    On success also refreshes the public event display and writes a log line.
    """
    num, key, label_key, vtype, special = prop
    lock = _get_guild_lock(guild_id)
    recalc_value = None
    event_name = None
    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            return "gone", None
        ok, err_text = _apply_property_change(event, key, vtype, special, new_value, lang)
        if not ok:
            return "error", err_text
        save_event(db_id, event, user_assignments)
        if special == "recalc_slots":
            recalc_value = event.get("max_player_slots")
        event_name = event.get("name")
    await update_event_displays(guild_id, channel_id)
    guild = bot.get_guild(guild_id)
    if guild:
        await send_to_log_channel(
            t("log.event_edited", lang, user=editor_name,
              property=t(label_key, lang), name=event_name),
            guild=guild)
    return "ok", recalc_value


def _edit_success_note(prop, lang, recalc_value):
    num, key, label_key, vtype, special = prop
    note = t("edit.updated_inline", lang, prop=_prop_short_label(label_key, lang))
    if special == "recalc_slots" and recalc_value is not None:
        note = f"{note} · {t('edit.recalculated', lang, slots=recalc_value)}"
    return note


async def _apply_edit(interaction, user_id, guild_id, channel_id, db_id, lang,
                      prop, new_value, via_modal=False):
    """Persist an edit from a live interaction, then refresh or surface an error."""
    target = _session_target(user_id)
    status, payload = await target.persist(
        guild_id, channel_id, prop, new_value, lang, interaction.user.name)
    if status == "gone":
        await _notify_event_gone(interaction, user_id, lang, via_modal=via_modal)
        return
    if status == "error":
        try:
            await interaction.response.send_message(payload, ephemeral=True)
        except discord.InteractionResponded:
            try:
                await interaction.followup.send(payload, ephemeral=True)
            except discord.HTTPException:
                pass
        return
    await _refresh_main_view(interaction, user_id, guild_id, channel_id, db_id, lang,
                             updated_note=_edit_success_note(prop, lang, payload),
                             via_modal=via_modal)


async def _apply_edit_dm(user_id, guild_id, channel_id, db_id, lang, prop,
                         new_value, editor_name):
    """Persist an edit without a live interaction (image hybrid path)."""
    target = _session_target(user_id)
    status, payload = await target.persist(
        guild_id, channel_id, prop, new_value, lang, editor_name)
    if status == "gone":
        session = _active_edit_sessions.get(user_id)
        dm_msg = session.get("dm_message") if session else None
        _close_session(user_id)
        if dm_msg is not None:
            try:
                await dm_msg.edit(embed=discord.Embed(
                    description=t("general.no_active_event", lang),
                    color=discord.Color.red()), view=None)
            except discord.HTTPException:
                pass
        return
    note = None
    if status == "error":
        session = _active_edit_sessions.get(user_id)
        dm_msg = session.get("dm_message") if session else None
        if dm_msg is not None:
            try:
                await dm_msg.channel.send(payload)
            except discord.HTTPException:
                pass
    else:
        note = _edit_success_note(prop, lang, payload)
    await _reshow_overview_dm(user_id, guild_id, channel_id, db_id, lang, note=note)


# ── Editor display helpers ─────────────────────────────────────────────────

def _scalar_hint(vtype, lang):
    if vtype == "reg_start":
        return t("edit.reg_start_hint", lang)
    if vtype == "string_nullable":
        return t("edit.description_hint", lang)
    return ""


def _scalar_placeholder(vtype):
    return {
        "date": "TT.MM.JJJJ",
        "time": "HH:MM",
        "reg_start": "TT.MM.JJJJ HH:MM / now / empty",
    }.get(vtype, "")


def _preset_label(value, vtype, lang):
    if vtype == "duration":
        return _format_duration_value(value, lang)
    if vtype == "percent":
        return _format_percent_value(value, lang)
    if vtype == "squad_count":
        return _format_count_value(value, lang)
    return _format_spawn_offset_value(value, lang)


async def _show_property_editor(interaction, user_id, guild_id, channel_id, db_id, lang, prop):
    """Swap the overview for the editor of a specific property."""
    num, key, label_key, vtype, special = prop
    target = _session_target(user_id)
    obj = target.load(guild_id, channel_id)
    if target.kind == "event" and not obj:
        await _notify_event_gone(interaction, user_id, lang)
        return
    label = _prop_short_label(label_key, lang)
    current_display = _format_property_value(obj, key, vtype, lang)

    def _editor_embed(extra=None):
        desc = t("edit.current_value", lang, value=current_display)
        if extra:
            desc = f"{desc}\n{extra}"
        return discord.Embed(title=label, description=desc, color=discord.Color.blurple())

    if vtype == "bool":
        view = EditBoolView(user_id, guild_id, channel_id, db_id, lang, prop, bool(obj.get(key)))
        embed = _editor_embed()
    elif vtype in ("duration", "spawn_offset", "percent", "squad_count"):
        presets = {"duration": _DURATION_PRESETS, "spawn_offset": _SPAWN_PRESETS,
                   "percent": _PERCENT_PRESETS, "squad_count": _COUNT_PRESETS}[vtype]
        view = EditPresetView(user_id, guild_id, channel_id, db_id, lang, prop, presets)
        embed = _editor_embed()
    elif vtype == "recurrence":
        view = EditRecurrenceView(user_id, guild_id, channel_id, db_id, lang, prop, obj)
        embed = _editor_embed()
    elif vtype == "image":
        view = EditImageView(user_id, guild_id, channel_id, db_id, lang, prop)
        embed = _editor_embed(t("edit.image_hint", lang))
    else:
        view = EditScalarView(user_id, guild_id, channel_id, db_id, lang, prop)
        embed = _editor_embed(_scalar_hint(vtype, lang) or None)
    _set_active_view(user_id, view)
    await interaction.response.edit_message(embed=embed, view=view)


# ── Views ──────────────────────────────────────────────────────────────────

class EditMainView(ui.View):
    """Persistent overview: property dropdown + Done button."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.db_id = db_id
        self.lang = lang
        target = _session_target(user_id)
        if target.kind == "guild":
            visible = list(_GUILD_EDIT_PROPERTIES)
        else:
            event, _ua, _db = _get_channel_event(guild_id, channel_id)
            visible = _visible_edit_properties(event) if event else list(_EDIT_PROPERTIES)
        # Keep the leading "NN. " numbering so dropdown entries line up with the
        # numbered overview list above.
        options = [discord.SelectOption(label=t(p[2], lang)[:100], value=p[1])
                   for p in visible]
        select = ui.Select(placeholder=t("edit.pick_property", lang), options=options,
                           min_values=1, max_values=1)
        select.callback = self._on_select
        self.add_item(select)
        done = ui.Button(label=t("general.done", lang),
                         style=discord.ButtonStyle.secondary, emoji="🛑")
        done.callback = self._on_done
        self.add_item(done)

    async def _on_select(self, interaction):
        target = _session_target(self.user_id)
        prop = _find_prop_in(target.properties(), interaction.data["values"][0])
        if not prop:
            return
        await _show_property_editor(interaction, self.user_id, self.guild_id,
                                    self.channel_id, self.db_id, self.lang, prop)

    async def _on_done(self, interaction):
        target = _session_target(self.user_id)
        text = target.finish_text(self.guild_id, self.channel_id, self.lang)
        _close_session(self.user_id)
        try:
            await interaction.response.edit_message(view=None)
        except discord.HTTPException:
            pass
        try:
            await interaction.channel.send(text)
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        await _handle_edit_timeout(self, self.user_id)


class _EditDialogView(ui.View):
    """Shared state + Cancel/timeout wiring for the per-property sub-editors."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.db_id = db_id
        self.lang = lang
        self.prop = prop

    def _add_cancel(self):
        cancel = ui.Button(label=t("general.cancel", self.lang),
                           style=discord.ButtonStyle.secondary, emoji="↩️")
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    async def _on_cancel(self, interaction):
        await _refresh_main_view(interaction, self.user_id, self.guild_id,
                                 self.channel_id, self.db_id, self.lang)

    async def _apply(self, interaction, value, via_modal=False):
        await _apply_edit(interaction, self.user_id, self.guild_id, self.channel_id,
                          self.db_id, self.lang, self.prop, value, via_modal=via_modal)

    async def on_timeout(self):
        await _handle_edit_timeout(self, self.user_id)


class EditScalarView(_EditDialogView):
    """Opens a modal for text/number properties (string/date/time/int/reg_start)."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop)
        btn = ui.Button(label=t("edit.open_input", lang),
                        style=discord.ButtonStyle.primary, emoji="⌨️")
        btn.callback = self._on_edit
        self.add_item(btn)
        self._add_cancel()

    async def _on_edit(self, interaction):
        await interaction.response.send_modal(EditScalarModal(
            self.user_id, self.guild_id, self.channel_id, self.db_id, self.lang, self.prop))


class EditScalarModal(ui.Modal):
    """Single-field text modal; validates via _validate_edit_text on submit."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        num, key, label_key, vtype, special = prop
        super().__init__(title=_prop_short_label(label_key, lang)[:45])
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.db_id = db_id
        self.lang = lang
        self.prop = prop
        is_long_text = vtype == "string_nullable"
        self.value_input = ui.TextInput(
            label=t("edit.input_label", lang)[:45],
            placeholder=_scalar_placeholder(vtype),
            style=discord.TextStyle.paragraph if is_long_text else discord.TextStyle.short,
            required=vtype not in ("string_nullable", "reg_start"),
            max_length=1024 if is_long_text else 200,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction):
        vtype = self.prop[3]
        value, err = _validate_edit_text(self.value_input.value, vtype, self.lang)
        if err:
            await interaction.response.send_message(t(err, self.lang), ephemeral=True)
            return
        await _apply_edit(interaction, self.user_id, self.guild_id, self.channel_id,
                          self.db_id, self.lang, self.prop, value, via_modal=True)


class EditBoolView(_EditDialogView):
    """Enable/Disable/Cancel buttons for a bool property."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop, current):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop)
        enable = ui.Button(
            label=t("edit.bool.enabled", lang), emoji="✅",
            style=discord.ButtonStyle.success if current else discord.ButtonStyle.secondary)
        enable.callback = self._make(True)
        self.add_item(enable)
        disable = ui.Button(
            label=t("edit.bool.disabled", lang), emoji="❌",
            style=discord.ButtonStyle.danger if not current else discord.ButtonStyle.secondary)
        disable.callback = self._make(False)
        self.add_item(disable)
        self._add_cancel()

    def _make(self, value):
        async def cb(interaction):
            await self._apply(interaction, value)
        return cb


class EditPresetView(_EditDialogView):
    """Dropdown of preset values for duration / spawn_offset (minutes)."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop, presets):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop)
        vtype = prop[3]
        # `None` in a preset list means "no limit" → option value "none" → stored None.
        options = [discord.SelectOption(
            label=_preset_label(v, vtype, lang)[:100],
            value="none" if v is None else str(v))
            for v in presets]
        select = ui.Select(placeholder=t("edit.pick_value", lang), options=options,
                           min_values=1, max_values=1)
        select.callback = self._on_select
        self.add_item(select)
        self._add_cancel()

    async def _on_select(self, interaction):
        raw = interaction.data["values"][0]
        await self._apply(interaction, None if raw == "none" else int(raw))


class EditImageView(_EditDialogView):
    """Image editor: keeps file-upload support via a short hybrid listen step."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop)
        send = ui.Button(label=t("edit.image_send", lang),
                         style=discord.ButtonStyle.primary, emoji="🖼️")
        send.callback = self._on_send
        self.add_item(send)
        clear = ui.Button(label=t("edit.image_clear", lang),
                          style=discord.ButtonStyle.secondary, emoji="🗑️")
        clear.callback = self._on_clear
        self.add_item(clear)
        self._add_cancel()

    async def _on_clear(self, interaction):
        await self._apply(interaction, None)

    async def _on_send(self, interaction):
        # Consume the interaction, then listen for the next DM so file uploads
        # (which modals can't accept) still work.
        await interaction.response.edit_message(
            embed=discord.Embed(description=t("edit.image_waiting", self.lang),
                                color=discord.Color.blurple()),
            view=None)

        def check(m):
            return m.author.id == self.user_id and isinstance(m.channel, discord.DMChannel)

        try:
            msg = await bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            await _handle_edit_timeout(self, self.user_id)
            return
        value, err = _validate_edit_value(msg, self.prop[1], "image", self.lang)
        if err:
            try:
                await msg.channel.send(t(err, self.lang))
            except discord.HTTPException:
                pass
            await _reshow_overview_dm(self.user_id, self.guild_id, self.channel_id,
                                      self.db_id, self.lang)
            return
        await _apply_edit_dm(self.user_id, self.guild_id, self.channel_id, self.db_id,
                             self.lang, self.prop, value, msg.author.name)


class EditRecurrenceView(_EditDialogView):
    """Dropdown of the 12 recurrence types; complex ones chain a modal."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop, event):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop)
        day = _event_weekday_name(event, lang)
        options = [discord.SelectOption(
            label=t(f"edit.recurrence.opt.{vid}", lang, day=day)[:100], value=vid)
            for vid, _spec in _RECURRENCE_OPTIONS]
        select = ui.Select(placeholder=t("edit.pick_value", lang), options=options,
                           min_values=1, max_values=1)
        select.callback = self._on_select
        self.add_item(select)
        self._add_cancel()

    async def _on_select(self, interaction):
        vid = interaction.data["values"][0]
        spec = _RECURRENCE_SPEC.get(vid)
        if isinstance(spec, dict):
            await self._apply(interaction, dict(spec))
            return
        modal_cls = {
            "interval": None,  # handled below (needs rtype)
            "specific_date": RecurrenceDateModal,
            "weekdays": RecurrenceWeekdaysModal,
            "month_days": RecurrenceMonthDaysModal,
        }.get(spec)
        if spec == "interval":
            await interaction.response.send_modal(RecurrenceIntervalModal(
                self.user_id, self.guild_id, self.channel_id, self.db_id, self.lang,
                self.prop, vid))
        elif modal_cls is not None:
            await interaction.response.send_modal(modal_cls(
                self.user_id, self.guild_id, self.channel_id, self.db_id, self.lang, self.prop))


class _RecurrenceModal(ui.Modal):
    """Base for recurrence follow-up modals (one text field, apply on submit)."""

    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop,
                 title, field_label, placeholder=""):
        super().__init__(title=title[:45])
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.db_id = db_id
        self.lang = lang
        self.prop = prop
        self.value_input = ui.TextInput(label=field_label[:45], placeholder=placeholder[:100],
                                        required=True, max_length=40)
        self.add_item(self.value_input)

    async def _apply(self, interaction, value):
        await _apply_edit(interaction, self.user_id, self.guild_id, self.channel_id,
                          self.db_id, self.lang, self.prop, value, via_modal=True)

    async def _error(self, interaction, key):
        await interaction.response.send_message(t(key, self.lang), ephemeral=True)


class RecurrenceIntervalModal(_RecurrenceModal):
    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop, rtype):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop,
                         title=t(f"edit.recurrence.opt.{rtype}", lang),
                         field_label=t("edit.recurrence.field.interval", lang),
                         placeholder="1")
        self.rtype = rtype

    async def on_submit(self, interaction):
        try:
            n = int(self.value_input.value.strip())
        except ValueError:
            n = 0
        if n < 1:
            await self._error(interaction, "edit.invalid_integer")
            return
        await self._apply(interaction, {"type": self.rtype, "interval": n})


class RecurrenceDateModal(_RecurrenceModal):
    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop,
                         title=t("edit.recurrence.opt.specific_date", lang),
                         field_label=t("edit.recurrence.field.date", lang),
                         placeholder="TT.MM.JJJJ HH:MM")

    async def on_submit(self, interaction):
        event, _ua, _db = _get_channel_event(self.guild_id, self.channel_id)
        event_time = (event.get("time") if event else None) or "20:00"
        parts = self.value_input.value.strip().split(maxsplit=1)
        if not parts or not parts[0]:
            await self._error(interaction, "edit.recurrence.invalid_specific_date")
            return
        date_str = parts[0]
        time_str = parts[1] if len(parts) > 1 else event_time
        try:
            datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        except ValueError:
            await self._error(interaction, "edit.recurrence.invalid_specific_date")
            return
        await self._apply(interaction, {"type": "specific_date", "date": date_str, "time": time_str})


class RecurrenceWeekdaysModal(_RecurrenceModal):
    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop,
                         title=t("edit.recurrence.opt.specific_weekdays", lang),
                         field_label=t("edit.recurrence.field.weekdays", lang),
                         placeholder="1,3,5")

    async def on_submit(self, interaction):
        nums = _parse_int_list(self.value_input.value.strip())
        if not nums or not all(1 <= n <= 7 for n in nums):
            await self._error(interaction, "edit.recurrence.invalid_weekdays")
            return
        weekdays = sorted({n - 1 for n in nums})
        await self._apply(interaction, {"type": "specific_weekdays", "weekdays": weekdays})


class RecurrenceMonthDaysModal(_RecurrenceModal):
    def __init__(self, user_id, guild_id, channel_id, db_id, lang, prop):
        super().__init__(user_id, guild_id, channel_id, db_id, lang, prop,
                         title=t("edit.recurrence.opt.specific_month_days", lang),
                         field_label=t("edit.recurrence.field.month_days", lang),
                         placeholder="1,15")

    async def on_submit(self, interaction):
        nums = _parse_int_list(self.value_input.value.strip())
        if not nums or not all(1 <= n <= 31 for n in nums):
            await self._error(interaction, "edit.recurrence.invalid_month_days")
            return
        await self._apply(interaction, {"type": "specific_month_days", "month_days": sorted(set(nums))})


async def start_dm_edit_session(interaction, guild_id, channel_id, db_id, lang,
                               target=None):
    """Open (or reclaim) a view-based DM edit session for this event.

    The caller must have already deferred the interaction ephemerally; this
    replies via followup.

    target: an EditTarget instance (defaults to _EVENT_TARGET when None).
    """
    if target is None:
        target = _EVENT_TARGET
    user = interaction.user
    existing = _active_edit_sessions.get(user.id)
    if existing is not None:
        if time.monotonic() - existing.get("last_activity", 0) < SESSION_STALE_AFTER_SECONDS:
            await interaction.followup.send(t("edit.active_session", lang), ephemeral=True)
            return
        await _force_close_stale_session(user.id)

    try:
        dm = await user.create_dm()
    except discord.Forbidden:
        await interaction.followup.send(t("edit.dm_blocked", lang), ephemeral=True)
        return

    session = {
        "guild_id": guild_id, "channel_id": channel_id, "db_id": db_id,
        "lang": lang, "dm_message": None, "active_view": None,
        "last_activity": time.monotonic(),
        "target": target,
    }
    _active_edit_sessions[user.id] = session

    obj = target.load(guild_id, channel_id)
    if target.kind == "event" and not obj:
        _active_edit_sessions.pop(user.id, None)
        await interaction.followup.send(t("general.no_active_event", lang), ephemeral=True)
        return

    view = EditMainView(user.id, guild_id, channel_id, db_id, lang)
    try:
        dm_msg = await dm.send(embed=target.overview_embed(obj, lang), view=view)
    except discord.Forbidden:
        _active_edit_sessions.pop(user.id, None)
        await interaction.followup.send(t("edit.dm_blocked", lang), ephemeral=True)
        return
    session["dm_message"] = dm_msg
    session["active_view"] = view
    link = f"\n[{t('edit.dm_open_link', lang)}]({dm_msg.jump_url})"
    await interaction.followup.send(f"{t('edit.dm_sent', lang)}{link}", ephemeral=True)


# ---------------------------------------------------------------------------
# Delete confirmation
# ---------------------------------------------------------------------------

class DeleteConfirmationView(BaseConfirmationView):
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Delete Event")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("event.delete_button", lang), style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)

        lang = get_guild_language(self.guild_id)
        event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await send_feedback(interaction, t("event.nothing_to_delete", lang))
            return

        event_name = event["name"]
        settings = get_guild_settings(self.guild_id) or DEFAULT_GUILD_SETTINGS
        caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0

        # 1. Write summary to log channel
        summary_embed = build_event_summary_embed(event, lang)
        log_ch = get_log_channel(self.guild_id)
        if log_ch:
            try:
                await log_ch.send(embed=summary_embed)
            except Exception as e:
                logger.error(f"Could not send summary to log: {e}")

        await send_to_log_channel(
            t("log.event_deleted", lang, user=interaction.user.name, name=event_name),
            guild=interaction.guild)

        # 2. Delete the event embed message and ping messages from channel
        channel = bot.get_channel(self.channel_id) or await bot.fetch_channel(self.channel_id)
        await _delete_event_messages(channel, event)

        # 3. Soft-delete in DB
        delete_event(db_id)

        await send_feedback(interaction, t("event.deleted", lang, name=event_name))

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


def _build_open_confirm_embed(event, lang):
    """Confirmation embed shown before manually opening registration. When a ping will
    be sent (ping_on_open + targets configured), it lists the target roles/users — these
    render as mentions in the embed, which does NOT trigger an actual notification."""
    desc = t("reg.open_confirm", lang, name=event["name"])
    if event.get("ping_on_open", False):
        targets = _build_ping_text(event).strip()
        if targets:
            desc += "\n\n" + t("reg.open_confirm_ping", lang, targets=targets)
    return discord.Embed(
        title=t("reg.open_confirm_title", lang),
        description=desc,
        color=discord.Color.green())


class OpenConfirmationView(BaseConfirmationView):
    """Confirm/Cancel before manually opening registration (which may ping roles)."""
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Open Registration")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("reg.open_button", lang), style=discord.ButtonStyle.success)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        gid, cid = self.guild_id, self.channel_id
        lang = get_guild_language(gid)

        lock = _get_guild_lock(gid)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(gid, cid)
            if not event:
                await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
                return
            if event.get("registration_open", False):
                await send_feedback(interaction, t("reg.already_open", lang), ephemeral=True)
                return
            event["registration_open"] = True
            event["is_closed"] = False
            save_event(db_id, event, user_assignments)

        await send_feedback(interaction, t("reg.manually_opened", lang, name=event["name"]), ephemeral=True)

        # Replace the below-embed announcement: post the "now open" ping (if enabled),
        # which also deletes the now-stale early-access / countdown announcement.
        ch = bot.get_channel(cid)
        content = None
        if event.get("ping_on_open", False):
            ping_text = _build_ping_text(event)
            if ping_text:
                content = f"{ping_text}" + t("reg.opened_announcement", lang, name=event["name"])
        await _set_channel_announcement(
            ch, event, db_id, user_assignments, content=content,
            mentions=discord.AllowedMentions(roles=True, users=True))

        await update_event_displays(gid, cid)
        await send_to_log_channel(t("log.reg_opened", lang, name=event["name"]), guild=interaction.guild)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), embed=None, view=None)


class CloseConfirmationView(BaseConfirmationView):
    """Confirm/Cancel before manually closing registration."""
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Close Registration")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("reg.close_button", lang), style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        gid, cid = self.guild_id, self.channel_id
        lang = get_guild_language(gid)

        lock = _get_guild_lock(gid)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(gid, cid)
            if not event:
                await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
                return
            if is_player_mode(event):
                # Player mode has no early-access gate; the disabled buttons are the only thing
                # stopping joins, so a real close must lock it (unregister stays allowed).
                event["is_closed"] = True
                event["registration_open"] = False
            else:
                # Rep/caster mode: revert to the early-access / not-yet-open state instead of
                # hard-locking. Early-access roles keep registering (with their caps) and the
                # buttons stay enabled. Clear the scheduled open time so the loop doesn't
                # immediately auto-reopen; a *future* time set later via Edit Event still opens.
                event["registration_open"] = False
                event["registration_start_time"] = None
            save_event(db_id, event, user_assignments)

        await send_feedback(interaction, t("reg.manually_closed", lang, name=event["name"]), ephemeral=True)
        await send_to_log_channel(t("log.reg_closed", lang, user=interaction.user.name, name=event["name"]), guild=interaction.guild)
        await update_event_displays(gid, cid)

        # Delete the now-stale announcement below the embed; the embed already shows the status.
        ch = bot.get_channel(cid)
        await _set_channel_announcement(ch, event, db_id, user_assignments, content=None)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), embed=None, view=None)


class ConsolidateConfirmationView(BaseConfirmationView):
    """Confirm/Cancel before manually consolidating player-mode squads."""
    def __init__(self, guild_id, channel_id):
        super().__init__(title="Consolidate Squads")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("consolidate.confirm_button", lang), style=discord.ButtonStyle.primary)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)
        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return
        self._edit_in_place(interaction)
        await interaction.response.defer(ephemeral=True)
        gid, cid = self.guild_id, self.channel_id
        lang = get_guild_language(gid)

        lock = _get_guild_lock(gid)
        async with lock:
            event, user_assignments, db_id = _get_channel_event(gid, cid)
            if not event:
                await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
                return
            if not is_player_mode(event):
                await send_feedback(interaction, t("consolidate.player_mode_only", lang), ephemeral=True)
                return
            removed = consolidate_all_player_squads(event, user_assignments)
            if removed:
                save_event(db_id, event, user_assignments)

        if removed:
            await send_feedback(interaction, t("consolidate.done", lang, count=removed), ephemeral=True)
            await send_to_log_channel(
                t("log.squads_consolidated", lang, name=event["name"], count=removed),
                guild=interaction.guild)
            await update_event_displays(gid, cid)
        else:
            await send_feedback(interaction, t("consolidate.none", lang), ephemeral=True)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), embed=None, view=None)


# ############################# #
# POST-CREATION ROLE WIZARD     #
# ############################# #

class WizardSquadRolesView(BaseView):
    """Step 1/2: configure squad rep roles/users and early-access roles/users."""
    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Squad Roles")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        self.squad_rep_select = ui.RoleSelect(
            placeholder=t("wizard.squad_rep_title", lang),
            min_values=0, max_values=25, row=0)
        self.squad_rep_select.callback = self._squad_rep_selected
        self.add_item(self.squad_rep_select)

        self.community_rep_select = ui.RoleSelect(
            placeholder=t("wizard.community_rep_title", lang),
            min_values=0, max_values=25, row=1)
        self.community_rep_select.callback = self._community_rep_selected
        self.add_item(self.community_rep_select)

        # The "notify when registration opens" question only makes sense when
        # registration isn't already open at creation; otherwise there's no
        # open moment to announce, so we skip it (ping_on_open stays False).
        self.ping_select = None
        if not event.get("registration_open", False):
            self.ping_select = ui.Select(
                placeholder=t("wizard.ping_select_title", lang),
                options=[
                    discord.SelectOption(label=t("wizard.ping_no", lang), value="no", default=True),
                    discord.SelectOption(label=t("wizard.ping_yes", lang), value="yes"),
                ],
                min_values=1, max_values=1, row=2)
            self.ping_select.callback = self._ping_selected
            self.add_item(self.ping_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=3)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=3)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._squad_rep_roles = []
        self._community_rep_roles = []
        self._ping_on_open = False

    async def _squad_rep_selected(self, interaction):
        self._squad_rep_roles = [r.id for r in self.squad_rep_select.values]
        await interaction.response.defer()

    async def _community_rep_selected(self, interaction):
        self._community_rep_roles = [r.id for r in self.community_rep_select.values]
        await interaction.response.defer()

    async def _ping_selected(self, interaction):
        self._ping_on_open = self.ping_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._squad_rep_roles:
            self.event["squad_rep_role_ids"] = self._squad_rep_roles
        if self._community_rep_roles:
            self.event["community_rep_role_ids"] = self._community_rep_roles
        self.event["ping_on_open"] = self._ping_on_open

    async def _advance_after_squad_roles(self, interaction):
        # When a role gate is configured, offer the optional per-type slot limits;
        # otherwise jump straight to the next wizard step.
        if _gate_configured(self.event):
            lang = get_guild_language(self.guild_id)
            next_view = WizardSlotLimitsView(self.guild_id, self.channel_id, self.event,
                                             self.user_assignments, self.settings, self.interaction_user)
            await interaction.response.edit_message(
                content=f"**{t('wizard.slot_limits_title', lang)}**\n{t('wizard.slot_limits_desc', lang)}",
                view=next_view)
            return
        await _advance_to_post_roles(interaction, self.guild_id, self.channel_id, self.event,
                                     self.user_assignments, self.settings, self.interaction_user)

    async def _continue(self, interaction):
        self._save_selections()
        await self._advance_after_squad_roles(interaction)

    async def _skip(self, interaction):
        await self._advance_after_squad_roles(interaction)


def _gate_configured(event) -> bool:
    """True when at least one register-type role is set (caps are meaningful then)."""
    return bool(event.get("squad_rep_role_ids") or event.get("community_rep_role_ids"))


async def _advance_to_post_roles(interaction, guild_id, channel_id, event,
                                 user_assignments, settings, interaction_user):
    """Transition from the role/slot-limit steps to caster roles (rep) or timing (player)."""
    lang = get_guild_language(guild_id)
    if is_player_mode(event):
        next_view = WizardTimingView(guild_id, channel_id, event, user_assignments,
                                     settings, interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.timing_title', lang)}**\n{t('wizard.timing_desc', lang)}",
            view=next_view)
        return
    next_view = WizardCasterRolesView(guild_id, channel_id, event, user_assignments,
                                      settings, interaction_user)
    await interaction.response.edit_message(
        content=f"**{t('wizard.caster_roles_title', lang)}**\n{t('wizard.caster_roles_desc', lang)}",
        view=next_view)


class WizardSlotLimitsView(BaseView):
    """Optional per-register-type limits, shown only when a role gate is configured.

    Rep mode shows four dropdowns (two seat-% caps + two squad caps); player mode
    shows only the two % caps (squad limits don't apply; #12 forced to 1). Option
    labels carry their register-type prefix so a chosen value stays self-explanatory.
    """

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Slot Limits")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)
        rep_mode = not is_player_mode(event)

        self._early_pct = event.get("community_rep_cap_percent")
        self._reg_squads = event.get("max_squads_per_user", 1) or 1
        self._early_squads = event.get("early_access_squads_per_role")

        self.early_pct_select = ui.Select(
            placeholder=t("wizard.cap_early_pct_title", lang),
            options=_capped_options("limit.prefix.early", _PERCENT_PRESETS,
                                    _format_percent_value, lang, self._early_pct),
            min_values=1, max_values=1, row=0)
        self.early_pct_select.callback = self._early_pct_selected
        self.add_item(self.early_pct_select)

        btn_row = 1
        if rep_mode:
            self.early_squads_select = ui.Select(
                placeholder=t("wizard.cap_early_squads_title", lang),
                options=_capped_options("limit.prefix.early", _COUNT_PRESETS,
                                        _format_squads_per_role, lang, self._early_squads),
                min_values=1, max_values=1, row=1)
            self.early_squads_select.callback = self._early_squads_selected
            self.add_item(self.early_squads_select)

            self.reg_squads_select = ui.Select(
                placeholder=t("wizard.cap_regular_squads_title", lang),
                options=_capped_options("limit.prefix.regular", _REGULAR_SQUAD_PRESETS,
                                        _format_squads_per_user, lang, self._reg_squads),
                min_values=1, max_values=1, row=2)
            self.reg_squads_select.callback = self._reg_squads_selected
            self.add_item(self.reg_squads_select)
            btn_row = 3

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=btn_row)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)
        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=btn_row)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

    @staticmethod
    def _value(raw):
        return None if raw == "none" else int(raw)

    async def _early_pct_selected(self, interaction):
        self._early_pct = self._value(self.early_pct_select.values[0])
        await interaction.response.defer()

    async def _reg_squads_selected(self, interaction):
        self._reg_squads = int(self.reg_squads_select.values[0])
        await interaction.response.defer()

    async def _early_squads_selected(self, interaction):
        self._early_squads = self._value(self.early_squads_select.values[0])
        await interaction.response.defer()

    def _save_selections(self):
        self.event["community_rep_cap_percent"] = self._early_pct
        if not is_player_mode(self.event):
            self.event["max_squads_per_user"] = self._reg_squads
            self.event["early_access_squads_per_role"] = self._early_squads

    async def _continue(self, interaction):
        self._save_selections()
        await _advance_to_post_roles(interaction, self.guild_id, self.channel_id, self.event,
                                     self.user_assignments, self.settings, self.interaction_user)

    async def _skip(self, interaction):
        await _advance_to_post_roles(interaction, self.guild_id, self.channel_id, self.event,
                                     self.user_assignments, self.settings, self.interaction_user)


def _capped_options(prefix_key, presets, value_fmt, lang, current):
    """SelectOptions labeled '<type>: <value>' so the choice stays self-explanatory.

    A `None` preset becomes the option value "none" (→ stored None / no limit).
    """
    prefix = t(prefix_key, lang)
    opts = []
    for v in presets:
        opts.append(discord.SelectOption(
            label=f"{prefix}: {value_fmt(v, lang)}"[:100],
            value="none" if v is None else str(v),
            default=(v == current)))
    return opts


class WizardCasterRolesView(BaseView):
    """Step 2/2: configure caster roles/users and early-access roles/users."""
    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Caster Roles")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        self.caster_role_select = ui.MentionableSelect(
            placeholder=t("wizard.caster_role_title", lang),
            min_values=0, max_values=25, row=0)
        self.caster_role_select.callback = self._caster_role_selected
        self.add_item(self.caster_role_select)

        self.caster_early_select = ui.MentionableSelect(
            placeholder=t("wizard.caster_early_title", lang),
            min_values=0, max_values=25, row=1)
        self.caster_early_select.callback = self._caster_early_selected
        self.add_item(self.caster_early_select)

        ping_default = event.get("ping_on_open", False)
        self.ping_select = ui.Select(
            placeholder=t("wizard.ping_select_title", lang),
            options=[
                discord.SelectOption(label=t("wizard.ping_no", lang), value="no", default=not ping_default),
                discord.SelectOption(label=t("wizard.ping_yes", lang), value="yes", default=ping_default),
            ],
            min_values=1, max_values=1, row=2)
        self.ping_select.callback = self._ping_selected
        self.add_item(self.ping_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=3)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=3)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._caster_roles = []
        self._caster_users = []
        self._caster_early_roles = []
        self._caster_early_users = []
        self._ping_on_open = ping_default

    async def _caster_role_selected(self, interaction):
        self._caster_roles = [v.id for v in self.caster_role_select.values if isinstance(v, discord.Role)]
        self._caster_users = [str(v.id) for v in self.caster_role_select.values if isinstance(v, (discord.Member, discord.User))]
        await interaction.response.defer()

    async def _caster_early_selected(self, interaction):
        self._caster_early_roles = [v.id for v in self.caster_early_select.values if isinstance(v, discord.Role)]
        self._caster_early_users = [str(v.id) for v in self.caster_early_select.values if isinstance(v, (discord.Member, discord.User))]
        await interaction.response.defer()

    async def _ping_selected(self, interaction):
        self._ping_on_open = self.ping_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._caster_roles or self._caster_users:
            self.event["caster_role_ids"] = self._caster_roles
            self.event["caster_user_ids"] = self._caster_users
        if self._caster_early_roles or self._caster_early_users:
            self.event["caster_community_role_ids"] = self._caster_early_roles
            self.event["caster_community_user_ids"] = self._caster_early_users
        self.event["ping_on_open"] = self._ping_on_open

    async def _continue(self, interaction):
        self._save_selections()
        lang = get_guild_language(self.guild_id)
        next_view = WizardTimingView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                     self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.timing_title', lang)}**\n{t('wizard.timing_desc', lang)}",
            view=next_view)

    async def _skip(self, interaction):
        lang = get_guild_language(self.guild_id)
        next_view = WizardTimingView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                     self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.timing_title', lang)}**\n{t('wizard.timing_desc', lang)}",
            view=next_view)


class WizardTimingView(BaseView):
    """Step 3: configure event reminder and registration countdown."""
    REMINDER_OPTIONS = [0, 15, 30, 60, 120, 240, 480, 1440]
    COUNTDOWN_OPTIONS = [0, 60, 300, 600, 900, 1800, 3600, 7200, 14400, 28800]  # seconds

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Timing")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        self._has_countdown = event.get("registration_start_time") is not None
        lang = get_guild_language(guild_id)

        # Row 0: Reminder dropdown
        reminder_options = []
        for minutes in self.REMINDER_OPTIONS:
            if minutes == 0:
                label = t("wizard.reminder_none", lang)
            else:
                label = t(f"wizard.reminder_{minutes}", lang)
            reminder_options.append(discord.SelectOption(label=label, value=str(minutes), default=(minutes == 0)))

        self.reminder_select = ui.Select(placeholder=t("wizard.reminder_placeholder", lang),
                                         options=reminder_options, min_values=1, max_values=1, row=0)
        self.reminder_select.callback = self._reminder_selected
        self.add_item(self.reminder_select)

        # Row 1: Countdown dropdown (only when registration is scheduled)
        btn_row = 1
        if self._has_countdown:
            countdown_options = []
            for seconds in self.COUNTDOWN_OPTIONS:
                if seconds == 0:
                    label = t("wizard.countdown_none", lang)
                else:
                    label = t(f"wizard.countdown_{seconds}s", lang)
                countdown_options.append(discord.SelectOption(label=label, value=str(seconds), default=(seconds == 0)))

            self.countdown_select = ui.Select(placeholder=t("wizard.countdown_placeholder", lang),
                                              options=countdown_options, min_values=1, max_values=1, row=1)
            self.countdown_select.callback = self._countdown_selected
            self.add_item(self.countdown_select)
            btn_row = 2

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=btn_row)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=btn_row)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._selected_minutes = None
        self._selected_countdown = None

    async def _reminder_selected(self, interaction):
        self._selected_minutes = int(self.reminder_select.values[0])
        await interaction.response.defer()

    async def _countdown_selected(self, interaction):
        self._selected_countdown = int(self.countdown_select.values[0])
        await interaction.response.defer()

    def _save_selections(self):
        if self._selected_minutes is not None and self._selected_minutes > 0:
            self.event["event_reminder_minutes"] = self._selected_minutes
        if self._selected_countdown is not None:
            self.event["countdown_seconds"] = self._selected_countdown if self._selected_countdown > 0 else 0

    async def _advance_after_timing(self, interaction):
        lang = get_guild_language(self.guild_id)
        if is_player_mode(self.event):
            # Player mode: one user per registration, no squad-limit step — but
            # offer the in-squad-role toggle (player-mode analogue of playstyle).
            self.event["max_squads_per_user"] = 1
            next_view = WizardPlayerRolesView(
                self.guild_id, self.channel_id, self.event, self.user_assignments,
                self.settings, self.interaction_user)
            content = f"**{t('wizard.player_roles_step_title', lang)}**\n{t('wizard.player_roles_step_desc', lang)}"
            await interaction.response.edit_message(content=content, embed=None, view=next_view)
            return
        default_limit = self.event.get("max_squads_per_user", 1)
        next_view = WizardSquadLimitView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                         self.settings, self.interaction_user)
        if _gate_configured(self.event):
            # The per-user squad limit was already set in the Slot Limits step;
            # this step now only configures playstyle.
            content = f"**{t('wizard.playstyle_step_title', lang)}**\n{t('wizard.playstyle_step_desc', lang)}"
        else:
            content = f"**{t('wizard.squad_limit_title', lang)}**\n{t('wizard.squad_limit_desc', lang, default=default_limit)}"
        await interaction.response.edit_message(content=content, embed=None, view=next_view)

    async def _continue(self, interaction):
        self._save_selections()
        await self._advance_after_timing(interaction)

    async def _skip(self, interaction):
        await self._advance_after_timing(interaction)


class WizardSquadLimitView(BaseView):
    """Step 4: configure max squads per user and squad-registration options."""

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Squad Limit")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        # When a role gate is configured, the per-user squad limit (#12) is set in
        # the Slot Limits step instead, so this step only configures playstyle.
        self.limit_select = None
        play_row = 0
        if not _gate_configured(event):
            current_default = event.get("max_squads_per_user", 1)
            options = []
            for n in range(1, 21):
                label = f"{n} Squad" if n == 1 else f"{n} Squads"
                options.append(discord.SelectOption(label=label, value=str(n), default=(n == current_default)))
            self.limit_select = ui.Select(placeholder=t("wizard.squad_limit_placeholder", lang),
                                          options=options, min_values=1, max_values=1, row=0)
            self.limit_select.callback = self._limit_selected
            self.add_item(self.limit_select)
            play_row = 1

        playstyle_default = bool(event.get("playstyle_enabled", True))
        self.playstyle_select = ui.Select(
            placeholder=t("wizard.playstyle_select_placeholder", lang),
            options=[
                discord.SelectOption(label=t("wizard.playstyle_enabled", lang),
                                     value="yes", default=playstyle_default),
                discord.SelectOption(label=t("wizard.playstyle_disabled", lang),
                                     value="no", default=not playstyle_default),
            ],
            min_values=1, max_values=1, row=play_row)
        self.playstyle_select.callback = self._playstyle_selected
        self.add_item(self.playstyle_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=2)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=2)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._selected_limit = None
        self._selected_playstyle_enabled = None

    async def _limit_selected(self, interaction):
        self._selected_limit = int(self.limit_select.values[0])
        await interaction.response.defer()

    async def _playstyle_selected(self, interaction):
        self._selected_playstyle_enabled = self.playstyle_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._selected_limit is not None:
            self.event["max_squads_per_user"] = self._selected_limit
        if self._selected_playstyle_enabled is not None:
            self.event["playstyle_enabled"] = self._selected_playstyle_enabled

    async def _continue(self, interaction):
        self._save_selections()
        await _advance_to_dont_waste_or_confirmation(
            interaction, self.guild_id, self.channel_id, self.event,
            self.user_assignments, self.settings, self.interaction_user)

    async def _skip(self, interaction):
        await _advance_to_dont_waste_or_confirmation(
            interaction, self.guild_id, self.channel_id, self.event,
            self.user_assignments, self.settings, self.interaction_user)


class WizardPlayerRolesView(BaseView):
    """Player-mode step: enable or disable the in-squad role selection (Squad
    Leader, Medic, Pilot, …). Player-mode analogue of the rep-mode playstyle
    toggle. When disabled, players can't pick a role and roles aren't shown."""

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Player Roles")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        roles_default = bool(event.get("player_roles_enabled", True))
        self.roles_select = ui.Select(
            placeholder=t("wizard.player_roles_select_placeholder", lang),
            options=[
                discord.SelectOption(label=t("wizard.player_roles_enabled", lang),
                                     value="yes", default=roles_default),
                discord.SelectOption(label=t("wizard.player_roles_disabled", lang),
                                     value="no", default=not roles_default),
            ],
            min_values=1, max_values=1, row=0)
        self.roles_select.callback = self._roles_selected
        self.add_item(self.roles_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=1)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=1)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._selected_roles_enabled = None

    async def _roles_selected(self, interaction):
        self._selected_roles_enabled = self.roles_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._selected_roles_enabled is not None:
            self.event["player_roles_enabled"] = self._selected_roles_enabled

    async def _to_confirmation(self, interaction):
        self._save_selections()
        await _advance_to_dont_waste_or_confirmation(
            interaction, self.guild_id, self.channel_id, self.event,
            self.user_assignments, self.settings, self.interaction_user)

    async def _continue(self, interaction):
        await self._to_confirmation(interaction)

    async def _skip(self, interaction):
        await self._to_confirmation(interaction)


async def _advance_to_dont_waste_or_confirmation(interaction, guild_id, channel_id, event,
                                                 user_assignments, settings, interaction_user):
    """Show the don't-waste-slots step, or go straight to confirmation when the
    unused pool can't fit an oversized pair anyway."""
    unused = infantry_unused_pool(event)
    if event.get("mode", "rep") != "player" and unused >= 2:
        lang = get_guild_language(guild_id)
        content = (f"**{t('wizard.dont_waste_step_title', lang)}**\n"
                   f"{t('wizard.dont_waste_step_desc', lang, unused=unused)}")
        view = WizardDontWasteSlotsView(guild_id, channel_id, event, user_assignments,
                                        settings, interaction_user)
        await interaction.response.edit_message(content=content, embed=None, view=view)
        return
    embed = _build_confirmation_embed(event, guild_id)
    confirm_view = WizardConfirmationView(guild_id, channel_id, event, user_assignments,
                                          settings, interaction_user)
    await interaction.response.edit_message(content=None, embed=embed, view=confirm_view)


class WizardDontWasteSlotsView(BaseView):
    """Step: enable or disable the "don't waste slots" mode, which offers the
    unused infantry seats as oversized squads in mirrored pairs."""

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Dont Waste Slots")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        enabled_default = bool(event.get("dont_waste_slots", False))
        self.mode_select = ui.Select(
            placeholder=t("wizard.dont_waste_select_placeholder", lang),
            options=[
                discord.SelectOption(label=t("wizard.dont_waste_enabled", lang),
                                     value="yes", default=enabled_default),
                discord.SelectOption(label=t("wizard.dont_waste_disabled", lang),
                                     value="no", default=not enabled_default),
            ],
            min_values=1, max_values=1, row=0)
        self.mode_select.callback = self._mode_selected
        self.add_item(self.mode_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=1)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=1)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._selected_enabled = None

    async def _mode_selected(self, interaction):
        self._selected_enabled = self.mode_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._selected_enabled is not None:
            self.event["dont_waste_slots"] = self._selected_enabled

    async def _to_confirmation(self, interaction):
        self._save_selections()
        embed = _build_confirmation_embed(self.event, self.guild_id)
        confirm_view = WizardConfirmationView(
            self.guild_id, self.channel_id, self.event, self.user_assignments,
            self.settings, self.interaction_user)
        await interaction.response.edit_message(content=None, embed=embed, view=confirm_view)

    async def _continue(self, interaction):
        await self._to_confirmation(interaction)

    async def _skip(self, interaction):
        await self._to_confirmation(interaction)


# ############################# #
# WIZARD CONFIRMATION            #
# ############################# #

def _build_confirmation_embed(event: dict, guild_id: int) -> discord.Embed:
    """Build a pre-creation summary embed for the confirmation step."""
    lang = get_guild_language(guild_id)
    embed = discord.Embed(
        title=t("wizard.confirmation_title", lang),
        color=discord.Color.gold(),
    )

    embed.add_field(name=t("wizard.summary_name", lang), value=event["name"], inline=True)

    date_str = event["date"]
    time_str = event.get("time", "20:00")
    try:
        event_dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        event_ts = int(event_dt.timestamp())
        embed.add_field(name=t("wizard.summary_datetime", lang),
                        value=f"<t:{event_ts}:f>", inline=True)
    except ValueError:
        embed.add_field(name=t("wizard.summary_datetime", lang),
                        value=f"{date_str} {time_str}", inline=True)

    desc = event.get("description")
    if desc:
        embed.add_field(name=t("wizard.summary_description", lang), value=desc, inline=False)

    reg_open = event.get("registration_open", False)
    reg_start_time = event.get("registration_start_time")
    if reg_open:
        reg_val = t("wizard.summary_reg_immediate", lang)
    elif reg_start_time and isinstance(reg_start_time, datetime):
        ts = int(reg_start_time.timestamp())
        reg_val = t("wizard.summary_reg_at", lang, ts=ts)
    else:
        reg_val = t("wizard.summary_reg_immediate", lang)
    embed.add_field(name=t("wizard.summary_registration", lang), value=reg_val, inline=True)

    reminder_minutes = event.get("event_reminder_minutes")
    if reminder_minutes and reminder_minutes > 0:
        reminder_val = t(f"wizard.reminder_{reminder_minutes}", lang)
    else:
        reminder_val = t("wizard.reminder_none", lang)
    embed.add_field(name=t("wizard.summary_reminder", lang), value=reminder_val, inline=True)

    ping_val = t("wizard.summary_ping_yes", lang) if event.get("ping_on_open", False) else t("wizard.summary_ping_no", lang)
    embed.add_field(name=t("wizard.summary_ping", lang), value=ping_val, inline=True)

    if event.get("mode", "rep") != "player":
        playstyle_val = (t("wizard.summary_playstyle_yes", lang)
                         if event.get("playstyle_enabled", True)
                         else t("wizard.summary_playstyle_no", lang))
        embed.add_field(name=t("wizard.summary_playstyle", lang), value=playstyle_val, inline=True)
    else:
        roles_val = (t("wizard.summary_player_roles_yes", lang)
                     if event.get("player_roles_enabled", True)
                     else t("wizard.summary_player_roles_no", lang))
        embed.add_field(name=t("wizard.summary_player_roles", lang), value=roles_val, inline=True)

    if event.get("mode", "rep") != "player" and infantry_unused_pool(event) >= 2:
        dw_val = (t("wizard.summary_dont_waste_yes", lang)
                  if event.get("dont_waste_slots", False)
                  else t("wizard.summary_dont_waste_no", lang))
        embed.add_field(name=t("wizard.summary_dont_waste", lang), value=dw_val, inline=True)

    if event.get("registration_start_time") is not None:
        cd_seconds = event.get("countdown_seconds")
        if cd_seconds is not None and cd_seconds > 0:
            countdown_val = t(f"wizard.countdown_{cd_seconds}s", lang)
        elif cd_seconds == 0:
            countdown_val = t("wizard.countdown_none", lang)
        else:
            countdown_val = t("wizard.countdown_none", lang)
        embed.add_field(name=t("wizard.summary_countdown", lang), value=countdown_val, inline=True)

    # Recurrence / duration / (recreate-after, only for recurring events)
    embed.add_field(name=t("wizard.summary_recurrence", lang),
                    value=_format_recurrence(event.get("recurrence"), lang, event=event), inline=True)
    embed.add_field(name=t("wizard.summary_duration", lang),
                    value=_format_duration_value(event.get("duration_minutes"), lang), inline=True)
    if (event.get("recurrence") or {}).get("type", "never") != "never":
        embed.add_field(name=t("wizard.summary_spawn_offset", lang),
                        value=_format_spawn_offset_value(event.get("spawn_offset_minutes"), lang), inline=True)

    # Calculate unused slots for confirmation summary
    _cap = event.get("server_max_players", 100)
    _max_casters = event.get("max_caster_slots", 2)
    _inf_size = event.get("infantry_squad_size", 6)
    _veh_size = event.get("vehicle_squad_size", 2)
    _heli_size = event.get("heli_squad_size", 1)
    _max_veh = event.get("max_vehicle_squads", 6)
    _max_heli = event.get("max_heli_squads", 2)
    _veh_slots = _max_veh * _veh_size
    _heli_slots = _max_heli * _heli_size
    _inf_pool = _cap - _max_casters - _veh_slots - _heli_slots
    _max_inf = _inf_pool // _inf_size if _inf_size > 0 else 0
    _unused = _cap - _max_casters - (_max_inf * _inf_size) - _veh_slots - _heli_slots
    _unused_label = "Ungenutzt" if lang == "de" else "Unused"

    server_info = (
        f"**{t('settings.server_max_players', lang)}:** {_cap}\n"
        f"**{t('settings.infantry_squad_size', lang)}:** {_inf_size}\n"
        f"**{t('settings.vehicle_squad_size', lang)}:** {_veh_size}\n"
        f"**{t('settings.heli_squad_size', lang)}:** {_heli_size}\n"
        f"**{t('settings.max_vehicle_squads', lang)}:** {_max_veh}\n"
        f"**{t('settings.max_heli_squads', lang)}:** {_max_heli}\n"
        f"**{t('settings.max_caster_slots', lang)}:** {_max_casters}\n"
        f"**{t('settings.max_squads_per_user', lang)}:** {event.get('max_squads_per_user', '?')}"
    )
    if not dont_waste_slots_active(event):
        server_info += f"\n**{_unused_label}:** {_unused}"
    embed.add_field(name=t("wizard.summary_server", lang), value=server_info, inline=False)

    none_text = t("wizard.summary_none", lang)

    def _fmt(role_ids, user_ids):
        parts = [f"<@&{rid}>" for rid in role_ids] + [f"<@{uid}>" for uid in user_ids]
        return ", ".join(parts) if parts else none_text

    roles_info = (
        f"**{t('wizard.summary_squad_roles', lang)}:** "
        f"{_fmt(event.get('squad_rep_role_ids', []), event.get('squad_rep_user_ids', []))}\n"
        f"**{t('wizard.summary_community_roles', lang)}:** "
        f"{_fmt(event.get('community_rep_role_ids', []), event.get('community_rep_user_ids', []))}\n"
        f"**{t('wizard.summary_caster_roles', lang)}:** "
        f"{_fmt(event.get('caster_role_ids', []), event.get('caster_user_ids', []))}\n"
        f"**{t('wizard.summary_caster_early', lang)}:** "
        f"{_fmt(event.get('caster_community_role_ids', []), event.get('caster_community_user_ids', []))}"
    )
    embed.add_field(name=t("wizard.summary_roles", lang), value=roles_info, inline=False)

    # Slot limits — only relevant once early-access roles are configured.
    if event.get("community_rep_role_ids"):
        limit_lines = [
            f"**{t('wizard.summary_early_pct_cap', lang)}:** "
            f"{_format_percent_value(event.get('community_rep_cap_percent'), lang)}"
        ]
        if event.get("mode", "rep") != "player":
            limit_lines.append(
                f"**{t('wizard.summary_early_squad_cap', lang)}:** "
                f"{_format_count_value(event.get('early_access_squads_per_role'), lang)}")
        embed.add_field(name=t("wizard.summary_slot_limits", lang),
                        value="\n".join(limit_lines), inline=False)

    return embed


class WizardConfirmationView(BaseView):
    """Final step: show event summary and Confirm/Cancel buttons."""
    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Event Confirmation")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        confirm_btn = ui.Button(label=t("general.confirm", lang), style=discord.ButtonStyle.success, row=0)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

        cancel_btn = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary, row=0)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction):
        if self.check_response(interaction):
            return

        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("wizard.creating", lang), embed=None, view=None)

        if channel_has_active_event(self.guild_id, self.channel_id):
            await interaction.edit_original_response(content=t("event.already_exists_in_channel", lang))
            return

        # Send announcement embed to channel first (no DB yet — avoids orphaned records)
        channel = bot.get_channel(self.channel_id) or await bot.fetch_channel(self.channel_id)
        caster_enabled = self.settings.get("caster_registration_enabled", True) and self.event.get("max_caster_slots", 2) > 0
        embed = format_event_details(self.event, lang, caster_enabled)
        view = EventActionView(lang, mode=self.event.get("mode", "rep"))
        try:
            msg = await channel.send(embed=embed, view=view)
            self.event["event_message_id"] = msg.id
            self.event["announcement_sent"] = True
        except discord.Forbidden:
            logger.error(f"Missing permissions to send in channel {self.channel_id}")
            await interaction.edit_original_response(
                content=t("general.error", lang, error="Bot lacks permission to send messages in this channel."))
            return

        # Send ping message if enabled and registration opens immediately
        if self.event.get("ping_on_open", False) and self.event.get("registration_open", False):
            ping_text = _build_ping_text(self.event)
            if ping_text:
                try:
                    ping_msg = await channel.send(
                        content=f"{ping_text}" + t("reg.opened_announcement", lang, name=self.event["name"]),
                        allowed_mentions=discord.AllowedMentions(roles=True, users=True))
                    self.event["announcement_message_id"] = ping_msg.id
                except discord.Forbidden:
                    pass

        # Ping community reps about early access (only if regular registration isn't already open)
        if (self.event.get("ping_on_open", False)
                and not self.event.get("registration_open", False)
                and (self.event.get("community_rep_role_ids") or self.event.get("community_rep_user_ids"))):
            mentions = [f"<@&{rid}>" for rid in self.event.get("community_rep_role_ids", [])]
            mentions += [f"<@{uid}>" for uid in self.event.get("community_rep_user_ids", [])]
            early_ping_text = " ".join(mentions) + " "
            try:
                ping_msg = await channel.send(
                    content=f"{early_ping_text}" + t("reg.early_access_announcement", lang, name=self.event["name"]),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True))
                self.event["announcement_message_id"] = ping_msg.id
            except discord.Forbidden:
                pass

        # Persist to DB only after successful channel send
        db_id = create_event(self.guild_id, self.channel_id, self.event)
        save_event(db_id, self.event, self.user_assignments)

        # Build reg info for logging
        reg_open = self.event.get("registration_open", False)
        reg_start_time = self.event.get("registration_start_time")
        reg_info = t("reg.opened_now", lang) if reg_open else ""
        if reg_start_time:
            ts = int(reg_start_time.timestamp())
            reg_info = t("reg.opens_at_info", lang, ts=ts)

        await send_to_log_channel(
            t("log.event_created", lang,
              name=self.event["name"], date=self.event["date"], time=self.event["time"],
              user=self.interaction_user.name, reg_info=reg_info),
            guild_id=self.guild_id)

        # Also post the full approved settings (the embed the creator confirmed)
        # to the log channel for traceability. Best-effort: never break creation.
        settings_embed = _build_confirmation_embed(self.event, self.guild_id)
        settings_embed.title = t("log.event_created_settings_title", lang, name=self.event["name"])
        settings_embed.color = discord.Color.blue()
        log_ch = get_log_channel(self.guild_id)
        if log_ch:
            try:
                await log_ch.send(embed=settings_embed)
            except Exception as e:
                logger.error(f"Could not send event settings to log: {e}")

        await interaction.edit_original_response(
            content=t("event.created", lang, name=self.event["name"], reg_info=reg_info))

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("wizard.event_cancelled", lang), embed=None, view=None)


# ############################# #
# EVENT CREATION                #
# ############################# #

class _EventConfigBridgeView(ui.View):
    """Bridge between first modal and server config modal — single Continue button."""
    def __init__(self, guild_id, channel_id, settings, parsed, author):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.settings = settings
        self.parsed = parsed
        self.author = author
        lang = get_guild_language(guild_id)
        btn = ui.Button(label=t("event.config_continue", lang), style=discord.ButtonStyle.success)
        btn.callback = self._open_config
        self.add_item(btn)

    async def _open_config(self, interaction: discord.Interaction):
        if hasattr(self, "_responded") and self._responded:
            return
        self._responded = True
        modal = EventServerConfigModal(
            self.guild_id, self.channel_id, self.settings, self.parsed, self.author)
        await interaction.response.send_modal(modal)


class EventServerConfigModal(ui.Modal):
    """Second modal: server/squad configuration, pre-filled from guild settings."""
    def __init__(self, guild_id, channel_id, settings, parsed, author):
        lang = get_guild_language(guild_id)
        super().__init__(title=t("event.config_title", lang))
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.settings = settings
        self.parsed = parsed
        self.author = author

        mode = parsed.get("mode", "rep")
        seat_label_key = "event.seats_label" if mode == "player" else "event.server_max_label"
        self.server_max = ui.TextInput(
            label=t(seat_label_key, lang),
            default=str(settings.get("server_max_players", 100)),
            required=True, max_length=5)
        self.add_item(self.server_max)

        # Caster slot field only in rep mode — player mode has no casters.
        if mode != "player":
            self.max_casters = ui.TextInput(
                label=t("event.max_casters_label", lang),
                default=str(settings.get("max_caster_slots", 2)),
                required=True, max_length=3)
            self.add_item(self.max_casters)
        else:
            self.max_casters = None

        inf = settings.get("infantry_squad_size", 6)
        veh = settings.get("vehicle_squad_size", 2)
        heli = settings.get("heli_squad_size", 1)
        self.squad_sizes = ui.TextInput(
            label=t("event.squad_sizes_label", lang),
            default=f"{inf} / {veh} / {heli}",
            placeholder="6 / 2 / 1",
            required=True, max_length=20)
        self.add_item(self.squad_sizes)

        self.max_vehicles = ui.TextInput(
            label=t("event.max_vehicles_label", lang),
            default=str(settings.get("max_vehicle_squads", 6)),
            required=True, max_length=3)
        self.add_item(self.max_vehicles)

        self.max_helis = ui.TextInput(
            label=t("event.max_helis_label", lang),
            default=str(settings.get("max_heli_squads", 2)),
            required=True, max_length=3)
        self.add_item(self.max_helis)

    async def on_submit(self, interaction: discord.Interaction):
        lang = get_guild_language(self.guild_id)

        # Parse and validate all fields
        mode = self.parsed.get("mode", "rep")
        try:
            server_max = int(self.server_max.value.strip())
            max_casters = 0 if mode == "player" else int(self.max_casters.value.strip())
            max_veh = int(self.max_vehicles.value.strip())
            max_heli = int(self.max_helis.value.strip())
        except ValueError:
            await interaction.response.send_message(t("event.invalid_time", lang), ephemeral=True)
            return

        if max_veh < 0 or max_heli < 0:
            await interaction.response.send_message(t("event.invalid_time", lang), ephemeral=True)
            return

        # Parse combined squad sizes
        parts = self.squad_sizes.value.split("/")
        if len(parts) != 3:
            await interaction.response.send_message(t("event.invalid_squad_sizes", lang), ephemeral=True)
            return
        try:
            inf_size = int(parts[0].strip())
            veh_size = int(parts[1].strip())
            heli_size = int(parts[2].strip())
        except ValueError:
            await interaction.response.send_message(t("event.invalid_squad_sizes", lang), ephemeral=True)
            return
        if inf_size < 1 or veh_size < 1 or heli_size < 1:
            await interaction.response.send_message(t("event.invalid_squad_sizes", lang), ephemeral=True)
            return

        # Build event with overrides from this modal
        event = build_default_event(
            self.settings,
            name=self.parsed["name"],
            date=self.parsed["date"],
            time_str=self.parsed["time"],
            description=self.parsed["description"],
            registration_open=self.parsed["reg_open"],
            registration_start_time=self.parsed["reg_start_time"],
            server_max_players=server_max,
            max_caster_slots=max_casters,
            infantry_squad_size=inf_size,
            vehicle_squad_size=veh_size,
            heli_squad_size=heli_size,
            max_vehicle_squads=max_veh,
            max_heli_squads=max_heli,
            mode=mode,
        )

        # Launch wizard step 1
        wizard_view = WizardSquadRolesView(
            self.guild_id, self.channel_id, event, {},
            self.settings, self.author)
        wizard_msg = f"**{t('wizard.squad_roles_title', lang)}**\n{t('wizard.squad_roles_desc', lang)}"
        await interaction.response.send_message(wizard_msg, view=wizard_view, ephemeral=True)


class EventCreationModal(ui.Modal):
    def __init__(self, guild_id: int, channel_id: int, mode: str = "rep"):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.mode = mode if mode in ("rep", "player") else "rep"
        lang = get_guild_language(guild_id)
        super().__init__(title=t("event.create_title", lang))

        defaults = resolve_event_defaults()

        self.event_name = ui.TextInput(label=t("event.name_label", lang), required=True, max_length=100)
        self.add_item(self.event_name)
        self.event_date = ui.TextInput(label=t("event.date_label", lang), placeholder="TT.MM.JJJJ",
                                       default=defaults["date"] or None, required=True, max_length=10)
        self.add_item(self.event_date)
        self.event_time = ui.TextInput(label=t("event.time_label", lang), placeholder="HH:MM",
                                       default=defaults["time"] or None, required=True, max_length=5)
        self.add_item(self.event_time)
        self.event_desc = ui.TextInput(label=t("event.description_label", lang), style=discord.TextStyle.paragraph, required=False, max_length=1024)
        self.add_item(self.event_desc)

        settings = get_guild_settings(guild_id) or DEFAULT_GUILD_SETTINGS
        wizard_hint = t("wizard.reg_start_hint", lang)
        self.reg_start = ui.TextInput(label=t("wizard.reg_start", lang), placeholder=wizard_hint,
                                      default=defaults["reg_start"] or None, required=False, max_length=25)
        self.add_item(self.reg_start)

    async def on_submit(self, interaction: discord.Interaction):
        lang = get_guild_language(self.guild_id)

        # Validate date
        date_str = self.event_date.value.strip()
        if not parse_date(date_str):
            await interaction.response.send_message(t("event.invalid_date", lang), ephemeral=True)
            return

        # Validate time
        time_str = self.event_time.value.strip()
        match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            await interaction.response.send_message(t("event.invalid_time", lang), ephemeral=True)
            return
        time_str = f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"

        # Check no active event in this channel
        if channel_has_active_event(self.guild_id, self.channel_id):
            await interaction.response.send_message(t("event.already_exists_in_channel", lang), ephemeral=True)
            return

        settings = get_guild_settings(self.guild_id) or DEFAULT_GUILD_SETTINGS

        # Parse registration start
        reg_start_raw = (self.reg_start.value or "").strip()
        reg_open = False
        reg_start_time = None
        immediate_words = {"sofort", "now", "immediately", "jetzt"}

        if not reg_start_raw:
            reg_start_time = compute_reg_start_15th()
            if reg_start_time <= datetime.now():
                reg_open = True
                reg_start_time = None
        elif reg_start_raw.lower() in immediate_words:
            reg_open = True
        else:
            reg_start_time = parse_registration_start(reg_start_raw)
            if reg_start_time is None:
                await interaction.response.send_message(t("event.invalid_date", lang), ephemeral=True)
                return
            if reg_start_time <= datetime.now():
                reg_open = True
                reg_start_time = None

        # Validate registration start is before event start
        if reg_start_time is not None:
            event_dt = parse_date(date_str)
            if event_dt and time_str:
                hours, minutes = map(int, time_str.split(":"))
                event_dt = event_dt.replace(hour=hours, minute=minutes)
            if event_dt and reg_start_time >= event_dt:
                await interaction.response.send_message(t("event.reg_after_event", lang), ephemeral=True)
                return

        # Store parsed data and show bridge to server config modal
        parsed = {
            "name": self.event_name.value.strip(),
            "date": date_str,
            "time": time_str,
            "description": self.event_desc.value.strip() if self.event_desc.value else None,
            "reg_open": reg_open,
            "reg_start_time": reg_start_time,
            "mode": self.mode,
        }
        bridge = _EventConfigBridgeView(self.guild_id, self.channel_id, settings, parsed, interaction.user)
        await interaction.response.send_message(
            t("event.config_prompt", lang), view=bridge, ephemeral=True)


class EventModeSelectView(BaseView):
    """Schritt von /create_event: erklärt beide Anmelde-Modi und lässt die Orga
    per Button einen wählen, der das EventCreationModal öffnet."""
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=300, title="Event Mode")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        rep_button = ui.Button(label=t("event.mode_rep_button", lang),
                               style=discord.ButtonStyle.primary, emoji="🪖")
        rep_button.callback = lambda i: self._open(i, "rep")
        self.add_item(rep_button)

        player_button = ui.Button(label=t("event.mode_player_button", lang),
                                  style=discord.ButtonStyle.success, emoji="🎮")
        player_button.callback = lambda i: self._open(i, "player")
        self.add_item(player_button)

    async def _open(self, interaction, mode):
        modal = EventCreationModal(self.guild_id, self.channel_id, mode=mode)
        await interaction.response.send_modal(modal)


# ############################# #
# BACKGROUND TASKS              #
# ############################# #

async def _get_or_fetch_channel(channel_id: int):
    """Return the channel by id, falling back to an API fetch, or None on failure."""
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            ch = None
    return ch


async def _delete_event_messages(channel, event):
    """Best-effort delete of every bot message tied to an event: the embed, the
    ping messages, and the (legacy + current) announcement/countdown/early-access
    messages. Safe when the channel or messages are already gone."""
    if channel is None:
        return
    msg_id = event.get("event_message_id")
    if msg_id:
        try:
            await (await channel.fetch_message(msg_id)).delete()
        except Exception as e:
            logger.warning(f"Could not delete event embed: {e}")
    for mid in (event.get("ping_message_ids", []) or []):
        try:
            await (await channel.fetch_message(mid)).delete()
        except Exception:
            pass
    for field in ("countdown_message_id", "early_access_message_id", "announcement_message_id"):
        mid = event.get(field)
        if mid:
            try:
                await (await channel.fetch_message(mid)).delete()
            except Exception:
                pass


async def _archive_event(event: dict, guild_id: int, channel_id: int, lang: str):
    """Log the event summary to the guild log channel and delete the embed + related messages."""
    event_name = event.get("name", "?")
    summary_embed = build_event_summary_embed(event, lang)
    log_ch = get_log_channel(guild_id)
    if log_ch:
        try:
            await log_ch.send(embed=summary_embed)
        except Exception:
            pass
    await send_to_log_channel(
        t("log.event_expired", lang, name=event_name),
        guild_id=guild_id)

    ch = await _get_or_fetch_channel(channel_id)
    if ch is None:
        return

    await _delete_event_messages(ch, event)


async def _set_channel_announcement(ch, event, db_id, user_assignments,
                                    content=None, mentions=None, attempts=1):
    """Make ``content`` the single bot announcement below the event embed.

    Posts the new message (if ``content`` is given), records it in
    ``event["announcement_message_id"]``, then deletes whatever announcement was there
    before. Pass ``content=None`` to just clear the current announcement. Best-effort:
    the channel or messages may already be gone. Also sweeps the legacy trackers
    (``early_access_message_id`` / ``countdown_message_id`` / ``ping_message_ids``) so
    events created before this scheme self-heal on their next announcement.
    """
    old_ids = []
    if event.get("announcement_message_id"):
        old_ids.append(event["announcement_message_id"])
    for legacy_key in ("early_access_message_id", "countdown_message_id"):
        if event.get(legacy_key):
            old_ids.append(event[legacy_key])
    old_ids.extend(event.get("ping_message_ids", []) or [])

    new_id = None
    if content is not None and ch is not None:
        for i in range(max(1, attempts)):
            try:
                msg = await ch.send(
                    content=content,
                    allowed_mentions=mentions or discord.AllowedMentions.none())
                new_id = msg.id
                break
            except discord.Forbidden:
                break
            except Exception as e:
                logger.warning(f"Attempt {i+1} to post announcement for '{event.get('name')}' failed: {e}")
                if i + 1 < attempts:
                    await asyncio.sleep(1)

    # Record the new id and clear the legacy trackers BEFORE deleting the old messages, so
    # a crash mid-delete can't lose the new id or resurrect the old ones.
    event["announcement_message_id"] = new_id
    event["early_access_message_id"] = None
    event["countdown_message_id"] = None
    event["ping_message_ids"] = []
    save_event(db_id, event, user_assignments)

    if ch is not None:
        for mid in old_ids:
            if mid == new_id:
                continue
            try:
                await (await ch.fetch_message(mid)).delete()
            except Exception:
                pass


async def _maybe_spawn_recurrence(old_event: dict, guild_id: int, channel_id: int, lang: str):
    """If `old_event.recurrence` is not 'never', create a follow-up event.

    Failures are logged and swallowed — the expiry flow has already completed.
    """
    rec = old_event.get("recurrence") or {}
    if not isinstance(rec, dict) or rec.get("type", "never") == "never":
        return

    event_dt = compute_event_start(old_event)
    if event_dt is None:
        logger.warning(f"Recurrence skipped for event in channel {channel_id}: bad date/time")
        return

    try:
        next_start = compute_next_occurrence(event_dt, rec)
    except Exception as e:
        logger.error(f"Recurrence: compute_next_occurrence failed for channel {channel_id}: {e}", exc_info=True)
        return

    if next_start is None:
        return

    if channel_has_active_event(guild_id, channel_id):
        logger.warning(f"Recurrence: channel {channel_id} still has an active event after expiry; skipping spawn")
        return

    try:
        new_event = clone_event_for_recurrence(old_event, next_start)
        new_db_id = create_event(guild_id, channel_id, new_event)
    except Exception as e:
        logger.error(f"Recurrence: failed to create follow-up for channel {channel_id}: {e}", exc_info=True)
        return

    ch = await _get_or_fetch_channel(channel_id)
    if ch is not None:
        settings = get_guild_settings(guild_id) or DEFAULT_GUILD_SETTINGS
        caster_enabled = settings.get("caster_registration_enabled", True) and new_event.get("max_caster_slots", 0) > 0
        try:
            await send_event_details(ch, new_event, new_db_id, lang, caster_enabled)
        except Exception as e:
            logger.error(f"Recurrence: failed to post embed for channel {channel_id}: {e}", exc_info=True)

    await send_to_log_channel(
        t("log.recurrence_spawned", lang,
          name=new_event.get("name", "?"),
          date=new_event["date"],
          time=new_event["time"]),
        guild_id=guild_id,
    )


async def check_events_loop():
    """Background task: check registration start, reminders, expiry for all events."""
    await bot.wait_until_ready()
    sleep_interval = REGISTRATION_CHECK_INTERVAL

    while not bot.is_closed():
        try:
            await asyncio.sleep(sleep_interval)
            sleep_interval = REGISTRATION_CHECK_INTERVAL

            for row in get_all_active_events_global():
                event = row["event"]
                db_id = row["db_id"]
                guild_id = row["guild_id"]
                channel_id = row["channel_id"]
                user_assignments = row["user_assignments"]
                _ensure_event_keys(event)

                settings = get_guild_settings(guild_id)
                if not settings:
                    continue
                lang = settings.get("language", "de")
                countdown_seconds = settings.get("registration_countdown_seconds", 60)

                is_closed = event.get("is_closed", False)
                is_open = event.get("registration_open", False)

                now = datetime.now()
                start_dt = compute_event_start(event)
                end_dt = compute_event_end(event, start=start_dt)

                # ── Close registration automatically when the event starts ──
                if start_dt and now >= start_dt and not is_closed:
                    event["is_closed"] = True
                    is_closed = True
                    # Consolidate partially-filled player squads once, as the event
                    # begins, so the roster going in is compact.
                    if is_player_mode(event):
                        removed = consolidate_all_player_squads(event, user_assignments)
                        if removed:
                            bot.loop.create_task(send_to_log_channel(
                                t("log.squads_consolidated", lang, name=event["name"], count=removed),
                                guild_id=guild_id))
                    save_event(db_id, event, user_assignments)

                    ch = bot.get_channel(channel_id)
                    if not ch:
                        try:
                            ch = await bot.fetch_channel(channel_id)
                        except Exception:
                            ch = None
                    if ch:
                        caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
                        await send_event_details(ch, event, db_id, lang, caster_enabled)
                        # The "register now" announcement is stale now the event has started.
                        await _set_channel_announcement(ch, event, db_id, user_assignments, content=None)

                # ── End-of-event handling ──
                if end_dt and now > end_dt:
                    rtype = (event.get("recurrence") or {}).get("type", "never")
                    if rtype == "never":
                        await _archive_event(event, guild_id, channel_id, lang)
                        expire_event(db_id)
                        continue

                    spawn_offset = max(0, event.get("spawn_offset_minutes", 5) or 0)
                    spawn_at = end_dt + timedelta(minutes=spawn_offset)
                    if now >= spawn_at:
                        await _archive_event(event, guild_id, channel_id, lang)
                        expire_event(db_id)
                        await _maybe_spawn_recurrence(event, guild_id, channel_id, lang)
                    # During the gap [end → spawn_at]: embed stays, do nothing.
                    continue

                # ── Countdown message (only if NOT closed and NOT expired) ──
                if not is_open and not is_closed and not event.get("countdown_sent", False):
                    start_time = event.get("registration_start_time")
                    event_countdown = event.get("countdown_seconds")
                    effective_countdown = event_countdown if event_countdown is not None else countdown_seconds
                    if start_time and isinstance(start_time, datetime) and effective_countdown > 0:
                        countdown_time = start_time - timedelta(seconds=effective_countdown)
                        if datetime.now() >= countdown_time and datetime.now() < start_time:
                            event["countdown_sent"] = True
                            save_event(db_id, event, user_assignments)

                            ch = bot.get_channel(channel_id)
                            if not ch:
                                try:
                                    ch = await bot.fetch_channel(channel_id)
                                except Exception:
                                    ch = None
                            if ch:
                                caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
                                await send_event_details(ch, event, db_id, lang, caster_enabled)
                                ping_text = _build_ping_text(event)
                                ts = int(start_time.timestamp())
                                remaining_secs = effective_countdown
                                if remaining_secs < 60:
                                    remaining = t("time.seconds", lang, n=remaining_secs)
                                elif remaining_secs < 3600:
                                    mins = remaining_secs // 60
                                    remaining = t("time.minute", lang) if mins == 1 else t("time.minutes", lang, n=mins)
                                else:
                                    hours = remaining_secs // 3600
                                    mins = (remaining_secs % 3600) // 60
                                    h_str = t("time.hour", lang) if hours == 1 else t("time.hours", lang, n=hours)
                                    remaining = f"{h_str} {t('time.minutes', lang, n=mins)}" if mins else h_str
                                content = f"{ping_text}" + t("reg.opens_soon", lang, name=event["name"], ts=ts, remaining=remaining)
                                # Replaces the early-access ping (if any) with the countdown.
                                await _set_channel_announcement(
                                    ch, event, db_id, user_assignments, content=content,
                                    mentions=discord.AllowedMentions(roles=True))

                # ── Open registration (only if NOT closed) ──
                if not is_open and not is_closed:
                    start_time = event.get("registration_start_time")
                    if start_time and isinstance(start_time, datetime) and datetime.now() >= start_time:
                        event["registration_open"] = True
                        save_event(db_id, event, user_assignments)

                        ch = bot.get_channel(channel_id)
                        if not ch:
                            try:
                                ch = await bot.fetch_channel(channel_id)
                            except Exception:
                                ch = None
                        if ch:
                            # PRIORITY 1: Replace the announcement with the "now open" ping —
                            # this also deletes the stale countdown / early-access announcement.
                            # When ping_on_open is off, still clear the stale pre-open announcement.
                            content = None
                            if event.get("ping_on_open", False):
                                ping_text = _build_ping_text(event)
                                if ping_text:
                                    content = f"{ping_text}" + t("reg.opened_announcement", lang, name=event["name"])
                            await _set_channel_announcement(
                                ch, event, db_id, user_assignments, content=content,
                                mentions=discord.AllowedMentions(roles=True, users=True), attempts=2)

                            # PRIORITY 2: Send/update event embed
                            caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
                            await send_event_details(ch, event, db_id, lang, caster_enabled)

                        bot.loop.create_task(
                            send_to_log_channel(t("log.reg_opened", lang, name=event["name"]), guild_id=guild_id)
                        )

                # ── Event reminder ──
                reminder_minutes = event.get("event_reminder_minutes")
                if reminder_minutes and not event.get("event_reminder_sent", False):
                    try:
                        event_dt = datetime.strptime(f"{event['date']} {event.get('time', '20:00')}", "%d.%m.%Y %H:%M")
                        reminder_time = event_dt - timedelta(minutes=reminder_minutes)
                        if datetime.now() >= reminder_time:
                            event["event_reminder_sent"] = True
                            save_event(db_id, event, user_assignments)

                            ch = bot.get_channel(channel_id)
                            if not ch:
                                try:
                                    ch = await bot.fetch_channel(channel_id)
                                except Exception:
                                    ch = None

                            target = None
                            parent_msg = None
                            event_message_id = event.get("event_message_id")
                            if ch and event_message_id:
                                try:
                                    parent_msg = await ch.fetch_message(event_message_id)
                                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                    parent_msg = None

                            if parent_msg is not None:
                                target = parent_msg.thread
                                if target is None:
                                    try:
                                        target = await parent_msg.create_thread(
                                            name=t("reminder.thread_name", lang, name=event["name"])[:100],
                                            auto_archive_duration=1440,
                                        )
                                    except discord.HTTPException as e:
                                        logger.warning(
                                            f"Failed to create reminder thread for '{event['name']}': {e}"
                                        )
                                        target = None

                            if target is None:
                                target = ch

                            if target is not None:
                                ping_text = _build_registered_users_ping_text(user_assignments)
                                event_ts = int(event_dt.timestamp())
                                content = f"{ping_text}" + t(
                                    "reminder.event_starting_soon",
                                    lang,
                                    name=event["name"],
                                    ts=event_ts,
                                )
                                await target.send(
                                    content=content,
                                    allowed_mentions=discord.AllowedMentions(
                                        roles=False, users=True, everyone=False
                                    ),
                                )
                    except ValueError:
                        pass

                # ── Fast polling near registration open ──
                if not is_open and not is_closed:
                    start_time = event.get("registration_start_time")
                    if start_time and isinstance(start_time, datetime):
                        seconds_until = (start_time - datetime.now()).total_seconds()
                        if 0 < seconds_until <= REGISTRATION_CRITICAL_WINDOW:
                            sleep_interval = REGISTRATION_CHECK_INTERVAL_FAST

        except Exception as e:
            logger.error(f"Error in events loop: {e}", exc_info=True)


# ############################# #
# BOT EVENTS                   #
# ############################# #

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")
    init_db()

    # Initialize log channels for all guilds
    for guild in bot.guilds:
        settings = get_guild_settings(guild.id)
        if not settings:
            continue

        log_channel_id = settings.get("log_channel_id")
        if log_channel_id:
            ch = guild.get_channel(log_channel_id)
            if ch:
                set_log_channel(guild.id, ch)
                lang = settings.get("language", "de")
                try:
                    await ch.send(t("log.bot_started", lang, bot_name=str(bot.user)))
                except Exception:
                    pass

    # Start background task
    bot.loop.create_task(check_events_loop())


# ############################# #
# SLASH COMMANDS — SETUP & SET  #
# ############################# #

@bot.tree.command(name="setup", description="Initial server setup for the event bot (admin only)")
@app_commands.describe(
    organizer_role="The role that can manage events",
    log_channel="Channel for bot log messages",
    language="Bot language (de/en)",
)
async def setup_command(interaction: discord.Interaction,
                        organizer_role: discord.Role,
                        log_channel: discord.TextChannel = None,
                        language: str = "de"):
    if not await check_admin(interaction):
        return

    if language not in SUPPORTED_LANGUAGES:
        language = "de"

    settings = get_guild_settings(interaction.guild.id)
    if settings is None:
        settings = dict(DEFAULT_GUILD_SETTINGS)

    settings["organizer_role_id"] = organizer_role.id
    if log_channel:
        settings["log_channel_id"] = log_channel.id
        set_log_channel(interaction.guild.id, log_channel)
    settings["language"] = language

    save_guild_settings(interaction.guild.id, settings)

    lang = language
    msg = t("setup.role_set", lang, role=organizer_role.name)
    if log_channel:
        msg += "\n" + t("setup.log_channel_set", lang, channel=log_channel.name)
    msg += "\n" + t("setup.language_set", lang, language=get_language_name(language))
    msg += "\n\n" + t("setup.complete", lang)
    await interaction.response.send_message(msg, ephemeral=True)


@setup_command.autocomplete("language")
async def language_autocomplete(interaction, current: str):
    return [
        app_commands.Choice(name="Deutsch", value="de"),
        app_commands.Choice(name="English", value="en"),
    ]


# ── /set_* commands ──

@bot.tree.command(name="set_organizer_role", description="Set the organizer role (admin only)")
@app_commands.describe(role="The role that can manage events")
async def set_organizer_role_cmd(interaction: discord.Interaction, role: discord.Role):
    if not await check_admin(interaction):
        return
    settings = get_guild_settings(interaction.guild.id)
    if not settings:
        settings = dict(DEFAULT_GUILD_SETTINGS)
    settings["organizer_role_id"] = role.id
    save_guild_settings(interaction.guild.id, settings)
    lang = settings.get("language", "de")
    await interaction.response.send_message(t("set.organizer_role", lang, role=role.name), ephemeral=True)


@bot.tree.command(name="set_language", description="Set the bot language (admin only)")
@app_commands.describe(language="Language code (de/en)")
async def set_language_cmd(interaction: discord.Interaction, language: str):
    if not await check_admin(interaction):
        return
    if language not in SUPPORTED_LANGUAGES:
        await interaction.response.send_message("Supported: de, en", ephemeral=True)
        return
    settings = get_guild_settings(interaction.guild.id)
    if not settings:
        settings = dict(DEFAULT_GUILD_SETTINGS)
    settings["language"] = language
    save_guild_settings(interaction.guild.id, settings)
    await interaction.response.send_message(t("set.language", language, language_name=get_language_name(language)), ephemeral=True)

    # Refresh all active event embeds so they display in the new language
    for row in get_all_active_events(interaction.guild.id):
        await update_event_displays(interaction.guild.id, row["channel_id"])


@set_language_cmd.autocomplete("language")
async def lang_ac(interaction, current):
    return [app_commands.Choice(name="Deutsch", value="de"), app_commands.Choice(name="English", value="en")]


@bot.tree.command(name="set_log_channel", description="Set the log channel (admin only)")
@app_commands.describe(channel="The channel for bot logs")
async def set_log_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await check_admin(interaction):
        return
    settings = get_guild_settings(interaction.guild.id)
    if not settings:
        settings = dict(DEFAULT_GUILD_SETTINGS)
    settings["log_channel_id"] = channel.id
    save_guild_settings(interaction.guild.id, settings)
    set_log_channel(interaction.guild.id, channel)
    lang = settings.get("language", "de")
    await interaction.response.send_message(t("set.log_channel", lang, channel=channel.name), ephemeral=True)


@bot.tree.command(name="config_defaults",
                  description="Edit the default event settings new events inherit (organizer only)")
async def config_defaults_cmd(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    lang = get_guild_language(interaction.guild.id)
    await interaction.response.defer(ephemeral=True)
    await start_dm_edit_session(interaction, interaction.guild.id,
                                interaction.channel.id, 0, lang, target=_GUILD_TARGET)


# ############################# #
# SLASH COMMANDS — EVENTS       #
# ############################# #

@bot.tree.command(name="create_event", description="Create a new event in this channel (organizer only)")
async def event_command(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    lang = _lang(interaction)
    if channel_has_active_event(interaction.guild.id, interaction.channel_id):
        await interaction.response.send_message(t("event.already_exists_in_channel", lang), ephemeral=True)
        return
    embed = discord.Embed(
        title=t("event.mode_select_title", lang),
        description=t("event.mode_select_desc", lang),
        color=discord.Color.blurple())
    embed.add_field(name=t("event.mode_rep_name", lang),
                    value=t("event.mode_rep_desc", lang), inline=False)
    embed.add_field(name=t("event.mode_player_name", lang),
                    value=t("event.mode_player_desc", lang), inline=False)
    view = EventModeSelectView(interaction.guild.id, interaction.channel_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="delete_event", description="Delete the event in this channel (organizer only)")
async def delete_event_command(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    lang = _lang(interaction)
    event, _, _ = _get_channel_event(interaction.guild.id, interaction.channel_id)
    if not event:
        await interaction.response.send_message(t("event.nothing_to_delete", lang), ephemeral=True)
        return

    embed = discord.Embed(
        title=t("event.delete_confirm_title", lang),
        description=t("event.delete_confirm", lang, name=event["name"]),
        color=discord.Color.red())
    view = DeleteConfirmationView(interaction.guild.id, interaction.channel_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="update", description="Refresh event display (organizer only)")
async def update_command(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)
    event, _, _ = _get_channel_event(gid, cid)
    if not event:
        await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
        return
    await update_event_displays(gid, cid)
    await send_feedback(interaction, t("general.success", lang), ephemeral=True)


# ############################# #
# EVENT REMINDER                #
# ############################# #


# ############################# #
# EVENT ROLE MANAGEMENT         #
# ############################# #

@bot.tree.command(name="set_event_roles", description="Add roles to the event (organizer only)")
@app_commands.describe(
    ping_role="Role to ping for announcements",
    squad_rep_role="Role for squad representatives",
    community_rep_role="Role for community reps (early squad access)",
    caster_role="Role for casters",
    caster_community_role="Role for caster community (early caster access)",
)
async def set_event_roles_cmd(interaction: discord.Interaction,
                               ping_role: discord.Role = None,
                               squad_rep_role: discord.Role = None,
                               community_rep_role: discord.Role = None,
                               caster_role: discord.Role = None,
                               caster_community_role: discord.Role = None):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    lock = _get_guild_lock(gid)
    async with lock:
        event, user_assignments, db_id = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return

        changes = []
        role_mapping = {
            "ping_role_ids": ping_role,
            "squad_rep_role_ids": squad_rep_role,
            "community_rep_role_ids": community_rep_role,
            "caster_role_ids": caster_role,
            "caster_community_role_ids": caster_community_role,
        }
        for key, role in role_mapping.items():
            if role is not None:
                if role.id not in event.get(key, []):
                    event.setdefault(key, []).append(role.id)
                    changes.append(f"{key}: +{role.name}")

        if not changes:
            await send_feedback(interaction, t("roles.no_changes", lang), ephemeral=True)
            return

        save_event(db_id, event, user_assignments)

    msg = t("roles.updated", lang) + "\n" + "\n".join(changes)
    await send_feedback(interaction, msg, ephemeral=True)
    await update_event_displays(gid, cid)
    await send_to_log_channel(
        t("log.roles_updated", lang, user=interaction.user.name, changes=", ".join(changes)),
        guild=interaction.guild)


_ROLE_KEYS = [
    "ping_role_ids", "squad_rep_role_ids", "community_rep_role_ids",
    "caster_role_ids", "caster_community_role_ids",
]

@bot.tree.command(name="clear_event_roles", description="Clear event roles (organizer only)")
@app_commands.describe(role_type="Which role category to clear (or 'all')")
@app_commands.choices(role_type=[
    app_commands.Choice(name="All roles", value="all"),
    app_commands.Choice(name="Ping roles", value="ping_role_ids"),
    app_commands.Choice(name="Roles allowed to register", value="squad_rep_role_ids"),
    app_commands.Choice(name="Roles with early access", value="community_rep_role_ids"),
    app_commands.Choice(name="Caster roles", value="caster_role_ids"),
    app_commands.Choice(name="Caster community roles (early access)", value="caster_community_role_ids"),
])
async def clear_event_roles_cmd(interaction: discord.Interaction, role_type: str = "all"):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    lock = _get_guild_lock(gid)
    async with lock:
        event, user_assignments, db_id = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return

        keys_to_clear = _ROLE_KEYS if role_type == "all" else [role_type]
        cleared_any = False
        for key in keys_to_clear:
            if event.get(key):
                event[key] = []
                cleared_any = True

        if not cleared_any:
            await send_feedback(interaction, t("roles.no_roles", lang), ephemeral=True)
            return

        save_event(db_id, event, user_assignments)

    if role_type == "all":
        await send_feedback(interaction, t("roles.cleared_all", lang), ephemeral=True)
    else:
        await send_feedback(interaction, t("roles.cleared", lang, role_type=role_type), ephemeral=True)
    await update_event_displays(gid, cid)
    await send_to_log_channel(
        t("log.roles_cleared", lang, user=interaction.user.name, role_type=role_type),
        guild=interaction.guild)


# ############################# #
# ADMIN SQUAD MANAGEMENT        #
# ############################# #

def _find_squad_by_name(event, squad_name):
    """Find squad by name (case-insensitive). Returns (squad_id, location) or (None, None).
    With duplicate names, returns the first match."""
    lower = squad_name.strip().lower()
    for sid, data in event.get("squads", {}).items():
        if data.get("name", "").lower() == lower:
            return sid, "squads"
    for st in SQUAD_TYPES:
        wl_key = _waitlist_key(st)
        for entry in event.get(wl_key, []):
            if entry[0].lower() == lower:
                return entry[4], wl_key
    return None, None


async def _squad_name_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for squad_name params -- lists squads + waitlist entries."""
    gid = interaction.guild.id
    cid = interaction.channel_id
    event, _, _ = _get_channel_event(gid, cid)
    if not event:
        return []
    choices = []
    for sid, data in event.get("squads", {}).items():
        name = data.get("name", sid)
        choices.append(app_commands.Choice(name=name, value=sid))
    for entry in _all_squad_waitlist_entries(event):
        choices.append(app_commands.Choice(name=entry[0], value=entry[4]))
    current_lower = current.lower()
    return [c for c in choices if current_lower in c.name.lower()][:25]


@bot.tree.command(name="admin_edit_squad", description="Edit a squad's size (organizer only)")
@app_commands.describe(squad_name="Name of the squad", new_size="New squad size")
async def admin_edit_squad_cmd(interaction: discord.Interaction, squad_name: str, new_size: int):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    if new_size < 1:
        await send_feedback(interaction, t("admin.invalid_size", lang), ephemeral=True)
        return

    lock = _get_guild_lock(gid)
    async with lock:
        event, user_assignments, db_id = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return

        # Try direct ID lookup first (from autocomplete), then fall back to name search
        if squad_name in event.get("squads", {}):
            found_id, location = squad_name, "squads"
        else:
            found_id, location = _find_squad_by_name(event, squad_name)
        if found_id is None:
            await send_feedback(interaction, t("admin.squad_not_found", lang, name=squad_name), ephemeral=True)
            return

        display_name = _resolve_squad_name(event, found_id)

        if location == "squads":
            old_size = event["squads"][found_id]["size"]
            delta = new_size - old_size
            event["squads"][found_id]["size"] = new_size
            event["player_slots_used"] = max(0, min(event["player_slots_used"] + delta, event["max_player_slots"]))
            save_event(db_id, event, user_assignments)
            if delta < 0:
                freed_type = event["squads"][found_id].get("type")
                await _process_squad_waitlist(event, user_assignments, db_id, gid, cid, abs(delta), freed_type=freed_type)
        else:
            # In per-type waitlist — update the tuple entry
            for i, entry in enumerate(event[location]):
                if len(entry) > 4 and entry[4] == found_id:
                    old_size = entry[3]
                    lst = list(entry)
                    lst[3] = new_size
                    event[location][i] = tuple(lst)
                    break
            save_event(db_id, event, user_assignments)

    await send_feedback(interaction,
        t("admin.squad_edited", lang, name=display_name, old=old_size, new=new_size),
        ephemeral=True)
    await send_to_log_channel(
        t("log.admin_squad_edited", lang, user=interaction.user.name, squad=display_name, old=old_size, new=new_size),
        guild=interaction.guild)
    await update_event_displays(gid, cid)

@admin_edit_squad_cmd.autocomplete("squad_name")
async def admin_edit_squad_autocomplete(interaction, current: str):
    return await _squad_name_autocomplete(interaction, current)


@bot.tree.command(name="admin_waitlist", description="Show current waitlist (organizer only)")
async def admin_waitlist_cmd(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    event, _, _ = _get_channel_event(gid, cid)
    if not event:
        await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
        return

    caster_wl = event.get("caster_waitlist", [])

    if not _any_squad_waitlist(event) and not caster_wl:
        await send_feedback(interaction, t("admin.waitlist_empty", lang), ephemeral=True)
        return

    embed = discord.Embed(
        title=t("admin.waitlist_title", lang, name=event["name"]),
        color=discord.Color.orange())

    type_labels = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
    entry_key = ("admin.waitlist_squad_entry"
                 if event.get("playstyle_enabled", True)
                 else "admin.waitlist_squad_entry_no_playstyle")
    for st in SQUAD_TYPES:
        wl = event.get(_waitlist_key(st), [])
        if wl:
            lines = []
            for i, entry in enumerate(wl, 1):
                squad_name, squad_type, playstyle, size, *_rest = entry
                lines.append(t(entry_key, lang,
                              pos=i, name=squad_name, type=type_labels.get(squad_type, squad_type),
                              size=size, playstyle=playstyle))
            embed.add_field(
                name=t("embed.type_waitlist_label", lang, type=t(f"embed.type_{st}", lang), count=len(wl)),
                value="\n".join(lines), inline=False)

    if caster_wl:
        lines = []
        for i, entry in enumerate(caster_wl, 1):
            name, uid = entry[0], entry[1]
            lines.append(t("admin.waitlist_caster_entry", lang, pos=i, name=name, uid=uid))
        embed.add_field(name="Casters", value="\n".join(lines), inline=False)

    await send_feedback(interaction, "", embed=embed, ephemeral=True)


@bot.tree.command(name="admin_user_assignments", description="Show all user-squad assignments (organizer only)")
async def admin_user_assignments_cmd(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    event, user_assignments, _ = _get_channel_event(gid, cid)
    if not event:
        await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
        return

    if not user_assignments:
        await send_feedback(interaction, t("admin.assignments_empty", lang), ephemeral=True)
        return

    # Group by squad id
    squads_to_users = {}
    for uid, assignments in user_assignments.items():
        if isinstance(assignments, str):
            assignments = [assignments]
        for a in assignments:
            squads_to_users.setdefault(a, []).append(uid)

    embed = discord.Embed(
        title=t("admin.assignments_title", lang),
        color=discord.Color.blue())

    lines = []
    for assignment_key in sorted(squads_to_users.keys()):
        uids = squads_to_users[assignment_key]
        if assignment_key == "__caster__":
            display_name = "Caster"
        else:
            display_name = _resolve_squad_name(event, assignment_key)
        member_mentions = []
        for uid in uids:
            member = interaction.guild.get_member(int(uid))
            if member:
                member_mentions.append(f"<@{uid}> ({member.display_name})")
            else:
                member_mentions.append(f"<@{uid}>")
        lines.append(f"**{display_name}**:\n" + "\n".join(f"  - {m}" for m in member_mentions))

    # Discord embed field limit is 1024 chars, so chunk if needed
    text = "\n".join(lines)
    if len(text) <= 4096:
        embed.description = text
    else:
        embed.description = text[:4090] + "\n..."

    await send_feedback(interaction, "", embed=embed, ephemeral=True)


@bot.tree.command(name="admin_reset_assignment", description="Reset a user's assignment (organizer only)")
@app_commands.describe(user="The user whose assignment to reset")
async def admin_reset_assignment_cmd(interaction: discord.Interaction, user: discord.Member):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    lock = _get_guild_lock(gid)
    async with lock:
        event, user_assignments, db_id = _get_channel_event(gid, cid)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return

        uid = str(user.id)
        current = get_user_assignments(user_assignments, uid)
        if not current:
            await send_feedback(interaction, t("admin.user_not_assigned", lang), ephemeral=True)
            return

        del user_assignments[uid]
        save_event(db_id, event, user_assignments)

    await send_feedback(interaction,
        t("admin.assignment_reset", lang, user=user.display_name, squads=", ".join(current)),
        ephemeral=True)
    await send_to_log_channel(
        t("log.admin_assignment_reset", lang, user=interaction.user.name, target=user.display_name),
        guild=interaction.guild)


# ############################# #
# CSV EXPORT                    #
# ############################# #

@bot.tree.command(name="export_csv", description="Export squad list as CSV (organizer only)")
async def export_csv_cmd(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    event, user_assignments, _ = _get_channel_event(gid, cid)
    if not event:
        await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
        return

    output = io.StringIO()
    writer = csv.writer(output)

    status_registered = "Angemeldet" if lang == "de" else "Registered"
    status_waitlist = "Warteliste" if lang == "de" else "Waitlist"

    if is_player_mode(event):
        writer.writerow(["User ID", "Display Name", "Squad Type", "Squad Name", "Status"])
        for squad_name, data in event.get("squads", {}).items():
            squad_type = data.get("type", "")
            for m in data.get("members", []):
                writer.writerow([
                    m.get("user_id", ""), m.get("name", ""),
                    squad_type, squad_name, status_registered,
                ])
        for entry in _all_squad_waitlist_entries(event):
            # (display_name, squad_type, None, 1, user_id, display_name)
            if len(entry) < 6:
                continue
            display_name = entry[5]
            squad_type = entry[1]
            user_id = entry[4]
            writer.writerow([user_id, display_name, squad_type, "", status_waitlist])
    else:
        writer.writerow(["Squad Name", "Squad Type", "Size", "Playstyle", "Rep Name", "Squad ID", "Status"])
        for sid, data in event.get("squads", {}).items():
            writer.writerow([
                data.get("name", ""), data.get("type", ""), data.get("size", 0),
                data.get("playstyle", ""), data.get("rep_name", ""),
                sid, status_registered,
            ])
        for entry in _all_squad_waitlist_entries(event):
            squad_name, squad_type, playstyle, size, squad_id, *rest = entry
            rep_name = rest[0] if rest else ""
            writer.writerow([
                squad_name, squad_type, size, playstyle,
                rep_name, squad_id, status_waitlist,
            ])

    output.seek(0)
    date_str = event.get("date", "unknown").replace(".", "-")
    filename_stem = "players" if is_player_mode(event) else "squads"
    filename = f"{filename_stem}_{date_str}.csv"
    file = discord.File(fp=io.BytesIO(output.getvalue().encode("utf-8")), filename=filename)

    await interaction.response.send_message(
        t("export.csv_header", lang, name=event["name"]),
        file=file, ephemeral=True)


# ############################# #
# TEST COMMAND                  #
# ############################# #

@bot.tree.command(name="test", description="Run the test suite (organizer only)")
async def test_command(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    await interaction.response.defer(ephemeral=True)

    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "Test/test.py"],
            capture_output=True, text=True, timeout=30,
        )
        output_text = result.stdout
        if result.stderr:
            output_text += "\n--- STDERR ---\n" + result.stderr
    except subprocess.TimeoutExpired:
        output_text = "Test timed out after 30 seconds."
    except Exception as e:
        output_text = f"Error running tests: {e}"

    buf = io.BytesIO(output_text.encode("utf-8"))
    file = discord.File(fp=buf, filename=f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    await interaction.followup.send("Test results:", file=file, ephemeral=True)


@bot.tree.command(name="sync", description="Sync slash commands (admin only)")
async def sync_command(interaction: discord.Interaction):
    if not await check_admin(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    await bot.tree.sync()
    await interaction.followup.send("Slash commands synced!", ephemeral=True)


@bot.tree.command(name="help", description="Show help for available commands")
async def help_command(interaction: discord.Interaction):
    lang = _lang(interaction)
    embed = discord.Embed(title=t("help.title", lang), color=discord.Color.blue())

    if lang == "de":
        embed.add_field(name="Events", value=(
            "`/create_event` - Event erstellen (im aktuellen Kanal)\n"
            "`/delete_event` - Event im Kanal löschen\n"
            "Event verwalten (öffnen/schließen, bearbeiten, löschen) → ⚙️ Admin-Button\n"
            "Anmelden → 🪖 / 🎙️ Buttons\n"
            "Abmelden → ❌ Button\n"
            "Kalender-Datei (.ics) exportieren → 📅 Kalender-Button\n"
            "`/update` - Event-Anzeige aktualisieren\n"
            "`/export_csv` - Squad-Liste als CSV exportieren"
        ), inline=False)
        embed.add_field(name="Event-Einstellungen (Organisator)", value=(
            "`/set_event_roles` - Event-Rollen setzen\n"
            "`/clear_event_roles` - Event-Rollen löschen"
        ), inline=False)
        embed.add_field(name="Admin-Verwaltung (Organisator)", value=(
            "`/admin_edit_squad` - Squad-Größe ändern\n"
            "`/admin_waitlist` - Warteliste anzeigen\n"
            "`/admin_user_assignments` - Zuweisungen anzeigen\n"
            "`/admin_reset_assignment` - Zuweisung zurücksetzen"
        ), inline=False)
        embed.add_field(name="Konfiguration (Admin)", value=(
            "`/setup` - Ersteinrichtung des Bots\n"
            "`/set_organizer_role` - Organisator-Rolle setzen\n"
            "`/set_language` - Sprache ändern\n"
            "`/set_log_channel` - Log-Kanal setzen\n"
            "`/config_defaults` - Standard-Event-Einstellungen bearbeiten\n"
            "`/sync` - Slash-Commands synchronisieren\n"
            "`/test` - Test-Suite ausführen"
        ), inline=False)
    else:
        embed.add_field(name="Events", value=(
            "`/create_event` - Create event (in current channel)\n"
            "`/delete_event` - Delete event in channel\n"
            "Event management (open/close, edit, delete) → ⚙️ Admin button\n"
            "Register → 🪖 / 🎙️ buttons\n"
            "Decline → ❌ button\n"
            "Export calendar file (.ics) → 📅 Calendar button\n"
            "`/update` - Refresh event display\n"
            "`/export_csv` - Export squad list as CSV"
        ), inline=False)
        embed.add_field(name="Event Settings (Organizer)", value=(
            "`/set_event_roles` - Set event roles\n"
            "`/clear_event_roles` - Clear event roles"
        ), inline=False)
        embed.add_field(name="Admin Management (Organizer)", value=(
            "`/admin_edit_squad` - Edit squad size\n"
            "`/admin_waitlist` - Show waitlist\n"
            "`/admin_user_assignments` - Show assignments\n"
            "`/admin_reset_assignment` - Reset user assignment"
        ), inline=False)
        embed.add_field(name="Configuration (admin)", value=(
            "`/setup` - Initial bot setup\n"
            "`/set_organizer_role` - Set organizer role\n"
            "`/set_language` - Change language\n"
            "`/set_log_channel` - Set log channel\n"
            "`/config_defaults` - Edit default event settings\n"
            "`/sync` - Sync slash commands\n"
            "`/test` - Run test suite"
        ), inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ############################# #
# START                         #
# ############################# #

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(TOKEN)
