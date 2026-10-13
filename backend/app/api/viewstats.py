"""Chapter view counting: daily counters plus a bounded distinct-reader set."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from ..common.logging import get_logger
from ..storage.models import User
from ..storage.repository import record_view
from .auth_routes import client_ip

log = get_logger(__name__)

MAX_SEEN = 50_000


class ViewerDedupe:
    """Remembers (novel, viewer) pairs for today; resets at the day change or
    when it hits ``cap`` so memory stays bounded."""

    def __init__(self, cap: int = MAX_SEEN) -> None:
        self.cap = cap
        self._day: date | None = None
        self._seen: set[tuple[int, str]] = set()

    def first_today(self, novel_id: int, viewer: str, day: date) -> bool:
        if day != self._day or len(self._seen) >= self.cap:
            self._day = day
            self._seen.clear()
        key = (novel_id, viewer)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def clear(self) -> None:
        self._seen.clear()
        self._day = None


_dedupe = ViewerDedupe()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def viewer_key(request: Request, user: User | None, day: date) -> str:
    """User id if signed in, else a daily-salted hash; never a raw IP."""
    if user is not None:
        return f"u{user.id}"
    digest = hashlib.sha256(f"{client_ip(request)}{day.isoformat()}".encode())
    return digest.hexdigest()[:16]


def track_chapter_view(
    session: Session, request: Request, user: User | None, novel_id: int
) -> None:
    """Count a view. Never raises: a stats failure must not break reading."""
    try:
        day = today_utc()
        new_reader = _dedupe.first_today(novel_id, viewer_key(request, user, day), day)
        with session.begin_nested():
            record_view(session, novel_id, day, new_reader=new_reader)
    except Exception as e:  # noqa: BLE001
        log.warning("viewstats.fail", novel_id=novel_id, err=str(e))
