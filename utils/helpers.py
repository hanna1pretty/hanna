import os
import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from config import (
    DEFAULT_MODEL, DEFAULT_MODELS, DEFAULT_PROVIDERS,
    BASE_URL, TOP_TOOLS_KEY, ADMIN_IDS, INITIAL_CREDITS, MAX_HISTORY,
    PUBLIC_DAILY_REQUEST_LIMIT, PUBLIC_DAILY_TOKEN_LIMIT
)

logger  = logging.getLogger(__name__)
DB_PATH = "data/hanna.db"

# Thread pool khusus untuk DB — agar DB call tidak block event loop
_db_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")

# ─── DB CONNECTION ─────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")    # concurrent read/write
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")    # 8 MB cache
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn

def _run_db(fn):
    """Jalankan fungsi DB sinkron di thread pool, agar event loop tidak terblokir."""
    return asyncio.get_event_loop().run_in_executor(_db_executor, fn)

# ─── INIT DB ───────────────────────────────────────────────────────
def _init_db_sync():
    with _get_conn() as conn:
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id  INTEGER NOT NULL,
                model    TEXT NOT NULL,
                bot_name TEXT NOT NULL DEFAULT 'default',
                PRIMARY KEY (user_id, bot_name)
            );
            CREATE TABLE IF NOT EXISTS chat_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                bot_name   TEXT    DEFAULT 'default',
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS providers (
                name     TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                api_key  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS models (
                id        TEXT PRIMARY KEY,
                cat       TEXT NOT NULL,
                name      TEXT NOT NULL,
                desc      TEXT NOT NULL,
                in_price  REAL DEFAULT 0.0,
                out_price REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS usage_logs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER NOT NULL,
                bot_name          TEXT    DEFAULT 'default',
                provider          TEXT    NOT NULL,
                model             TEXT    NOT NULL,
                prompt_tokens     INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd          REAL    DEFAULT 0.0,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id    INTEGER NOT NULL,
                bot_name   TEXT NOT NULL DEFAULT 'default',
                expires_at TEXT NOT NULL,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, bot_name)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                bot_name   TEXT NOT NULL DEFAULT 'default',
                title      TEXT NOT NULL DEFAULT 'Percakapan baru',
                archived  INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS active_conversations (
                user_id         INTEGER NOT NULL,
                bot_name        TEXT NOT NULL DEFAULT 'default',
                conversation_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, bot_name)
            );
            CREATE INDEX IF NOT EXISTS idx_history_user ON chat_history(user_id, bot_name);
            CREATE INDEX IF NOT EXISTS idx_usage_user   ON usage_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, bot_name, updated_at);
        """)

        history_columns = {row[1] for row in c.execute("PRAGMA table_info(chat_history)").fetchall()}
        if "conversation_id" not in history_columns:
            c.execute("ALTER TABLE chat_history ADD COLUMN conversation_id INTEGER")
            legacy_pairs = c.execute(
                "SELECT DISTINCT user_id, COALESCE(bot_name, 'default') AS bot_name FROM chat_history"
            ).fetchall()
            for pair in legacy_pairs:
                c.execute(
                    "INSERT INTO conversations (user_id, bot_name, title) VALUES (?, ?, ?)",
                    (pair[0], pair[1], "Percakapan lama"),
                )
                conversation_id = c.lastrowid
                c.execute(
                    "INSERT OR REPLACE INTO active_conversations (user_id, bot_name, conversation_id) VALUES (?, ?, ?)",
                    (pair[0], pair[1], conversation_id),
                )
                c.execute(
                    "UPDATE chat_history SET conversation_id=? WHERE user_id=? AND COALESCE(bot_name, 'default')=? AND conversation_id IS NULL",
                    (conversation_id, pair[0], pair[1]),
                )
            logger.info("Migrated legacy chat history to conversations.")

        # Migrate the original single-column primary key without deleting data.
        user_columns = c.execute("PRAGMA table_info(users)").fetchall()
        pk_columns = [row[1] for row in user_columns if row[5]]
        if pk_columns == ["user_id"]:
            c.executescript("""
                ALTER TABLE users RENAME TO users_legacy;
                CREATE TABLE users (
                    user_id  INTEGER NOT NULL,
                    model    TEXT NOT NULL,
                    bot_name TEXT NOT NULL DEFAULT 'default',
                    PRIMARY KEY (user_id, bot_name)
                );
                INSERT OR IGNORE INTO users (user_id, model, bot_name)
                    SELECT user_id, model, COALESCE(bot_name, 'default') FROM users_legacy;
                DROP TABLE users_legacy;
            """)
            logger.info("Migrated users table to composite (user_id, bot_name) key.")

        # Default settings
        defaults = {
            "active_provider": "toptools",
            "base_url":        BASE_URL,
            "api_key":         TOP_TOOLS_KEY,
            "initial_credits": str(INITIAL_CREDITS),
            "private_mode":    "1",
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        # Default providers
        for p in DEFAULT_PROVIDERS:
            c.execute(
                "INSERT OR IGNORE INTO providers (name, base_url, api_key) VALUES (?, ?, ?)",
                (p["name"], p["base_url"], p["api_key"])
            )
        if TOP_TOOLS_KEY:
            c.execute("UPDATE providers SET api_key=? WHERE name='toptools' AND api_key=''", (TOP_TOOLS_KEY,))
            c.execute("UPDATE settings  SET value=?   WHERE key='api_key'  AND value=''",   (TOP_TOOLS_KEY,))

        # Default models (hanya jika kosong)
        if c.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 0:
            for m in DEFAULT_MODELS:
                c.execute(
                    "INSERT INTO models (id,cat,name,desc,in_price,out_price) VALUES (?,?,?,?,?,?)",
                    (m["id"], m["cat"], m["name"], m["desc"], m.get("in_price",0.0), m.get("out_price",0.0))
                )
        conn.commit()
    logger.info("Database initialized.")

def init_db():
    """Sync wrapper — dipanggil sekali saat startup."""
    _init_db_sync()

# ─── ADMIN & ACCESS ────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    # Fail closed: an empty admin list must never grant administrator access.
    return bool(ADMIN_IDS) and user_id in ADMIN_IDS

def _get_private_mode_sync() -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='private_mode'").fetchone()
        return row["value"] == "1" if row else True

async def is_private_mode_async() -> bool:
    return await _run_db(_get_private_mode_sync)

def is_private_mode() -> bool:          # untuk keyboard (sync context)
    return _get_private_mode_sync()

async def toggle_private_mode() -> bool:
    current = await is_private_mode_async()
    new_val = "0" if current else "1"
    def _toggle():
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('private_mode',?)", (new_val,))
            conn.commit()
    await _run_db(_toggle)
    return new_val == "1"

async def can_use_bot_async(user_id: int) -> bool:
    return is_admin(user_id) or not await is_private_mode_async()

def can_use_bot(user_id: int) -> bool:  # sync fallback
    return is_admin(user_id) or not _get_private_mode_sync()

async def check_public_limit(user_id: int, bot_name: str = "default") -> tuple[bool, str]:
    """Check the daily public quota; administrators are never limited here."""
    if is_admin(user_id) or await is_premium_user(user_id, bot_name):
        return True, ""
    if await is_private_mode_async():
        return False, "Bot sedang dalam mode admin saja."

    def _check():
        admin_contact = ", ".join(str(value) for value in ADMIN_IDS) or "admin bot"

        def premium_message(reason: str) -> str:
            return (
                f"<b>Limit penggunaan tercapai</b>\n\n"
                f"{reason}\n\n"
                "Ingin melanjutkan? Hubungi admin untuk membeli credit atau mengaktifkan akses premium.\n"
                f"ID admin: <code>{admin_contact}</code>"
            )

        with _get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS requests,
                          COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens
                   FROM usage_logs
                   WHERE user_id=? AND date(created_at)=date('now')""",
                (user_id,),
            ).fetchone()
            requests = int(row["requests"])
            tokens = int(row["tokens"])
            if requests >= PUBLIC_DAILY_REQUEST_LIMIT:
                return False, premium_message(
                    f"Batas harian tercapai: {PUBLIC_DAILY_REQUEST_LIMIT} permintaan."
                )
            if tokens >= PUBLIC_DAILY_TOKEN_LIMIT:
                return False, premium_message(
                    f"Batas token harian tercapai: {PUBLIC_DAILY_TOKEN_LIMIT:,} token."
                )
            return True, ""
    return await _run_db(_check)

