import logging
from pyrogram import filters
from pyrogram.enums import ParseMode
import keyboards as kb
from handlers.start import api_menu_text, build_limits_text, premium_offer_text
from utils.helpers import (
    is_admin, set_api_key, set_base_url,
    save_provider, add_custom_model, delete_custom_model,
    get_active_api, grant_premium, is_premium_user, list_premium_users,
    mask_key, revoke_premium, set_initial_credits
)

logger = logging.getLogger(__name__)

def register(app, bot_name: str = "default"):

    @app.on_message(filters.command("premium"))
    async def premium_cmd(c, m):
        active = await is_premium_user(m.from_user.id, bot_name)
        await m.reply_text(premium_offer_text(active), parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("grantpremium"))
    async def grantpremium_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Akses ditolak. Command ini hanya untuk admin.")
        if len(m.command) < 3:
            return await m.reply_text(
                "Format: /grantpremium <telegram_user_id> <hari>\n"
                "Contoh: /grantpremium 123456789 30"
            )
        try:
            user_id = int(m.command[1])
            days = int(m.command[2])
            await grant_premium(user_id, days, bot_name)
        except (ValueError, TypeError):
            return await m.reply_text("User ID dan hari harus berupa angka yang valid.")
        await m.reply_text(
            f"Akses premium untuk <code>{user_id}</code> diaktifkan selama "
            f"<b>{days} hari</b>.",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("premiumusers"))
    async def premiumusers_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Akses ditolak. Command ini hanya untuk admin.")
        users = await list_premium_users(bot_name)
        if not users:
            return await m.reply_text("Belum ada user premium yang aktif.")
        lines = ["<b>USER PREMIUM AKTIF</b>", ""]
        lines.extend(
            f"<code>{row['user_id']}</code> — berakhir {row['expires_at']} UTC"
            for row in users
        )
        await m.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("revokepremium"))
    async def revokepremium_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Akses ditolak. Command ini hanya untuk admin.")
        if len(m.command) < 2:
            return await m.reply_text("Format: /revokepremium <telegram_user_id>")
        try:
            user_id = int(m.command[1])
        except ValueError:
            return await m.reply_text("Telegram user ID harus berupa angka.")
        removed = await revoke_premium(user_id, bot_name)
        await m.reply_text(
            "Akses premium dicabut." if removed else "User tersebut tidak memiliki premium aktif."
        )

    @app.on_message(filters.command(["api", "apikey"]))
    async def api_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text(f"Access denied. Admin only.\nYour ID: {m.from_user.id}")
        await m.reply_text(api_menu_text(), reply_markup=kb.api_settings_keyboard())

    @app.on_message(filters.command(["balance", "saldo", "limits"]))
    async def balance_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text(f"Access denied. Admin only.\nYour ID: {m.from_user.id}")
        wait = await m.reply_text("Checking API balance...")
        text = await build_limits_text(m.from_user.id, bot_name)
        await wait.edit_text(text, reply_markup=kb.limits_keyboard())

    @app.on_message(filters.command("setbalance"))
    async def setbalance_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text("Usage: /setbalance <usd>\nExample: /setbalance 220")
        try:
            val = float(m.text.split(None, 1)[1].strip().replace("$", ""))
            await set_initial_credits(val)
            await m.reply_text(f"Saldo kredit dikalibrasi ke ${val:.2f} dan riwayat pemakaian di-reset.")
        except ValueError:
            await m.reply_text("Format tidak valid. Contoh: /setbalance 220.00")

    @app.on_message(filters.command("setkey"))
    async def setkey_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text("Usage: /setkey <new_api_key>")
        new_key = m.text.split(None, 1)[1].strip()
        await set_api_key(new_key)
        try:
            await m.delete()
        except Exception:
            pass
        api = get_active_api()
        await m.reply_text(
            f"API Key updated.\n\nProvider : {api['provider'].upper()}\nKey      : {mask_key(api['api_key'])}",
            reply_markup=kb.api_settings_keyboard()
        )

    @app.on_message(filters.command("seturl"))
    async def seturl_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text("Usage: /seturl <https://domain.com/api/v1>")
        await set_base_url(m.text.split(None, 1)[1].strip())
        api = get_active_api()
        await m.reply_text(
            f"Base URL updated.\n\nProvider : {api['provider'].upper()}\nURL      : {api['base_url']}",
            reply_markup=kb.api_settings_keyboard()
        )

    @app.on_message(filters.command("setprovider"))
    async def setprovider_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        parts = m.text.split(None, 3)
        if len(parts) < 4:
            return await m.reply_text(
                "Usage:\n/setprovider <name> <base_url> <api_key>\n\n"
                "Example:\n/setprovider openrouter https://openrouter.ai/api/v1 sk-or-xxx"
            )
        _, name, url, key = parts
        await save_provider(name, url, key)
        try:
            await m.delete()
        except Exception:
            pass
        api = get_active_api()
        await m.reply_text(
            f"Provider '{api['provider'].upper()}' saved and activated.\n\n"
            f"Base URL : {api['base_url']}\nAPI Key  : {mask_key(api['api_key'])}",
            reply_markup=kb.api_settings_keyboard()
        )

    @app.on_message(filters.command("addmodel"))
    async def addmodel_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text(
                "Usage:\n/addmodel <id> | <Category> | <Name> | <in_price> | <out_price>\n\n"
                "Categories: Free / Pay as you go\n"
                "Example:\n/addmodel openai/gpt-4o | Pay as you go | GPT-4o | 2.5 | 10.0"
            )
        raw      = m.text.split(None, 1)[1]
        segments = [s.strip() for s in raw.split("|")]
        model_id = segments[0]
        cat      = segments[1] if len(segments) > 1 else "Pay as you go"
        name     = segments[2] if len(segments) > 2 else model_id
        try:
            in_p  = float(segments[3]) if len(segments) > 3 else 1.0
            out_p = float(segments[4]) if len(segments) > 4 else 5.0
        except ValueError:
            in_p, out_p = 1.0, 5.0
        await add_custom_model(model_id, cat, name, in_p, out_p)
        await m.reply_text(f"Model '{name}' ({model_id}) added to '{cat}' — ${in_p}/1M in, ${out_p}/1M out.")

    @app.on_message(filters.command("delmodel"))
    async def delmodel_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Access denied. Admin only.")
        if len(m.command) < 2:
            return await m.reply_text("Usage: /delmodel <model_id>")
        model_id = m.text.split(None, 1)[1].strip()
        if await delete_custom_model(model_id):
            await m.reply_text(f"Model '{model_id}' removed.")
        else:
            await m.reply_text(f"Model '{model_id}' not found.")
