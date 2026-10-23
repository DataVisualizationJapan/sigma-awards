"""Text clean-up helpers shared by the Sigma Awards data build and its tests.

Standard library only. Every function is pure so the rules can be tested on
literal inputs.
"""

from __future__ import annotations

import io
import re
from urllib.parse import urlsplit

ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}

PLACEHOLDERS = frozenset({"none", "n/a", "na", "nil", "nil.", "-", "—"})

_URL_START = re.compile(r"^https?://")
_INNER_URL = re.compile(r"https?://")
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^()\s>]*)>?\s*\)")
# Wrappers legitimately carry another URL after "/" or "=".
_WRAPPER_HOSTS = frozenset({"web.archive.org", "translate.google.com"})


def decode_entities(text: str) -> str:
    """Decode only &amp; &lt; &gt; &quot; &apos; and numeric references, once.

    Unlike html.unescape this never touches references without a semicolon,
    so URL query strings such as "&para=" or "&timestamp=" stay intact.
    """

    def replace(match: re.Match[str]) -> str:
        body = match.group(1)
        if body in _NAMED:
            return _NAMED[body]
        try:
            code = int(body[2:], 16) if body[1] in "xX" else int(body[1:])
            return chr(code) if code and not 0xD800 <= code <= 0xDFFF else match.group(0)
        except (ValueError, OverflowError):
            return match.group(0)

    return ENTITY_RE.sub(replace, text)


def is_placeholder(value: object) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDERS


def blank_placeholder(value: str) -> str:
    return "" if is_placeholder(value) else value


_UTF8_MULTIBYTE = re.compile(
    rb"[\xc2-\xdf][\x80-\xbf]|\xe0[\xa0-\xbf][\x80-\xbf]|[\xe1-\xec\xee\xef][\x80-\xbf]{2}"
    rb"|\xed[\x80-\x9f][\x80-\xbf]|\xf0[\x90-\xbf][\x80-\xbf]{2}|[\xf1-\xf3][\x80-\xbf]{3}"
    rb"|\xf4[\x80-\x8f][\x80-\xbf]{2}"
)


def decode_csv_bytes(data: bytes, source: str = "CSV") -> str:
    """Decode line by line: UTF-8, falling back to Mac Roman for a bad line.

    A bad line that also holds valid UTF-8 multibyte text would be garbled
    by a whole-line Mac Roman read, so it stops the build instead
    (SystemExit naming source and line number).
    """
    lines = data.splitlines(keepends=True)
    out: list[str] = []
    for index, line in enumerate(lines):
        try:
            out.append(line.decode("utf-8-sig" if index == 0 else "utf-8"))
        except UnicodeDecodeError:
            if _UTF8_MULTIBYTE.search(line):
                raise SystemExit(
                    f"{source}: line {index + 1} mixes valid UTF-8 and invalid bytes; not re-reading it as Mac Roman"
                )
            out.append(line.decode("mac_roman"))
    return "".join(out)


def _is_wrapper(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if host in _WRAPPER_HOSTS:
        return True
    return host in ("google.com", "www.google.com") and parts.path.startswith("/url")


def _split_concatenated(token: str) -> list[str]:
    """Split "A/https://B" unless A is a known wrapper around B."""
    for match in _INNER_URL.finditer(token, 1):
        start = match.start()
        if token[start - 1] == "/" and not _is_wrapper(token):
            return [token[:start]] + _split_concatenated(token[start:])
    return [token]


def _trim(url: str) -> str:
    if ":~:text=" in url:
        return url
    while url:
        last = url[-1]
        if last in ".,;:":
            url = url[:-1]
        elif last == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        elif last == "]" and url.count("]") > url.count("["):
            url = url[:-1]
        else:
            break
    return url


def is_valid_url(url: str) -> bool:
    if not url or re.search(r"\s", url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and "." in parts.netloc


def normalize_url_cell(raw: str) -> tuple[list[str], list[str]]:
    """Return (urls, dropped) for one link cell.

    dropped lists the discarded fragments; consecutive ones are joined.
    """
    text = decode_entities(raw).strip()
    text = _MARKDOWN_LINK.sub(lambda m: f" {m.group(1)} ", text).replace("](", " ")
    urls: list[str] = []
    dropped: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            dropped.append(" ".join(run))
            run.clear()

    for fragment in text.split():
        if not _URL_START.match(fragment):
            run.append(fragment)
            continue
        for piece in _split_concatenated(fragment):
            url = _trim(piece)
            if is_valid_url(url):
                flush()
                urls.append(url)
            else:
                run.append(piece)
    flush()
    return urls, dropped


def normalize_links(cells: list[str]) -> tuple[list[str], list[dict]]:
    """Normalize link cells in order. Returns (links, fixes).

    fixes has one record per cell whose result differs from its text.
    """
    links: list[str] = []
    fixes: list[dict] = []
    for raw in cells:
        urls, dropped = normalize_url_cell(raw)
        if urls != [raw] or dropped:
            fixes.append({"original": raw, "result": urls, "dropped": dropped})
        for url in urls:
            if url not in links:
                links.append(url)
    return links, fixes


def read_text_lines(data: bytes, source: str = "CSV") -> io.StringIO:
    return io.StringIO(decode_csv_bytes(data, source), newline="")
