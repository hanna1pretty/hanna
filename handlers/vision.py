import base64
import os
import logging
from pyrogram import filters
from config import MAX_IMAGE_BYTES, MAX_PROMPT_LENGTH
from utils.ai import vision_completion
from utils.helpers import get_model, can_use_bot

logger = logging.getLogger(__name__)

def register(app, bot_name: str = "default"):

    @app.on_message(filters.photo & filters.private)
    async def vision_handler(c, m):
        uid = m.from_user.id
        if not can_use_bot(uid):
            return await m.reply_text("Access denied. Admin only.")

        prompt = (m.caption or "Describe this image in detail.").strip()
        if len(prompt) > MAX_PROMPT_LENGTH:
            return await m.reply_text(f"Caption terlalu panjang. Maksimum {MAX_PROMPT_LENGTH} karakter.")
        if (m.photo.file_size or 0) > MAX_IMAGE_BYTES:
            return await m.reply_text(
                f"Foto terlalu besar. Maksimum {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            )
        wait_msg  = await m.reply_text("Analyzing image...")
        file_path = None

        try:
            file_path = await m.download()
            with open(file_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode("utf-8")

            active_model = get_model(uid, bot_name)
            reply = await vision_completion(uid, active_model, prompt, b64_img, bot_name)

            if len(reply) <= 4096:
                await wait_msg.edit_text(reply)
            else:
                await wait_msg.delete()
                for i in range(0, len(reply), 4096):
                    await m.reply_text(reply[i:i+4096])

        except Exception as e:
            logger.exception(f"Vision error uid={uid}: {e}")
            await wait_msg.edit_text("⚠️ Gagal menganalisis gambar. Periksa log server untuk detailnya.")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
