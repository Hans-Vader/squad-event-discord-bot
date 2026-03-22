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
from datetime import datetime, timedelta
import logging
import sys
import csv
import io
import re

from config import TOKEN, ADMIN_IDS, REGISTRATION_CHECK_INTERVAL
from database import (
    init_db, get_guild_settings, save_guild_settings, guild_is_configured,
    get_guild_language, get_event_by_channel, get_all_active_events,
    get_all_active_events_global, save_event, create_event, delete_event,
    expire_event, channel_has_active_event, build_default_event,
    DEFAULT_GUILD_SETTINGS,
)
from utils import (
    has_organizer_role, is_guild_admin, has_role, parse_date,
    compute_expiry_date, parse_registration_start, compute_reg_start_15th, generate_squad_id,
    format_event_details, build_event_summary_embed,
    send_to_log_channel, set_log_channel, get_log_channel,
    export_log_file, clear_log_file, logger,
    resolve_event_defaults,
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
# Track active DM edit sessions: user_id -> {guild_id, channel_id}
_active_edit_sessions: dict[int, dict] = {}
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
    (7,  "max_vehicle_squads",     "edit.property.max_vehicles",    "int",             None),
    (8,  "max_heli_squads",        "edit.property.max_helis",       "int",             None),
    (9,  "infantry_squad_size",    "edit.property.infantry_size",   "int",             None),
    (10, "vehicle_squad_size",     "edit.property.vehicle_size",    "int",             None),
    (11, "heli_squad_size",        "edit.property.heli_size",       "int",             None),
    (12, "max_squads_per_user",    "edit.property.max_squads_user", "int",             None),
    (13, "event_reminder_minutes", "edit.property.reminder",        "int_nullable",    None),
    (14, "registration_start_time","edit.property.reg_start",       "reg_start",       None),
    (15, "embed_image_url",        "edit.property.image",           "image",           None),
]


def _get_guild_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _guild_locks:
        _guild_locks[guild_id] = asyncio.Lock()
    return _guild_locks[guild_id]


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
        "squads": {}, "casters": {}, "waitlist": [], "caster_waitlist": [],
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
    }
    for key, default in defaults.items():
        if key not in event:
            event[key] = default

    # Recover missing expiry_date
    if "expiry_date" not in event and event.get("date"):
        recovered = compute_expiry_date(event["date"], event.get("time"))
        if recovered:
            event["expiry_date"] = recovered


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


def get_user_squad_names(user_assignments: dict, user_id: str) -> list:
    return [a for a in get_user_assignments(user_assignments, str(user_id)) if a != "__caster__"]


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
    try:
        done = False
        try:
            done = interaction.response.is_done()
        except Exception:
            pass

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
        role_ids = event.get("squad_rep_role_ids", [])
        user_ids = event.get("squad_rep_user_ids", [])
        deny_key = "gate.squad_denied"
    elif registration_type == "caster":
        role_ids = event.get("caster_role_ids", [])
        user_ids = event.get("caster_user_ids", [])
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


def _build_ping_text(event, include_community_rep=False):
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
    if include_community_rep:
        for rid in event.get("community_rep_role_ids", []):
            role_ids.add(rid)
        for uid in event.get("community_rep_user_ids", []):
            user_ids.add(uid)
    mentions = [f"<@&{rid}>" for rid in role_ids] + [f"<@{uid}>" for uid in user_ids]
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
        view = EventActionView()

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
async def register_squad(interaction, guild_id, channel_id, squad_name, squad_type, playstyle):
    """Register a squad. Uses guild lock for thread safety."""
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
        current_squads = get_user_squad_names(user_assignments, user_id)
        if len(current_squads) >= max_squads:
            if max_squads == 1 and current_squads:
                await send_feedback(interaction, t("squad.already_assigned", lang, name=current_squads[0]), ephemeral=True)
            else:
                await send_feedback(interaction, t("squad.max_reached", lang, current=len(current_squads), max=max_squads), ephemeral=True)
            return False

        # Duplicate check
        for existing in event["squads"]:
            if existing.lower() == squad_name.lower():
                await send_feedback(interaction, t("squad.duplicate_name", lang, name=existing), ephemeral=True)
                return False
        for entry in event["waitlist"]:
            if entry[0].lower() == squad_name.lower():
                await send_feedback(interaction, t("squad.duplicate_name", lang, name=squad_name), ephemeral=True)
                return False

        sizes = _get_squad_sizes(event)
        size = sizes.get(squad_type, sizes["infantry"])
        squad_id = generate_squad_id(squad_name)
        available = event["max_player_slots"] - event["player_slots_used"]
        rep_name = interaction.user.display_name

        if size <= available:
            event["squads"][squad_name] = {
                "type": squad_type, "playstyle": playstyle,
                "size": size, "id": squad_id, "rep_name": rep_name,
            }
            event["player_slots_used"] += size
            add_user_assignment(user_assignments, user_id, squad_name)
            save_event(db_id, event, user_assignments)
            result = "registered"
            wl_pos = None
        else:
            event["waitlist"].append((squad_name, squad_type, playstyle, size, squad_id, rep_name))
            add_user_assignment(user_assignments, user_id, squad_name)
            save_event(db_id, event, user_assignments)
            result = "waitlisted"
            wl_pos = len(event["waitlist"])

    type_labels = {"infantry": "Infanterie" if lang == "de" else "Infantry",
                   "vehicle": "Fahrzeug" if lang == "de" else "Vehicle",
                   "heli": "Heli"}
    type_label = type_labels.get(squad_type, squad_type)
    user_squads_now = len(get_user_squad_names(user_assignments, user_id))
    squad_info = t("squad.your_squads_info", lang, current=user_squads_now, max=max_squads)

    if result == "registered":
        await send_feedback(interaction,
            t("squad.registered", lang, name=squad_name, type=type_label, size=size, playstyle=playstyle, info=squad_info),
            ephemeral=True)
        await send_to_log_channel(
            t("log.squad_registered", lang, user=interaction.user.name, squad=squad_name, type=type_label, size=size, playstyle=playstyle),
            guild=interaction.guild)
    else:
        await send_feedback(interaction,
            t("squad.waitlisted", lang, name=squad_name, type=type_label, size=size, playstyle=playstyle, pos=wl_pos, info=squad_info),
            ephemeral=True)
        await send_to_log_channel(
            t("log.squad_waitlisted", lang, user=interaction.user.name, squad=squad_name),
            guild=interaction.guild)

    await update_event_displays(guild_id, channel_id)
    return True


# ---------------------------------------------------------------------------
# Core: squad unregistration
# ---------------------------------------------------------------------------
async def unregister_squad(interaction, guild_id, channel_id, squad_name, is_admin=False):
    lock = _get_guild_lock(guild_id)
    lang = get_guild_language(guild_id)

    async with lock:
        event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
        if not event:
            await send_feedback(interaction, t("general.no_active_event", lang), ephemeral=True)
            return None

        squad_name_lower = squad_name.strip().lower()
        freed_slots = 0

        found_in_event = None
        for name in list(event["squads"].keys()):
            if name.lower() == squad_name_lower:
                found_in_event = name
                break

        found_in_waitlist = None
        for i, entry in enumerate(event["waitlist"]):
            if entry[0].lower() == squad_name_lower:
                found_in_waitlist = i
                break

        if found_in_event is None and found_in_waitlist is None:
            await send_feedback(interaction, t("squad.not_found", lang, name=squad_name), ephemeral=True)
            return None

        if found_in_event is not None:
            squad_data = event["squads"].pop(found_in_event)
            freed_slots = squad_data.get("size", 0)
            event["player_slots_used"] = max(0, event["player_slots_used"] - freed_slots)

        elif found_in_waitlist is not None:
            event["waitlist"].pop(found_in_waitlist)

        for uid in list(user_assignments.keys()):
            assignments = get_user_assignments(user_assignments, uid)
            if any(a.lower() == squad_name_lower for a in assignments):
                remove_user_assignment(user_assignments, uid, squad_name)

        save_event(db_id, event, user_assignments)

        if freed_slots > 0:
            await _process_squad_waitlist(event, user_assignments, db_id, guild_id, channel_id, freed_slots)

    await send_feedback(interaction, t("squad.unregistered", lang, name=squad_name), ephemeral=True)
    await send_to_log_channel(
        t("log.squad_unregistered", lang, user=interaction.user.name, squad=squad_name, freed=freed_slots),
        guild=interaction.guild)
    await update_event_displays(guild_id, channel_id)
    return freed_slots


