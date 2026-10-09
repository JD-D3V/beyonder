"""Community features: ratings and reviews, chapter comments, reports."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..auth.deps import current_user, require_admin
from ..auth.throttle import SlidingWindow
from ..storage.db import get_session
from ..storage.models import Comment, ContentReport, Review, User
from ..storage.repository import get_chapter_by_idx, get_novel

router = APIRouter()

_comment_posts = SlidingWindow(limit=10, window_s=5 * 60)
_review_writes = SlidingWindow(limit=5, window_s=60 * 60)


def reset_throttles() -> None:
    _comment_posts.clear()
    _review_writes.clear()


def _too_many(what: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "too_many_posts",
            "detail": f"Too many {what}. Wait a while and try again.",
        },
    )


def _display_name(name: str | None, user_id: int) -> str:
    """The user's chosen public name; never any part of the email."""
    return name or f"reader-{user_id}"


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


# --- Schemas --------------------------------------------------------------

class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("body")
    @classmethod
    def _blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ReviewOut(BaseModel):
    id: int
    user_id: int
    author: str
    rating: int
    body: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RatingOut(BaseModel):
    average: Optional[float] = None
    count: int = 0
    histogram: dict[int, int] = Field(default_factory=dict)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("comment body is empty")
        return v


class CommentOut(BaseModel):
    id: int
    chapter_idx: int
    parent_id: Optional[int] = None
    user_id: Optional[int] = None
    author: Optional[str] = None
    body: str
    deleted: bool = False
    created_at: Optional[str] = None
    replies: list["CommentOut"] = Field(default_factory=list)


class ReportIn(BaseModel):
    kind: Literal["review", "comment"]
    target_id: int
    reason: str = Field(default="", max_length=500)


class ReportOut(BaseModel):
    id: int
    kind: str
    target_id: int
    reporter_id: int
    reporter: str
    reason: str
    created_at: Optional[str] = None
    resolved: bool
    target_body: Optional[str] = None
    target_author: Optional[str] = None


# --- Reviews / ratings ----------------------------------------------------

def _require_novel(s, novel_id: int) -> None:
    if get_novel(s, novel_id) is None:
        raise HTTPException(404, "novel not found")


def _review_out(r: Review, name: str | None) -> ReviewOut:
    return ReviewOut(
        id=r.id, user_id=r.user_id, author=_display_name(name, r.user_id), rating=r.rating,
        body=r.body, created_at=_iso(r.created_at), updated_at=_iso(r.updated_at),
    )


