import html
import re
from typing import Iterable


FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_+.-]*)\s*$")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def _inline(text: str) -> str:
    """Convert a conservative Markdown subset after escaping user/AI text."""
    placeholders: list[str] = []

    def hold(value: str) -> str:
        token = f"\x00{len(placeholders)}\x00"
        placeholders.append(value)
        return token

    text = html.escape(text, quote=False)
    text = LINK_RE.sub(lambda m: hold(f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>'), text)
    text = INLINE_CODE_RE.sub(lambda m: hold(f"<code>{m.group(1)}</code>"), text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)",
                  lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    for index, value in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def _format_plain_lines(lines: Iterable[str]) -> str:
    output: list[str] = []
    quote_lines: list[str] = []
    list_open = False

    def flush_quote():
        nonlocal quote_lines
        if quote_lines:
            output.append(f"<blockquote>{'<br>'.join(quote_lines)}</blockquote>")
            quote_lines = []

    def close_list():
        nonlocal list_open
        if list_open:
            output.append("</blockquote>")
            list_open = False

    for raw in lines:
        line = raw.rstrip()
        if line.startswith(">"):
            close_list()
            quote_lines.append(_inline(line[1:].lstrip()))
            continue
        flush_quote()
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
        if heading:
            close_list()
            output.append(f"<b>{_inline(heading.group(1).strip())}</b>")
            continue
        bullet = re.match(r"^\s*(?:[-*+] |\d+[.)] )(.+)$", line)
        if bullet:
            if not list_open:
                # Telegram HTML has no list tags; a blockquote gives a clean premium visual.
                output.append("<blockquote>")
                list_open = True
            output.append(f"• {_inline(bullet.group(1).strip())}<br>")
            continue
        close_list()
        if line.strip():
            output.append(_inline(line))
        elif output and not output[-1].endswith("\n"):
            output.append("")
    flush_quote()
    close_list()
    return "\n".join(output).replace("\n\n\n", "\n\n")


def format_ai_response(text: str) -> str:
    """Render common AI Markdown as Telegram HTML without exposing raw fences."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return "<i>AI mengembalikan jawaban kosong.</i>"

    parts: list[str] = []
    plain: list[str] = []
    code_lines: list[str] = []
    language = ""
    in_code = False

    def flush_plain():
        nonlocal plain
        if plain:
            rendered = _format_plain_lines(plain)
            if rendered:
                parts.append(rendered)
            plain = []

    for line in text.split("\n"):
        fence = FENCE_RE.match(line)
        if fence:
            if not in_code:
                flush_plain()
                in_code = True
                language = fence.group(1).lower()
                code_lines = []
            else:
                code = html.escape("\n".join(code_lines), quote=False)
                lang_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
                parts.append(f"<pre><code{lang_attr}>{code}</code></pre>")
                in_code = False
                language = ""
                code_lines = []
            continue
        if in_code:
            code_lines.append(line)
        else:
            plain.append(line)

    if in_code:
        # Render incomplete streaming fences as a valid code block.
        code = html.escape("\n".join(code_lines), quote=False)
        lang_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
        parts.append(f"<pre><code{lang_attr}>{code}</code></pre>")
    else:
        flush_plain()
    return "\n\n".join(parts) or "<i>AI mengembalikan jawaban kosong.</i>"


def split_raw_response(text: str, max_chars: int = 3800) -> list[str]:
    """Split at paragraph/code boundaries before applying HTML formatting."""
    blocks = re.split(r"\n{2,}", (text or "").strip())
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]
