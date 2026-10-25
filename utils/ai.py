import asyncio
import inspect
import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from config import API_TIMEOUT, API_RETRIES, RETRY_DELAY, SYSTEM_PROMPT
from utils.helpers import get_active_api, record_usage

logger = logging.getLogger(__name__)
WIB = ZoneInfo("Asia/Jakarta")


class StreamingError(RuntimeError):
    """Streaming failed; partial_text prevents an unsafe duplicate retry."""

    def __init__(self, message: str, partial_text: str = ""):
        super().__init__(message)
        self.partial_text = partial_text


def _estimate_tokens(text: str) -> int:
    return max(1, len(str(text)) // 4)


def _current_system_prompt() -> str:
    now = datetime.now(WIB)
    now_text = now.strftime("%A, %d %B %Y %H:%M:%S WIB")
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Current server time: {now_text}. Timezone: Asia/Jakarta (WIB). "
        "When the user asks for the current time, date, day, or WIB time, "
        "answer from this timestamp and state that it is the bot's current time. "
        "Do not invent live web data, news, weather, prices, or events; say when "
        "you do not have a live data source."
    )


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _record_usage_background(uid: int, provider: str, model: str,
                             prompt_tokens: int, completion_tokens: int,
                             bot_name: str = "default") -> None:
    task = asyncio.create_task(
        record_usage(uid, provider, model, int(prompt_tokens), int(completion_tokens), bot_name=bot_name)
    )

    def _done(completed):
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            logger.warning("Usage recording failed: %s", error)

    task.add_done_callback(_done)


async def _post_with_retry(url: str, headers: dict, payload: dict) -> dict:
    """POST JSON with bounded async retries."""
    last_error = None
    for attempt in range(1, API_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 429 or response.status >= 500:
                        wait = RETRY_DELAY * attempt
                        logger.warning(
                            "API status %s; retry %s/%s in %.1fs",
                            response.status, attempt, API_RETRIES, wait,
                        )
                        await response.read()
                        if attempt < API_RETRIES:
                            await asyncio.sleep(wait)
                            continue
                    if response.status != 200:
                        await response.read()
                        raise RuntimeError(f"API request failed with status {response.status}")
                    return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            last_error = error
            logger.warning("API request attempt %s/%s failed: %s", attempt, API_RETRIES, error)
            if attempt < API_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    raise last_error or RuntimeError("API request failed after retries")


def _content_from_delta(delta) -> str:
    if isinstance(delta, str):
        return delta
    if isinstance(delta, list):
        return "".join(
            part.get("text", "") for part in delta
            if isinstance(part, dict) and isinstance(part.get("text", ""), str)
        )
    return ""


async def _stream_once(url: str, headers: dict, payload: dict, on_text=None):
    """Read OpenAI-compatible SSE and return (text, usage)."""
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
    pieces = []
    usage = {}
    last_sent = ""
    finished = False
    started_at = time.perf_counter()
    first_piece_at = None

    async def process_line(raw_line: str):
        nonlocal last_sent, finished, first_piece_at
        line = raw_line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            return
        raw_data = line[5:].strip()
        if raw_data == "[DONE]":
            finished = True
            return
        try:
            chunk = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.debug("Ignoring malformed SSE chunk")
            return

        if isinstance(chunk.get("usage"), dict):
            usage.update(chunk["usage"])
        choices = chunk.get("choices") or []
        if not choices:
            return
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        piece = _content_from_delta(delta.get("content", ""))
        if not piece:
            return
        if first_piece_at is None:
            first_piece_at = time.perf_counter()
            logger.info("AI first token in %.0f ms url=%s", (first_piece_at - started_at) * 1000, url)
        pieces.append(piece)
        current = "".join(pieces)
        if on_text and current != last_sent:
            result = on_text(current)
            if inspect.isawaitable(result):
                await result
            last_sent = current

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                body = await response.text()
                logger.warning("Streaming API returned status %s: %s", response.status, body[:300])
                raise RuntimeError(f"Streaming API failed with status {response.status}")

            buffer = ""
            async for raw_chunk in response.content:
                buffer += raw_chunk.decode("utf-8", errors="ignore")
                lines = buffer.split("\n")
                buffer = lines.pop()
                for line in lines:
                    await process_line(line)
                    if finished:
                        break
                if finished:
                    break
            if not finished and buffer:
                await process_line(buffer)

    logger.info("AI stream completed in %.0f ms url=%s", (time.perf_counter() - started_at) * 1000, url)
    return "".join(pieces).strip(), usage


async def stream_chat_completion(uid: int, model: str, history: list,
                                 bot_name: str = "default", on_text=None) -> str:
    """Stream chat response and call on_text(full_text) as deltas arrive."""
    api = get_active_api()
    provider = api["provider"]
    api_key = api["api_key"]
    if not api_key:
        raise StreamingError(f"API Key untuk provider '{provider}' belum diatur.")

    messages = [{"role": "system", "content": _current_system_prompt()}] + history
    payload = {"model": model, "messages": messages, "stream": True}
    headers = {**_headers(api_key), "Accept": "text/event-stream"}
    url = f"{api['base_url']}/chat/completions"
    partial = ""
    last_error = None

    async def _capture(text: str):
        nonlocal partial
        partial = text
        if on_text:
            result = on_text(text)
            if inspect.isawaitable(result):
                await result

    request_started = time.perf_counter()
    for attempt in range(1, API_RETRIES + 1):
        try:
            reply, usage = await _stream_once(url, headers, payload, on_text=_capture)
            if not reply:
                raise RuntimeError("Streaming API returned no text")
            p_tokens = usage.get("prompt_tokens") or _estimate_tokens(str(messages))
            c_tokens = usage.get("completion_tokens") or _estimate_tokens(reply)
            _record_usage_background(uid, provider, model, p_tokens, c_tokens, bot_name)
            logger.info(
                "[%s] streamed uid=%s model=%s in=%s out=%s total_ms=%.0f",
                bot_name, uid, model, p_tokens, c_tokens,
                (time.perf_counter() - request_started) * 1000,
            )
            return reply
        except StreamingError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as error:
            last_error = error
            if partial:
                raise StreamingError(str(error), partial_text=partial) from error
            if attempt < API_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    raise StreamingError(str(last_error or "Streaming failed"), partial_text=partial)


async def chat_completion(uid: int, model: str, history: list,
                          bot_name: str = "default") -> str:
    """Non-streaming fallback used when SSE is unavailable or fails early."""
    api = get_active_api()
    provider = api["provider"]
    api_key = api["api_key"]
    if not api_key:
        return f"⚠️ API Key untuk provider '{provider}' belum diatur.\nGunakan /setkey <API_KEY>"

    messages = [{"role": "system", "content": _current_system_prompt()}] + history
    headers = _headers(api_key)
    payload = {"model": model, "messages": messages}
    url = f"{api['base_url']}/chat/completions"
    try:
        data = await _post_with_retry(url, headers, payload)
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        p_tokens = usage.get("prompt_tokens") or _estimate_tokens(str(messages))
        c_tokens = usage.get("completion_tokens") or _estimate_tokens(reply)
        _record_usage_background(uid, provider, model, p_tokens, c_tokens, bot_name)
        return reply
    except (KeyError, IndexError):
        logger.exception("Unexpected non-streaming API response")
        return "⚠️ Format respons API tidak dikenali."
    except Exception:
        logger.exception("Non-streaming chat error uid=%s", uid)
        return "⚠️ API sedang tidak dapat digunakan. Coba lagi nanti."


async def vision_completion(uid: int, model: str, prompt: str,
                            b64_image: str, bot_name: str = "default") -> str:
    api = get_active_api()
    provider = api["provider"]
    api_key = api["api_key"]
    if not api_key:
        return f"⚠️ API Key untuk provider '{provider}' belum diatur."

    vision_model = model if any(k in model.lower() for k in ["vision", "vl", "vis"]) else "DeepSeek-V4-Flash-Vision-Exp"
    messages = [
        {"role": "system", "content": _current_system_prompt()},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}},
        ]},
    ]
    try:
        data = await _post_with_retry(
            f"{api['base_url']}/chat/completions", _headers(api_key),
            {"model": vision_model, "messages": messages},
        )
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        _record_usage_background(
            uid, provider, vision_model,
            usage.get("prompt_tokens") or _estimate_tokens(prompt),
            usage.get("completion_tokens") or _estimate_tokens(reply),
            bot_name,
        )
        return reply
    except Exception:
        logger.exception("Vision error uid=%s", uid)
        return "⚠️ Gagal menganalisis gambar. Coba lagi nanti."


