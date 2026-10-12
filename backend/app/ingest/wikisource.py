"""Public-domain classics from zh.wikisource.org via the MediaWiki API.

Each work is a small hard-coded config: the table-of-contents page and a
pattern for the sub-pages that are chapters (titles verified against the live
site). Requests carry a descriptive User-Agent and are spaced one second apart.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx
from bs4 import BeautifulSoup

from ..common.logging import get_logger

log = get_logger(__name__)

API_URL = "https://zh.wikisource.org/w/api.php"
USER_AGENT = "BeyonderSeed/1.0 (+https://github.com/JD-D3V/beyonder)"
REQUEST_INTERVAL = 1.0
SOURCE_NOTE = "Source: Wikisource (public domain)"


@dataclass(frozen=True)
class Work:
    key: str
    title: str  # catalog title (simplified)
    author: str
    toc_page: str  # Wikisource page whose links are the chapters
    link_re: str  # full page title of a chapter
    description: str
    tags: tuple[str, ...] = field(default_factory=tuple)


WORKS: dict[str, Work] = {
    w.key: w
    for w in (
        Work("xiyouji", "西游记", "吴承恩", "西遊記", r"^西遊記/第\d+回$",
             "Journey to the West: the monk Tripitaka and his disciples travel to India for the scriptures.",
             ("classic", "mythology", "adventure")),
        Work("fengshen", "封神演义", "许仲琳", "封神演義", r"^封神演義/卷\d+$",
             "Investiture of the Gods: the fall of the Shang dynasty, told with gods and immortals.",
             ("classic", "mythology", "war")),
        Work("sanguo", "三国演义", "罗贯中", "三國演義", r"^三國演義/第\d+回$",
             "Romance of the Three Kingdoms: the wars at the end of the Han dynasty.",
             ("classic", "historical", "war")),
        Work("shuihu", "水浒传", "施耐庵", "水滸傳 (100回本)", r"^水滸傳 \(100回本\)/第\d+回$",
             "Water Margin: 108 outlaws gather at Liangshan Marsh.",
             ("classic", "wuxia", "historical")),
        Work("liaozhai", "聊斋志异", "蒲松龄", "聊齋志異", r"^聊齋志異/第\d+卷$",
             "Strange Tales from a Chinese Studio: ghosts, fox spirits and scholars.",
             ("classic", "supernatural", "short-stories")),
        Work("honglou", "红楼梦", "曹雪芹", "紅樓夢", r"^紅樓夢/第\d+回$",
             "Dream of the Red Chamber: the rise and fall of the Jia family.",
             ("classic", "family", "romance")),
    )
}


@dataclass
class WikiChapter:
    page: str
    title: str
    text: str


class Throttle:
    """Spaces calls at least ``interval`` seconds apart."""

    def __init__(self, interval: float = REQUEST_INTERVAL,
                 clock: Callable[[], float] = time.monotonic):
        self.interval = interval
        self._clock = clock
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            gap = self.interval - (self._clock() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
        self._last = self._clock()


class WikisourceClient:
    def __init__(self, client: httpx.AsyncClient | None = None, interval: float = REQUEST_INTERVAL):
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
        )
        self._throttle = Throttle(interval)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _api(self, **params) -> dict:
        await self._throttle.wait()
        params.update(format="json", redirects=1)
        resp = await self._client.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Wikisource: {data['error'].get('info', 'error')}")
        return data

    async def chapter_pages(self, work: Work) -> list[str]:
        """Chapter page titles in TOC order."""
        data = await self._api(action="parse", page=work.toc_page, prop="links")
        pat = re.compile(work.link_re)
        seen: set[str] = set()
        out: list[str] = []
        for link in data["parse"]["links"]:
            name = link["*"]
            if link.get("ns", 0) == 0 and pat.match(name) and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    async def chapter(self, page: str) -> WikiChapter:
        data = await self._api(
            action="parse", page=page, prop="text", disableeditsection=1
        )
        title, text = html_to_chapter(data["parse"]["text"]["*"], fallback=page.split("/")[-1])
        return WikiChapter(page=page, title=title, text=text)


_DROP_SELECTORS = [
    "table", "style", "script", "sup.reference", ".reference", ".mw-references-wrap",
    "ol.references", ".noprint", ".ws-noexport", ".mw-editsection", "#headerContainer",
    ".navbox", ".toc", "#toc", "figure", "img", ".reflist", ".licenseContainer",
    ".licensetpl", "hr",
]


def _header_title(soup: BeautifulSoup, fallback: str) -> str:
    """Chapter heading from the Wikisource header template: the lines between
    the book name (bold) and the author credit."""
    cell = None
    for td in soup.find_all("td"):
        if td.find("b") and "作者" in td.get_text():
            cell = td
            break
    if cell is None:
        return fallback
    lines: list[str] = []
    for node in cell.find("b").next_siblings:
        if getattr(node, "name", None) == "span" and "作者" in node.get_text():
            break
        if getattr(node, "name", None) == "br":
            lines.append("")
            continue
        if not lines:
            lines.append("")
        lines[-1] += node.get_text() if hasattr(node, "get_text") else str(node)
    title = " ".join(x.strip() for x in lines if x.strip())
    return title or fallback


_STOP_HEADINGS = {"註釋", "注釋", "注释", "註解", "校勘記", "校勘记", "腳註", "脚注", "參考文獻", "外部連結"}
_NAV_RE = re.compile(r"^(上一回|上一卷)?[\s\u3000]*(回目[录錄]|目[录錄])[\s\u3000]*(下一回|下一卷)?$")
_HEADING_RE = re.compile(r"^第[\d一二三四五六七八九十百零〇]+[回卷]$")


def html_to_chapter(html: str, fallback: str = "") -> tuple[str, str]:
    """(title, plain-text paragraphs) from a parsed Wikisource page. Footnotes,
    navigation and templates are dropped; poem lines stay one per line."""
    soup = BeautifulSoup(html, "lxml")
    title = _header_title(soup, fallback)
    for sel in _DROP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    paras: list[str] = []
    root = soup.select_one(".mw-parser-output") or soup
    for el in root.find_all(["p", "dl", "ul", "blockquote", "h2", "h3", "h4", "div"]):
        if el.name == "div":
            # Only centred headings (some works print the chapter heading here).
            if "center" not in (el.get("class") or []) or el.find(["p", "dl", "div"]):
                continue
        elif el.find_parent(["dl", "ul", "blockquote"]) and el.name != "p":
            continue
        elif el.name == "p" and el.find_parent(["dl", "blockquote"]):
            continue
        if el.name in ("h2", "h3", "h4") and el.get_text("", strip=True) in _STOP_HEADINGS:
            break
        if el.name in ("dl", "ul"):
            leaves = [x for x in el.find_all(["dd", "dt", "li"]) if not x.find(["dd", "dt", "li"])]
            text = "\n".join(x.get_text("", strip=True) for x in leaves if x.get_text(strip=True))
        else:
            text = el.get_text("", strip=True)
        text = re.sub(r"[ \t\u3000]+\n", "\n", text).strip()
        if not text or _NAV_RE.match(text):
            continue
        paras.append(text)
    # Some works print the real chapter heading as the first line instead of
    # in the header template, which then only knows "第001回".
    if paras and _HEADING_RE.match(title.replace(" ", "")) and paras[0].startswith("第") \
            and len(paras[0]) < 60 and "\n" not in paras[0]:
        title = re.sub(r"[\s\u3000]+", " ", paras.pop(0))
    return title, "\n\n".join(paras)
