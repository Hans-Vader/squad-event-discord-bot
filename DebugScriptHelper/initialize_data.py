#!/usr/bin/env python3
"""
Initialize the database with the new schema.
Run this once before starting the bot, or let the bot create it automatically on startup.
"""

from database import init_db

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
