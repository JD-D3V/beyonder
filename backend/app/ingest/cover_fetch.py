"""Find and store a cover automatically when a book is added.

Two sources, both through the SSRF-guarded fetch and the normal cover
pipeline (``covers.process_cover``):

* web imports: ``og:image`` / ``twitter:image`` / the first large ``<img>`` on
  the book's index or first page;
* seeded classics: Wikidata (entity search by the original title, then the
  P18 image on Wikimedia Commons).

Nothing here ever raises into a caller: a missing or bad cover must not fail
an import.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..common.config import settings
from ..common.logging import get_logger
from ..storage.db import get_session
from ..storage.repository import get_cover_updated_at, get_novel, set_cover
from .covers import CoverError, MAX_UPLOAD_BYTES, process_cover
from .scraper import fetch_bytes_guarded, fetch_html

log = get_logger(__name__)

MIN_IMG_SIDE = 150  # an <img> must declare at least this size to count as "large"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=600"
MAX_JSON_BYTES = 512 * 1024

_META_KEYS = (
    ("property", "og:image"),
    ("property", "og:image:url"),
    ("property", "og:image:secure_url"),
    ("name", "twitter:image"),
    ("name", "twitter:image:src"),
    ("property", "twitter:image"),
)


def _http_url(raw: str | None, base: str) -> str | None:
    raw = (raw or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    url = urljoin(base, raw)
    return url if urlsplit(url).scheme in ("http", "https") else None


def _side(v: str | None) -> int:
    digits = "".join(ch for ch in (v or "") if ch.isdigit())
    return int(digits) if digits else 0


def extract_cover_url(html: str, base_url: str) -> str | None:
    """og:image, then twitter:image, then the first large <img>; absolute URL."""
    soup = BeautifulSoup(html, "lxml")
    for attr, key in _META_KEYS:
        tag = soup.find("meta", attrs={attr: key})
        url = _http_url(tag.get("content") if tag else None, base_url)
        if url:
            return url
    link = soup.find("link", rel="image_src")
    url = _http_url(link.get("href") if link else None, base_url)
    if url:
        return url
    for img in soup.find_all("img"):
        if max(_side(img.get("width")), _side(img.get("height"))) < MIN_IMG_SIDE:
            continue
        url = _http_url(img.get("src") or img.get("data-src"), base_url)
        if url:
            return url
    return None


async def _wikidata_json(params: str) -> dict:
    raw = await fetch_bytes_guarded(f"{WIKIDATA_API}?{params}&format=json", MAX_JSON_BYTES)
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


async def wikidata_cover_url(title: str) -> str | None:
    """Commons image URL for a work, found by its original title."""
    search = await _wikidata_json(
        f"action=wbsearchentities&language=zh&uselang=en&limit=5&search={quote(title)}"
    )
    ids = [r["id"] for r in search.get("search", []) if isinstance(r, dict) and r.get("id")]
    if not ids:
        return None
    ents = (await _wikidata_json(
        f"action=wbgetentities&props=claims&ids={'|'.join(ids)}"
    )).get("entities", {})
    for qid in ids:  # search order = relevance order
        claims = (ents.get(qid) or {}).get("claims", {}).get("P18") or []
        for c in claims:
            name = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
            if isinstance(name, str) and name:
                return COMMONS_FILE.format(name=quote(name.replace(" ", "_")))
    return None


async def store_cover_from_url(novel_id: int, image_url: str) -> bool:
    """Fetch, validate and store ``image_url`` unless the book already has a
    cover. False on any failure."""
    try:
        with get_session() as s:
            if get_novel(s, novel_id) is None or get_cover_updated_at(s, novel_id):
                return False
        raw = await fetch_bytes_guarded(image_url, MAX_UPLOAD_BYTES)
        cover = await process_cover(raw)
        with get_session() as s:
            if get_novel(s, novel_id) is None or get_cover_updated_at(s, novel_id):
                return False
            set_cover(
                s, novel_id, data=cover.data, width=cover.width,
                height=cover.height, content_type=cover.content_type,
            )
        log.info("cover.auto_stored", novel_id=novel_id)
        return True
    except (CoverError, Exception) as e:  # noqa: BLE001 - best effort by design
        log.info("cover.auto_skipped", novel_id=novel_id, err=str(e)[:200])
        return False


async def auto_cover(
    novel_id: int,
    *,
    page_urls: tuple[str, ...] | list[str] = (),
    image_urls: tuple[str | None, ...] | list[str | None] = (),
    wikidata_title: str | None = None,
) -> bool:
    """Try, in order: each page's og:image, each known image URL, Wikidata.

    Returns whether a cover was stored. Never raises.
    """
    if not settings.auto_covers:
        return False
    tried: set[str] = set()
    try:
        for page in page_urls:
            try:
                found = extract_cover_url(await fetch_html(page), page)
            except Exception as e:  # noqa: BLE001
                log.info("cover.page_failed", novel_id=novel_id, err=str(e)[:200])
                continue
            if found and found not in tried:
                tried.add(found)
                if await store_cover_from_url(novel_id, found):
                    return True
        for image in image_urls:
            if image and image not in tried:
                tried.add(image)
                if await store_cover_from_url(novel_id, image):
                    return True
        if wikidata_title:
            try:
                found = await wikidata_cover_url(wikidata_title)
            except Exception as e:  # noqa: BLE001
                log.info("cover.wikidata_failed", novel_id=novel_id, err=str(e)[:200])
                found = None
            if found and await store_cover_from_url(novel_id, found):
                return True
    except Exception as e:  # noqa: BLE001
        log.warning("cover.auto_failed", novel_id=novel_id, err=str(e)[:200])
    return False


_tasks: set[asyncio.Task] = set()


def spawn_auto_cover(novel_id: int, **kwargs) -> None:
    """Fire-and-forget ``auto_cover`` on the running loop (no-op without one)."""
    if not settings.auto_covers:
        return
    try:
        task = asyncio.get_running_loop().create_task(auto_cover(novel_id, **kwargs))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
