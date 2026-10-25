import asyncio
import os
import shutil
import sqlite3
import time
from pathlib import Path

from pyrogram import filters
from pyrogram.enums import ParseMode

from config import ADMIN_IDS, PUBLIC_DAILY_REQUEST_LIMIT, PUBLIC_DAILY_TOKEN_LIMIT
from utils.helpers import get_active_api, is_admin, is_private_mode, list_premium_users

_PROCESS_STARTED = time.monotonic()
DB_PATH = Path("data/hanna.db")


def _read_cpu_sample():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            values = handle.readline().split()[1:]
        numbers = [int(value) for value in values]
        idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
        total = sum(numbers)
        return total, idle
    except (OSError, ValueError, IndexError):
        return None


def _cpu_percent():
    first = _read_cpu_sample()
    if not first:
        return None
    time.sleep(0.08)
    second = _read_cpu_sample()
    if not second:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    return round(max(0.0, min(100.0, 100 * (1 - idle_delta / total_delta))), 1) if total_delta else 0.0


def _memory_info():
    values = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(0, total - available)
        return used / 1024, total / 1024, (used / total * 100) if total else None
    except (OSError, ValueError):
        return None, None, None


def _system_snapshot():
    cpu = _cpu_percent()
    mem_used, mem_total, mem_percent = _memory_info()
    disk = shutil.disk_usage(".")
    uptime_seconds = time.monotonic() - _PROCESS_STARTED
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            uptime_seconds = float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "cpu": cpu,
        "mem_used": mem_used,
        "mem_total": mem_total,
        "mem_percent": mem_percent,
        "disk_used": disk.used / (1024 ** 3),
        "disk_total": disk.total / (1024 ** 3),
        "disk_percent": disk.used / disk.total * 100 if disk.total else 0,
        "uptime": uptime_seconds,
        "db_size": db_size / (1024 ** 2),
    }


def _db_ping():
    started = time.perf_counter()
    try:
        with sqlite3.connect(str(DB_PATH), timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
        return round((time.perf_counter() - started) * 1000, 2), "OK"
    except sqlite3.Error as error:
        return round((time.perf_counter() - started) * 1000, 2), f"ERROR: {type(error).__name__}"


def _format_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days}h {hours:02d}j {minutes:02d}m {seconds:02d}d"


def admin_help_text() -> str:
    return (
        "<b>PERINTAH ADMIN HANNA AI</b>\n\n"
        "<b>Diagnostik</b>\n"
        "/ping - latency Telegram, database, CPU, memory, disk, uptime\n"
        "/status - ringkasan system, provider, dan premium\n"
        "/adminhelp - daftar command admin ini\n\n"
        "<b>Premium</b>\n"
        "/premium - lihat paket premium dan status akun\n"
        "/grantpremium ID hari - aktifkan premium setelah pembayaran diverifikasi\n"
        "/premiumusers - daftar premium aktif\n"
        "/revokepremium ID - cabut premium\n\n"
        "<b>Provider dan model</b>\n"
        "/api - buka pengaturan provider\n"
        "/balance - cek saldo provider dan pemakaian lokal\n"
        "/setkey KEY - ganti API key provider\n"
        "/seturl URL - ganti base URL provider\n"
        "/setprovider nama URL KEY - simpan dan aktifkan provider\n"
        "/addmodel ID | KATEGORI | NAMA | HARGA_IN | HARGA_OUT\n"
        "/delmodel ID - hapus model custom\n"
        "/setbalance USD - reset tracker lokal, bukan saldo provider\n\n"
        "<b>Akses</b>\n"
        "Gunakan menu API untuk mengubah mode Admin saja atau Publik.\n"
        f"Limit publik saat ini: {PUBLIC_DAILY_REQUEST_LIMIT} request atau "
        f"{PUBLIC_DAILY_TOKEN_LIMIT:,} token per hari."
    )


def register(app, bot_name: str = "default"):
    @app.on_message(filters.command(["adminhelp", "admin_help"]))
    async def adminhelp_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Akses ditolak. Command ini hanya untuk admin.")
        await m.reply_text(admin_help_text(), parse_mode=ParseMode.HTML)

    @app.on_message(filters.command(["ping", "status"]))
    async def status_cmd(c, m):
        if not is_admin(m.from_user.id):
            return await m.reply_text("Akses ditolak. Command ini hanya untuk admin.")
        started = time.perf_counter()
        try:
            await c.get_me()
            telegram_ms = (time.perf_counter() - started) * 1000
            db_result = await asyncio.to_thread(_db_ping)
            snapshot = await asyncio.to_thread(_system_snapshot)
            premium_users = await list_premium_users(bot_name)
            api = get_active_api()
            cpu = f"{snapshot['cpu']:.1f}%" if snapshot["cpu"] is not None else "n/a"
            memory = (
                f"{snapshot['mem_used']:.0f}/{snapshot['mem_total']:.0f} MB "
                f"({snapshot['mem_percent']:.1f}%)"
                if snapshot["mem_percent"] is not None else "n/a"
            )
            text = (
                "<b>STATUS HANNA AI</b>\n\n"
                f"Telegram API: <code>{telegram_ms:.1f} ms</code>\n"
                f"Database: <code>{db_result[1]} ({db_result[0]:.1f} ms)</code>\n"
                f"CPU: <code>{cpu}</code>\n"
                f"Memory: <code>{memory}</code>\n"
                f"Disk: <code>{snapshot['disk_used']:.1f}/{snapshot['disk_total']:.1f} GB "
                f"({snapshot['disk_percent']:.1f}%)</code>\n"
                f"Uptime: <code>{_format_uptime(snapshot['uptime'])}</code>\n"
                f"Database size: <code>{snapshot['db_size']:.2f} MB</code>\n\n"
                f"Provider: <code>{api['provider']}</code>\n"
                f"Premium aktif: <code>{len(premium_users)}</code> user\n"
                f"Mode: <code>{'admin saja' if is_private_mode() else 'publik'}</code>"
            )
            await m.reply_text(text, parse_mode=ParseMode.HTML)
        except Exception:
            await m.reply_text("Status tidak dapat dibaca. Periksa log server.")
