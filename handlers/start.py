import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
import keyboards as kb
from config import ADMIN_IDS
from utils.helpers import (
    set_model, get_model, clear_history,
    get_active_api, mask_key, switch_provider,
    is_admin, can_use_bot_async, is_private_mode, toggle_private_mode,
    get_credit_summary_sync, get_credit_summary, model_exists
)
from utils.ai import check_live_api_balance

logger = logging.getLogger(__name__)
WIB = ZoneInfo("Asia/Jakarta")

async def safe_edit(message, text, reply_markup=None, parse_mode=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"safe_edit: {e}")

def api_menu_text():
    api      = get_active_api()
    cred     = get_credit_summary_sync()
    mode_str = "ADMIN ONLY (Locked)" if is_private_mode() else "PUBLIC (All Users)"
    admin_str= ", ".join(str(x) for x in ADMIN_IDS) if ADMIN_IDS else "Not Set (Open)"
    return (
        "HANNA AI — API & ADMIN SETTINGS\n\n"
        f"Active Provider  : {api['provider'].upper()}\n"
        f"Base URL         : {api['base_url']}\n"
        f"API Key          : {mask_key(api['api_key'])}\n"
        f"Tracked Balance  : ${cred['remaining']:.4f} / ${cred['initial']:.2f}\n"
        f"Bot Access Mode  : {mode_str}\n"
        f"Admin IDs        : {admin_str}\n\n"
        "Admin Commands:\n"
        "/balance               — Cek saldo kredit\n"
        "/setbalance <usd>      — Set patokan saldo\n"
        "/setkey <api_key>      — Ganti API Key\n"
        "/seturl <base_url>     — Ganti Base URL\n"
        "/setprovider <n> <url> <key>\n"
        "/addmodel <id>|<cat>|<name>|<in>|<out>\n"
        "/delmodel <id>\n\n"
        "Pilih provider atau toggle akses:"
    )

async def build_limits_text(uid: int, bot_name: str = "default") -> str:
    active, cred, live_balance = await asyncio.gather(
        asyncio.to_thread(get_model, uid, bot_name),
        get_credit_summary(),
        check_live_api_balance()
    )
    api = get_active_api()
    return (
        "<b>HANNA AI — BALANCE &amp; LIMITS</b>\n\n"
        f"Provider          : <b>{api['provider'].upper()}</b>\n"
        f"Active Model      : <code>{active}</code>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"Provider Balance  : {live_balance}\n"
        f"Local Estimasi    : ${cred['remaining']:.4f} / ${cred['initial']:.2f}\n"
        f"Local Terpakai    : ${cred['spent']:.4f}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"Total Requests    : {cred['requests']}x\n"
        f"Input Tokens      : {cred['input_tokens']:,}\n"
        f"Output Tokens     : {cred['output_tokens']:,}\n"
        f"Total Tokens      : {cred['total_tokens']:,}\n\n"
        f"<code>Diperiksa: {datetime.now(WIB).strftime('%d-%m-%Y %H:%M:%S WIB')}</code>\n"
        "Catatan: Local Estimasi bukan saldo akun provider."
    )