async def generate_image(uid: int, prompt: str, bot_name: str = "default") -> str:
    api = get_active_api()
    provider = api["provider"]
    api_key = api["api_key"]
    if not api_key:
        raise RuntimeError(f"API Key untuk provider '{provider}' belum diatur.")
    data = await _post_with_retry(
        f"{api['base_url']}/images/generations", _headers(api_key),
        {"prompt": prompt, "n": 1, "size": "1024x1024"},
    )
    _record_usage_background(
        uid, provider, "image-gen", _estimate_tokens(prompt), 0, bot_name
    )
    return data["data"][0]["url"]


async def check_live_api_balance() -> str:
    api = get_active_api()
    base_url = api["base_url"].rstrip("/")
    root_url = base_url[:-3] if base_url.endswith("/v1") else base_url
    api_key = api["api_key"]
    if not api_key:
        return "API Key belum diatur"

    headers = {**_headers(api_key), "Accept": "application/json"}
    timeout = aiohttp.ClientTimeout(total=4)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in [f"{base_url}/credits", f"{root_url}/credits"]:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        continue
                    raw = await response.json()
                    data = raw.get("data", raw)
                    if not isinstance(data, dict):
                        continue
                    if "total_credits" in data:
                        total = float(data["total_credits"])
                        used = float(data.get("total_usage", 0))
                        return f"${total - used:.4f} (Total: ${total:.2f} | Used: ${used:.4f})"
                    if "credits" in data or "balance" in data:
                        return f"${float(data.get('credits', data.get('balance'))):.4f}"
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
                continue
    return "Tidak tersedia dari API provider (gunakan dashboard TopTools)"