async def is_premium_user(user_id: int, bot_name: str = "default") -> bool:
    def _check():
        with _get_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM premium_users
                   WHERE user_id=? AND bot_name=? AND expires_at > datetime('now')""",
                (user_id, bot_name),
            ).fetchone()
            return row is not None
    return await _run_db(_check)


def is_premium_user_sync(user_id: int, bot_name: str = "default") -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM premium_users
               WHERE user_id=? AND bot_name=? AND expires_at > datetime('now')""",
            (user_id, bot_name),
        ).fetchone()
        return row is not None


def get_model_info(model_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return dict(row) if row else None


async def can_use_model_async(user_id: int, model_id: str, bot_name: str = "default") -> tuple[bool, str]:
    if is_admin(user_id) or await is_premium_user(user_id, bot_name):
        return True, ""
    model = await _run_db(lambda: get_model_info(model_id))
    if not model or str(model.get("cat", "")).lower() == "free":
        return True, ""
    admin_contact = ", ".join(str(value) for value in ADMIN_IDS) or "admin bot"
    return False, (
        "<b>AKSES PREMIUM DIPERLUKAN</b>\n\n"
        f"Model <code>{model['name']}</code> termasuk kategori Pay as you go.\n"
        "User publik dapat menggunakan model gratis. Untuk memakai model Pay as you go, "
        "aktifkan paket premium melalui admin.\n\n"
        f"ID admin: <code>{admin_contact}</code>"
    )

async def grant_premium(user_id: int, days: int, bot_name: str = "default"):
    if days <= 0 or days > 3650:
        raise ValueError("days must be between 1 and 3650")

    def _grant():
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO premium_users (user_id, bot_name, expires_at)
                   VALUES (?, ?, datetime('now', ?))
                   ON CONFLICT(user_id, bot_name) DO UPDATE SET
                     expires_at = datetime(
                         CASE WHEN premium_users.expires_at > datetime('now')
                              THEN premium_users.expires_at ELSE datetime('now') END,
                         ?
                     )""",
                (user_id, bot_name, f"+{days} days", f"+{days} days"),
            )
            conn.commit()
    await _run_db(_grant)

async def revoke_premium(user_id: int, bot_name: str = "default") -> bool:
    def _revoke():
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM premium_users WHERE user_id=? AND bot_name=?",
                (user_id, bot_name),
            )
            changed = conn.execute("SELECT changes()").fetchone()[0] > 0
            conn.commit()
            return changed
    return await _run_db(_revoke)

async def list_premium_users(bot_name: str = "default") -> list:
    def _list():
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT user_id, expires_at FROM premium_users
                   WHERE bot_name=? AND expires_at > datetime('now')
                   ORDER BY expires_at ASC""", (bot_name,)
            ).fetchall()
            return [dict(row) for row in rows]
    return await _run_db(_list)