def register(app, bot_name: str = "default"):

    @app.on_message(filters.command("start"))
    async def start(c, m):
        if not await can_use_bot_async(m.from_user.id):
            return await m.reply_text(
                f"Access Denied. Bot dalam mode ADMIN ONLY.\nYour ID: {m.from_user.id}"
            )
        await m.reply_text(
            kb.welcome_text(m.from_user, bot_name),
            reply_markup=kb.start_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("myid"))
    async def myid_cmd(c, m):
        uid    = m.from_user.id
        status = "ADMIN (Full Access)" if is_admin(uid) else "USER"
        await m.reply_text(
            f"YOUR TELEGRAM INFO\n\nUser ID  : {uid}\nRole     : {status}\n\n"
            "Masukkan angka di atas ke variabel ADMIN_ID pada file .env kamu."
        )

    @app.on_message(filters.command("clear"))
    async def clear_cmd(c, m):
        if not await can_use_bot_async(m.from_user.id):
            return
        await clear_history(m.from_user.id, bot_name)
        await m.reply_text("History cleared.")

    @app.on_callback_query()
    async def cb(c, q):
        d   = q.data
        uid = q.from_user.id

        if not await can_use_bot_async(uid):
            return await q.answer("Access denied. Bot is locked for Admin only.", show_alert=True)

        if d == "open_commands":
            await q.answer()
            await safe_edit(q.message,
                "<b>HANNA AI — MENU</b>\n\nPilih fitur yang ingin digunakan:",
                reply_markup=kb.commands_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "open_models":
            await q.answer()
            await safe_edit(q.message,
                "<b>PILIH KATEGORI MODEL</b>\n\nPilih model yang ingin digunakan:",
                reply_markup=kb.category_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "open_api":
            if not is_admin(uid):
                return await q.answer("Access denied. Admin only.", show_alert=True)
            await q.answer()
            await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())

        elif d == "toggle_access":
            if not is_admin(uid):
                return await q.answer("Access denied. Admin only.", show_alert=True)
            new_state = await toggle_private_mode()
            label     = "ADMIN ONLY" if new_state else "PUBLIC"
            await q.answer(f"Bot Access changed to {label}", show_alert=True)
            await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())

        elif d.startswith("switchprov_"):
            if not is_admin(uid):
                return await q.answer("Access denied. Admin only.", show_alert=True)
            pname  = d.split("switchprov_", 1)[1]
            ok, _  = await switch_provider(pname)
            if ok:
                await q.answer(f"Switched to {pname.upper()}", show_alert=True)
                await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())
            else:
                await q.answer("Provider not found", show_alert=True)

        elif d.startswith("filter_"):
            await q.answer()
            cat = d.split("filter_", 1)[1]
            await safe_edit(q.message, f"Models : {cat}\n\nClick model below to activate:",
                reply_markup=kb.models_keyboard(cat))

        elif d.startswith("setmodel_"):
            mid = d.split("setmodel_", 1)[1]
            if not mid or len(mid) > 120 or not model_exists(mid):
                return await q.answer("Model tidak tersedia.", show_alert=True)
            await set_model(uid, mid, bot_name)
            await q.answer(f"Model changed to {mid}", show_alert=True)
            await safe_edit(q.message,
                f"Model Active : {mid}\n\nNow send any message to chat with Hanna AI.",
                reply_markup=kb.start_keyboard())

        elif d == "back_start":
            await q.answer()
            await safe_edit(
                q.message, kb.welcome_text(q.from_user, bot_name),
                reply_markup=kb.start_keyboard(), parse_mode=ParseMode.HTML
            )

        elif d == "cmd_clear":
            await clear_history(uid, bot_name)
            await q.answer("History cleared", show_alert=True)

        elif d == "cmd_chat":
            await q.answer()
            active = get_model(uid, bot_name)
            api    = get_active_api()
            await safe_edit(q.message,
                f"CHAT MODE\n\nProvider     : {api['provider'].upper()}\nActive Model : {active}\n\n"
                "Send any text message to chat with Hanna AI.",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_image":
            await q.answer()
            await safe_edit(q.message,
                "IMAGE GENERATION\n\nUsage: /img <your prompt>\n\nExample:\n/img futuristic city at night",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_vision":
            await q.answer()
            await safe_edit(q.message,
                "VISION ANALYSIS\n\nSend a photo with caption to analyze the image.\n"
                "Recommended model: DeepSeek-V4-Flash-Vision-Exp",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_file":
            await q.answer()
            await safe_edit(q.message,
                "<b>BACA FILE</b>\n\nKirim file TXT, MD, CSV, JSON, LOG, atau PDF di chat privat ini.\n"
                "Ukuran maksimum 5 MB. Gunakan /export untuk menerima riwayat chat sebagai TXT.",
                reply_markup=kb.back_commands_keyboard(),
                parse_mode=ParseMode.HTML)

        elif d in ("cmd_limits", "refresh_limits"):
            await q.answer("Checking balance...")
            text = await build_limits_text(uid, bot_name)
            await safe_edit(q.message, text, reply_markup=kb.limits_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "cmd_help":
            await q.answer()
            await safe_edit(q.message,
                "<b>BANTUAN &amp; PERINTAH</b>\n\n"
                "/start — Menu utama\n"
                "/myid — Lihat Telegram ID\n"
                "/balance — Cek balance provider\n"
                "/api — Pengaturan API (admin)\n"
                "/img &lt;prompt&gt; — Buat gambar\n"
                "/export — Kirim riwayat chat sebagai TXT\n"
                "/clear — Hapus riwayat chat\n\n"
                "Untuk membaca file, kirim TXT, CSV, JSON, LOG, atau PDF secara langsung.",
                reply_markup=kb.back_commands_keyboard(), parse_mode=ParseMode.HTML)
        else:
            await q.continue_propagation()
