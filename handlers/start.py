import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
import keyboards as kb
from config import (
    ADMIN_IDS, PREMIUM_PACKAGES, PUBLIC_DAILY_REQUEST_LIMIT,
    PUBLIC_DAILY_TOKEN_LIMIT,
)
from utils.helpers import (
    set_model, get_model, clear_history,
    create_conversation, switch_conversation,
    get_active_api, mask_key, switch_provider,
    is_admin, can_use_bot_async, is_private_mode, toggle_private_mode,
    get_credit_summary_sync, get_credit_summary, is_premium_user, model_exists,
    can_use_model_async
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
    mode_str = "Admin saja" if is_private_mode() else "Publik"
    admin_str = ", ".join(str(x) for x in ADMIN_IDS) if ADMIN_IDS else "Tidak diatur"
    return (
        "PENGATURAN ADMIN HANNA AI\n\n"
        f"Provider aktif: {api['provider'].upper()}\n"
        f"Base URL: {api['base_url']}\n"
        f"API key: {mask_key(api['api_key'])}\n"
        f"Pemakaian lokal: ${cred['spent']:.4f}\n"
        f"Mode akses: {mode_str}\n"
        f"Admin: {admin_str}\n\n"
        "Batas user publik:\n"
        f"{PUBLIC_DAILY_REQUEST_LIMIT} permintaan dan {PUBLIC_DAILY_TOKEN_LIMIT:,} token per hari.\n"
        "Admin tidak terkena batas internal. Saldo provider tetap mengikuti aturan provider."
    )

def premium_offer_text(active: bool = False) -> str:
    package_lines = "\n".join(
        f"<b>{name}</b>: {price} untuk akses premium {days} hari"
        for name, price, days in PREMIUM_PACKAGES
    )
    status = "Aktif" if active else "Belum aktif"
    return (
        "<b>HANNA AI  /  PREMIUM ACCESS</b>\n"
        "<code>EXTENDED WORKSPACE PRIVILEGES</code>\n\n"
        f"Status akun: <b>{status}</b>\n\n"
        "<b>PREMIUM INCLUDE</b>\n"
        "• Akses model Pay as you go\n"
        "• Melewati limit publik harian\n"
        "• Akses vision dan pemrosesan file\n"
        "• Multi-conversation tanpa batas internal\n\n"
        "<b>PAKET TERSEDIA</b>\n"
        f"{package_lines}\n\n"
        "Paket di atas adalah harga awal dan dapat disesuaikan owner.\n\n"
        "Pembayaran dilakukan manual kepada admin. Setelah pembayaran diverifikasi, "
        "admin mengaktifkan akses premium untuk akun Telegram Anda."
    )

async def build_limits_text(uid: int, bot_name: str = "default") -> str:
    active, cred, live_balance, premium = await asyncio.gather(
        asyncio.to_thread(get_model, uid, bot_name),
        get_credit_summary(),
        check_live_api_balance(),
        is_premium_user(uid, bot_name),
    )
    api = get_active_api()
    return (
        "<b>SALDO DAN LIMIT</b>\n\n"
        f"Provider: <b>{api['provider'].upper()}</b>\n"
        f"Model: <code>{active}</code>\n\n"
        f"Akses premium: <code>{'Aktif' if premium or is_admin(uid) else 'Tidak aktif'}</code>\n"
        f"Saldo provider (live): {live_balance}\n"
        f"Pemakaian lokal: ${cred['spent']:.4f}\n"
        f"Total permintaan: {cred['requests']}\n"
        f"Token input: {cred['input_tokens']:,}\n"
        f"Token output: {cred['output_tokens']:,}\n\n"
        f"Limit user publik: {PUBLIC_DAILY_REQUEST_LIMIT} permintaan atau "
        f"{PUBLIC_DAILY_TOKEN_LIMIT:,} token per hari.\n"
        "Admin: tanpa batas internal.\n\n"
        f"<code>Diperbarui: {datetime.now(WIB).strftime('%d-%m-%Y %H:%M:%S WIB')}</code>\n"
        "Saldo live berasal dari endpoint provider jika tersedia."
    )

def register(app, bot_name: str = "default"):

    @app.on_message(filters.command("start"))
    async def start(c, m):
        if not await can_use_bot_async(m.from_user.id):
            return await m.reply_text(
                f"Akses ditolak. Bot sedang dalam mode admin saja.\nID kamu: {m.from_user.id}"
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
            "Gunakan angka tersebut sebagai ADMIN_ID pada file .env."
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
            return await q.answer("Akses ditolak. Bot sedang dalam mode admin saja.", show_alert=True)

        if d == "open_commands":
            await q.answer()
            await safe_edit(q.message,
                "<b>MENU HANNA AI</b>\n\nPilih fitur yang ingin digunakan:",
                reply_markup=kb.commands_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "open_models":
            await q.answer()
            await safe_edit(q.message,
                "<b>PILIH MODEL</b>\n\nPilih kategori model yang ingin digunakan:",
                reply_markup=kb.category_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "open_conversations":
            await q.answer()
            await safe_edit(
                q.message,
                "<b>PERCAKAPAN</b>\n\nPilih percakapan atau buat percakapan baru.",
                reply_markup=await kb.conversations_keyboard(uid, bot_name),
                parse_mode=ParseMode.HTML,
            )

        elif d == "new_conversation":
            await create_conversation(uid, "Percakapan baru", bot_name)
            await q.answer("Percakapan baru dibuat.", show_alert=True)
            await safe_edit(
                q.message,
                "<b>PERCAKAPAN BARU</b>\n\nPercakapan aktif sudah diganti. Kirim pesan untuk mulai.",
                reply_markup=await kb.conversations_keyboard(uid, bot_name),
                parse_mode=ParseMode.HTML,
            )

        elif d.startswith("switchconv_"):
            try:
                conversation_id = int(d.split("switchconv_", 1)[1])
            except ValueError:
                return await q.answer("Percakapan tidak valid.", show_alert=True)
            if not await switch_conversation(uid, conversation_id, bot_name):
                return await q.answer("Percakapan tidak ditemukan.", show_alert=True)
            await q.answer("Percakapan aktif diganti.", show_alert=True)
            await safe_edit(
                q.message,
                "<b>PERCAKAPAN AKTIF</b>\n\nKirim pesan untuk melanjutkan percakapan ini.",
                reply_markup=await kb.conversations_keyboard(uid, bot_name),
                parse_mode=ParseMode.HTML,
            )

        elif d == "open_api":
            if not is_admin(uid):
                return await q.answer("Akses ditolak. Menu ini hanya untuk admin.", show_alert=True)
            await q.answer()
            await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())

        elif d == "toggle_access":
            if not is_admin(uid):
                return await q.answer("Akses ditolak. Menu ini hanya untuk admin.", show_alert=True)
            new_state = await toggle_private_mode()
            label     = "ADMIN SAJA" if new_state else "PUBLIK"
            await q.answer(f"Mode akses diubah menjadi {label}.", show_alert=True)
            await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())

        elif d.startswith("switchprov_"):
            if not is_admin(uid):
                return await q.answer("Akses ditolak. Menu ini hanya untuk admin.", show_alert=True)
            pname  = d.split("switchprov_", 1)[1]
            ok, _  = await switch_provider(pname)
            if ok:
                await q.answer(f"Provider aktif: {pname.upper()}.", show_alert=True)
                await safe_edit(q.message, api_menu_text(), reply_markup=kb.api_settings_keyboard())
            else:
                await q.answer("Provider tidak ditemukan.", show_alert=True)

        elif d.startswith("filter_"):
            await q.answer()
            cat = d.split("filter_", 1)[1]
            await safe_edit(q.message, f"Kategori: {cat}\n\nPilih model yang ingin digunakan:",
                reply_markup=kb.models_keyboard(cat, uid, bot_name))

        elif d.startswith("setmodel_"):
            mid = d.split("setmodel_", 1)[1]
            if not mid or len(mid) > 120 or not model_exists(mid):
                return await q.answer("Model tidak tersedia.", show_alert=True)
            model_allowed, model_message = await can_use_model_async(uid, mid, bot_name)
            if not model_allowed:
                return await q.answer("Model ini khusus premium.", show_alert=True)
            await set_model(uid, mid, bot_name)
            await q.answer(f"Model aktif: {mid}", show_alert=True)
            await safe_edit(q.message,
                f"Model aktif: {mid}\n\nKirim pesan untuk mulai menggunakan model ini.",
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

        elif d == "cmd_premium":
            await q.answer()
            await safe_edit(
                q.message,
                premium_offer_text(await is_premium_user(uid, bot_name)),
                reply_markup=kb.back_commands_keyboard(),
                parse_mode=ParseMode.HTML,
            )

        elif d == "cmd_chat":
            await q.answer()
            active = get_model(uid, bot_name)
            api    = get_active_api()
            await safe_edit(q.message,
                f"MODE CHAT\n\nProvider: {api['provider'].upper()}\nModel: {active}\n\n"
                "Kirim pesan untuk mulai chat dengan Hanna AI.",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_image":
            await q.answer()
            await safe_edit(q.message,
                "BUAT GAMBAR\n\nGunakan perintah:\n/img <deskripsi gambar>\n\n"
                "Contoh:\n/img kota futuristik pada malam hari",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_vision":
            await q.answer()
            await safe_edit(q.message,
                "ANALISIS GAMBAR\n\nKirim foto dengan caption untuk menganalisis gambar.\n"
                "Model vision dipilih otomatis bila diperlukan.",
                reply_markup=kb.back_commands_keyboard())

        elif d == "cmd_file":
            await q.answer()
            await safe_edit(q.message,
                "<b>BACA FILE</b>\n\nKirim file TXT, MD, CSV, JSON, LOG, atau PDF di chat pribadi ini.\n"
                "Untuk membuat dokumen, minta langsung: <i>buatkan PDF tentang...</i> atau "
                "<i>simpan sebagai TXT</i>. Jawaban panjang otomatis dikirim sebagai TXT.\n"
                "Ukuran file masuk maksimum 5 MB. Gunakan /export untuk mengunduh riwayat chat.",
                reply_markup=kb.back_commands_keyboard(),
                parse_mode=ParseMode.HTML)

        elif d in ("cmd_limits", "refresh_limits"):
            await q.answer("Memperbarui saldo...")
            text = await build_limits_text(uid, bot_name)
            await safe_edit(q.message, text, reply_markup=kb.limits_keyboard(), parse_mode=ParseMode.HTML)

        elif d == "cmd_help":
            await q.answer()
            await safe_edit(q.message,
                "<b>BANTUAN</b>\n\n"
                "/start - Buka menu utama\n"
                "/myid - Lihat ID Telegram\n"
                "/balance - Lihat saldo dan limit\n"
                "/api - Pengaturan API admin\n"
                "/img &lt;deskripsi&gt; - Buat gambar\n"
                "/export - Unduh riwayat chat\n"
                "/clear - Hapus riwayat chat\n\n"
                "Untuk membaca file, kirim TXT, CSV, JSON, LOG, atau PDF secara langsung.\n"
                "Untuk membuat dokumen, gunakan prompt seperti: <i>buatkan PDF tentang...</i> "
                "atau <i>simpan jawaban ini sebagai TXT</i>.",
                reply_markup=kb.back_commands_keyboard(), parse_mode=ParseMode.HTML)
        else:
            await q.continue_propagation()
