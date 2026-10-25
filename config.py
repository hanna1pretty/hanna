import math
import os
import re
from dotenv import load_dotenv

load_dotenv()

# ─── CORE BOT CONFIG ───────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
API_HASH    = os.getenv("API_HASH", "").strip()
PROXY_SCHEME = os.getenv("PROXY_SCHEME", "socks5").strip().lower()
PROXY_HOST = os.getenv("PROXY_HOST", "").strip()
PROXY_PORT = int(os.getenv("PROXY_PORT", "1080"))
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "").strip()
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

def _required_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value

API_ID = _required_int("API_ID")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")
if not API_HASH:
    raise ValueError("API_HASH is required")
if PROXY_SCHEME not in {"socks4", "socks5", "http"}:
    raise ValueError("PROXY_SCHEME must be socks4, socks5, or http")
if not 1 <= PROXY_PORT <= 65535:
    raise ValueError("PROXY_PORT must be between 1 and 65535")

# Multiple bots: BOT_TOKEN_2, BOT_TOKEN_3, dst (opsional)
EXTRA_TOKENS = [
    os.environ[k].strip() for k in sorted(os.environ)
    if re.fullmatch(r"BOT_TOKEN_[2-9][0-9]*", k) and os.environ[k].strip()
]

# ─── ADMIN & ACCESS ────────────────────────────────────────────────
raw_admins = os.getenv("ADMIN_ID", "").strip()
if not raw_admins:
    raise ValueError("ADMIN_ID is required; use /myid in Telegram to find it")
try:
    ADMIN_IDS = [int(x.strip()) for x in raw_admins.split(",")]
except ValueError as exc:
    raise ValueError("ADMIN_ID must contain comma-separated numeric Telegram IDs") from exc
if any(value <= 0 for value in ADMIN_IDS):
    raise ValueError("ADMIN_ID must contain positive Telegram IDs")

# ─── API / PROVIDER ────────────────────────────────────────────────
TOP_TOOLS_KEY = os.getenv("TOP_TOOLS_API_KEY", "")
BASE_URL      = os.getenv("BASE_URL", "https://top-tools-ai.com/api/v1")

# ─── KREDIT & MODEL ────────────────────────────────────────────────
INITIAL_CREDITS = float(os.getenv("INITIAL_CREDITS", "220.00"))
DEFAULT_MODEL   = os.getenv("DEFAULT_MODEL", "top-tools-ai").strip() or "top-tools-ai"

# Max history per user (configurable)
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))

# Retry config
API_TIMEOUT  = int(os.getenv("API_TIMEOUT", "60"))
API_RETRIES  = int(os.getenv("API_RETRIES", "2"))
RETRY_DELAY  = float(os.getenv("RETRY_DELAY", "2.0"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", "10485760"))
MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", "4000"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "5242880"))
MAX_EXTRACTED_CHARS = int(os.getenv("MAX_EXTRACTED_CHARS", "20000"))
STREAM_UPDATE_INTERVAL = float(os.getenv("STREAM_UPDATE_INTERVAL", "0.8"))
PUBLIC_DAILY_REQUEST_LIMIT = int(os.getenv("PUBLIC_DAILY_REQUEST_LIMIT", "40"))
PUBLIC_DAILY_TOKEN_LIMIT = int(os.getenv("PUBLIC_DAILY_TOKEN_LIMIT", "100000"))

if not math.isfinite(INITIAL_CREDITS) or INITIAL_CREDITS < 0:
    raise ValueError("INITIAL_CREDITS must be a finite non-negative number")
if MAX_HISTORY <= 0 or API_TIMEOUT <= 0 or API_RETRIES <= 0 or RETRY_DELAY < 0:
    raise ValueError("MAX_HISTORY, API_TIMEOUT, API_RETRIES must be positive and RETRY_DELAY non-negative")
if (MAX_IMAGE_BYTES <= 0 or MAX_PROMPT_LENGTH <= 0 or MAX_FILE_BYTES <= 0
        or MAX_EXTRACTED_CHARS <= 0 or STREAM_UPDATE_INTERVAL <= 0):
    raise ValueError("File/image/prompt limits and STREAM_UPDATE_INTERVAL must be positive")
if PUBLIC_DAILY_REQUEST_LIMIT <= 0 or PUBLIC_DAILY_TOKEN_LIMIT <= 0:
    raise ValueError("Public daily request and token limits must be positive")

# ─── SYSTEM PROMPT ─────────────────────────────────────────────────
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are Hanna, a fast, smart, and helpful AI assistant. "
    "Answer clearly and concisely. If the user writes in Indonesian, reply in Indonesian. "
    "If in English, reply in English."
)

# ─── DEFAULT MODELS ────────────────────────────────────────────────
DEFAULT_MODELS = [
    {
        "id": "top-tools-ai",
        "cat": "Free",
        "name": "Top-Tools-Ai",
        "desc": "512K context - 10M free/day",
        "in_price": 0.0,
        "out_price": 0.0
    },
    {
        "id": "gpt-5.6-sol",
        "cat": "Pay as you go",
        "name": "GPT-5.6-Sol",
        "desc": "$1.00/1M in - $8.00/1M out",
        "in_price": 1.00,
        "out_price": 8.00
    },
    {
        "id": "claude-opus-5",
        "cat": "Pay as you go",
        "name": "Claude Opus 5",
        "desc": "$3.00/1M in - $13.00/1M out",
        "in_price": 3.00,
        "out_price": 13.00
    },
    {
        "id": "DeepSeek-V4-Flash-Vision-Exp",
        "cat": "Pay as you go",
        "name": "DeepSeek Vision",
        "desc": "$0.17/1M in - Vision capable",
        "in_price": 0.17,
        "out_price": 0.50
    },
]

# ─── DEFAULT PROVIDERS ─────────────────────────────────────────────
DEFAULT_PROVIDERS = [
    {"name": "toptools",   "base_url": BASE_URL,                          "api_key": TOP_TOOLS_KEY},
    {"name": "openrouter", "base_url": "https://openrouter.ai/api/v1",    "api_key": ""},
    {"name": "openai",     "base_url": "https://api.openai.com/v1",       "api_key": ""},
    {"name": "deepseek",   "base_url": "https://api.deepseek.com/v1",     "api_key": ""},
]
