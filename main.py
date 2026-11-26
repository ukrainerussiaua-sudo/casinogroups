"""Точка входа для хостинга (запускает `python main.py`). Вся логика — в bot.py."""
import asyncio

import bot

if __name__ == "__main__":
    asyncio.run(bot.main())