def mask_key(key: str) -> str:
    if not key:
        return "NOT SET"
    return f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "***"

# ─── KREDIT ────────────────────────────────────────────────────────
async def set_initial_credits(amount: float):
    def _set():
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('initial_credits',?)", (str(amount),))
            conn.execute("DELETE FROM usage_logs")
            conn.commit()
    await _run_db(_set)

async def record_usage(user_id: int, provider: str, model_id: str,
                       prompt_tokens: int, completion_tokens: int,
                       fixed_cost: float = None, bot_name: str = "default"):
    def _record():
        with _get_conn() as conn:
            if fixed_cost is not None:
                cost = fixed_cost
            else:
                row = conn.execute(
                    "SELECT in_price, out_price, cat FROM models WHERE id=?", (model_id,)
                ).fetchone()
                if row and row["cat"].lower() != "free":
                    cost = (prompt_tokens / 1_000_000) * float(row["in_price"] or 1.0) \
                         + (completion_tokens / 1_000_000) * float(row["out_price"] or 5.0)
                else:
                    cost = 0.0
            conn.execute(
                """INSERT INTO usage_logs
                   (user_id,bot_name,provider,model,prompt_tokens,completion_tokens,cost_usd)
                   VALUES (?,?,?,?,?,?,?)""",
                (user_id, bot_name, provider, model_id, prompt_tokens, completion_tokens, cost)
            )
            conn.commit()
    await _run_db(_record)

