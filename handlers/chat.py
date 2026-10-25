import asyncio
import logging
import time
import os

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified

from config import STREAM_UPDATE_INTERVAL
from utils.ai import StreamingError, chat_completion, stream_chat_completion
from utils.helpers import (
    add_history, can_use_bot_async, can_use_model_async, check_public_limit,
    get_history, get_model_async,
)
from utils.telegram_format import format_ai_response, split_raw_response
from utils.file_export import create_export_file, detect_export_format, should_export

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

    def __init__(self, message, stop_spinner: asyncio.Event | None = None):
        self.message = message
        self.stop_spinner = stop_spinner
        self.last_text = ""
        self.last_update = 0.0
        self.lock = asyncio.Lock()

    async def update(self, text: str, force: bool = False):
        if not text:
            return
        if self.stop_spinner:
            self.stop_spinner.set()
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
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    frames = [
        f"<code>{glyph}</code>"
        for glyph in spinner
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
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.8, STREAM_UPDATE_INTERVAL))
        except asyncio.TimeoutError:
            continue


async def _finalize_message(client, wait_msg, reply: str, prompt: str = "") -> None:
    reply = (reply or "").strip()
    if should_export(prompt, reply):
        extension = detect_export_format(prompt) or "txt"
        file_path = None
        try:
            file_path = await asyncio.to_thread(create_export_file, prompt, reply, extension)
            caption = (
                f"<b>FILE SIAP</b>\n"
                f"Format: <code>.{extension}</code>\n"
                "Dibuat otomatis oleh Hanna AI."
            )
            await client.send_document(
                wait_msg.chat.id, str(file_path), caption=caption,
                parse_mode=ParseMode.HTML,
            )
            await wait_msg.delete()
        except Exception:
            logger.exception("Could not create or send export file")
            await wait_msg.edit_text(
                "<b>File belum dapat dibuat</b>\n\n"
                "Coba lagi dengan format TXT atau Markdown, atau periksa log container.",
                parse_mode=ParseMode.HTML,
            )
        finally:
            if file_path:
                try:
                    os.remove(file_path)
                except OSError:
                    logger.warning("Could not remove export file %s", file_path)
        return
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
        wait_msg = await m.reply_text(
            "<code>⠋</code>",
            parse_mode=ParseMode.HTML,
        )
        stop_animation = asyncio.Event()
        animation_task = asyncio.create_task(_animate_placeholder(wait_msg, stop_animation))

        try:
            model, history = await asyncio.gather(
                get_model_async(uid, bot_name),
                get_history(uid, bot_name),
            )
            model_allowed, model_message = await can_use_model_async(uid, model, bot_name)
            if not model_allowed:
                stop_animation.set()
                await asyncio.gather(animation_task, return_exceptions=True)
                return await wait_msg.edit_text(model_message, parse_mode=ParseMode.HTML)
            await add_history(uid, "user", user_text, bot_name)
            editor = TelegramStreamEditor(wait_msg, stop_spinner=stop_animation)
            history_with_user = history + [{"role": "user", "content": user_text}]

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
                    stop_animation.set()
                    await editor.update("> Streaming tidak tersedia, mencoba mode normal...", force=True)
                    reply = await chat_completion(uid, model, history_with_user, bot_name)

            await add_history(uid, "assistant", reply, bot_name)
            await _finalize_message(c, wait_msg, reply, user_text)
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
