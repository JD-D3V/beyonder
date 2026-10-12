import asyncio

import httpx
import pytest

from app.ingest import scraper
from app.ingest.scraper import UnsafeURL, assert_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "file:///etc/passwd",
        "ftp://93.184.216.34/",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeURL):
        asyncio.run(assert_public_url(url))


def test_public_literal_ip_allowed():
    asyncio.run(assert_public_url("https://93.184.216.34/page"))


def test_hostname_resolving_private_rejected(monkeypatch):
    monkeypatch.setattr(
        scraper.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 80))],
    )
    with pytest.raises(UnsafeURL):
        asyncio.run(assert_public_url("http://internal.example/"))


def _public(monkeypatch, ip="93.184.216.34"):
    monkeypatch.setattr(
        scraper.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))]
    )


def test_redirect_to_private_blocked(monkeypatch):
    def handler(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    monkeypatch.setattr(scraper, "_transport", httpx.MockTransport(handler))
    with pytest.raises(UnsafeURL):
        asyncio.run(scraper._fetch_http("http://93.184.216.34/"))


def test_connection_pinned_to_validated_ip(monkeypatch):
    _public(monkeypatch)
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers["host"], req.extensions.get("sni_hostname")))
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://other.example/b"})
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(scraper, "_transport", httpx.MockTransport(handler))
    assert asyncio.run(scraper._fetch_http("https://novel.example/a")) == "ok"
    assert seen == [
        ("93.184.216.34", "novel.example", "novel.example"),
        ("93.184.216.34", "other.example", "other.example"),
    ]


def test_rebinding_after_redirect_rechecked(monkeypatch):
    answers = iter(["93.184.216.34", "10.0.0.5"])
    monkeypatch.setattr(
        scraper.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (next(answers), 443))],
    )
    handler = lambda req: httpx.Response(302, headers={"location": "https://evil.example/"})
    monkeypatch.setattr(scraper, "_transport", httpx.MockTransport(handler))
    with pytest.raises(UnsafeURL):
        asyncio.run(scraper._fetch_http("https://novel.example/"))


def test_oversized_body_rejected(monkeypatch):
    _public(monkeypatch)
    big = b"x" * (scraper.MAX_PAGE_BYTES + 1)
    monkeypatch.setattr(
        scraper, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, content=big))
    )
    with pytest.raises(scraper.FetchTooLarge):
        asyncio.run(scraper._fetch_http("https://novel.example/"))


def test_streamed_body_without_length_capped(monkeypatch):
    _public(monkeypatch)

    async def gen():
        for _ in range(10):
            yield b"y" * 1024

    monkeypatch.setattr(
        scraper, "_transport",
        httpx.MockTransport(lambda r: httpx.Response(200, content=gen())),
    )
    with pytest.raises(scraper.FetchTooLarge):
        asyncio.run(scraper.fetch_bytes_guarded("https://novel.example/", 4096))


def test_slow_body_hits_deadline(monkeypatch):
    _public(monkeypatch)

    async def slow():
        yield b"a"
        await asyncio.sleep(5)
        yield b"b"

    monkeypatch.setattr(scraper, "FETCH_DEADLINE_S", 0.2)
    monkeypatch.setattr(
        scraper, "_transport",
        httpx.MockTransport(lambda r: httpx.Response(200, content=slow())),
    )
    with pytest.raises(scraper.FetchTooLarge, match="timed out"):
        asyncio.run(scraper._fetch_http("https://novel.example/"))


class FakeRoute:
    def __init__(self, url):
        self.request = type("R", (), {"url": url})()
        self.action = None

    async def abort(self):
        self.action = "abort"

    async def continue_(self):
        self.action = "continue"


def _route(url):
    r = FakeRoute(url)
    asyncio.run(scraper.make_route_guard()(r))
    return r.action


def test_playwright_guard_checks_every_request(monkeypatch):
    _public(monkeypatch)
    assert _route("https://cdn.example/app.js") == "continue"
    assert _route("http://127.0.0.1:6333/collections") == "abort"
    assert _route("http://169.254.169.254/latest") == "abort"
    assert _route("wss://cdn.example/socket") == "abort"
    assert _route("ws://93.184.216.34/") == "abort"
    assert _route("file:///etc/passwd") == "abort"
    assert _route("data:text/plain,hi") == "continue"
    _public(monkeypatch, "10.1.1.1")
    assert _route("https://rebind.example/pixel.png") == "abort"