@router.get("/novels/{novel_id}/reviews", response_model=list[ReviewOut])
async def list_reviews(
    novel_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ReviewOut]:
    with get_session() as s:
        _require_novel(s, novel_id)
        rows = s.execute(
            select(Review, User.display_name)
            .join(User, User.id == Review.user_id)
            .where(Review.novel_id == novel_id)
            .order_by(Review.created_at.desc(), Review.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_review_out(r, name) for r, name in rows]


@router.get("/novels/{novel_id}/rating", response_model=RatingOut)
async def get_rating(novel_id: int) -> RatingOut:
    with get_session() as s:
        _require_novel(s, novel_id)
        counts = dict(
            s.execute(
                select(Review.rating, func.count(Review.id))
                .where(Review.novel_id == novel_id)
                .group_by(Review.rating)
            ).all()
        )
    hist = {i: int(counts.get(i, 0)) for i in range(1, 6)}
    total = sum(hist.values())
    avg = (
        round(sum(k * v for k, v in hist.items()) / total, 2) if total else None
    )
    return RatingOut(average=avg, count=total, histogram=hist)


@router.put("/novels/{novel_id}/review", response_model=ReviewOut)
async def put_review(
    novel_id: int, body: ReviewIn, user: User = Depends(current_user)
) -> ReviewOut:
    with get_session() as s:
        _require_novel(s, novel_id)
        if not _review_writes.hit(f"u{user.id}"):
            raise _too_many("review changes")
        s.execute(
            pg_insert(Review)
            .values(
                novel_id=novel_id, user_id=user.id,
                rating=body.rating, body=body.body,
            )
            .on_conflict_do_update(
                index_elements=[Review.novel_id, Review.user_id],
                set_={
                    "rating": body.rating, "body": body.body,
                    "updated_at": func.now(),
                },
            )
        )
        r = s.execute(
            select(Review).where(
                Review.novel_id == novel_id, Review.user_id == user.id
            )
        ).scalar_one()
        return _review_out(r, getattr(user, 'display_name', None))


@router.delete("/novels/{novel_id}/review", status_code=204)
async def delete_own_review(
    novel_id: int, user: User = Depends(current_user)
) -> Response:
    with get_session() as s:
        _require_novel(s, novel_id)
        if not _review_writes.hit(f"u{user.id}"):
            raise _too_many("review changes")
        s.execute(
            sa_delete(Review).where(
                Review.novel_id == novel_id, Review.user_id == user.id
            )
        )
    return Response(status_code=204)


@router.delete("/reviews/{review_id}", status_code=204)
async def admin_delete_review(
    review_id: int, _admin: User = Depends(require_admin)
) -> Response:
    with get_session() as s:
        r = s.get(Review, review_id)
        if r is None:
            raise HTTPException(404, "review not found")
        s.delete(r)
    return Response(status_code=204)


# --- Comments -------------------------------------------------------------

def _require_chapter(s, novel_id: int, idx: int) -> None:
    _require_novel(s, novel_id)
    if get_chapter_by_idx(s, novel_id, idx) is None:
        raise HTTPException(404, "chapter not found")


def _comment_out(c: Comment, name: str | None) -> CommentOut:
    if c.deleted:
        return CommentOut(
            id=c.id, chapter_idx=c.chapter_idx, parent_id=c.parent_id,
            body="[deleted]", deleted=True, created_at=_iso(c.created_at),
        )
    return CommentOut(
        id=c.id, chapter_idx=c.chapter_idx, parent_id=c.parent_id,
        user_id=c.user_id, author=_display_name(name, c.user_id), body=c.body,
        created_at=_iso(c.created_at),
    )


@router.get(
    "/novels/{novel_id}/chapters/{idx}/comments", response_model=list[CommentOut]
)
async def list_comments(novel_id: int, idx: int) -> list[CommentOut]:
    with get_session() as s:
        _require_chapter(s, novel_id, idx)
        rows = s.execute(
            select(Comment, User.display_name)
            .join(User, User.id == Comment.user_id)
            .where(Comment.novel_id == novel_id, Comment.chapter_idx == idx)
            .order_by(Comment.created_at, Comment.id)
        ).all()
    replies: dict[int, list[CommentOut]] = {}
    tops: list[tuple[Comment, str]] = []
    for c, name in rows:
        if c.parent_id is None:
            tops.append((c, name))
        elif not c.deleted:
            replies.setdefault(c.parent_id, []).append(_comment_out(c, name))
    out: list[CommentOut] = []
    for c, name in reversed(tops):  # newest first
        kids = replies.get(c.id, [])
        if c.deleted and not kids:
            continue
        node = _comment_out(c, name)
        node.replies = kids  # oldest first (query order)
        out.append(node)
    return out


@router.post(
    "/novels/{novel_id}/chapters/{idx}/comments",
    response_model=CommentOut, status_code=201,
)
async def post_comment(
    novel_id: int, idx: int, body: CommentIn, user: User = Depends(current_user)
) -> CommentOut:
    with get_session() as s:
        _require_chapter(s, novel_id, idx)
        if body.parent_id is not None:
            parent = s.get(Comment, body.parent_id)
            if parent is None or parent.deleted:
                raise HTTPException(404, "parent comment not found")
            if (
                parent.novel_id != novel_id
                or parent.chapter_idx != idx
                or parent.parent_id is not None
            ):
                raise HTTPException(
                    400, "replies must target a top-level comment in this chapter"
                )
        if not _comment_posts.hit(f"u{user.id}"):
            raise _too_many("comments")
        c = Comment(
            novel_id=novel_id, chapter_idx=idx, user_id=user.id,
            parent_id=body.parent_id, body=body.body,
        )
        s.add(c)
        s.flush()
        s.refresh(c)
        return _comment_out(c, getattr(user, 'display_name', None))


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: int, user: User = Depends(current_user)
) -> Response:
    with get_session() as s:
        c = s.get(Comment, comment_id)
        if c is None:
            raise HTTPException(404, "comment not found")
        if c.user_id != user.id and not user.is_admin:
            raise HTTPException(403, "Not your comment.")
        c.deleted = True
    return Response(status_code=204)


# --- Reports --------------------------------------------------------------

@router.post("/reports")
async def create_report(body: ReportIn, user: User = Depends(current_user)) -> dict:
    model = Review if body.kind == "review" else Comment
    with get_session() as s:
        if s.get(model, body.target_id) is None:
            raise HTTPException(404, f"{body.kind} not found")
        s.execute(
            pg_insert(ContentReport)
            .values(
                kind=body.kind, target_id=body.target_id,
                reporter_id=user.id, reason=body.reason.strip(),
            )
            .on_conflict_do_nothing(constraint="uq_report_once")
        )
    return {"ok": True}


@router.get("/admin/reports", response_model=list[ReportOut])
async def list_reports(
    resolved: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
) -> list[ReportOut]:
    with get_session() as s:
        rows = s.execute(
            select(ContentReport, User.display_name)
            .join(User, User.id == ContentReport.reporter_id)
            .where(ContentReport.resolved.is_(resolved))
            .order_by(ContentReport.created_at.desc(), ContentReport.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        out: list[ReportOut] = []
        for rep, rname in rows:
            model = Review if rep.kind == "review" else Comment
            target = s.get(model, rep.target_id)
            t_body = t_author = None
            if target is not None:
                t_body = target.body
                author = s.get(User, target.user_id)
                t_author = (
                    _display_name(author.display_name, author.id) if author else None
                )
            out.append(
                ReportOut(
                    id=rep.id, kind=rep.kind, target_id=rep.target_id,
                    reporter_id=rep.reporter_id, reporter=_display_name(rname, rep.reporter_id),
                    reason=rep.reason, created_at=_iso(rep.created_at),
                    resolved=rep.resolved, target_body=t_body,
                    target_author=t_author,
                )
            )
        return out


@router.post("/admin/reports/{report_id}/resolve")
async def resolve_report(
    report_id: int, _admin: User = Depends(require_admin)
) -> dict:
    with get_session() as s:
        rep = s.get(ContentReport, report_id)
        if rep is None:
            raise HTTPException(404, "report not found")
        rep.resolved = True
    return {"ok": True, "id": report_id}
