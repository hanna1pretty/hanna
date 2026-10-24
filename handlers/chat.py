import logging
import asyncio
from pyrogram import filters
from utils.helpers import get_model_async, get_history, add_history, can_use_bot_async
from utils.ai import chat_completion

logger = logging.getLogger(__name__)

RESERVED_COMMANDS = [
    "start","myid","clear","img","image","help",
    "api","apikey","balance","saldo","limits","setbalance",
    "setkey","seturl","setprovider","addmodel","delmodel"
]

def register(app, bot_name: str = "default"):

    @app.on_message(filters.text & filters.private & ~filters.command(RESERVED_COMMANDS))
    async def chat_handler(c, m):
        uid = m.from_user.id

        # Cek akses — async, tidak block
        if not await can_use_bot_async(uid):
            return await m.reply_text(f"Access Denied. Bot dalam mode ADMIN ONLY.\nYour ID: {uid}")

        user_text = m.text

        # Kirim acknowledgement sedini mungkin agar user tidak menunggu tanpa feedback.
        wait_msg = await m.reply_text("⏳ Memproses pesan...")

        model, history = await asyncio.gather(
            get_model_async(uid, bot_name),
            get_history(uid, bot_name)
        )

        # Tambah history user sebelum kirim ke API
        await add_history(uid, "user", user_text, bot_name)

        try:
            reply = await chat_completion(uid, model, history + [{"role":"user","content":user_text}], bot_name)

            # Simpan history assistant (fire-and-forget, tidak tunda reply)
            asyncio.create_task(add_history(uid, "assistant", reply, bot_name))

            if len(reply) <= 4096:
                await wait_msg.edit_text(reply)
            else:
                await wait_msg.delete()
                for i in range(0, len(reply), 4096):
                    await m.reply_text(reply[i:i+4096])

        except Exception:
            logger.exception("chat_handler error uid=%s", uid)
            await wait_msg.edit_text("⚠️ Terjadi kesalahan saat memproses pesan. Coba lagi nanti.")
