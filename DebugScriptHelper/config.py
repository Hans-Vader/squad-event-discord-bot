#!/usr/bin/env python3
"""
Minimal configuration for the Event Registration Bot.

Only the Discord bot token is read from environment variables.
All server-specific settings (organizer role, squad sizes, language, etc.)
are stored per-guild in the database and managed via /setup and /set_* commands.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("config")

# ── The only environment variable ─────────────────────────────────────────
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    logger.warning("DISCORD_BOT_TOKEN not found in environment variables")

# ── Optional: admin user IDs for bot-level superadmin (bypass all checks) ─
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [aid.strip() for aid in _admin_ids_raw.split(",") if aid.strip()]

# ── Background task interval (seconds) ────────────────────────────────────
REGISTRATION_CHECK_INTERVAL = 10
REGISTRATION_CHECK_INTERVAL_FAST = 1     # used near registration open
REGISTRATION_CRITICAL_WINDOW = 60        # how far ahead (seconds) to switch to fast polling

if REGISTRATION_CRITICAL_WINDOW <= REGISTRATION_CHECK_INTERVAL:
    raise ValueError(
        f"REGISTRATION_CRITICAL_WINDOW ({REGISTRATION_CRITICAL_WINDOW}s) must be greater than "
        f"REGISTRATION_CHECK_INTERVAL ({REGISTRATION_CHECK_INTERVAL}s), otherwise the fast polling "
        f"window may be missed entirely."
    )

# ── Debug mode ────────────────────────────────────────────────────────────
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ── Event creation defaults (pre-filled in modal) ────────────────────────
EVENT_DEFAULT_DATE = os.getenv("EVENT_DEFAULT_DATE", "last_sunday")
EVENT_DEFAULT_TIME = os.getenv("EVENT_DEFAULT_TIME", "20:00")
EVENT_DEFAULT_REG_START = os.getenv("EVENT_DEFAULT_REG_START", "")
