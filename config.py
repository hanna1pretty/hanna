import os
from dotenv import load_dotenv

load_dotenv()

# ─── CORE BOT CONFIG ───────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")

# Multiple bots: BOT_TOKEN_2, BOT_TOKEN_3, dst (opsional)
EXTRA_TOKENS = [
    v.strip() for k, v in os.environ.items()
    if k.startswith("BOT_TOKEN_") and v.strip()
]

# ─── ADMIN & ACCESS ────────────────────────────────────────────────
raw_admins  = os.getenv("ADMIN_ID", "0")
ADMIN_IDS   = [int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()]

# ─── API / PROVIDER ────────────────────────────────────────────────
TOP_TOOLS_KEY = os.getenv("TOP_TOOLS_API_KEY", "")
BASE_URL      = os.getenv("BASE_URL", "https://top-tools-ai.com/api/v1")

# ─── KREDIT & MODEL ────────────────────────────────────────────────
INITIAL_CREDITS = float(os.getenv("INITIAL_CREDITS", "220.00"))
DEFAULT_MODEL   = "top-tools-ai"

# Max history per user (configurable)
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))

# Retry config
API_TIMEOUT  = int(os.getenv("API_TIMEOUT", "120"))
API_RETRIES  = int(os.getenv("API_RETRIES", "3"))
RETRY_DELAY  = float(os.getenv("RETRY_DELAY", "2.0"))

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
