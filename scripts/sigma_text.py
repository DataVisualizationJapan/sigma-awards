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


def scan_url_cell(raw: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Return (urls, dropped, notes) for one link cell.

    dropped lists the discarded fragments; consecutive ones are joined.
    notes pairs each dropped run with the valid URL just before it
    (a run before the first URL has no URL to attach to).
    """
    text = decode_entities(raw).strip()
    text = _MARKDOWN_LINK.sub(lambda m: f" {m.group(1)} ", text).replace("](", " ")
    urls: list[str] = []
    dropped: list[str] = []
    notes: list[tuple[str, str]] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            dropped.append(" ".join(run))
            if urls:
                notes.append((urls[-1], dropped[-1]))
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
    return urls, dropped, notes


def normalize_url_cell(raw: str) -> tuple[list[str], list[str]]:
    """Return (urls, dropped) for one link cell."""
    urls, dropped, _ = scan_url_cell(raw)
    return urls, dropped


def collect_link_notes(cells: list[str]) -> dict[str, str]:
    """Map each URL to the text that followed it in the link cells (joined by a space)."""
    notes: dict[str, str] = {}
    for raw in cells:
        for url, note in scan_url_cell(raw)[2]:
            if not re.search(r"\w", note):
                continue
            notes[url] = f"{notes[url]} {note}" if url in notes else note
    return notes


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


# --- Markup in free-text fields ---------------------------------------------

BLOCK_TAGS = (
    "br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "pre", "hr", "blockquote", "table", "tr",
)
INLINE_TAGS = ("b", "strong", "em", "i", "u", "s", "small", "span", "sup", "sub", "code", "abbr", "td", "th")
KNOWN_TAGS = frozenset(BLOCK_TAGS + INLINE_TAGS + ("a", "img", "tbody", "thead"))

_NAMES = "|".join(sorted(KNOWN_TAGS, key=len, reverse=True))
_TAG = re.compile(rf"<(/?)({_NAMES})(?=[\s/>])([^<>]*)>", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_IMG = re.compile(r"<img(?=[\s/>])[^<>]*>", re.I)
_DEBRIS_OPEN = re.compile(
    r"<div(?=\s)[^<>]*?(?:id\s*=\s*[\"']?gtx-trans|class\s*=\s*[\"']?gtx-trans-icon)[^<>]*>", re.I
)
_DIV = re.compile(r"<(/?)div(?=[\s/>])[^<>]*>", re.I)
_HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_MD_LINK = re.compile(r"(?<!!)\[([^\[\]]*)\]\(\s*<?((?:[^()\s<>]|\([^()\s]*\))+)>?\s*\)")
# Runs of "*" or "_" stay as they are, so cleaning already-clean text changes nothing.
_BOLD = re.compile(r"(?<!\*)\*\*(?=[^\s*])(.+?)(?<=[^*])\*\*(?!\*)")
_BOLD_UNDERSCORE = re.compile(r"(?<![\w?&/=.])__(?=[^\s_])(.+?)(?<=[^\s_])__(?![\w=])")
_URL_TOKEN = re.compile(r"(https?://\S+)")
_QUOTE_HEAD = re.compile(r"^(?:>\s+)+")
_HEADING_HEAD = re.compile(r"^#{1,6}\s+")
_OPEN_BOLD_HEAD = re.compile(r"^\*\*(?!\*)\s*")
_OPEN_BOLD_TAIL = re.compile(r"\s*(?<!\*)\*\*$")
_SYMBOLS_ONLY = re.compile(r"^[\s*_#\-=·•]*$")
_DOUBLE_SCHEME = re.compile(r"^(?:https?(?::/{0,2})?)+(?=https?://)", re.I)
# What is left of a second "https://" pasted onto the end of a URL, such as "...award/s://".
_TRAILING_SCHEME = re.compile(r"(?:h?t?t?p)?s://$", re.I)
_SPACES = re.compile(r"\s+")
_TAG_LIKE = re.compile(r"</?[A-Za-z][^<>]*>")

PARAGRAPH = "\n\n"


def collapse_spaces(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _strip_debris(text: str) -> str:
    """Remove the translate-extension <div id="gtx-trans"> blocks along with what they hold."""
    while True:
        match = _DEBRIS_OPEN.search(text)
        if not match:
            return text
        depth, end = 1, None
        for tag in _DIV.finditer(text, match.end()):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                end = tag.end()
                break
        text = text[: match.start()] + text[end if end is not None else match.end() :]


def _strip_emphasis(paragraph: str) -> str:
    paragraph = _BOLD.sub(r"\1", paragraph)
    # URLs can hold "__" (e.g. "?__tn__=") and must stay as written.
    parts = _URL_TOKEN.split(paragraph)
    for index in range(0, len(parts), 2):
        parts[index] = _BOLD_UNDERSCORE.sub(r"\1", parts[index])
    return "".join(parts)


def _same_url(url: str, label: str) -> bool:
    return url.rstrip("/") in (label.rstrip("/"), _trim(label).rstrip("/"))


def ref_url(raw: str) -> str:
    """The URL to list for a link in the text, or "" when it is not a usable http(s) URL.

    A repeated scheme ("https://https://x", "httphttps://x") keeps the last one, a stray
    scheme fragment at the end ("x/s://") is cut off, and trailing punctuation goes the
    same way as in the link cells.
    """
    url = _TRAILING_SCHEME.sub("", _DOUBLE_SCHEME.sub("", raw.strip()))
    url = _trim(url)
    return url if is_valid_url(url) else ""


def _html_to_text_once(raw: str) -> tuple[str, list[dict]]:
    """Turn a free-text field with HTML tags or Markdown into plain paragraphs.

    Returns (text, refs). Paragraphs are separated by PARAGRAPH, newlines in the
    source also start a new paragraph. refs lists the links found in the text,
    in order, as {"url", "label"} (label "" when it adds nothing to the URL);
    only URLs that pass is_valid_url are listed. Angle brackets that are not one
    of KNOWN_TAGS stay as written.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _IMG.sub("", _strip_debris(_COMMENT.sub("", text)))
    out: list[str] = []
    refs: list[dict] = []
    anchor: tuple[dict | None, int] | None = None

    def add_text(segment: str) -> None:
        def link(match: re.Match[str]) -> str:
            label = _strip_emphasis(collapse_spaces(match.group(1)))
            if ref_url(match.group(2)):
                refs.append({"url": ref_url(match.group(2)), "label": label})
            return match.group(1)

        out.append(_MD_LINK.sub(link, segment))

    def close_anchor(labelled: bool) -> None:
        nonlocal anchor
        if anchor is None:
            return
        ref, start = anchor
        if ref is not None and labelled:
            ref["label"] = _strip_emphasis(collapse_spaces("".join(out[start:])))
        anchor = None

    pos = 0
    for match in _TAG.finditer(text):
        add_text(text[pos : match.start()])
        pos = match.end()
        closing, name = bool(match.group(1)), match.group(2).lower()
        if name == "a":
            if closing:
                close_anchor(True)
                continue
            close_anchor(False)
            href = _HREF.search(match.group(3))
            url = next((g for g in href.groups() if g is not None), "").strip() if href else ""
            ref = {"url": ref_url(url), "label": ""} if ref_url(url) else None
            if ref is not None:
                refs.append(ref)
            anchor = (ref, len(out))
        elif name in BLOCK_TAGS:
            out.append("\n")
    add_text(text[pos:])
    close_anchor(False)

    paragraphs = []
    for part in "".join(out).split("\n"):
        part = _HEADING_HEAD.sub("", _QUOTE_HEAD.sub("", collapse_spaces(part)))
        part = collapse_spaces(_OPEN_BOLD_TAIL.sub("", _OPEN_BOLD_HEAD.sub("", _strip_emphasis(part))))
        if not _SYMBOLS_ONLY.match(part):
            paragraphs.append(part)
    for ref in refs:
        if not ref["label"] or _same_url(ref["url"], ref["label"]):
            ref["label"] = ""
    return PARAGRAPH.join(paragraphs), refs


def html_to_text(raw: str) -> tuple[str, list[dict]]:
    """_html_to_text_once, repeated until the text stops changing.

    Mangled markup (e.g. in machine translations) can turn into new markup once its
    neighbours are gone; repeating keeps the result stable across rebuilds that read
    their own output. refs come from the first pass only.
    """
    text, refs = _html_to_text_once(raw)
    for _ in range(5):
        again = _html_to_text_once(text)[0]
        if again == text:
            break
        text = again
    return text, refs


def merge_refs(groups: list[list[dict]]) -> list[dict]:
    """Join refs lists, dropping repeated URLs. A later label fills in a blank one."""
    merged: dict[str, dict] = {}
    for refs in groups:
        for ref in refs:
            known = merged.get(ref["url"])
            if known is None:
                merged[ref["url"]] = dict(ref)
            elif not known["label"] and ref["label"]:
                known["label"] = ref["label"]
    return list(merged.values())


def find_tag_like(text: str) -> list[str]:
    """Markup-looking pieces left in text that html_to_text does not treat as tags."""
    return [piece for piece in _TAG_LIKE.findall(text) if not _TAG.fullmatch(piece)]
