import asyncio
import logging
import time

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified

from config import STREAM_UPDATE_INTERVAL
from utils.ai import StreamingError, chat_completion, stream_chat_completion
from utils.helpers import (
    add_history, can_use_bot_async, check_public_limit, get_history,
    get_model_async,
)

logger = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4096

RESERVED_COMMANDS = [
    "start", "myid", "clear", "export", "img", "image", "help",
    "api", "apikey", "balance", "saldo", "limits", "setbalance",
    "setkey", "seturl", "setprovider", "addmodel", "delmodel",
    "premium", "grantpremium", "premiumusers", "revokepremium",
    "ping", "status", "adminhelp", "admin_help",
]


class TelegramStreamEditor:
    """Throttle Telegram edits so one API token does not cause FloodWait."""

    def __init__(self, message):
        self.message = message
        self.last_text = ""
        self.last_update = 0.0
        self.lock = asyncio.Lock()

    async def update(self, text: str, force: bool = False):
        if not text or len(text) > TELEGRAM_LIMIT:
            return
        async with self.lock:
            now = time.monotonic()
            if not force and now - self.last_update < STREAM_UPDATE_INTERVAL:
                return
            if text == self.last_text:
                return
            try:
                await self.message.edit_text(text, parse_mode=ParseMode.DISABLED)
                self.last_text = text
                self.last_update = now
            except MessageNotModified:
                self.last_text = text
                self.last_update = now
            except FloodWait as error:
                logger.warning("Telegram FloodWait during stream: %ss", error.value)
            except Exception:
                logger.warning("Could not update streaming message", exc_info=True)


async def _finalize_message(client, wait_msg, reply: str) -> None:
    reply = (reply or "").strip() or "⚠️ AI mengembalikan jawaban kosong."
    if len(reply) <= TELEGRAM_LIMIT:
        try:
            await wait_msg.edit_text(reply, parse_mode=ParseMode.DISABLED)
        except MessageNotModified:
            pass
        return

    try:
        await wait_msg.delete()
    except Exception:
        logger.debug("Could not delete long-response placeholder", exc_info=True)
    for start in range(0, len(reply), TELEGRAM_LIMIT):
        await client.send_message(
            wait_msg.chat.id,
            reply[start:start + TELEGRAM_LIMIT],
            parse_mode=ParseMode.DISABLED,
        )


def register(app, bot_name: str = "default"):
    @app.on_message(filters.text & filters.private & ~filters.command(RESERVED_COMMANDS))
    async def chat_handler(c, m):
        uid = m.from_user.id
        if not await can_use_bot_async(uid):
            return await m.reply_text(
                f"Akses ditolak. Bot sedang dalam mode admin saja.\nID kamu: {uid}"
            )
        allowed, limit_message = await check_public_limit(uid, bot_name)
        if not allowed:
            return await m.reply_text(limit_message, parse_mode=ParseMode.HTML)

        user_text = (m.text or "").strip()
        wait_msg = await m.reply_text("⏳ Hanna sedang menulis...", parse_mode=ParseMode.DISABLED)

        try:
            model, history = await asyncio.gather(
                get_model_async(uid, bot_name),
                get_history(uid, bot_name),
            )
            await add_history(uid, "user", user_text, bot_name)
            editor = TelegramStreamEditor(wait_msg)
            history_with_user = history + [{"role": "user", "content": user_text}]

            try:
                reply = await stream_chat_completion(
                    uid, model, history_with_user, bot_name,
                    on_text=editor.update,
                )
            except StreamingError as error:
                if error.partial_text:
                    reply = error.partial_text + "\n\n⚠️ Respons streaming terhenti."
                    logger.warning("Partial streaming response for uid=%s: %s", uid, error)
                else:
                    logger.warning("Streaming unavailable for uid=%s; using normal mode: %s", uid, error)
                    await editor.update("⏳ Streaming tidak tersedia, mencoba mode normal...", force=True)
                    reply = await chat_completion(uid, model, history_with_user, bot_name)

            await add_history(uid, "assistant", reply, bot_name)
            await _finalize_message(c, wait_msg, reply)
        except Exception:
            logger.exception("chat_handler error uid=%s", uid)
            try:
                await wait_msg.edit_text(
                    "⚠️ Terjadi kesalahan saat memproses pesan. Coba lagi nanti.",
                    parse_mode=ParseMode.DISABLED,
                )
            except Exception:
                logger.warning("Could not show chat error uid=%s", uid, exc_info=True)
