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
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

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


class UnsafeURL(ValueError):
    """The URL points somewhere a user-supplied scrape must never reach."""


_MAX_REDIRECTS = 5


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        and not ip.is_unspecified
    )


async def assert_public_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to non-public addresses.

    Every resolved address must be public. (A DNS answer can still change
    between this check and the fetch; this blocks the direct cases, not a
    rebinding attacker with control of a nameserver.)
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"unsupported scheme: {parts.scheme or '(none)'}")
    host = parts.hostname
    if not host:
        raise UnsafeURL("missing host")
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo, host, parts.port or None, type=socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise UnsafeURL(f"cannot resolve host: {host}") from e
        addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        raise UnsafeURL("address is not publicly routable")


async def _fetch_http(url: str) -> str:
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=_TIMEOUT_MS / 1000,
        headers={"user-agent": _USER_AGENT},
    ) as client:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_public_url(current)
            resp = await client.get(current)
            if resp.is_redirect and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            resp.raise_for_status()
            # Novel mirrors mislabel charsets constantly; let httpx guess from
            # the bytes rather than trusting a bogus header.
            return resp.text
        raise UnsafeURL("too many redirects")


class FetchTooLarge(ValueError):
    """The remote body exceeded the caller's size cap."""


async def fetch_bytes_guarded(url: str, max_bytes: int) -> bytes:
    """SSRF-guarded GET returning the body, streamed and capped at ``max_bytes``.

    Same checks as the page fetcher: every hop (including redirects) must
    resolve to public addresses.
    """
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=_TIMEOUT_MS / 1000,
        headers={"user-agent": _USER_AGENT},
    ) as client:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_public_url(current)
            async with client.stream("GET", current) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                resp.raise_for_status()
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise FetchTooLarge("response too large")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise FetchTooLarge("response too large")
                return bytes(buf)
        raise UnsafeURL("too many redirects")


async def _fetch_playwright(url: str) -> str:
    from playwright.async_api import async_playwright  # imported lazily

    await assert_public_url(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(user_agent=_USER_AGENT)
            async def _guard(route):
                req = route.request
                if req.is_navigation_request():
                    try:
                        await assert_public_url(req.url)
                    except UnsafeURL:
                        await route.abort()
                        return
                await route.continue_()

            await ctx.route("**/*", _guard)
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
    except UnsafeURL:
        raise
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
            except UnsafeURL:
                raise  # a blocked URL is the caller's error, not "empty text"
            except Exception as e:
                log.error("scrape.fail", url=u, err=str(e))
                return ScrapedPage(url=u, title=None, text="")

    return await asyncio.gather(*[_one(u) for u in urls])


async def fetch_html(url: str) -> str:
    """SSRF-guarded fetch of a page's raw HTML."""
    return await _fetch(url)
