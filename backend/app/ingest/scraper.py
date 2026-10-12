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
from urllib.parse import urljoin, urlsplit, urlunsplit

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
    # og:image / twitter:image / first large <img>, when the page has one.
    cover_url: str | None = None


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


async def resolve_public(url: str) -> list[str]:
    """Reject non-http(s) URLs and hosts that resolve to non-public addresses.

    Returns the validated IP addresses. Every resolved address must be public.
    Callers connect to one of these IPs (see ``_guarded_get``) so a second DNS
    answer cannot swap in a private address between check and connect.
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
    return [str(a) for a in addrs]


async def assert_public_url(url: str) -> None:
    await resolve_public(url)


class FetchTooLarge(ValueError):
    """The remote body exceeded the caller's size cap (or the fetch timed out)."""


MAX_PAGE_BYTES = 5 * 1024 * 1024
FETCH_DEADLINE_S = 30.0

# Tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


def _pin(url: str, ip: str) -> tuple[str, dict[str, str], dict]:
    """URL rewritten to connect to ``ip``, keeping Host header and TLS SNI."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = ip_host + (f":{parts.port}" if parts.port else "")
    headers = {"host": parts.netloc.rsplit("@", 1)[-1]}
    ext: dict = {}
    try:
        ipaddress.ip_address(host)
    except ValueError:
        ext["sni_hostname"] = host
    return urlunsplit(parts._replace(netloc=netloc)), headers, ext


async def _guarded_get(url: str, max_bytes: int, deadline: float) -> tuple[bytes, str]:
    """SSRF-guarded GET: DNS pinned to the validated IP, redirects re-validated
    per hop, body streamed with a size cap, whole fetch under a deadline."""

    async def run() -> tuple[bytes, str]:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=_TIMEOUT_MS / 1000,
            headers={"user-agent": _USER_AGENT},
            transport=_transport,
        ) as client:
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                ips = await resolve_public(current)
                target, headers, ext = _pin(current, ips[0])
                async with client.stream(
                    "GET", target, headers=headers, extensions=ext
                ) as resp:
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
                    return bytes(buf), resp.headers.get("content-type", "")
            raise UnsafeURL("too many redirects")

    try:
        return await asyncio.wait_for(run(), deadline)
    except asyncio.TimeoutError as e:
        raise FetchTooLarge("fetch timed out") from e


async def _fetch_http(url: str) -> str:
    body, ctype = await _guarded_get(url, MAX_PAGE_BYTES, FETCH_DEADLINE_S)
    # Novel mirrors mislabel charsets constantly; let httpx guess from the
    # bytes rather than trusting a bogus header.
    return httpx.Response(200, headers={"content-type": ctype}, content=body).text


async def fetch_bytes_guarded(url: str, max_bytes: int) -> bytes:
    """SSRF-guarded GET returning the body, streamed and capped at ``max_bytes``."""
    body, _ = await _guarded_get(url, max_bytes, FETCH_DEADLINE_S)
    return body


def make_route_guard():
    """Playwright route handler: SSRF-check EVERY request, not just navigations."""

    async def _guard(route):
        url = route.request.url
        scheme = urlsplit(url).scheme.lower()
        if scheme in ("data", "blob", "about"):
            await route.continue_()
            return
        if scheme not in ("http", "https"):  # ws/wss, ftp, file, ...
            await route.abort()
            return
        try:
            await assert_public_url(url)
        except UnsafeURL:
            await route.abort()
            return
        await route.continue_()

    return _guard


async def _fetch_playwright(url: str) -> str:
    from playwright.async_api import async_playwright  # imported lazily

    await assert_public_url(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent=_USER_AGENT, service_workers="block"
            )
            await ctx.route("**/*", make_route_guard())
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


def _cover_hint(html: str, url: str) -> str | None:
    try:
        from .cover_fetch import extract_cover_url

        return extract_cover_url(html, url)
    except Exception:  # noqa: BLE001 - a cover hint is never worth failing a scrape
        return None


async def scrape_url(url: str) -> ScrapedPage:
    log.info("scrape.start", url=url, backend=settings.scraper_backend)
    html = await _fetch(url)
    title, text = await _extract(html)
    return ScrapedPage(url=url, title=title, text=text, cover_url=_cover_hint(html, url))


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