async def get_credit_summary() -> dict:
    def _query():
        with _get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='initial_credits'").fetchone()
            initial = float(row["value"]) if row else INITIAL_CREDITS
            stat = conn.execute("""
                SELECT COUNT(*)                           AS total_req,
                       COALESCE(SUM(prompt_tokens),0)    AS total_in,
                       COALESCE(SUM(completion_tokens),0) AS total_out,
                       COALESCE(SUM(cost_usd),0.0)       AS total_spent
                FROM usage_logs
            """).fetchone()
            spent     = float(stat["total_spent"])
            remaining = max(0.0, initial - spent)
            return {
                "initial":       initial,
                "spent":         spent,
                "remaining":     remaining,
                "requests":      stat["total_req"],
                "input_tokens":  stat["total_in"],
                "output_tokens": stat["total_out"],
                "total_tokens":  stat["total_in"] + stat["total_out"],
            }
    return await _run_db(_query)

def get_credit_summary_sync() -> dict:   # untuk keyboards
    with _get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='initial_credits'").fetchone()
        initial = float(row["value"]) if row else INITIAL_CREDITS
        stat = conn.execute("""
            SELECT COUNT(*)                           AS total_req,
                   COALESCE(SUM(prompt_tokens),0)    AS total_in,
                   COALESCE(SUM(completion_tokens),0) AS total_out,
                   COALESCE(SUM(cost_usd),0.0)       AS total_spent
            FROM usage_logs
        """).fetchone()
        spent = float(stat["total_spent"])
        return {
            "initial": initial, "spent": spent,
            "remaining": max(0.0, initial - spent),
            "requests": stat["total_req"],
            "input_tokens": stat["total_in"], "output_tokens": stat["total_out"],
            "total_tokens": stat["total_in"] + stat["total_out"],
        }

# ─── API & PROVIDER ────────────────────────────────────────────────
def get_active_api() -> dict:           # sync — dipanggil dari AI module
    with _get_conn() as conn:
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings").fetchall()}
    return {
        "provider": rows.get("active_provider", "toptools"),
        "base_url": rows.get("base_url", BASE_URL).rstrip("/"),
        "api_key":  rows.get("api_key", TOP_TOOLS_KEY),
    }

async def set_api_key(new_key: str):
    active = get_active_api()["provider"]
    def _set():
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('api_key',?)", (new_key.strip(),))
            conn.execute("UPDATE providers SET api_key=? WHERE name=?", (new_key.strip(), active))
            conn.commit()
    await _run_db(_set)

async def set_base_url(new_url: str):
    clean  = new_url.strip().rstrip("/")
    active = get_active_api()["provider"]
    def _set():
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('base_url',?)", (clean,))
            conn.execute("UPDATE providers SET base_url=? WHERE name=?", (clean, active))
            conn.commit()
    await _run_db(_set)

async def save_provider(name: str, base_url: str, api_key: str):
    pname     = name.strip().lower()
    clean_url = base_url.strip().rstrip("/")
    clean_key = api_key.strip()
    def _save():
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO providers (name,base_url,api_key) VALUES (?,?,?)",
                         (pname, clean_url, clean_key))
            for k, v in [("active_provider",pname),("base_url",clean_url),("api_key",clean_key)]:
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v))
            conn.commit()
    await _run_db(_save)

