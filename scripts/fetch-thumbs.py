#!/usr/bin/env python3
"""Attach official Sigma Awards site images to catalog entries.

Only images published on https://www.sigmaawards.org/ are used.
Work URLs themselves are never captured.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "public" / "data" / "entries.json"
THUMB_DIR = ROOT / "public" / "thumbs"
GHOST = "https://the-sigma-awards.ghost.io/ghost/api/content/posts/slug/{slug}/"
API_KEY = "29e805af8facb29fe957af6e30"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

SKIP_HOSTS = (
    "gijn.org",
    "flourish.studio",
    "gravatar.com",
    "github.com",
    "githubusercontent.com",
)
SKIP_TITLE = (
    "sigma awards 2024 winners reveal",
    "the sigma awards",
    "what's next",
    "whats next",
)
FILENAME_2023 = {
    "always-scared": "Always Scared",
    "AP-sigmas-23": "Putin's Attack on Ukraine",
    "lighthouse-reports": "Border Outrage",
    "Screenshot-2023-09-28": "Game of Votes",
    "amenaza-roboto": "La ciudad sumergida",
    "ghost-polluters": "Ghosts of Polluters Past",
    "NRK-worlds-apart": "Worlds Apart",
    "ABC-culture-crosshairs": "Culture in the Crosshairs",
    "yao-hua-1": "Yao-Hua Law",
    "frontex-1": "Frontex Involved in Illegal Pushbacks",
}

POSTS = [
    {
        "slug": "from-toxic-supply-chains-in-africa-to-baltic-sabotage-to-stolen-children-in-syria-10-data-projects-win-2026-sigma-awards",
        "year": 2026,
        "mode": "heading-image",
    },
    {
        "slug": "from-flammable-buildings-to-slaverys-hidden-legacy-to-tainted-groundwater-projects-from-10-countries-win-gijns-2025-sigma-awards",
        "year": 2025,
        "mode": "heading-image",
    },
    {
        "slug": "meet-the-winners-of-the-sigmas-2024-for-data-journalism",
        "year": 2024,
        "mode": "bookmarks",
    },
    {
        "slug": "the-sigmas-2023-winners",
        "year": 2023,
        "mode": "filename-map",
    },
    {
        "slug": "shortlist-2024",
        "year": 2024,
        "mode": "heading-image",
    },
]


def request(url: str, referer: str = "https://www.sigmaawards.org/") -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Referer": referer,
        },
    )
    with urlopen(req, timeout=40) as handle:
        return handle.read()


def fetch_html(slug: str) -> str:
    raw = request(f"{GHOST.format(slug=slug)}?key={API_KEY}&formats=html")
    return json.loads(raw)["posts"][0]["html"] or ""


def skip_image(src: str, cls: str) -> bool:
    if not src or src.startswith("data:"):
        return True
    if "kg-bookmark-icon" in cls:
        return True
    host = urlparse(src).netloc.lower().removeprefix("www.")
    if any(host == skip or host.endswith("." + skip) for skip in SKIP_HOSTS):
        return True
    low = src.lower()
    return any(token in low for token in ("favicon", "gravatar", "link-icon.svg", "foto_rowan"))


def heading_core(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.split(r"\s+[—–]\s+", text, maxsplit=1)[0]
    return text.strip(" :")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = heading_core(text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u00c0-\u024f\u0400-\u04ff\u0600-\u06ff\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def url_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path).lower()
    return host, path


def urls_match(a: str, b: str) -> bool:
    ha, pa = url_key(a)
    hb, pb = url_key(b)
    if not ha or not hb or ha != hb:
        return False
    if pa == pb:
        return True
    return bool(pa) and bool(pb) and (pa.startswith(pb) or pb.startswith(pa))


class Extractor(HTMLParser):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode
        self.pairs: list[dict[str, str]] = []
        self.heading_parts: list[str] | None = None
        self.heading = ""
        self.href = ""
        self.heading_href = ""
        self.took_image = False
        self.in_bookmark_title = False
        self.bookmark_title: list[str] = []
        self.bookmark_href = ""
        self.bookmark_img = ""
        self.in_bookmark = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {key: value or "" for key, value in attrs}
        cls = attrs_d.get("class", "")
        if tag in {"h2", "h3", "h4"}:
            self.heading_parts = []
            self.heading_href = ""
            self.took_image = False
        elif tag == "a":
            href = attrs_d.get("href", "")
            if self.heading_parts is not None and href:
                self.heading_href = href
            if "kg-bookmark-container" in cls:
                self._flush_bookmark()
                self.in_bookmark = True
                self.bookmark_href = href
                self.bookmark_title = []
                self.bookmark_img = ""
        elif tag == "img":
            src = attrs_d.get("src", "")
            if skip_image(src, cls):
                return
            if self.mode == "bookmarks":
                if self.in_bookmark and not self.bookmark_img:
                    self.bookmark_img = src
            else:
                self._add_image(src, attrs_d.get("alt", ""))
        if "kg-bookmark-title" in cls:
            self.in_bookmark_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h2", "h3", "h4"} and self.heading_parts is not None:
            text = re.sub(r"\s+", " ", "".join(self.heading_parts)).strip()
            if text:
                self.heading = text
                self.href = self.heading_href
            self.heading_parts = None
        elif tag == "figure" and self.in_bookmark:
            self._flush_bookmark()
        if tag == "div" and self.in_bookmark_title:
            self.in_bookmark_title = False

    def handle_data(self, data: str) -> None:
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.in_bookmark_title:
            self.bookmark_title.append(data)

    def _add_image(self, src: str, alt: str) -> None:
        if self.mode == "filename-map":
            name = Path(urlparse(src).path).stem
            mapped = next((title for stem, title in FILENAME_2023.items() if stem in name), "")
            self.pairs.append({"title": mapped or alt, "url": src, "href": ""})
            return
        if self.took_image:
            return
        if not self.heading:
            return
        if normalize(self.heading) in SKIP_TITLE:
            return
        self.pairs.append({"title": self.heading, "url": src, "href": self.href})
        self.took_image = True

    def _flush_bookmark(self) -> None:
        if self.mode != "bookmarks" or not self.in_bookmark:
            return
        title = re.sub(r"\s+", " ", "".join(self.bookmark_title)).strip()
        href = self.bookmark_href
        img = self.bookmark_img
        self.in_bookmark = False
        self.in_bookmark_title = False
        self.bookmark_title = []
        self.bookmark_href = ""
        self.bookmark_img = ""
        if not img:
            return
        if normalize(title) in SKIP_TITLE:
            return
        host = urlparse(href).netloc.lower()
        if any(skip in host for skip in ("youtube.com", "youtu.be", "github.com")):
            return
        self.pairs.append({"title": title, "url": img, "href": href})


def score_title(hint: str, entry: dict) -> float:
    left = normalize(hint)
    right = normalize(entry["title"])
    if not left or not right:
        return 0
    if left == right:
        return 100
    if left in right or right in left:
        return 92
    left_tokens = {token for token in left.split() if len(token) >= 3}
    right_tokens = {token for token in right.split() if len(token) >= 3}
    if not left_tokens or not right_tokens:
        return 0
    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 0
    return 70 * overlap / min(len(left_tokens), len(right_tokens))


def match_entry(pair: dict, year: int, entries: list[dict], used: set[str], min_score: float = 70) -> dict | None:
    year_entries = [entry for entry in entries if entry["year"] == year and entry["id"] not in used]
    href = pair.get("href") or ""
    if href:
        url_hits = [entry for entry in year_entries if urls_match(href, entry.get("url") or "")]
        if len(url_hits) == 1:
            return url_hits[0]
    ranked = sorted(
        ((score_title(pair["title"], entry), entry) for entry in year_entries),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < min_score:
        return None
    if min_score >= 70 and len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 8 and ranked[0][0] < 92:
        return None
    return ranked[0][1]


def ghost_size_url(url: str, width: int = 1000) -> str:
    if "storage.ghost.io" not in url or "/content/images/" not in url or "/size/" in url:
        return url
    return url.replace("/content/images/", f"/content/images/size/w{width}/")


def extension_for(url: str, content_type: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def download(url: str, dest_base: Path) -> Path | None:
    candidates = []
    sized = ghost_size_url(url)
    if sized != url:
        candidates.append(sized)
    if url.startswith("http://"):
        candidates.append("https://" + url[len("http://") :])
    candidates.append(url)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            req = Request(
                candidate,
                headers={"User-Agent": UA, "Accept": "image/*,*/*", "Referer": "https://www.sigmaawards.org/"},
            )
            with urlopen(req, timeout=40) as handle:
                body = handle.read()
                content_type = handle.headers.get_content_type()
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        if len(body) < 2000:
            continue
        ext = extension_for(candidate, content_type)
        dest = dest_base.with_suffix(ext)
        dest.write_bytes(body)
        return dest
    return None


def main() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    entries = payload["entries"]
    for entry in entries:
        entry.pop("thumb", None)
    used: set[str] = set()
    unmatched: list[str] = []
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    for post in POSTS:
        html = fetch_html(post["slug"])
        parser = Extractor(post["mode"])
        parser.feed(html)
        print(f"{post['year']} {post['mode']} {post['slug'][:48]}: {len(parser.pairs)} images")
        for pair in parser.pairs:
            entry = match_entry(pair, post["year"], entries, set())
            if entry and entry["id"] in used:
                continue
            if entry is None:
                near = match_entry(pair, post["year"], entries, set(), min_score=50)
                if near and near["id"] in used:
                    continue
                unmatched.append(f"{post['year']} {pair['title'][:80]}")
                print("  unmatched:", pair["title"][:80])
                continue
            dest_base = THUMB_DIR / entry["id"]
            existing = next(THUMB_DIR.glob(f"{entry['id']}.*"), None)
            if existing and existing.stat().st_size > 2000:
                actual = existing
            else:
                actual = download(pair["url"], dest_base)
            if actual is None:
                print("  download failed:", entry["id"], pair["url"][:80])
                continue
            entry["thumb"] = f"thumbs/{actual.name}"
            used.add(entry["id"])
            print(f"  {entry['id']} <- {entry['title'][:60]}")

    for leftover in THUMB_DIR.glob("*"):
        if leftover.is_file() and leftover.stem not in used:
            leftover.unlink()

    DATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"thumbs {len(used)}")
    print(f"unmatched {len(unmatched)}")
    for row in unmatched:
        print(" ", row)


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
