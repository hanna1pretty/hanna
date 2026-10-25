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
from utils.telegram_format import format_ai_response, split_raw_response

logger = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4096
FORMAT_LIMIT = 3900

RESERVED_COMMANDS = [
    "start", "myid", "clear", "export", "img", "image", "help",
    "api", "apikey", "balance", "saldo", "limits", "setbalance",
    "setkey", "seturl", "setprovider", "addmodel", "delmodel",
    "premium", "grantpremium", "premiumusers", "revokepremium",
    "ping", "status", "adminhelp", "admin_help",
]


class TelegramStreamEditor:
    """Throttle Telegram edits while rendering partial AI Markdown as HTML."""

    def __init__(self, message):
        self.message = message
        self.last_text = ""
        self.last_update = 0.0
        self.lock = asyncio.Lock()

    async def update(self, text: str, force: bool = False):
        if not text:
            return
        async with self.lock:
            now = time.monotonic()
            if not force and now - self.last_update < STREAM_UPDATE_INTERVAL:
                return
            rendered = format_ai_response(text)
            if len(rendered) > TELEGRAM_LIMIT:
                return
            if rendered == self.last_text:
                return
            try:
                await self.message.edit_text(rendered, parse_mode=ParseMode.HTML)
                self.last_text = rendered
                self.last_update = now
            except MessageNotModified:
                self.last_text = rendered
                self.last_update = now
            except FloodWait as error:
                logger.warning("Telegram FloodWait during stream: %ss", error.value)
            except Exception:
                logger.warning("Could not update streaming message", exc_info=True)


async def _animate_placeholder(message, stop_event: asyncio.Event):
    frames = [
        "<b>Hanna sedang menulis</b>",
        "<b>Hanna sedang menulis.</b>",
        "<b>Hanna sedang menulis..</b>",
        "<b>Hanna sedang menulis...</b>",
    ]
    index = 0
    while not stop_event.is_set():
        try:
            await message.edit_text(frames[index % len(frames)], parse_mode=ParseMode.HTML)
        except (MessageNotModified, FloodWait):
            pass
        except Exception:
            logger.debug("Could not animate placeholder", exc_info=True)
        index += 1
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.55)
        except asyncio.TimeoutError:
            continue


async def _finalize_message(client, wait_msg, reply: str) -> None:
    reply = (reply or "").strip()
    chunks = split_raw_response(reply, FORMAT_LIMIT)
    first = format_ai_response(chunks[0])
    if len(chunks) == 1 and len(first) <= TELEGRAM_LIMIT:
        try:
            await wait_msg.edit_text(first, parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass
        return

    try:
        await wait_msg.edit_text(first, parse_mode=ParseMode.HTML)
    except Exception:
        await wait_msg.delete()
    for chunk in chunks[1:]:
        await client.send_message(
            wait_msg.chat.id,
            format_ai_response(chunk),
            parse_mode=ParseMode.HTML,
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
        wait_msg = await m.reply_text("<b>Hanna sedang menulis</b>", parse_mode=ParseMode.HTML)
        stop_animation = asyncio.Event()
        animation_task = asyncio.create_task(_animate_placeholder(wait_msg, stop_animation))

        try:
            model, history = await asyncio.gather(
                get_model_async(uid, bot_name),
                get_history(uid, bot_name),
            )
            await add_history(uid, "user", user_text, bot_name)
            editor = TelegramStreamEditor(wait_msg)
            history_with_user = history + [{"role": "user", "content": user_text}]
            stop_animation.set()
            await asyncio.gather(animation_task, return_exceptions=True)

            try:
                reply = await stream_chat_completion(
                    uid, model, history_with_user, bot_name,
                    on_text=editor.update,
                )
            except StreamingError as error:
                if error.partial_text:
                    reply = error.partial_text + "\n\n> Respons streaming terhenti."
                    logger.warning("Partial streaming response for uid=%s: %s", uid, error)
                else:
                    logger.warning("Streaming unavailable for uid=%s; using normal mode: %s", uid, error)
                    await editor.update("> Streaming tidak tersedia, mencoba mode normal...", force=True)
                    reply = await chat_completion(uid, model, history_with_user, bot_name)

            await add_history(uid, "assistant", reply, bot_name)
            await _finalize_message(c, wait_msg, reply)
        except Exception:
            logger.exception("chat_handler error uid=%s", uid)
            try:
                await wait_msg.edit_text(
                    "<b>Terjadi kesalahan</b>\n\nCoba lagi nanti.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                logger.warning("Could not show chat error uid=%s", uid, exc_info=True)
        finally:
            stop_animation.set()
            if not animation_task.done():
                animation_task.cancel()
            await asyncio.gather(animation_task, return_exceptions=True)
