import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta
from config import API_TIMEOUT, API_RETRIES, RETRY_DELAY, SYSTEM_PROMPT
from utils.helpers import get_active_api, record_usage

logger = logging.getLogger(__name__)

def _estimate_tokens(text: str) -> int:
    return max(1, len(str(text)) // 4)

async def _post_with_retry(url: str, headers: dict, payload: dict) -> dict:
    """POST ke API dengan retry + exponential backoff. Fully async, tidak block."""
    last_err = None
    for attempt in range(1, API_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 429:
                        wait = RETRY_DELAY * attempt
                        logger.warning(f"Rate limited. Retry {attempt}/{API_RETRIES} in {wait}s")
                        await asyncio.sleep(wait)   # async sleep — tidak block user lain
                        continue
                    if resp.status >= 500:
                        wait = RETRY_DELAY * attempt
                        logger.warning(f"Server error {resp.status}. Retry {attempt}/{API_RETRIES} in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        await resp.read()
                        raise RuntimeError(f"API request failed with status {resp.status}")
                    return await resp.json()
        except aiohttp.ClientConnectorError as e:
            last_err = e
            logger.error(f"Connection error attempt {attempt}: {e}")
            await asyncio.sleep(RETRY_DELAY * attempt)
        except asyncio.TimeoutError:
            last_err = TimeoutError("Request timed out")
            logger.error(f"Timeout attempt {attempt}/{API_RETRIES}")
            await asyncio.sleep(RETRY_DELAY * attempt)

    raise last_err or RuntimeError("Max retries exceeded")

# ─── CHAT COMPLETION ───────────────────────────────────────────────
async def chat_completion(uid: int, model: str, history: list,
                          bot_name: str = "default") -> str:
    api      = get_active_api()
    provider = api["provider"]
    api_key  = api["api_key"]

    if not api_key:
        return f"⚠️ API Key untuk provider '{provider}' belum diatur.\nGunakan /setkey <API_KEY>"

    # System prompt + history (sudah ada dari get_history)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages}
    url     = f"{api['base_url']}/chat/completions"

    try:
        data  = await _post_with_retry(url, headers, payload)
        reply = data["choices"][0]["message"]["content"]

        usage    = data.get("usage", {})
        p_tokens = usage.get("prompt_tokens")     or _estimate_tokens(str(messages))
        c_tokens = usage.get("completion_tokens") or _estimate_tokens(reply)

        # Record usage async — tidak block reply ke user
        asyncio.create_task(
            record_usage(uid, provider, model, int(p_tokens), int(c_tokens), bot_name=bot_name)
        )

        logger.info(f"[{bot_name}] uid={uid} model={model} in={p_tokens} out={c_tokens}")
        return reply

    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected API response: {e}")
        return "⚠️ Unexpected response format from API."
    except RuntimeError as e:
        logger.error("API runtime error: %s", e)
        return "⚠️ API sedang tidak dapat digunakan. Coba lagi nanti."
    except Exception:
        logger.exception("Unhandled error in chat_completion uid=%s", uid)
        return "⚠️ Terjadi kesalahan saat menghubungi AI. Coba lagi nanti."

# ─── VISION ────────────────────────────────────────────────────────
async def vision_completion(uid: int, model: str, prompt: str,
                            b64_image: str, bot_name: str = "default") -> str:
    api      = get_active_api()
    provider = api["provider"]
    api_key  = api["api_key"]

    if not api_key:
        return f"⚠️ API Key untuk provider '{provider}' belum diatur."

    vision_model = model if any(k in model.lower() for k in ["vision","vl","vis"]) \
                   else "DeepSeek-V4-Flash-Vision-Exp"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text",      "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
        ]}
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": vision_model, "messages": messages}
    url     = f"{api['base_url']}/chat/completions"

    try:
        data  = await _post_with_retry(url, headers, payload)
        reply = data["choices"][0]["message"]["content"]

        usage    = data.get("usage", {})
        p_tokens = usage.get("prompt_tokens")     or _estimate_tokens(prompt)
        c_tokens = usage.get("completion_tokens") or _estimate_tokens(reply)

        asyncio.create_task(
            record_usage(uid, provider, vision_model, int(p_tokens), int(c_tokens), bot_name=bot_name)
        )
        return reply
    except Exception:
        logger.exception("Vision error uid=%s", uid)
        return "⚠️ Gagal menganalisis gambar. Coba lagi nanti."

# ─── IMAGE GENERATION ──────────────────────────────────────────────
async def generate_image(uid: int, prompt: str, bot_name: str = "default") -> str:
    api      = get_active_api()
    provider = api["provider"]
    api_key  = api["api_key"]

    if not api_key:
        raise RuntimeError(f"API Key untuk provider '{provider}' belum diatur.")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "n": 1, "size": "1024x1024"}
    url     = f"{api['base_url']}/images/generations"

    data = await _post_with_retry(url, headers, payload)
    asyncio.create_task(
        record_usage(uid, provider, "image-gen", _estimate_tokens(prompt), 0,
                     fixed_cost=0.02, bot_name=bot_name)
    )
    return data["data"][0]["url"]

# ─── LIVE BALANCE ──────────────────────────────────────────────────
async def check_live_api_balance() -> str:
    api      = get_active_api()
    base_url = api["base_url"].rstrip("/")
    root_url = base_url[:-3] if base_url.endswith("/v1") else base_url
    api_key  = api["api_key"]

    if not api_key:
        return "API Key belum diatur"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=4)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Top Tools documents the chat/image endpoints but not a public balance endpoint.
        # Keep only the least-invasive compatibility probes and fail fast when unavailable.
        for url in [f"{base_url}/credits", f"{root_url}/credits"]:
            try:
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        raw = await r.json()
                        d   = raw.get("data", raw)
                        if isinstance(d, dict):
                            if "total_credits" in d:
                                total = float(d["total_credits"])
                                used  = float(d.get("total_usage", 0))
                                return f"${total-used:.4f} (Total: ${total:.2f} | Used: ${used:.4f})"
                            if "credits" in d or "balance" in d:
                                return f"${float(d.get('credits', d.get('balance'))):.4f}"
            except Exception:
                pass

        try:
            async with session.get(f"{base_url}/auth/key", headers=headers) as r:
                if r.status == 200:
                    d = (await r.json()).get("data", {})
                    if d.get("limit_remaining") is not None:
                        return f"${float(d['limit_remaining']):.4f} (Used: ${float(d.get('usage',0)):.4f})"
        except Exception:
            pass

    return "Tidak tersedia dari API provider (gunakan dashboard TopTools)"