async def switch_provider(name: str) -> tuple:
    pname = name.strip().lower()
    def _switch():
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT name,base_url,api_key FROM providers WHERE name=?", (pname,)
            ).fetchone()
            if not row:
                return False, "Provider not found."
            for k, v in [("active_provider",row["name"]),("base_url",row["base_url"]),("api_key",row["api_key"])]:
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v))
            conn.commit()
            return True, dict(row)
    return await _run_db(_switch)

def get_providers() -> list:            # sync — untuk keyboard
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT name,base_url,api_key FROM providers ORDER BY name ASC"
        ).fetchall()]

# ─── MODEL ─────────────────────────────────────────────────────────
def get_all_models(cat: str = "All") -> list:   # sync — для keyboard
    with _get_conn() as conn:
        if cat == "All":
            rows = conn.execute("SELECT * FROM models").fetchall()
        else:
            rows = conn.execute("SELECT * FROM models WHERE cat=?", (cat,)).fetchall()
        return [dict(r) for r in rows]

def model_exists(model_id: str) -> bool:
    with _get_conn() as conn:
        return conn.execute("SELECT 1 FROM models WHERE id=?", (model_id,)).fetchone() is not None

async def add_custom_model(model_id: str, cat: str, name: str,
                           in_price: float = 1.0, out_price: float = 5.0):
    desc = "Free Model" if cat.lower() == "free" else f"${in_price:.2f}/1M in - ${out_price:.2f}/1M out"
    def _add():
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO models (id,cat,name,desc,in_price,out_price) VALUES (?,?,?,?,?,?)",
                (model_id.strip(), cat.strip(), name.strip(), desc, in_price, out_price)
            )
            conn.commit()
    await _run_db(_add)

async def delete_custom_model(model_id: str) -> bool:
    def _del():
        with _get_conn() as conn:
            conn.execute("DELETE FROM models WHERE id=?", (model_id.strip(),))
            deleted = conn.execute("SELECT changes()").fetchone()[0] > 0
            conn.commit()
            return deleted
    return await _run_db(_del)

# ─── USER & HISTORY ────────────────────────────────────────────────
async def get_model_async(uid: int, bot_name: str = "default") -> str:
    def _get():
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT model FROM users WHERE user_id=? AND bot_name=?", (uid, bot_name)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (user_id,model,bot_name) VALUES (?,?,?)",
                    (uid, DEFAULT_MODEL, bot_name)
                )
                conn.commit()
                return DEFAULT_MODEL
            return row["model"]
    return await _run_db(_get)

def get_model(uid: int, bot_name: str = "default") -> str:   # sync fallback untuk keyboard
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT model FROM users WHERE user_id=? AND bot_name=?", (uid, bot_name)
        ).fetchone()
        if not row:
            conn.execute("INSERT INTO users (user_id,model,bot_name) VALUES (?,?,?)",
                         (uid, DEFAULT_MODEL, bot_name))
            conn.commit()
            return DEFAULT_MODEL
        return row["model"]

async def set_model(uid: int, model_id: str, bot_name: str = "default"):
    def _set():
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id,model,bot_name) VALUES (?,?,?)",
                (uid, model_id, bot_name)
            )
            conn.commit()
    await _run_db(_set)

def _ensure_conversation_sync(conn, uid: int, bot_name: str = "default") -> int:
    row = conn.execute(
        """SELECT conversation_id FROM active_conversations
           WHERE user_id=? AND bot_name=?""", (uid, bot_name)
    ).fetchone()
    if row:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE id=? AND user_id=? AND bot_name=? AND archived=0",
            (row["conversation_id"], uid, bot_name),
        ).fetchone()
        if conversation:
            return int(conversation["id"])
    conn.execute(
        "INSERT INTO conversations (user_id, bot_name, title) VALUES (?, ?, ?)",
        (uid, bot_name, "Percakapan baru"),
    )
    conversation_id = conn.lastrowid
    conn.execute(
        """INSERT OR REPLACE INTO active_conversations (user_id, bot_name, conversation_id)
           VALUES (?, ?, ?)""", (uid, bot_name, conversation_id)
    )
    return int(conversation_id)

