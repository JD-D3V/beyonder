"""Chapter scraper.

Two backends:

* ``playwright`` — headless Chromium, renders JavaScript. Best quality, but it
  needs a browser installed and roughly 300 MB of RAM per launch, which small
  cloud instances do not have.
* ``http`` — one plain HTTP GET. No JavaScript, tiny footprint. Good enough for
  the static HTML most novel mirrors serve.

``SCRAPER_BACKEND=auto`` (the default) tries Playwright and falls back to HTTP
when it is not installed or fails to launch.

Use for personal eval only. Don't redistribute scraped novels.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from ..common.config import settings
from ..common.logging import get_logger

log = get_logger(__name__)

_TIMEOUT_MS = 20_000
_USER_AGENT = "Mozilla/5.0 (compatible; Beyonder/0.1; +https://example.invalid)"

# Heuristic selectors per site family. Add more as needed.
_CONTENT_SELECTORS = [
    "article",
    ".content",
    "#content",
    ".chapter",
    "#chapter",
    ".novel_content",
    "main",
    "body",
]


@dataclass
class ScrapedPage:
    url: str
    title: str | None
    text: str


async def _extract(html: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript"]):
        tag.decompose()
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    body_text = ""
    for sel in _CONTENT_SELECTORS:
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(separator="\n", strip=True)
            if len(txt) > len(body_text):
                body_text = txt
    if not body_text:
        body_text = soup.get_text(separator="\n", strip=True)
    return title, body_text


async def _fetch_http(url: str) -> str:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=_TIMEOUT_MS / 1000,
        headers={"user-agent": _USER_AGENT},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        # Novel mirrors mislabel charsets constantly; let httpx guess from the
        # bytes rather than trusting a bogus header.
        return resp.text


async def _fetch_playwright(url: str) -> str:
    from playwright.async_api import async_playwright  # imported lazily

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(user_agent=_USER_AGENT)
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            except Exception as e:
                log.warning("scrape.goto_fail", url=url, err=str(e))
            # Let dynamic content render briefly
            try:
                await page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            return await page.content()
        finally:
            await browser.close()


async def _fetch(url: str) -> str:
    backend = settings.scraper_backend.lower()
    if backend == "http":
        return await _fetch_http(url)
    if backend == "playwright":
        return await _fetch_playwright(url)

    try:
        return await _fetch_playwright(url)
    except Exception as e:
        log.warning("scrape.playwright_unavailable", url=url, err=str(e))
        return await _fetch_http(url)


async def scrape_url(url: str) -> ScrapedPage:
    log.info("scrape.start", url=url, backend=settings.scraper_backend)
    html = await _fetch(url)
    title, text = await _extract(html)
    return ScrapedPage(url=url, title=title, text=text)


async def scrape_many(urls: list[str], concurrency: int = 3) -> list[ScrapedPage]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(u: str) -> ScrapedPage:
        async with sem:
            try:
                return await scrape_url(u)
            except Exception as e:
                log.error("scrape.fail", url=u, err=str(e))
                return ScrapedPage(url=u, title=None, text="")

    return await asyncio.gather(*[_one(u) for u in urls])
