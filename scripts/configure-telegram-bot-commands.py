#!/usr/bin/env python3
"""Publish WaiComputer Telegram BotCommand menu."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.routes.telegram import TELEGRAM_BOT_COMMANDS  # noqa: E402
from app.core.telegram_client import TelegramBotClient  # noqa: E402


async def main() -> None:
    await TelegramBotClient().set_my_commands(TELEGRAM_BOT_COMMANDS)
    print("Telegram bot commands configured.")


if __name__ == "__main__":
    asyncio.run(main())
