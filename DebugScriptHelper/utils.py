#!/usr/bin/env python3
"""
Utility functions for the DCN Event Registration Bot.

All formatting functions accept a ``lang`` parameter for i18n.
"""

import calendar
import hashlib
import io
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import Embed

from i18n import t
from config import ADMIN_IDS

logger = logging.getLogger("event_bot")

# ---------------------------------------------------------------------------
# Log channel — set per guild at runtime
# ---------------------------------------------------------------------------

# Map guild_id -> discord.TextChannel for log channels
_log_channels: dict[int, discord.TextChannel] = {}


def set_log_channel(guild_id: int, channel: discord.TextChannel):
    _log_channels[guild_id] = channel


def get_log_channel(guild_id: int) -> Optional[discord.TextChannel]:
    return _log_channels.get(guild_id)


async def send_to_log_channel(message: str, guild: discord.Guild = None,
                              guild_id: int = None, level: str = "INFO"):
    """Send a formatted message to the guild's log channel."""
    gid = guild_id or (guild.id if guild else None)
    if not gid:
        return False

    # Also log to file
    getattr(logger, level.lower(), logger.info)(message)

    channel = _log_channels.get(gid)
    if not channel:
        return False

    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🚨"}
    labels = {"INFO": "INFO", "WARNING": "WARNUNG", "ERROR": "FEHLER", "CRITICAL": "KRITISCH"}
    icon = icons.get(level, "ℹ️")
    label = labels.get(level, "INFO")
    formatted = f"{icon} **{label}**: {message}"

    try:
        await channel.send(formatted)
        return True
    except Exception as e:
        logger.error(f"Failed to send to log channel: {e}")
        return False


# ---------------------------------------------------------------------------
# Role / permission checks
# ---------------------------------------------------------------------------

def has_organizer_role(user, organizer_role_id: int) -> bool:
    """Check if user has the guild's organizer role or is a bot-level admin."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if not hasattr(user, "roles"):
        return False
    if organizer_role_id == 0:
        return False
    return any(role.id == organizer_role_id for role in user.roles)


def has_role(user, role_id: int) -> bool:
    """Check if user has a specific role by ID."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if not hasattr(user, "roles"):
        return False
    return any(role.id == role_id for role in user.roles)


def is_guild_admin(user) -> bool:
    """Check if user has Discord administrator permission or is bot-level admin."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if hasattr(user, "guild_permissions"):
        return user.guild_permissions.administrator
    return False


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string in format DD.MM.YYYY."""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        return None


def compute_expiry_date(date_str: str, time_str: str = None) -> Optional[datetime]:
    """Compute event expiry: 24 hours after event start."""
    event_dt = parse_date(date_str)
    if not event_dt:
        return None
    if time_str:
        try:
            hours, minutes = map(int, time_str.split(":"))
            event_dt = event_dt.replace(hour=hours, minute=minutes)
        except (ValueError, AttributeError):
            pass
    return event_dt + timedelta(days=1)


