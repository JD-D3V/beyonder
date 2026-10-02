import asyncio

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


def test_redirect_to_private_blocked(monkeypatch):
    class Resp:
        is_redirect = True
        headers = {"location": "http://169.254.169.254/"}
        text = "secret"

    class Client:
        def __init__(self, **kw):
            assert kw["follow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return Resp()

    monkeypatch.setattr(scraper.httpx, "AsyncClient", Client)
    with pytest.raises(UnsafeURL):
        asyncio.run(scraper._fetch_http("http://93.184.216.34/"))