async def _process_squad_waitlist(event, user_assignments, db_id, guild_id, channel_id, free_slots):
    """Move waiting squads into event if they fit."""
    if free_slots <= 0 or not event.get("waitlist"):
        return

    moved = []
    remaining = free_slots
    to_remove = []

    for i, entry in enumerate(event["waitlist"]):
        if remaining <= 0:
            break
        squad_name, squad_type, playstyle, size, squad_id, *_rest = entry
        rep_name = _rest[0] if _rest else None
        if size <= remaining:
            squad_data = {"type": squad_type, "playstyle": playstyle, "size": size, "id": squad_id}
            if rep_name:
                squad_data["rep_name"] = rep_name
            event["squads"][squad_name] = squad_data
            event["player_slots_used"] += size
            remaining -= size
            to_remove.append(i)
            moved.append((squad_name, size))

    for i in sorted(to_remove, reverse=True):
        event["waitlist"].pop(i)

    if moved:
        save_event(db_id, event, user_assignments)
        lang = get_guild_language(guild_id)
        for squad_name, size in moved:
            link = _build_event_message_link(event, channel_id, guild_id)
            dm_msg = t("squad.moved_from_waitlist", lang, name=squad_name)
            if link:
                dm_msg += f"\n[→ Event]({link})"
            await _send_squad_dm(user_assignments, squad_name, dm_msg)
            await send_to_log_channel(
                t("log.squad_moved", lang, squad=squad_name, size=size),
                guild_id=guild_id)


async def _send_squad_dm(user_assignments, squad_name, message):
    squad_lower = squad_name.lower()
    leader_id = None
    for uid in user_assignments:
        if squad_lower in [a.lower() for a in get_user_assignments(user_assignments, uid) if a != "__caster__"]:
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