def parse_registration_start(value: str) -> Optional[datetime]:
    """Parse registration start time flexibly.

    Supports: DD.MM.YYYY HH:MM, DD.MM HH:MM, ISO 8601, 'sofort'/'now'.
    Returns datetime or None.
    """
    text = value.strip()
    if not text:
        return None

    # ISO 8601
    if len(text) >= 10 and text[4] == "-":
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    normalized = text.replace("/", ".").replace("-", ".")

    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    for fmt in ("%d.%m %H:%M", "%d.%m %H:%M:%S"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.replace(year=datetime.now().year)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Event creation defaults
# ---------------------------------------------------------------------------

def compute_last_sunday(reference_date=None):
    """Compute the last Sunday of the current or next month.

    If the last Sunday of the current month has already passed,
    returns the last Sunday of the next month.
    """
    now = reference_date or datetime.now()
    year, month = now.year, now.month

    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    days_since_sunday = (dt.weekday() + 1) % 7
    last_sunday = dt - timedelta(days=days_since_sunday)

    if last_sunday.date() >= now.date():
        return last_sunday

    # Advance to next month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    days_since_sunday = (dt.weekday() + 1) % 7
    return dt - timedelta(days=days_since_sunday)



def compute_reg_start_15th(hour=15, minute=55, reference_date=None):
    """Compute the 15th of the current or next month at the given time.

    If the 15th at the specified time has already passed this month,
    returns the 15th of the next month.
    """
    now = reference_date or datetime.now()
    year, month = now.year, now.month

    candidate = datetime(year, month, 15, hour, minute)
    if candidate > now:
        return candidate

    # Advance to next month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 15, hour, minute)


def resolve_event_defaults():
    """Resolve .env event defaults into concrete pre-fill strings.

    Returns dict with keys 'date', 'time', 'reg_start', each either
    a formatted string or empty string (no pre-fill).
    """
    from config import EVENT_DEFAULT_DATE, EVENT_DEFAULT_TIME, EVENT_DEFAULT_REG_START

    result = {"date": "", "time": "", "reg_start": ""}

    if EVENT_DEFAULT_DATE.lower() == "last_sunday":
        result["date"] = compute_last_sunday().strftime("%d.%m.%Y")
    elif EVENT_DEFAULT_DATE:
        result["date"] = EVENT_DEFAULT_DATE

    if EVENT_DEFAULT_TIME:
        result["time"] = EVENT_DEFAULT_TIME

    if EVENT_DEFAULT_REG_START:
        parsed = parse_registration_start(EVENT_DEFAULT_REG_START)
        if parsed:
            result["reg_start"] = parsed.strftime("%d.%m.%Y %H:%M")
        else:
            result["reg_start"] = EVENT_DEFAULT_REG_START

    return result


# ---------------------------------------------------------------------------
# Squad ID generation
# ---------------------------------------------------------------------------

def generate_squad_id(squad_name: str) -> str:
    unique_base = f"{squad_name}_{int(time.time())}"
    return hashlib.md5(unique_base.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# Event summary (for log channel before deletion/expiry)
# ---------------------------------------------------------------------------

def build_event_summary_embed(event: dict, lang: str = "de") -> Embed:
    """Build a summary embed for a completed/expired/deleted event."""
    embed = Embed(
        title=t("event.summary_title", lang, name=event.get("name", "?")),
        color=discord.Color.orange(),
    )

    date_str = event.get("date", "?")
    time_str = event.get("time", "?")
    embed.add_field(name=t("event.summary_date", lang), value=f"{date_str} {time_str}", inline=True)

    squads = event.get("squads", {})
    waitlist = event.get("waitlist", [])
    embed.add_field(
        name=t("event.summary_squads", lang),
        value=f"{len(squads)} (+{len(waitlist)} {t('embed.waitlist_label', lang, count=len(waitlist))})",
        inline=True,
    )

    casters = event.get("casters", {})
    caster_wl = event.get("caster_waitlist", [])
    embed.add_field(
        name=t("event.summary_casters", lang),
        value=f"{len(casters)} (+{len(caster_wl)})",
        inline=True,
    )

    used = event.get("player_slots_used", 0)
    max_slots = event.get("max_player_slots", 0)
    embed.add_field(
        name=t("event.summary_players", lang),
        value=t("event.summary_slots_used", lang, used=used, max=max_slots),
        inline=False,
    )

    # List squads
    if squads:
        lines = []
        for name, data in squads.items():
            type_map = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
            tl = type_map.get(data.get("type", ""), "?")
            rep = data.get("rep_name", "")
            rep_suffix = f" — {rep}" if rep else ""
            lines.append(f"[{data.get('playstyle', 'Normal')}] **{name}** ({tl}, {data.get('size', 0)}){rep_suffix}")
        embed.add_field(
            name=f"{t('embed.squads_label', lang)} ({len(squads)})",
            value="\n".join(lines[:25]) or "—",
            inline=False,
        )

    if casters:
        caster_lines = [f"**{d.get('name', '?')}**" for d in casters.values()]
        embed.add_field(
            name=f"{t('event.summary_casters', lang)} ({len(casters)})",
            value="\n".join(caster_lines[:10]) or "—",
            inline=False,
        )

    embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))
    return embed


# ---------------------------------------------------------------------------
# Format event embed (main display)
# ---------------------------------------------------------------------------

