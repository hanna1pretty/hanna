import base64
import os
import logging
from pyrogram import filters
from pyrogram.enums import ParseMode
from config import MAX_IMAGE_BYTES, MAX_PROMPT_LENGTH
from utils.ai import vision_completion
from utils.helpers import can_use_bot, can_use_model_async, check_public_limit, get_model
from utils.telegram_format import format_ai_response, split_raw_response

logger = logging.getLogger(__name__)

def register(app, bot_name: str = "default"):

    @app.on_message(filters.photo & filters.private)
    async def vision_handler(c, m):
        uid = m.from_user.id
        if not can_use_bot(uid):
            return await m.reply_text("Akses ditolak. Bot sedang dalam mode admin saja.")
        allowed, limit_message = await check_public_limit(uid, bot_name)
        if not allowed:
            return await m.reply_text(limit_message, parse_mode=ParseMode.HTML)

        prompt = (m.caption or "Describe this image in detail.").strip()
        if len(prompt) > MAX_PROMPT_LENGTH:
            return await m.reply_text(f"Caption terlalu panjang. Maksimum {MAX_PROMPT_LENGTH} karakter.")
        if (m.photo.file_size or 0) > MAX_IMAGE_BYTES:
            return await m.reply_text(
                f"Foto terlalu besar. Maksimum {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )
        wait_msg  = await m.reply_text("Sedang menganalisis gambar...")
        file_path = None

        try:
            file_path = await m.download()
            with open(file_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode("utf-8")

            active_model = get_model(uid, bot_name)
            model_allowed, model_message = await can_use_model_async(
                uid, "DeepSeek-V4-Flash-Vision-Exp", bot_name
            )
            if not model_allowed:
                return await wait_msg.edit_text(model_message, parse_mode=ParseMode.HTML)
            reply = await vision_completion(uid, active_model, prompt, b64_img, bot_name)

            chunks = split_raw_response(reply, 3900)
            await wait_msg.edit_text(format_ai_response(chunks[0]), parse_mode=ParseMode.HTML)
            for chunk in chunks[1:]:
                await m.reply_text(format_ai_response(chunk), parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.exception(f"Vision error uid={uid}: {e}")
            await wait_msg.edit_text("Gagal menganalisis gambar. Silakan coba lagi.")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