class EventActionView(ui.View):
    """Persistent view with event action buttons."""
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(ui.Button(
            label="Squad", style=discord.ButtonStyle.success,
            custom_id="event_register_squad", emoji="🪖",
        ))
        self.add_item(ui.Button(
            label="Caster", style=discord.ButtonStyle.primary,
            custom_id="event_register_caster", emoji="🎙️",
        ))
        self.add_item(ui.Button(
            label="Info", style=discord.ButtonStyle.secondary,
            custom_id="event_info", emoji="ℹ️",
        ))
        self.add_item(ui.Button(
            label="Abmelden", style=discord.ButtonStyle.danger,
            custom_id="event_unregister", emoji="❌",
        ))
        self.add_item(ui.Button(
            label="Admin", style=discord.ButtonStyle.secondary,
            custom_id="event_admin", emoji="⚙️",
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id == "event_register_squad":
            await self._register_squad(interaction)
        elif custom_id == "event_register_caster":
            await self._register_caster(interaction)
        elif custom_id == "event_info":
            await self._info(interaction)
        elif custom_id == "event_unregister":
            await self._unregister(interaction)
        elif custom_id == "event_admin":
            await self._admin(interaction)
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

        user_id = str(interaction.user.id)
        max_squads = event.get("max_squads_per_user", 1)
        current = get_user_squad_names(user_assignments, user_id)
        if len(current) >= max_squads:
            if max_squads == 1 and current:
                await interaction.response.send_message(t("squad.already_assigned", lang, name=current[0]), ephemeral=True)
            else:
                await interaction.response.send_message(t("squad.max_reached", lang, current=len(current), max=max_squads), ephemeral=True)
            return

        settings = get_guild_settings(gid) or DEFAULT_GUILD_SETTINGS
        view = SquadRegistrationView(gid, cid, event)
        await interaction.response.send_message(
            f"**{t('squad.step_1_title', lang)}**\n{t('squad.step_1_desc', lang)}",
            view=view, ephemeral=True)

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

    async def _info(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        cid = interaction.channel_id
        lang = _lang(interaction)
        event, user_assignments, _ = _get_channel_event(gid, cid)
        user_id = str(interaction.user.id)
        assignments = get_user_assignments(user_assignments or {}, user_id)

        if not assignments:
            embed = discord.Embed(title="Info", description=t("info.no_assignment", lang), color=discord.Color.blue())
        elif "__caster__" in assignments:
            if event and user_id in event.get("casters", {}):
                embed = discord.Embed(title="Caster", description=t("info.caster_assigned", lang), color=discord.Color.green())
            else:
                embed = discord.Embed(title="Caster", description=t("info.caster_waitlisted", lang), color=discord.Color.orange())
        else:
            squad_names = [a for a in assignments if a != "__caster__"]
            desc_parts = []
            for sn in squad_names:
                if event and sn in event.get("squads", {}):
                    d = event["squads"][sn]
                    desc_parts.append(f"**{sn}** ({d.get('type', '?')}, {d.get('size', 0)}, {d.get('playstyle', 'Normal')})")
                else:
                    desc_parts.append(f"**{sn}** (Waitlist)")
            embed = discord.Embed(title="Squads", description="\n".join(desc_parts), color=discord.Color.green())

        if event:
            embed.add_field(name="Event", value=f"{event['name']} ({event['date']}, {event.get('time', '?')})", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _unregister(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        gid = interaction.guild.id
        cid = interaction.channel_id
        lang = _lang(interaction)
        _, user_assignments, _ = _get_channel_event(gid, cid)
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
            embed = discord.Embed(
                title=t("squad.unregister_title", lang),
                description=t("squad.unregister_confirm", lang, name=assignments[0]),
                color=discord.Color.red())
            view = SquadUnregisterConfirmView(gid, cid, assignments[0])
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            options = [discord.SelectOption(label=sn, value=sn) for sn in assignments if sn != "__caster__"]
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


# ---------------------------------------------------------------------------
# Squad registration flow views
# ---------------------------------------------------------------------------

class SquadRegistrationView(BaseView):
    def __init__(self, guild_id, channel_id, event):
        super().__init__(timeout=300, title="Squad Registration")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_type = None
        self.selected_playstyle = None
        self.event = event

        sizes = _get_squad_sizes(event)
        lang = get_guild_language(guild_id)

        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=[
                discord.SelectOption(label=t("squad.type_infantry", lang, size=sizes["infantry"]), value="infantry", ),
                discord.SelectOption(label=t("squad.type_vehicle", lang, size=sizes["vehicle"]), value="vehicle"),
                discord.SelectOption(label=t("squad.type_heli", lang, size=sizes["heli"]), value="heli"),
            ],
            custom_id="squad_type_select", row=0)
        self.type_select.callback = self._type_selected
        self.add_item(self.type_select)

        self.playstyle_select = ui.Select(
            placeholder=t("squad.playstyle_select", lang),
            options=[
                discord.SelectOption(label="Casual", value="Casual"),
                discord.SelectOption(label="Normal", value="Normal"),
                discord.SelectOption(label="Focused", value="Focused"),
            ],
            custom_id="squad_playstyle_select", row=1)
        self.playstyle_select.callback = self._playstyle_selected
        self.add_item(self.playstyle_select)

        self.continue_button = ui.Button(label=t("squad.continue", lang), style=discord.ButtonStyle.success, disabled=True, row=2)
        self.continue_button.callback = self._continue
        self.add_item(self.continue_button)

    def _build_status_content(self):
        lang = get_guild_language(self.guild_id)
        sizes = _get_squad_sizes(self.event)
        lines = [f"**{t('squad.step_1_title', lang)}**", t("squad.step_1_desc", lang)]
        if self.selected_type:
            type_label = t(f"squad.type_{self.selected_type}", lang, size=sizes.get(self.selected_type, "?"))
            lines.append(t("squad.selected_type", lang, label=type_label))
        if self.selected_playstyle:
            lines.append(t("squad.selected_playstyle", lang, label=self.selected_playstyle))
        return "\n".join(lines)

    async def _type_selected(self, interaction):
        self.selected_type = self.type_select.values[0]
        self.continue_button.disabled = not (self.selected_type and self.selected_playstyle)
        await interaction.response.edit_message(content=self._build_status_content(), view=self)

    async def _playstyle_selected(self, interaction):
        self.selected_playstyle = self.playstyle_select.values[0]
        self.continue_button.disabled = not (self.selected_type and self.selected_playstyle)
        await interaction.response.edit_message(content=self._build_status_content(), view=self)

    async def _continue(self, interaction):
        if not self.selected_type or not self.selected_playstyle:
            return
        lang = get_guild_language(self.guild_id)
        modal = SquadNameModal(self.guild_id, self.channel_id, self.selected_type, self.selected_playstyle)
        await interaction.response.send_modal(modal)


class SquadNameModal(ui.Modal):
    def __init__(self, guild_id, channel_id, squad_type, playstyle):
        lang = get_guild_language(guild_id)
        super().__init__(title=t("squad.register_title", lang))
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_type = squad_type
        self.playstyle = playstyle

        self.squad_name = ui.TextInput(
            label=t("squad.name_label", lang),
            placeholder=t("squad.name_placeholder", lang),
            required=True, min_length=2, max_length=30)
        self.add_item(self.squad_name)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await register_squad(interaction, self.guild_id, self.channel_id,
                             self.squad_name.value.strip(), self.squad_type, self.playstyle)


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
        await interaction.response.defer(ephemeral=True)
        await unregister_squad(interaction, self.guild_id, self.channel_id, self.squad_name)

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
        await interaction.response.defer(ephemeral=True)
        await unregister_squad(interaction, self.guild_id, self.channel_id, selected)


# ---------------------------------------------------------------------------
# Admin action view
# ---------------------------------------------------------------------------

class AdminActionView(BaseView):
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=3600, title="Admin")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)

        for label_key, style, cb_name, row in [
            ("admin.add_squad", discord.ButtonStyle.success, "_add_squad", 0),
            ("admin.remove_squad", discord.ButtonStyle.danger, "_remove_squad", 0),
            ("admin.add_caster", discord.ButtonStyle.success, "_add_caster", 1),
            ("admin.remove_caster", discord.ButtonStyle.danger, "_remove_caster", 1),
            ("admin.edit_event", discord.ButtonStyle.primary, "_edit", 2),
            ("admin.delete_event", discord.ButtonStyle.danger, "_delete", 2),
        ]:
            btn = ui.Button(label=t(label_key, lang), style=style, row=row)
            btn.callback = getattr(self, cb_name)
            self.add_item(btn)

    async def _edit(self, interaction):
        lang = get_guild_language(self.guild_id)

        if interaction.user.id in _active_edit_sessions:
            await interaction.response.send_message(
                t("edit.active_session", lang), ephemeral=True)
            return

        event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(
                t("general.no_active_event", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.user.create_dm()
        except discord.Forbidden:
            await interaction.followup.send(
                t("edit.dm_blocked", lang), ephemeral=True)
            return

        _active_edit_sessions[interaction.user.id] = {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
        }
        await interaction.followup.send(t("edit.dm_sent", lang), ephemeral=True)
        bot.loop.create_task(
            _run_dm_edit_session(interaction.user, self.guild_id, self.channel_id, db_id))

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

    async def _add_squad(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        view = _AdminSquadRegView(self.guild_id, self.channel_id, event)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _remove_squad(self, interaction):
        lang = get_guild_language(self.guild_id)
        event, _, _ = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.response.send_message(t("general.no_active_event", lang), ephemeral=True)
            return
        squads = event.get("squads", {})
        waitlist = event.get("waitlist", [])
        options = []
        for name, data in squads.items():
            options.append(discord.SelectOption(label=name, value=name))
        for entry in waitlist:
            options.append(discord.SelectOption(label=f"[WL] {entry[0]}", value=entry[0]))
        if not options:
            await interaction.response.send_message(t("embed.no_entries", lang), ephemeral=True)
            return
        view = _AdminRemoveSquadView(self.guild_id, self.channel_id, options)
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

class _AdminSquadRegView(BaseView):
    """Admin add-squad: type select + playstyle select + continue → name modal."""
    def __init__(self, guild_id, channel_id, event):
        super().__init__(timeout=300, title="Admin Add Squad")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.selected_type = None
        self.selected_playstyle = None
        self.selected_user = None

        sizes = _get_squad_sizes(event)
        lang = get_guild_language(guild_id)

        self.type_select = ui.Select(
            placeholder=t("squad.type_select", lang),
            options=[
                discord.SelectOption(label=t("squad.type_infantry", lang, size=sizes["infantry"]), value="infantry"),
                discord.SelectOption(label=t("squad.type_vehicle", lang, size=sizes["vehicle"]), value="vehicle"),
                discord.SelectOption(label=t("squad.type_heli", lang, size=sizes["heli"]), value="heli"),
            ], row=0)
        self.type_select.callback = self._type_selected
        self.add_item(self.type_select)

        self.playstyle_select = ui.Select(
            placeholder=t("squad.playstyle_select", lang),
            options=[
                discord.SelectOption(label="Casual", value="Casual"),
                discord.SelectOption(label="Normal", value="Normal"),
                discord.SelectOption(label="Focused", value="Focused"),
            ], row=1)
        self.playstyle_select.callback = self._playstyle_selected
        self.add_item(self.playstyle_select)

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
        lines = [f"**{t('squad.step_1_title', lang)}**", t("squad.step_1_desc", lang)]
        if self.selected_type:
            type_label = t(f"squad.type_{self.selected_type}", lang, size=sizes.get(self.selected_type, "?"))
            lines.append(t("squad.selected_type", lang, label=type_label))
        if self.selected_playstyle:
            lines.append(t("squad.selected_playstyle", lang, label=self.selected_playstyle))
        if self.selected_user:
            lines.append(t("admin.selected_rep_user", lang, user=self.selected_user.display_name))
        return "\n".join(lines)

    def _all_selected(self):
        return self.selected_type and self.selected_playstyle and self.selected_user

    async def _type_selected(self, interaction):
        self.selected_type = self.type_select.values[0]
        self.continue_button.disabled = not self._all_selected()
        await interaction.response.edit_message(content=self._build_status(), view=self)

    async def _playstyle_selected(self, interaction):
        self.selected_playstyle = self.playstyle_select.values[0]
        self.continue_button.disabled = not self._all_selected()
        await interaction.response.edit_message(content=self._build_status(), view=self)

    async def _user_selected(self, interaction):
        self.selected_user = self.user_select.values[0]
        self.continue_button.disabled = not self._all_selected()
        await interaction.response.edit_message(content=self._build_status(), view=self)

    async def _continue(self, interaction):
        if not self._all_selected():
            return
        modal = _AdminSquadNameModal(self.guild_id, self.channel_id, self.selected_type, self.selected_playstyle, self.selected_user)
        await interaction.response.send_modal(modal)


class _AdminSquadNameModal(ui.Modal):
    """Admin add-squad step 2: enter squad name and register."""
    def __init__(self, guild_id, channel_id, squad_type, playstyle, rep_user):
        lang = get_guild_language(guild_id)
        super().__init__(title=t("squad.register_title", lang))
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.squad_type = squad_type
        self.playstyle = playstyle
        self.rep_user = rep_user
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

            existing, _ = _find_squad_name(event, squad_name)
            if existing is not None:
                await interaction.followup.send(t("admin.duplicate_squad", lang, name=existing), ephemeral=True)
                return

            sizes = _get_squad_sizes(event)
            size = sizes.get(self.squad_type, sizes["infantry"])
            squad_id = generate_squad_id(squad_name)
            available = event["max_player_slots"] - event["player_slots_used"]

            rep_name = self.rep_user.display_name
            rep_uid = str(self.rep_user.id)

            if size <= available:
                event["squads"][squad_name] = {
                    "type": self.squad_type, "playstyle": self.playstyle,
                    "size": size, "id": squad_id, "rep_name": rep_name,
                }
                event["player_slots_used"] += size
                status = t("admin.squad_added_registered", lang, pos=0)
            else:
                event["waitlist"].append((squad_name, self.squad_type, self.playstyle, size, squad_id, rep_name))
                wl_pos = len(event["waitlist"])
                status = t("admin.squad_added_waitlist", lang)

            add_user_assignment(user_assignments, rep_uid, squad_name)
            save_event(db_id, event, user_assignments)

        type_labels = {"infantry": "Infanterie" if lang == "de" else "Infantry",
                       "vehicle": "Fahrzeug" if lang == "de" else "Vehicle", "heli": "Heli"}
        type_label = type_labels.get(self.squad_type, self.squad_type)
        await interaction.followup.send(
            t("admin.squad_added", lang, name=squad_name, type=type_label, size=size, playstyle=self.playstyle, status=status),
            ephemeral=True)
        await send_to_log_channel(
            t("log.admin_squad_added", lang, user=interaction.user.name, squad=squad_name, type=type_label, size=size, playstyle=self.playstyle),
            guild=interaction.guild)
        await update_event_displays(gid, cid)


class _AdminRemoveSquadView(BaseView):
    """Admin remove-squad: select menu of all squads + waitlist."""
    def __init__(self, guild_id, channel_id, options):
        super().__init__(timeout=120, title="Remove Squad")
        self.guild_id = guild_id
        self.channel_id = channel_id
        lang = get_guild_language(guild_id)
        select = ui.Select(placeholder=t("admin.select_squad_remove", lang), options=options, row=0)
        select.callback = self._selected
        self.add_item(select)

    async def _selected(self, interaction):
        selected = interaction.data["values"][0]
        await interaction.response.defer(ephemeral=True)
        result = await unregister_squad(interaction, self.guild_id, self.channel_id, selected, is_admin=True)
        if result is not None:
            lang = get_guild_language(self.guild_id)
            await send_feedback(interaction, t("admin.squad_removed", lang, name=selected, freed=result), ephemeral=True)


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

            caster_name = None
            if target_uid in event["casters"]:
                caster_name = event["casters"][target_uid]["name"]
                del event["casters"][target_uid]
                event["caster_slots_used"] = max(0, event["caster_slots_used"] - 1)
                remove_user_assignment(user_assignments, target_uid, "__caster__")
                save_event(db_id, event, user_assignments)
                await _process_caster_waitlist(event, user_assignments, db_id, gid, cid)
            else:
                for i, (uid, name) in enumerate(event.get("caster_waitlist", [])):
                    if uid == target_uid:
                        caster_name = name
                        event["caster_waitlist"].pop(i)
                        remove_user_assignment(user_assignments, target_uid, "__caster__")
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


# ---------------------------------------------------------------------------
# DM edit session: helpers, views, main loop
# ---------------------------------------------------------------------------

def _format_property_value(event, key, vtype, lang):
    """Format a property value for display in the edit list."""
    not_set = t("edit.not_set", lang)
    val = event.get(key)
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

    return text, None


def _format_display_value(value, vtype, lang):
    """Format a parsed value for the confirmation embed."""
    if value is None:
        return t("edit.not_set", lang)
    if value == "__immediate__":
        return t("wizard.summary_reg_immediate", lang)
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


class _EditConfirmView(ui.View):
    def __init__(self, lang):
        super().__init__(timeout=300)
        self.result = None
        btn_yes = ui.Button(label=t("general.confirm", lang), style=discord.ButtonStyle.success)
        btn_yes.callback = self._confirm
        self.add_item(btn_yes)
        btn_no = ui.Button(label=t("general.cancel", lang), style=discord.ButtonStyle.secondary)
        btn_no.callback = self._cancel
        self.add_item(btn_no)

    async def _confirm(self, interaction):
        self.result = "confirm"
        await interaction.response.defer()
        self.stop()

    async def _cancel(self, interaction):
        self.result = "cancel"
        await interaction.response.defer()
        self.stop()


class _EditMoreView(ui.View):
    def __init__(self, lang):
        super().__init__(timeout=300)
        self.result = None
        btn_more = ui.Button(label=t("edit.yes_more", lang), style=discord.ButtonStyle.primary)
        btn_more.callback = self._more
        self.add_item(btn_more)
        btn_done = ui.Button(label=t("edit.no_done", lang), style=discord.ButtonStyle.secondary)
        btn_done.callback = self._done
        self.add_item(btn_done)

    async def _more(self, interaction):
        self.result = "more"
        await interaction.response.defer()
        self.stop()

    async def _done(self, interaction):
        self.result = "done"
        await interaction.response.defer()
        self.stop()


async def _run_dm_edit_session(user, guild_id, channel_id, db_id):
    """Run the full DM-based event editing conversation."""
    try:
        lang = get_guild_language(guild_id)
        cancel_word = t("edit.cancel_word", lang)

        def dm_check(m):
            return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

        def _is_cancel(msg):
            return msg.content.strip().lower() == cancel_word

        while True:
            # Re-load event fresh each iteration
            event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
            if not event:
                await user.send(t("general.no_active_event", lang))
                break

            # Build grouped embed property list
            groups = [
                ("edit.group.general", _EDIT_PROPERTIES[0:4]),
                ("edit.group.squad_config", _EDIT_PROPERTIES[4:12]),
                ("edit.group.extras", _EDIT_PROPERTIES[12:15]),
            ]
            edit_embed = discord.Embed(
                title=t("edit.title", lang),
                description=t("edit.select_property", lang),
                color=discord.Color.blue(),
            )
            for group_key, props in groups:
                field_lines = []
                for num, key, label_key, vtype, special in props:
                    current = _format_property_value(event, key, vtype, lang)
                    field_lines.append(f"`{num:>2}.` {t(label_key, lang).split('. ', 1)[-1]}:  `{current}`")
                edit_embed.add_field(
                    name=t(group_key, lang),
                    value="\n".join(field_lines),
                    inline=False,
                )
            edit_embed.set_footer(text=t("edit.footer_hint", lang))

            await user.send(embed=edit_embed)

            # Wait for property number
            try:
                reply = await bot.wait_for("message", check=dm_check, timeout=300)
            except asyncio.TimeoutError:
                await user.send(t("edit.timeout", lang))
                break

            if _is_cancel(reply):
                continue  # back to overview

            try:
                choice = int(reply.content.strip())
            except ValueError:
                await user.send(t("edit.invalid_number", lang, max=len(_EDIT_PROPERTIES)))
                continue

            if choice < 1 or choice > len(_EDIT_PROPERTIES):
                await user.send(t("edit.invalid_number", lang, max=len(_EDIT_PROPERTIES)))
                continue

            num, key, label_key, vtype, special = _EDIT_PROPERTIES[choice - 1]

            # Show current value and prompt for new one
            current_display = _format_property_value(event, key, vtype, lang)
            prompt = t("edit.current_value", lang, value=current_display) + "\n"

            if vtype == "image":
                prompt += t("edit.image_hint", lang)
            elif vtype == "reg_start":
                prompt += t("edit.reg_start_hint", lang)
            elif vtype == "string_nullable":
                prompt += t("edit.description_hint", lang)
            else:
                prompt += t("edit.enter_new_value", lang)

            prompt += "\n" + t("edit.cancel_hint", lang)
            await user.send(prompt)

            # Wait for new value
            try:
                value_msg = await bot.wait_for("message", check=dm_check, timeout=300)
            except asyncio.TimeoutError:
                await user.send(t("edit.timeout", lang))
                break

            if _is_cancel(value_msg):
                continue  # back to overview

            # Validate
            new_value, error_key = _validate_edit_value(value_msg, key, vtype, lang)
            if error_key:
                await user.send(t(error_key, lang))
                continue

            # Confirmation embed with buttons
            new_display = _format_display_value(new_value, vtype, lang)
            confirm_embed = discord.Embed(
                title=t("edit.confirm_change", lang),
                color=discord.Color.orange(),
            )
            confirm_embed.add_field(
                name=t("edit.old_value", lang), value=f"`{current_display}`", inline=True)
            confirm_embed.add_field(
                name=t("edit.new_value", lang), value=f"`{new_display}`", inline=True)

            confirm_view = _EditConfirmView(lang)
            await user.send(embed=confirm_embed, view=confirm_view)

            timed_out = await confirm_view.wait()
            if timed_out:
                await user.send(t("edit.timeout", lang))
                break
            if confirm_view.result != "confirm":
                continue  # back to overview

            # Apply change under guild lock
            lock = _get_guild_lock(guild_id)
            async with lock:
                event, user_assignments, db_id = _get_channel_event(guild_id, channel_id)
                if not event:
                    await user.send(t("general.no_active_event", lang))
                    break

                # Handle registration start special case
                if key == "registration_start_time":
                    if new_value == "__immediate__":
                        event["registration_open"] = True
                        event["registration_start_time"] = None
                    elif new_value is None:
                        event["registration_start_time"] = None
                    elif isinstance(new_value, datetime) and new_value <= datetime.now():
                        event["registration_open"] = True
                        event["registration_start_time"] = None
                    else:
                        event["registration_start_time"] = new_value
                        event["registration_open"] = False
                else:
                    event[key] = new_value

                # Side effects
                if special == "recalc_slots":
                    event["max_player_slots"] = event["server_max_players"] - event["max_caster_slots"]

                if key in ("date", "time"):
                    new_expiry = compute_expiry_date(event["date"], event.get("time"))
                    if new_expiry:
                        event["expiry_date"] = new_expiry

                save_event(db_id, event, user_assignments)

            # Update channel display
            await update_event_displays(guild_id, channel_id)

            # Log the edit
            if special == "recalc_slots":
                await user.send(t("edit.recalculated", lang, slots=event["max_player_slots"]))

            guild = bot.get_guild(guild_id)
            if guild:
                await send_to_log_channel(
                    t("log.event_edited", lang,
                      user=user.name,
                      property=t(label_key, lang),
                      name=event["name"]),
                    guild=guild)

            # Combined "updated + edit more?" with event link and buttons
            link = _build_event_message_link(event, channel_id, guild_id) or ""
            more_msg = t("edit.updated", lang, link=link)
            more_msg += "\n" + t("edit.edit_more_question", lang)
            more_view = _EditMoreView(lang)
            await user.send(more_msg, view=more_view)

            timed_out = await more_view.wait()
            if timed_out or more_view.result != "more":
                await user.send(t("edit.finished", lang))
                break

    except discord.Forbidden:
        logger.warning(f"DM edit session: user {user.id} has DMs disabled mid-session")
    except Exception as e:
        logger.error(f"Error in DM edit session for user {user.id}: {e}", exc_info=True)
        try:
            await user.send(t("general.error", get_guild_language(guild_id), error=str(e)))
        except Exception:
            pass
    finally:
        _active_edit_sessions.pop(user.id, None)


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
        await interaction.response.defer(ephemeral=True)

        lang = get_guild_language(self.guild_id)
        event, user_assignments, db_id = _get_channel_event(self.guild_id, self.channel_id)
        if not event:
            await interaction.followup.send(t("event.nothing_to_delete", lang), ephemeral=True)
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
        msg_id = event.get("event_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except Exception as e:
                logger.warning(f"Could not delete event embed: {e}")

        for ping_msg_id in event.get("ping_message_ids", []):
            try:
                ping_msg = await channel.fetch_message(ping_msg_id)
                await ping_msg.delete()
            except Exception:
                pass
        countdown_msg_id = event.get("countdown_message_id")
        if countdown_msg_id:
            try:
                cd_msg = await channel.fetch_message(countdown_msg_id)
                await cd_msg.delete()
            except Exception:
                pass

        # 3. Soft-delete in DB
        delete_event(db_id)

        await interaction.followup.send(t("event.deleted", lang, name=event_name), ephemeral=True)

    async def _cancel(self, interaction):
        if self.check_response(interaction):
            return
        lang = get_guild_language(self.guild_id)
        await interaction.response.edit_message(content=t("general.cancelled", lang), view=None)


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

        self.squad_rep_select = ui.MentionableSelect(
            placeholder=t("wizard.squad_rep_title", lang),
            min_values=0, max_values=25, row=0)
        self.squad_rep_select.callback = self._squad_rep_selected
        self.add_item(self.squad_rep_select)

        self.community_rep_select = ui.MentionableSelect(
            placeholder=t("wizard.community_rep_title", lang),
            min_values=0, max_values=25, row=1)
        self.community_rep_select.callback = self._community_rep_selected
        self.add_item(self.community_rep_select)

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
        self._squad_rep_users = []
        self._community_rep_roles = []
        self._community_rep_users = []
        self._ping_on_open = False

    async def _squad_rep_selected(self, interaction):
        self._squad_rep_roles = [v.id for v in self.squad_rep_select.values if isinstance(v, discord.Role)]
        self._squad_rep_users = [str(v.id) for v in self.squad_rep_select.values if isinstance(v, (discord.Member, discord.User))]
        await interaction.response.defer()

    async def _community_rep_selected(self, interaction):
        self._community_rep_roles = [v.id for v in self.community_rep_select.values if isinstance(v, discord.Role)]
        self._community_rep_users = [str(v.id) for v in self.community_rep_select.values if isinstance(v, (discord.Member, discord.User))]
        await interaction.response.defer()

    async def _ping_selected(self, interaction):
        self._ping_on_open = self.ping_select.values[0] == "yes"
        await interaction.response.defer()

    def _save_selections(self):
        if self._squad_rep_roles or self._squad_rep_users:
            self.event["squad_rep_role_ids"] = self._squad_rep_roles
            self.event["squad_rep_user_ids"] = self._squad_rep_users
        if self._community_rep_roles or self._community_rep_users:
            self.event["community_rep_role_ids"] = self._community_rep_roles
            self.event["community_rep_user_ids"] = self._community_rep_users
        self.event["ping_on_open"] = self._ping_on_open

    async def _continue(self, interaction):
        self._save_selections()
        lang = get_guild_language(self.guild_id)
        next_view = WizardCasterRolesView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                          self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.caster_roles_title', lang)}**\n{t('wizard.caster_roles_desc', lang)}",
            view=next_view)

    async def _skip(self, interaction):
        lang = get_guild_language(self.guild_id)
        next_view = WizardCasterRolesView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                          self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.caster_roles_title', lang)}**\n{t('wizard.caster_roles_desc', lang)}",
            view=next_view)


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

        done_btn = ui.Button(label=t("general.done", lang), style=discord.ButtonStyle.success, row=3)
        done_btn.callback = self._done
        self.add_item(done_btn)

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

    async def _done(self, interaction):
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
    COUNTDOWN_OPTIONS = [0, 10, 60, 300, 600, 900, 1800, 3600, 7200, 14400, 28800]  # seconds

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

    async def _continue(self, interaction):
        self._save_selections()
        lang = get_guild_language(self.guild_id)
        default_limit = self.event.get("max_squads_per_user", 1)
        next_view = WizardSquadLimitView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                         self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.squad_limit_title', lang)}**\n{t('wizard.squad_limit_desc', lang, default=default_limit)}",
            embed=None, view=next_view)

    async def _skip(self, interaction):
        lang = get_guild_language(self.guild_id)
        default_limit = self.event.get("max_squads_per_user", 1)
        next_view = WizardSquadLimitView(self.guild_id, self.channel_id, self.event, self.user_assignments,
                                         self.settings, self.interaction_user)
        await interaction.response.edit_message(
            content=f"**{t('wizard.squad_limit_title', lang)}**\n{t('wizard.squad_limit_desc', lang, default=default_limit)}",
            embed=None, view=next_view)


class WizardSquadLimitView(BaseView):
    """Step 4: configure max squads per user for this event."""

    def __init__(self, guild_id, channel_id, event, user_assignments, settings, interaction_user):
        super().__init__(timeout=300, title="Wizard Squad Limit")
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event = event
        self.user_assignments = user_assignments
        self.settings = settings
        self.interaction_user = interaction_user
        lang = get_guild_language(guild_id)

        current_default = event.get("max_squads_per_user", 1)
        options = []
        for n in range(1, 11):
            label = f"{n} Squad" if n == 1 else f"{n} Squads"
            options.append(discord.SelectOption(label=label, value=str(n), default=(n == current_default)))

        self.limit_select = ui.Select(placeholder=t("wizard.squad_limit_placeholder", lang),
                                      options=options, min_values=1, max_values=1, row=0)
        self.limit_select.callback = self._limit_selected
        self.add_item(self.limit_select)

        skip_btn = ui.Button(label=t("general.skip", lang), style=discord.ButtonStyle.secondary, row=1)
        skip_btn.callback = self._skip
        self.add_item(skip_btn)

        continue_btn = ui.Button(label=t("wizard.continue", lang), style=discord.ButtonStyle.success, row=1)
        continue_btn.callback = self._continue
        self.add_item(continue_btn)

        self._selected_limit = None

    async def _limit_selected(self, interaction):
        self._selected_limit = int(self.limit_select.values[0])
        await interaction.response.defer()

    async def _continue(self, interaction):
        if self._selected_limit is not None:
            self.event["max_squads_per_user"] = self._selected_limit
        embed = _build_confirmation_embed(self.event, self.guild_id)
        confirm_view = WizardConfirmationView(
            self.guild_id, self.channel_id, self.event, self.user_assignments,
            self.settings, self.interaction_user)
        await interaction.response.edit_message(content=None, embed=embed, view=confirm_view)

    async def _skip(self, interaction):
        embed = _build_confirmation_embed(self.event, self.guild_id)
        confirm_view = WizardConfirmationView(
            self.guild_id, self.channel_id, self.event, self.user_assignments,
            self.settings, self.interaction_user)
        await interaction.response.edit_message(content=None, embed=embed, view=confirm_view)


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
                        value=f"<t:{event_ts}:f> (<t:{event_ts}:R>)", inline=True)
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

    if event.get("registration_start_time") is not None:
        cd_seconds = event.get("countdown_seconds")
        if cd_seconds is not None and cd_seconds > 0:
            countdown_val = t(f"wizard.countdown_{cd_seconds}s", lang)
        elif cd_seconds == 0:
            countdown_val = t("wizard.countdown_none", lang)
        else:
            countdown_val = t("wizard.countdown_none", lang)
        embed.add_field(name=t("wizard.summary_countdown", lang), value=countdown_val, inline=True)

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
        f"**{t('settings.max_squads_per_user', lang)}:** {event.get('max_squads_per_user', '?')}\n"
        f"**{_unused_label}:** {_unused}"
    )
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
        view = EventActionView()
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
            ping_text = _build_ping_text(self.event, include_community_rep=True)
            if ping_text:
                try:
                    ping_msg = await channel.send(
                        content=f"{ping_text}" + t("reg.opened_announcement", lang, name=self.event["name"]),
                        allowed_mentions=discord.AllowedMentions(roles=True, users=True))
                    self.event.setdefault("ping_message_ids", []).append(ping_msg.id)
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

        self.server_max = ui.TextInput(
            label=t("event.server_max_label", lang),
            default=str(settings.get("server_max_players", 100)),
            required=True, max_length=5)
        self.add_item(self.server_max)

        self.max_casters = ui.TextInput(
            label=t("event.max_casters_label", lang),
            default=str(settings.get("max_caster_slots", 2)),
            required=True, max_length=3)
        self.add_item(self.max_casters)

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
        try:
            server_max = int(self.server_max.value.strip())
            max_casters = int(self.max_casters.value.strip())
            max_veh = int(self.max_vehicles.value.strip())
            max_heli = int(self.max_helis.value.strip())
        except ValueError:
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
            expiry_date=self.parsed["expiry_date"],
            server_max_players=server_max,
            max_caster_slots=max_casters,
            infantry_squad_size=inf_size,
            vehicle_squad_size=veh_size,
            heli_squad_size=heli_size,
            max_vehicle_squads=max_veh,
            max_heli_squads=max_heli,
        )

        # Launch wizard step 1
        wizard_view = WizardSquadRolesView(
            self.guild_id, self.channel_id, event, {},
            self.settings, self.author)
        wizard_msg = f"**{t('wizard.squad_roles_title', lang)}**\n{t('wizard.squad_roles_desc', lang)}"
        await interaction.response.send_message(wizard_msg, view=wizard_view, ephemeral=True)


