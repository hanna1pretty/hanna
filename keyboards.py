from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.helpers import (
    get_all_models, get_providers, get_active_api,
    get_credit_summary_sync, is_private_mode
)

def welcome_text(user, bot_name: str = "HANNA AI"):
    first_name = user.first_name.upper() if user and user.first_name else "USER"
    api_info   = get_active_api()
    cred       = get_credit_summary_sync()
    return (
        f"— {first_name}\n/start\n— {bot_name}\n\n"
        "STRIPE  ADYEN  WHOP  PADDLE\n"
        "AND EXPRESSVPN AUTO HITTER\n\n"
        "Fast and Smooth experience\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"Provider      : {api_info['provider'].upper()}\n"
        f"Tier          : Free & Pay As You Go\n"
        f"Credits       : ${cred['remaining']:.4f} / ${cred['initial']:.2f}\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "What do you want to do?\nChoose an option below to get started."
    )

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Commands",         callback_data="open_commands"),
         InlineKeyboardButton("Models",           callback_data="open_models")],
        [InlineKeyboardButton("Balance & Limits", callback_data="cmd_limits"),
         InlineKeyboardButton("API Settings",     callback_data="open_api")],
    ])

def commands_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Chat",          callback_data="cmd_chat"),
         InlineKeyboardButton("Image Gen",     callback_data="cmd_image")],
        [InlineKeyboardButton("Vision",        callback_data="cmd_vision"),
         InlineKeyboardButton("Clear History", callback_data="cmd_clear")],
        [InlineKeyboardButton("Balance",       callback_data="cmd_limits"),
         InlineKeyboardButton("Help",          callback_data="cmd_help")],
        [InlineKeyboardButton("Models",        callback_data="open_models"),
         InlineKeyboardButton("API Settings",  callback_data="open_api")],
        [InlineKeyboardButton("Back",          callback_data="back_start")],
    ])

def category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("All",           callback_data="filter_All"),
         InlineKeyboardButton("Free",          callback_data="filter_Free")],
        [InlineKeyboardButton("Pay as you go", callback_data="filter_Pay as you go")],
        [InlineKeyboardButton("Back",          callback_data="back_start")],
    ])

def models_keyboard(cat: str = "All"):
    models = get_all_models(cat)
    btns   = [
        [InlineKeyboardButton(f"{m['name']}  [{m['cat']}]", callback_data=f"setmodel_{m['id']}")]
        for m in models
    ]
    btns.append([InlineKeyboardButton("Back", callback_data="open_models")])
    return InlineKeyboardMarkup(btns)

def api_settings_keyboard():
    providers  = get_providers()
    active     = get_active_api()["provider"]
    mode_label = "Access: ADMIN ONLY" if is_private_mode() else "Access: PUBLIC"
    btns, row  = [], []
    for p in providers:
        label = f"{p['name'].upper()} ✓" if p["name"] == active else p["name"].upper()
        row.append(InlineKeyboardButton(label, callback_data=f"switchprov_{p['name']}"))
        if len(row) == 2:
            btns.append(row); row = []
    if row:
        btns.append(row)
    btns.append([
        InlineKeyboardButton("Live Balance",  callback_data="cmd_limits"),
        InlineKeyboardButton(mode_label,      callback_data="toggle_access"),
    ])
    btns.append([InlineKeyboardButton("Back", callback_data="back_start")])
    return InlineKeyboardMarkup(btns)

def limits_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Refresh",      callback_data="refresh_limits"),
         InlineKeyboardButton("API Settings", callback_data="open_api")],
        [InlineKeyboardButton("Back",         callback_data="open_commands")],
    ])

def back_commands_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="open_commands")]])