def format_event_details(event: dict, lang: str = "de",
                         caster_enabled: bool = True) -> Embed | str:
    """Format event details as Discord embed."""
    if not event:
        return t("general.no_active_event", lang)

    if not event.get("name") or not event.get("date"):
        return t("general.no_active_event", lang)

    embed = Embed(
        title=t("embed.title", lang, name=event["name"]),
        description=event.get("description") or t("embed.no_description", lang),
        color=discord.Color.blue(),
    )

    # Event start (Discord timestamp)
    event_date_str = event["date"]
    event_time_str = event.get("time", "20:00")
    try:
        event_dt = datetime.strptime(f"{event_date_str} {event_time_str}", "%d.%m.%Y %H:%M")
        event_ts = int(event_dt.timestamp())
        embed.add_field(name=t("embed.event_start", lang), value=f"<t:{event_ts}:f> (<t:{event_ts}:R>)", inline=True)
    except ValueError:
        embed.add_field(name=t("embed.event_start", lang), value=f"{event_date_str} {event_time_str}", inline=True)

    # Registration status
    reg_open = event.get("registration_open", False)
    is_closed = event.get("is_closed", False)
    if is_closed:
        reg_status = t("reg.closed", lang)
    elif reg_open:
        reg_status = t("reg.open", lang)
    else:
        start_time = event.get("registration_start_time")
        if start_time and isinstance(start_time, datetime):
            ts = int(start_time.timestamp())
            reg_status = t("reg.opens_at", lang, ts=ts)
        else:
            reg_status = t("reg.not_open_yet", lang)
    embed.add_field(name=t("embed.registration", lang), value=reg_status, inline=True)

    # Reminder
    reminder_minutes = event.get("event_reminder_minutes")
    if reminder_minutes:
        if event.get("event_reminder_sent", False):
            embed.add_field(name=t("embed.reminder", lang),
                            value=t("embed.reminder_sent", lang, minutes=reminder_minutes), inline=True)
        else:
            embed.add_field(name=t("embed.reminder", lang),
                            value=t("embed.reminder_value", lang, minutes=reminder_minutes), inline=True)

    # Slot overview
    server_cap = event.get("server_max_players", 100)
    inf_size = event.get("infantry_squad_size", 6)
    veh_size = event.get("vehicle_squad_size", 2)
    heli_size = event.get("heli_squad_size", 1)
    max_vehicles = event.get("max_vehicle_squads", 5)
    max_helis = event.get("max_heli_squads", 2)
    max_casters = event.get("max_caster_slots", 2)
    max_squads_user = event.get("max_squads_per_user", 1)

    player_used = event.get("player_slots_used", 0)
    max_players = event.get("max_player_slots", server_cap)
    available = max_players - player_used

    squads_all = event.get("squads", {})
    waitlist = event.get("waitlist", [])
    vehicle_count = sum(1 for d in squads_all.values() if d.get("type") == "vehicle")
    vehicle_count += sum(1 for e in waitlist if e[1] == "vehicle")
    heli_count = sum(1 for d in squads_all.values() if d.get("type") == "heli")
    heli_count += sum(1 for e in waitlist if e[1] == "heli")
    infantry_count = sum(1 for d in squads_all.values() if d.get("type") == "infantry")
    infantry_count += sum(1 for e in waitlist if e[1] == "infantry")

    vehicle_player_slots = max_vehicles * veh_size
    heli_player_slots = max_helis * heli_size
    infantry_player_slots = server_cap - max_casters - vehicle_player_slots - heli_player_slots
    max_inf_squads = infantry_player_slots // inf_size if inf_size > 0 else 0

    slot_lines = [
        t("embed.server_slots", lang, cap=server_cap, free=available),
        t("embed.infantry_squads", lang, count=infantry_count, max=max_inf_squads, size=inf_size),
        t("embed.vehicle_squads", lang, count=vehicle_count, max=max_vehicles, size=veh_size),
        t("embed.heli_squads", lang, count=heli_count, max=max_helis, size=heli_size),
        t("embed.max_squads_per_user", lang, max=max_squads_user),
    ]
    embed.add_field(name=t("embed.available_slots", lang), value="\n".join(slot_lines), inline=False)

    # Caster slots
    if caster_enabled:
        caster_used = event.get("caster_slots_used", 0)
        caster_free = max_casters - caster_used
        embed.add_field(
            name=t("embed.caster_slots", lang),
            value=t("embed.caster_slots_value", lang, free=caster_free, used=caster_used, max=max_casters),
            inline=True,
        )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Squads by type
    squads = event.get("squads", {})
    infantry_squads = {n: d for n, d in squads.items() if d.get("type") == "infantry"}
    vehicle_squads = {n: d for n, d in squads.items() if d.get("type") == "vehicle"}
    heli_squads = {n: d for n, d in squads.items() if d.get("type") == "heli"}

    for squad_group, type_key, max_count in [
        (infantry_squads, "infantry", max_inf_squads),
        (vehicle_squads, "vehicle", max_vehicles),
        (heli_squads, "heli", max_helis),
    ]:
        if squad_group:
            text = ""
            label_key = f"embed.{type_key}_label"
            for squad_name, data in squad_group.items():
                playstyle = data.get("playstyle", "Normal")
                size = data.get("size", 0)
                rep = data.get("rep_name")
                rep_suffix = f" — {rep}" if rep else ""
                text += f"[{playstyle}] **{squad_name}** ({size}){rep_suffix}\n"
            embed.add_field(
                name=t(label_key, lang, count=len(squad_group), max=max_count),
                value=text,
                inline=False,
            )

    if not infantry_squads and not vehicle_squads and not heli_squads:
        embed.add_field(name=t("embed.squads_label", lang), value=t("embed.no_squads", lang), inline=False)

    # Casters
    if caster_enabled:
        casters = event.get("casters", {})
        if casters:
            caster_text = "\n".join(f"**{d.get('name', '?')}**" for d in casters.values())
            embed.add_field(name=t("embed.caster_label", lang, count=len(casters)), value=caster_text, inline=False)

    # Waitlist
    if waitlist:
        wl_text = ""
        for i, entry in enumerate(waitlist):
            squad_name, squad_type, playstyle, size, squad_id, *_rest = entry
            rep_name = _rest[0] if _rest else None
            type_map = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
            tl = type_map.get(squad_type, squad_type)
            rep_suffix = f" — {rep_name}" if rep_name else ""
            wl_text += f"{i+1}. [{playstyle}] **{squad_name}** ({tl}, {size}){rep_suffix}\n"
        embed.add_field(name=t("embed.waitlist_label", lang, count=len(waitlist)), value=wl_text, inline=False)

    # Caster waitlist
    if caster_enabled:
        caster_wl = event.get("caster_waitlist", [])
        if caster_wl:
            cwl_text = "\n".join(f"{i+1}. **{name}**" for i, (_, name) in enumerate(caster_wl))
            embed.add_field(name=t("embed.caster_waitlist_label", lang, count=len(caster_wl)), value=cwl_text, inline=False)

    # Image
    embed_image_url = event.get("embed_image_url")
    if embed_image_url:
        embed.set_image(url=embed_image_url)

    embed.set_footer(text=t("embed.footer", lang))
    return embed


# ---------------------------------------------------------------------------
# Log file management
# ---------------------------------------------------------------------------

LOG_FILE_PATH = "discord_bot.log"
LOG_BACKUP_FOLDER = "log_backups"


def export_log_file() -> Optional[dict]:
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return None
        buf = io.BytesIO()
        with open(LOG_FILE_PATH, "rb") as f:
            buf.write(f.read())
        buf.seek(0)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return {"buffer": buf, "filename": f"log_export_{ts}.log"}
    except Exception as e:
        logger.error(f"Error exporting log: {e}")
        return None


def clear_log_file() -> bool:
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return False
        os.makedirs(LOG_BACKUP_FOLDER, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        shutil.copy2(LOG_FILE_PATH, f"{LOG_BACKUP_FOLDER}/log_backup_{ts}.log")
        with open(LOG_FILE_PATH, "w") as f:
            f.write(f"--- Log reset: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        return True
    except Exception as e:
        logger.error(f"Error clearing log: {e}")
        return False