class EventCreationModal(ui.Modal):
    def __init__(self, guild_id: int, channel_id: int):
        self.guild_id = guild_id
        self.channel_id = channel_id
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

        # Store parsed data and show bridge to server config modal
        parsed = {
            "name": self.event_name.value.strip(),
            "date": date_str,
            "time": time_str,
            "description": self.event_desc.value.strip() if self.event_desc.value else None,
            "reg_open": reg_open,
            "reg_start_time": reg_start_time,
            "expiry_date": compute_expiry_date(date_str, time_str),
        }
        bridge = _EventConfigBridgeView(self.guild_id, self.channel_id, settings, parsed, interaction.user)
        await interaction.response.send_message(
            t("event.config_prompt", lang), view=bridge, ephemeral=True)


# ############################# #
# BACKGROUND TASKS              #
# ############################# #

async def check_events_loop():
    """Background task: check registration start, reminders, expiry for all events."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            await asyncio.sleep(REGISTRATION_CHECK_INTERVAL)

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

                # ── Skip all registration messages if event is expired or closed ──
                expiry = event.get("expiry_date")
                is_expired = expiry and datetime.now() > expiry

                if is_expired:
                    # Write summary to log, then delete embed, then expire in DB
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

                    # Delete the embed message and ping messages
                    ch = bot.get_channel(channel_id)
                    if not ch:
                        try:
                            ch = await bot.fetch_channel(channel_id)
                        except Exception:
                            ch = None
                    if ch:
                        msg_id = event.get("event_message_id")
                        if msg_id:
                            try:
                                msg = await ch.fetch_message(msg_id)
                                await msg.delete()
                            except Exception as e:
                                logger.warning(f"Could not delete expired event embed: {e}")
                        for ping_msg_id in event.get("ping_message_ids", []):
                            try:
                                ping_msg = await ch.fetch_message(ping_msg_id)
                                await ping_msg.delete()
                            except Exception:
                                pass
                        countdown_msg_id = event.get("countdown_message_id")
                        if countdown_msg_id:
                            try:
                                cd_msg = await ch.fetch_message(countdown_msg_id)
                                await cd_msg.delete()
                            except Exception:
                                pass

                    expire_event(db_id)
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
                                content = f"{ping_text}" + t("reg.opens_soon", lang, name=event["name"], ts=ts)
                                countdown_msg = await ch.send(content=content, allowed_mentions=discord.AllowedMentions(roles=True))
                                event["countdown_message_id"] = countdown_msg.id
                                save_event(db_id, event, user_assignments)

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
                            # Delete countdown message if it exists
                            countdown_msg_id = event.pop("countdown_message_id", None)
                            if countdown_msg_id:
                                try:
                                    old_msg = await ch.fetch_message(countdown_msg_id)
                                    await old_msg.delete()
                                except Exception:
                                    pass
                                save_event(db_id, event, user_assignments)

                            caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
                            await send_event_details(ch, event, db_id, lang, caster_enabled)
                            if event.get("ping_on_open", False):
                                ping_text = _build_ping_text(event, include_community_rep=True)
                                if ping_text:
                                    content = f"{ping_text}" + t("reg.opened_announcement", lang, name=event["name"])
                                    ping_msg = await ch.send(content=content, allowed_mentions=discord.AllowedMentions(roles=True, users=True))
                                    event.setdefault("ping_message_ids", []).append(ping_msg.id)
                                    save_event(db_id, event, user_assignments)

                        await send_to_log_channel(t("log.reg_opened", lang, name=event["name"]), guild_id=guild_id)

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
                            if ch:
                                ping_text = _build_ping_text(event)
                                event_ts = int(event_dt.timestamp())
                                content = (f"{ping_text}**{event['name']}** <t:{event_ts}:R>!\n"
                                           f"Event-Start: <t:{event_ts}:f>")
                                caster_enabled = settings.get("caster_registration_enabled", True) and event.get("max_caster_slots", 2) > 0
                                embed = format_event_details(event, lang, caster_enabled)
                                view = EventActionView()
                                await ch.send(content=content, embed=embed, view=view,
                                              allowed_mentions=discord.AllowedMentions(roles=True))
                    except ValueError:
                        pass

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


@bot.tree.command(name="set_defaults", description="Set default event parameters (admin only)")
@app_commands.describe(
    server_max_players="Server player capacity",
    infantry_squad_size="Infantry squad size",
    vehicle_squad_size="Vehicle squad size",
    heli_squad_size="Heli squad size",
    max_vehicle_squads="Max vehicle squads",
    max_heli_squads="Max heli squads",
    max_caster_slots="Max caster slots",
    max_squads_per_user="Max squads per user",
    caster_registration="Enable caster registration",
    countdown_seconds="Seconds before registration start for countdown",
)
async def set_defaults_cmd(interaction: discord.Interaction,
                           server_max_players: int = None,
                           infantry_squad_size: int = None,
                           vehicle_squad_size: int = None,
                           heli_squad_size: int = None,
                           max_vehicle_squads: int = None,
                           max_heli_squads: int = None,
                           max_caster_slots: int = None,
                           max_squads_per_user: int = None,
                           caster_registration: bool = None,
                           countdown_seconds: int = None):
    if not await check_admin(interaction):
        return

    settings = get_guild_settings(interaction.guild.id)
    if not settings:
        settings = dict(DEFAULT_GUILD_SETTINGS)
    lang = settings.get("language", "de")

    changes = []
    mapping = {
        "server_max_players": (server_max_players, 1),
        "infantry_squad_size": (infantry_squad_size, 1),
        "vehicle_squad_size": (vehicle_squad_size, 1),
        "heli_squad_size": (heli_squad_size, 1),
        "max_vehicle_squads": (max_vehicle_squads, 0),
        "max_heli_squads": (max_heli_squads, 0),
        "max_caster_slots": (max_caster_slots, 0),
        "max_squads_per_user": (max_squads_per_user, 1),
        "registration_countdown_seconds": (countdown_seconds, 0),
    }

    for key, (val, min_val) in mapping.items():
        if val is not None:
            if val < min_val:
                await interaction.response.send_message(t("set.value_too_low", lang, min=min_val), ephemeral=True)
                return
            settings[key] = val
            changes.append(t(f"set.{key}", lang, value=val))

    if caster_registration is not None:
        settings["caster_registration_enabled"] = caster_registration
        state = t("set.caster_enabled", lang) if caster_registration else t("set.caster_disabled", lang)
        changes.append(t("set.caster_registration", lang, state=state))

    if not changes:
        # Show current settings
        embed = discord.Embed(title=t("settings.title", lang), color=discord.Color.blue())
        for key in DEFAULT_GUILD_SETTINGS:
            if key in ("organizer_role_id", "log_channel_id", "language"):
                continue
            label = t(f"settings.{key}", lang)
            embed.add_field(name=label, value=str(settings.get(key, "?")), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    save_guild_settings(interaction.guild.id, settings)
    await interaction.response.send_message("\n".join(changes), ephemeral=True)


@bot.tree.command(name="settings", description="Show current server settings")
async def settings_command(interaction: discord.Interaction):
    if not await check_guild_configured(interaction):
        return
    settings = get_guild_settings(interaction.guild.id)
    lang = settings.get("language", "de")

    embed = discord.Embed(title=t("settings.title", lang), color=discord.Color.blue())

    orga_role = interaction.guild.get_role(settings.get("organizer_role_id", 0))
    embed.add_field(name=t("settings.organizer_role", lang),
                    value=orga_role.name if orga_role else t("settings.not_set", lang), inline=True)

    log_ch_id = settings.get("log_channel_id")
    log_ch = interaction.guild.get_channel(log_ch_id) if log_ch_id else None
    embed.add_field(name=t("settings.log_channel", lang),
                    value=f"#{log_ch.name}" if log_ch else t("settings.not_set", lang), inline=True)

    embed.add_field(name=t("settings.language", lang), value=get_language_name(settings.get("language", "de")), inline=True)

    for key in ["server_max_players", "infantry_squad_size", "vehicle_squad_size", "heli_squad_size",
                "max_vehicle_squads", "max_heli_squads", "max_caster_slots", "max_squads_per_user"]:
        embed.add_field(name=t(f"settings.{key}", lang), value=str(settings.get(key, "?")), inline=True)

    enabled = settings.get("caster_registration_enabled", True)
    embed.add_field(name=t("settings.caster_registration", lang),
                    value=t("set.caster_enabled", lang) if enabled else t("set.caster_disabled", lang), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ############################# #
# SLASH COMMANDS — EVENTS       #
# ############################# #

@bot.tree.command(name="event", description="Create a new event in this channel (organizer only)")
async def event_command(interaction: discord.Interaction):
    if not await check_organizer(interaction):
        return
    lang = _lang(interaction)
    if channel_has_active_event(interaction.guild.id, interaction.channel_id):
        await interaction.response.send_message(t("event.already_exists_in_channel", lang), ephemeral=True)
        return
    modal = EventCreationModal(interaction.guild.id, interaction.channel_id)
    await interaction.response.send_modal(modal)


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


@bot.tree.command(name="open", description="Open registration immediately (organizer only)")
async def open_command(interaction: discord.Interaction):
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
        if event.get("registration_open", False):
            await send_feedback(interaction, t("reg.already_open", lang), ephemeral=True)
            return
        event["registration_open"] = True
        event["is_closed"] = False
        save_event(db_id, event, user_assignments)

    await send_feedback(interaction, t("reg.manually_opened", lang, name=event["name"]), ephemeral=True)

    settings = get_guild_settings(gid) or DEFAULT_GUILD_SETTINGS
    ch = bot.get_channel(cid)
    if ch and event.get("ping_on_open", False):
        ping_text = _build_ping_text(event, include_community_rep=True)
        if ping_text:
            content = f"{ping_text}" + t("reg.opened_announcement", lang, name=event["name"])
            ping_msg = await ch.send(content=content, allowed_mentions=discord.AllowedMentions(roles=True, users=True))
            event.setdefault("ping_message_ids", []).append(ping_msg.id)
            save_event(db_id, event, user_assignments)

    await update_event_displays(gid, cid)
    await send_to_log_channel(t("log.reg_opened", lang, name=event["name"]), guild=interaction.guild)


@bot.tree.command(name="close", description="Close registration (organizer only)")
async def close_command(interaction: discord.Interaction):
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
        event["is_closed"] = True
        event["registration_open"] = False
        save_event(db_id, event, user_assignments)

    await send_feedback(interaction, t("reg.manually_closed", lang, name=event["name"]), ephemeral=True)
    await send_to_log_channel(t("log.reg_closed", lang, user=interaction.user.name, name=event["name"]), guild=interaction.guild)
    await update_event_displays(gid, cid)

    # Edit tracked ping messages to show "closed"
    ch = bot.get_channel(cid)
    if ch:
        for ping_msg_id in event.get("ping_message_ids", []):
            try:
                ping_msg = await ch.fetch_message(ping_msg_id)
                await ping_msg.edit(
                    content=t("ping.reg_closed", lang, name=event["name"]),
                    allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                pass


@bot.tree.command(name="register", description="Register a squad (guided flow)")
async def register_command(interaction: discord.Interaction):
    if not await check_guild_configured(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    event, user_assignments, _ = _get_channel_event(gid, cid)
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

    user_id = str(interaction.user.id)
    max_squads = event.get("max_squads_per_user", 1)
    current = get_user_squad_names(user_assignments, user_id)
    if len(current) >= max_squads:
        await interaction.response.send_message(t("squad.max_reached", lang, current=len(current), max=max_squads), ephemeral=True)
        return

    view = SquadRegistrationView(gid, cid, event)
    await interaction.response.send_message(
        f"**{t('squad.step_1_title', lang)}**\n{t('squad.step_1_desc', lang)}",
        view=view, ephemeral=True)


@bot.tree.command(name="unregister", description="Unregister from the event")
async def unregister_command(interaction: discord.Interaction):
    if not await check_guild_configured(interaction):
        return
    gid = interaction.guild.id
    cid = interaction.channel_id
    lang = _lang(interaction)

    _, user_assignments, _ = _get_channel_event(gid, cid)
    if not user_assignments:
        await interaction.response.send_message(t("info.not_registered", lang), ephemeral=True)
        return

    user_id = str(interaction.user.id)
    assignments = get_user_assignments(user_assignments, user_id)
    if not assignments:
        await interaction.response.send_message(t("info.not_registered", lang), ephemeral=True)
        return

    if "__caster__" in assignments:
        embed = discord.Embed(title=t("caster.unregister_title", lang),
                              description=t("caster.unregister_confirm", lang), color=discord.Color.red())
        view = CasterUnregisterConfirmView(gid, cid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    elif len(assignments) == 1:
        embed = discord.Embed(title=t("squad.unregister_title", lang),
                              description=t("squad.unregister_confirm", lang, name=assignments[0]), color=discord.Color.red())
        view = SquadUnregisterConfirmView(gid, cid, assignments[0])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        options = [discord.SelectOption(label=sn, value=sn) for sn in assignments if sn != "__caster__"]
        view = UserSquadUnregisterSelector(gid, cid, options)
        await interaction.response.send_message(t("squad.pick_to_unregister", lang), view=view, ephemeral=True)


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
    app_commands.Choice(name="Squad rep roles", value="squad_rep_role_ids"),
    app_commands.Choice(name="Community rep roles (early access)", value="community_rep_role_ids"),
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

def _find_squad_name(event, squad_name):
    """Find the exact-cased squad name in squads or waitlist (case-insensitive). Returns (exact_name, location)."""
    lower = squad_name.strip().lower()
    for name in event.get("squads", {}):
        if name.lower() == lower:
            return name, "squads"
    for i, entry in enumerate(event.get("waitlist", [])):
        if entry[0].lower() == lower:
            return entry[0], "waitlist"
    return None, None


async def _squad_name_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for squad_name params -- lists squads + waitlist entries."""
    gid = interaction.guild.id
    cid = interaction.channel_id
    event, _, _ = _get_channel_event(gid, cid)
    if not event:
        return []
    names = list(event.get("squads", {}).keys())
    names += [entry[0] for entry in event.get("waitlist", [])]
    current_lower = current.lower()
    return [app_commands.Choice(name=n, value=n) for n in names if current_lower in n.lower()][:25]


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

        exact_name, location = _find_squad_name(event, squad_name)
        if exact_name is None:
            await send_feedback(interaction, t("admin.squad_not_found", lang, name=squad_name), ephemeral=True)
            return

        if location == "squads":
            old_size = event["squads"][exact_name]["size"]
            delta = new_size - old_size
            event["squads"][exact_name]["size"] = new_size
            event["player_slots_used"] = max(0, min(event["player_slots_used"] + delta, event["max_player_slots"]))
            save_event(db_id, event, user_assignments)
            if delta < 0:
                await _process_squad_waitlist(event, user_assignments, db_id, gid, cid, abs(delta))
        else:
            # In waitlist — update the tuple entry
            for i, entry in enumerate(event["waitlist"]):
                if entry[0].lower() == exact_name.lower():
                    old_size = entry[3]
                    lst = list(entry)
                    lst[3] = new_size
                    event["waitlist"][i] = tuple(lst)
                    break
            save_event(db_id, event, user_assignments)

    await send_feedback(interaction,
        t("admin.squad_edited", lang, name=exact_name, old=old_size, new=new_size),
        ephemeral=True)
    await send_to_log_channel(
        t("log.admin_squad_edited", lang, user=interaction.user.name, squad=exact_name, old=old_size, new=new_size),
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

    squad_wl = event.get("waitlist", [])
    caster_wl = event.get("caster_waitlist", [])

    if not squad_wl and not caster_wl:
        await send_feedback(interaction, t("admin.waitlist_empty", lang), ephemeral=True)
        return

    embed = discord.Embed(
        title=t("admin.waitlist_title", lang, name=event["name"]),
        color=discord.Color.orange())

    if squad_wl:
        lines = []
        for i, entry in enumerate(squad_wl, 1):
            squad_name, squad_type, playstyle, size, *_rest = entry
            type_labels = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
            lines.append(t("admin.waitlist_squad_entry", lang,
                          pos=i, name=squad_name, type=type_labels.get(squad_type, squad_type),
                          size=size, playstyle=playstyle))
        embed.add_field(name="Squads", value="\n".join(lines), inline=False)

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

    # Group by squad name
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
    for squad_name in sorted(squads_to_users.keys()):
        uids = squads_to_users[squad_name]
        display_name = squad_name if squad_name != "__caster__" else "Caster"
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
    header = ["Squad Name", "Squad Type", "Size", "Playstyle", "Rep Name", "Squad ID", "Status"]
    writer.writerow(header)

    status_registered = "Angemeldet" if lang == "de" else "Registered"
    status_waitlist = "Warteliste" if lang == "de" else "Waitlist"

    for name, data in event.get("squads", {}).items():
        writer.writerow([
            name, data.get("type", ""), data.get("size", 0),
            data.get("playstyle", ""), data.get("rep_name", ""),
            data.get("id", ""), status_registered,
        ])

    for entry in event.get("waitlist", []):
        squad_name, squad_type, playstyle, size, squad_id, *rest = entry
        rep_name = rest[0] if rest else ""
        writer.writerow([
            squad_name, squad_type, size, playstyle,
            rep_name, squad_id, status_waitlist,
        ])

    output.seek(0)
    date_str = event.get("date", "unknown").replace(".", "-")
    filename = f"squads_{date_str}.csv"
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
            "`/event` - Event erstellen (im aktuellen Kanal)\n"
            "`/delete_event` - Event im Kanal löschen\n"
            "`/open` / `/close` - Registrierung öffnen/schließen\n"
            "`/register` - Squad anmelden\n"
            "`/unregister` - Abmelden\n"
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
            "`/set_defaults` - Standard-Werte ändern\n"
            "`/settings` - Aktuelle Einstellungen anzeigen\n"
            "`/sync` - Slash-Commands synchronisieren\n"
            "`/test` - Test-Suite ausführen"
        ), inline=False)
    else:
        embed.add_field(name="Events", value=(
            "`/event` - Create event (in current channel)\n"
            "`/delete_event` - Delete event in channel\n"
            "`/open` / `/close` - Open/close registration\n"
            "`/register` - Register a squad\n"
            "`/unregister` - Unregister\n"
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
            "`/set_defaults` - Change default values\n"
            "`/settings` - Show current settings\n"
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
