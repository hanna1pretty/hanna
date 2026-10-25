import html
from datetime import datetime
from zoneinfo import ZoneInfo

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.helpers import (
    get_all_models, get_model, get_providers, get_active_api,
    is_private_mode, list_conversations,
)

WIB = ZoneInfo("Asia/Jakarta")
QUOTES = [
    "Pelan-pelan tidak apa-apa, yang penting tetap bergerak.",
    "Hari yang baik dimulai dari niat yang baik.",
    "Tidak harus sempurna untuk menjadi berarti.",
    "Istirahat boleh, menyerah jangan.",
    "Satu langkah kecil hari ini tetap membawa kamu lebih dekat.",
    "Tenang, prosesmu tidak harus sama dengan proses orang lain.",
]
DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def display_name(user) -> str:
    if not user:
        return "Pengguna"
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    name = " ".join(part.strip() for part in parts if part and part.strip())
    if name:
        return name
    username = getattr(user, "username", None)
    return f"@{username}" if username else "Pengguna"


def time_greeting(current: datetime) -> str:
    if current.hour < 11:
        return "Selamat pagi"
    if current.hour < 15:
        return "Selamat siang"
    if current.hour < 18:
        return "Selamat sore"
    return "Selamat malam"


def welcome_text(user, bot_name: str = "HANNA AI", now: datetime | None = None):
    current = (now or datetime.now(WIB)).astimezone(WIB)
    name = html.escape(display_name(user))
    quote = html.escape(QUOTES[current.toordinal() % len(QUOTES)])
    time_text = (
        f"{DAYS_ID[current.weekday()]}, {current.day:02d} "
        f"{MONTHS_ID[current.month - 1]} {current.year} — {current:%H:%M:%S} WIB"
    )
    return (
        f"<b>{time_greeting(current)}, {name}.</b>\n\n"
        f"<code>{time_text}</code>\n"
        "--------------------\n"
        f"<b>Nama:</b> {name}\n"
        f"<b>Asisten:</b> {html.escape(bot_name)}\n"
        "--------------------\n\n"
        f"<i>\"{quote}\"</i>\n\n"
        "Pilih menu di bawah atau kirim pesan langsung."
    )


def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("CHAT AI", callback_data="cmd_chat"),
         InlineKeyboardButton("PILIH MODEL", callback_data="open_models")],
        [InlineKeyboardButton("BACA FILE", callback_data="cmd_file"),
         InlineKeyboardButton("ANALISIS GAMBAR", callback_data="cmd_vision")],
        [InlineKeyboardButton("SALDO & LIMIT", callback_data="cmd_limits"),
         InlineKeyboardButton("BANTUAN", callback_data="cmd_help")],
        [InlineKeyboardButton("PERCAKAPAN", callback_data="open_conversations"),
         InlineKeyboardButton("PREMIUM", callback_data="cmd_premium")],
    ])


def commands_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("CHAT AI", callback_data="cmd_chat"),
         InlineKeyboardButton("BUAT GAMBAR", callback_data="cmd_image")],
        [InlineKeyboardButton("ANALISIS GAMBAR", callback_data="cmd_vision"),
         InlineKeyboardButton("BACA FILE", callback_data="cmd_file")],
        [InlineKeyboardButton("HAPUS RIWAYAT", callback_data="cmd_clear"),
         InlineKeyboardButton("SALDO & LIMIT", callback_data="cmd_limits")],
        [InlineKeyboardButton("PERCAKAPAN", callback_data="open_conversations"),
         InlineKeyboardButton("PREMIUM", callback_data="cmd_premium")],
        [InlineKeyboardButton("PILIH MODEL", callback_data="open_models"),
         InlineKeyboardButton("PENGATURAN API", callback_data="open_api")],
        [InlineKeyboardButton("KEMBALI", callback_data="back_start")],
    ])


def category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("SEMUA MODEL", callback_data="filter_All")],
        [InlineKeyboardButton("GRATIS", callback_data="filter_Free"),
         InlineKeyboardButton("PAY AS YOU GO", callback_data="filter_Pay as you go")],
        [InlineKeyboardButton("KEMBALI", callback_data="back_start")],
    ])


def models_keyboard(cat: str = "All", user_id: int | None = None, bot_name: str = "default"):
    models = get_all_models(cat)
    active_model = get_model(user_id, bot_name) if user_id is not None else None
    buttons = [
        [InlineKeyboardButton(
            f"{m['name']} - {m['cat']}" + (" (Aktif)" if m["id"] == active_model else ""),
            callback_data=f"setmodel_{m['id']}"
        )]
        for m in models
    ]
    buttons.append([InlineKeyboardButton("KEMBALI", callback_data="open_models")])
    return InlineKeyboardMarkup(buttons)


def api_settings_keyboard():
    providers = get_providers()
    active = get_active_api()["provider"]
    mode_label = "MODE: ADMIN SAJA" if is_private_mode() else "MODE: PUBLIK"
    buttons, row = [], []
    for provider in providers:
        label = f"{provider['name'].upper()} (Aktif)" if provider["name"] == active else provider["name"].upper()
        row.append(InlineKeyboardButton(label, callback_data=f"switchprov_{provider['name']}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("PERBARUI SALDO", callback_data="cmd_limits"),
        InlineKeyboardButton(mode_label, callback_data="toggle_access"),
    ])
    buttons.append([InlineKeyboardButton("KEMBALI", callback_data="back_start")])
    return InlineKeyboardMarkup(buttons)


def limits_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PERBARUI SALDO", callback_data="refresh_limits"),
         InlineKeyboardButton("PENGATURAN API", callback_data="open_api")],
        [InlineKeyboardButton("KEMBALI", callback_data="back_start")],
    ])


def back_commands_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("KEMBALI KE MENU", callback_data="open_commands")]
    ])

async def conversations_keyboard(user_id: int, bot_name: str = "default"):
    conversations = await list_conversations(user_id, bot_name)
    buttons = []
    for item in conversations:
        marker = " (Aktif)" if item["active"] else ""
        title = item["title"][:42]
        buttons.append([
            InlineKeyboardButton(
                f"{title}{marker} • {item['messages']} MSG",
                callback_data=f"switchconv_{item['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("+ PERCAKAPAN BARU", callback_data="new_conversation")])
    buttons.append([InlineKeyboardButton("KEMBALI KE MENU", callback_data="open_commands")])
    return InlineKeyboardMarkup(buttons)
