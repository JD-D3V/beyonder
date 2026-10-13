"""Wikisource seed: HTML cleanup, API client (mocked HTTP), and the seed run."""
from __future__ import annotations

import httpx
import pytest

from app.ingest import wikisource
from app.ingest.wikisource import (
    WORKS, Throttle, Work, WikisourceClient, html_to_chapter,
)

PAGE = """
<div class="mw-parser-output"><div id="headerContainer">
<table><tbody><tr><td><b><a href="/wiki/x">西遊記</a></b><br />第一回<br />靈根育孕源流出 心性修持大道生<br />
<span>作者：</span><a>吳承恩</a></td></tr></tbody></table></div>
<style>.x{}</style>
<p>回目录　下一回</p>
<p>詩曰：</p>
<dl><dd><dl><dd>混沌未分天地亂，</dd><dd>茫茫渺渺無人見。</dd></dl></dd></dl>
<p>　　蓋聞天地之數<sup class="reference"><a>[1]</a></sup>，有十二萬九千六百歲為一元。</p>
<div class="mw-heading"><h2>蛇癖</h2></div>
<p>第二段。</p>
<table><tbody><tr><td>下一回</td></tr></tbody></table>
<div class="mw-heading"><h2>註釋</h2></div>
<ol class="references"><li>footnote text</li></ol>
<p>after notes</p>
<div class="licenseContainer"><p>此作品屬於公有領域</p></div>
</div>
"""


def test_html_to_chapter_keeps_prose_drops_chrome():
    title, text = html_to_chapter(PAGE, fallback="第001回")
    assert title == "第一回 靈根育孕源流出 心性修持大道生"
    assert text.split("\n\n") == [
        "詩曰：",
        "混沌未分天地亂，\n茫茫渺渺無人見。",
        "蓋聞天地之數，有十二萬九千六百歲為一元。",
        "蛇癖",
        "第二段。",
    ]
    for junk in ("[1]", "footnote", "下一回", "公有領域", "after notes", "style"):
        assert junk not in text


def test_title_falls_back_to_first_line_heading():
    html = (
        '<div class="mw-parser-output"><table><tbody><tr><td><b>紅樓夢</b><br />第001回<br />'
        "<span>作者：</span></td></tr></tbody></table>"
        '<div class="center"><b>第一回　甄士隱夢幻識通靈</b></div><p>正文。</p></div>'
    )
    title, text = html_to_chapter(html, fallback="第001回")
    assert title == "第一回 甄士隱夢幻識通靈"
    assert text == "正文。"


def test_works_cover_the_spec_list():
    assert [w.title for w in WORKS.values()] == [
        "西游记", "封神演义", "三国演义", "水浒传", "聊斋志异", "红楼梦",
    ]


def _transport(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        q = dict(req.url.params)
        if q["prop"] == "links":
            return httpx.Response(200, json={"parse": {"links": [
                {"ns": 0, "*": "西遊記/第002回"}, {"ns": 0, "*": "後西遊記"},
                {"ns": 0, "*": "西遊記/第001回"}, {"ns": 10, "*": "Template:x"},
                {"ns": 0, "*": "西遊記/第002回"},
            ]}})
        return httpx.Response(200, json={"parse": {"text": {"*": PAGE}}})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_client_lists_chapters_and_sends_user_agent():
    calls: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=_transport(calls))
    c = WikisourceClient(http, interval=0)
    pages = await c.chapter_pages(WORKS["xiyouji"])
    assert pages == ["西遊記/第002回", "西遊記/第001回"]  # TOC order, deduped, filtered
    ch = await c.chapter(pages[0])
    assert ch.title.startswith("第一回") and "混沌未分" in ch.text
    assert all(r.headers["user-agent"] == wikisource.USER_AGENT for r in calls)
    assert wikisource.USER_AGENT.startswith("BeyonderSeed/1.0")
    assert all(r.url.host == "zh.wikisource.org" for r in calls)


@pytest.mark.asyncio
async def test_throttle_spaces_requests(monkeypatch):
    slept: list[float] = []
    now = [100.0]

    async def fake_sleep(d):
        slept.append(d)
        now[0] += d

    monkeypatch.setattr(wikisource.asyncio, "sleep", fake_sleep)
    t = Throttle(1.0, clock=lambda: now[0])
    await t.wait()          # first call is immediate
    now[0] += 0.25
    await t.wait()          # 0.75 s still owed
    await t.wait()          # a full second owed
    assert slept == [pytest.approx(0.75), pytest.approx(1.0)]


class FakeClient:
    def __init__(self, n=5):
        self.n = n

    async def chapter_pages(self, work):
        return [f"{work.toc_page}/第{i:03d}回" for i in range(1, self.n + 1)]

    async def chapter(self, page):
        i = int(page[-4:-1])
        return wikisource.WikiChapter(page=page, title=f"第{i}回", text=f"正文{i}。" * 20)


@pytest.mark.db
@pytest.mark.asyncio
async def test_seed_creates_public_completed_novel_and_is_idempotent(db_session, monkeypatch):
    from sqlalchemy import select

    from app.scripts import seed_classics
    from app.storage.models import Chapter, Novel

    embedded = []

    async def fake_embed(novel_id, chaps):
        embedded.append((novel_id, len(chaps)))
        return 0

    monkeypatch.setattr(seed_classics, "embed_chapters", fake_embed)
    ids = await seed_classics.seed(["xiyouji"], max_chapters=3, client=FakeClient())
    assert len(ids) == 1 and embedded == [(ids[0], 3)]

    db_session.expire_all()
    n = db_session.get(Novel, ids[0])
    assert (n.title, n.visibility, n.owner_id, n.status) == ("西游记", "public", None, "completed")
    assert n.author == "吴承恩" and "Wikisource (public domain)" in n.description
    assert "classic" in n.tags
    chs = db_session.scalars(
        select(Chapter).where(Chapter.novel_id == n.id).order_by(Chapter.idx)
    ).all()
    assert [c.title for c in chs] == ["第1回", "第2回", "第3回"]
    assert all(c.source_url.startswith("https://zh.wikisource.org/wiki/") for c in chs)

    assert await seed_classics.seed(["xiyouji"], max_chapters=3, client=FakeClient()) == []
    assert db_session.scalars(select(Novel).where(Novel.title == "西游记")).all().__len__() == 1


def test_work_config_is_well_formed():
    import re

    for w in WORKS.values():
        assert isinstance(w, Work) and w.title and w.author and w.toc_page
        assert re.compile(w.link_re)


def test_inline_style_and_variant_tooltips_are_dropped():
    from app.ingest.wikisource import html_to_chapter

    css = ".mw-parser-output .variant-text{display:inline}" * 40
    html = (
        '<div class="mw-parser-output"><style>' + css + "</style>"
        "<table><tr><td><b>西遊記</b><br/>第十二回<br/>"
        '玄奘秉誠建大會<span class="variant-tooltip">一作「觀音顯象」</span>'
        '<style>' + css + '</style><span>作者：吳承恩</span></td></tr></table>'
        "<p>正文第一段。<style>.x{color:red}</style><script>alert(1)</script></p></div>"
    )
    title, body = html_to_chapter(html, fallback="fb")
    assert title == "第十二回 玄奘秉誠建大會"
    assert body == "正文第一段。"
    long_title, _ = html_to_chapter("<p>x</p>", fallback="長" * 600)
    assert len(long_title) == 512
