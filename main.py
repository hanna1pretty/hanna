import os
import asyncio
import logging
import os

try:
    import uvloop
    uvloop.install()
except ImportError:
    uvloop = None

from pyrogram import Client
from config import (
    BOT_TOKEN, API_ID, API_HASH, EXTRA_TOKENS,
    PROXY_SCHEME, PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD,
)
from utils.helpers import init_db
from utils.logger import setup_logging
from handlers import start, api_manager, admin_tools, image, vision, chat, files, web

logger = logging.getLogger(__name__)

def make_client(token: str, bot_name: str, session_suffix: str = "") -> Client:
    """Buat satu instance Pyrogram Client."""
    proxy = None
    if PROXY_HOST:
        proxy = {
            "scheme": PROXY_SCHEME,
            "hostname": PROXY_HOST,
            "port": PROXY_PORT,
        }
        if PROXY_USERNAME:
            proxy["username"] = PROXY_USERNAME
        if PROXY_PASSWORD:
            proxy["password"] = PROXY_PASSWORD
    return Client(
        f"hanna_bot{session_suffix}",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=token,
        workdir="data",
        proxy=proxy,
    )

def register_all(app: Client, bot_name: str):
    """Daftarkan semua handler ke satu app."""
    start.register(app, bot_name)
    api_manager.register(app, bot_name)
    admin_tools.register(app, bot_name)
    image.register(app, bot_name)
    vision.register(app, bot_name)
    files.register(app, bot_name)
    web.register(app, bot_name)
    chat.register(app, bot_name)

async def run_bot(app: Client):
    await app.start()
    logger.info(f"Bot started: {app.name}")
    await asyncio.gather(asyncio.get_event_loop().create_future())  # run forever

async def main_async():
    setup_logging()
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    init_db()

    clients = []

    # Bot utama
    if BOT_TOKEN:
        app = make_client(BOT_TOKEN, "Hanna AI", "")
        register_all(app, "Hanna AI")
        clients.append(app)
        logger.info("Main bot registered.")

    # Bot tambahan (BOT_TOKEN_2, BOT_TOKEN_3, ...)
    for idx, token in enumerate(EXTRA_TOKENS, start=2):
        bot_name = f"Hanna AI Bot {idx}"
        app = make_client(token, bot_name, f"_{idx}")
        register_all(app, bot_name)
        clients.append(app)
        logger.info(f"Extra bot {idx} registered.")

    logger.info(f"Starting {len(clients)} bot(s)...")

    try:
        # Jalankan semua bot secara bersamaan
        await asyncio.gather(*[app.start() for app in clients])
        logger.info("All bots running. Press Ctrl+C to stop.")
        await asyncio.get_event_loop().create_future()  # run forever
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await asyncio.gather(
            *[app.stop() for app in clients if app.is_connected],
            return_exceptions=True,
        )
        logger.info("All bots stopped.")

if __name__ == "__main__":
    asyncio.run(main_async())
