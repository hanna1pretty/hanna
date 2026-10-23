import logging
from pyrogram import filters
from utils.ai import generate_image
from utils.helpers import can_use_bot

logger = logging.getLogger(__name__)

def register(app, bot_name: str = "default"):

    @app.on_message(filters.command(["img", "image"]) & filters.private)
    async def image_cmd(c, m):
        uid = m.from_user.id
        if not can_use_bot(uid):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text("Usage: /img <prompt>\n\nExample: /img futuristic city at night")

        prompt = m.text.split(None, 1)[1].strip()
        if len(prompt) > 4000:
            return await m.reply_text("Prompt terlalu panjang. Maksimum 4000 karakter.")
        wait_msg = await m.reply_text("Generating image...")
        try:
            img_url = await generate_image(uid, prompt, bot_name)
            await m.reply_photo(img_url, caption=f"Prompt: {prompt}")
            await wait_msg.delete()
        except Exception as e:
            logger.exception(f"Image gen error uid={uid}: {e}")
            await wait_msg.edit_text("⚠️ Gagal membuat gambar. Periksa log server untuk detailnya.")