async def get_history(uid: int, bot_name: str = "default") -> list:
    def _get():
        with _get_conn() as conn:
            conversation_id = _ensure_conversation_sync(conn, uid, bot_name)
            rows = conn.execute(
                """SELECT role, content FROM chat_history
                   WHERE conversation_id=? ORDER BY id DESC LIMIT ?""",
                (conversation_id, MAX_HISTORY),
            ).fetchall()
            conn.commit()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    return await _run_db(_get)

async def add_history(uid: int, role: str, content: str, bot_name: str = "default"):
    def _add():
        with _get_conn() as conn:
            conversation_id = _ensure_conversation_sync(conn, uid, bot_name)
            conn.execute(
                """INSERT INTO chat_history
                   (user_id, bot_name, conversation_id, role, content)
                   VALUES (?, ?, ?, ?, ?)""",
                (uid, bot_name, conversation_id, role, content),
            )
            conn.execute(
                """UPDATE conversations SET updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""", (conversation_id,)
            )
            conn.execute(
                """DELETE FROM chat_history
                   WHERE conversation_id=? AND id NOT IN (
                       SELECT id FROM chat_history WHERE conversation_id=?
                       ORDER BY id DESC LIMIT ?
                   )""", (conversation_id, conversation_id, MAX_HISTORY),
            )
            conn.commit()
    await _run_db(_add)

async def clear_history(uid: int, bot_name: str = "default"):
    def _clear():
        with _get_conn() as conn:
            conversation_id = _ensure_conversation_sync(conn, uid, bot_name)
            conn.execute("DELETE FROM chat_history WHERE conversation_id=?", (conversation_id,))
            conn.execute(
                "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (conversation_id,),
            )
            conn.commit()
    await _run_db(_clear)

async def list_conversations(uid: int, bot_name: str = "default") -> list:
    def _list():
        with _get_conn() as conn:
            active_id = _ensure_conversation_sync(conn, uid, bot_name)
            rows = conn.execute(
                """SELECT c.id, c.title, c.updated_at, COUNT(h.id) AS messages
                   FROM conversations c LEFT JOIN chat_history h ON h.conversation_id=c.id
                   WHERE c.user_id=? AND c.bot_name=? AND c.archived=0
                   GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT 20""",
                (uid, bot_name),
            ).fetchall()
            conn.commit()
            return [dict(row) | {"active": row["id"] == active_id} for row in rows]
    return await _run_db(_list)

async def create_conversation(uid: int, title: str = "Percakapan baru", bot_name: str = "default") -> int:
    def _create():
        with _get_conn() as conn:
            clean_title = " ".join((title or "Percakapan baru").split())[:60] or "Percakapan baru"
            conn.execute(
                "INSERT INTO conversations (user_id, bot_name, title) VALUES (?, ?, ?)",
                (uid, bot_name, clean_title),
            )
            conversation_id = int(conn.lastrowid)
            conn.execute(
                """INSERT OR REPLACE INTO active_conversations
                   (user_id, bot_name, conversation_id) VALUES (?, ?, ?)""",
                (uid, bot_name, conversation_id),
            )
            conn.commit()
            return conversation_id
    return await _run_db(_create)

async def switch_conversation(uid: int, conversation_id: int, bot_name: str = "default") -> bool:
    def _switch():
        with _get_conn() as conn:
            row = conn.execute(
                """SELECT id FROM conversations
                   WHERE id=? AND user_id=? AND bot_name=? AND archived=0""",
                (conversation_id, uid, bot_name),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                """INSERT OR REPLACE INTO active_conversations
                   (user_id, bot_name, conversation_id) VALUES (?, ?, ?)""",
                (uid, bot_name, conversation_id),
            )
            conn.commit()
            return True
    return await _run_db(_switch)
