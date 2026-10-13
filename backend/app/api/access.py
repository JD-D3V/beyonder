"""Who may see which book. One rule, used by every route that takes a novel id.

Public books are visible to everyone. Private books are visible to their owner
and to admins; everyone else gets a 404 (never a 403, so a private book's
existence is not revealed).
"""
from __future__ import annotations

from fastapi import HTTPException

from ..storage.models import Novel, User
from ..storage.repository import get_novel


def can_see(novel: Novel, user: User | None) -> bool:
    if novel.visibility == "public":
        return True
    if user is None:
        return False
    return bool(user.is_admin) or (
        novel.owner_id is not None and novel.owner_id == user.id
    )


def visible_novel_or_404(session, novel_id: int, user: User | None) -> Novel:
    novel = get_novel(session, novel_id)
    if novel is None or not can_see(novel, user):
        raise HTTPException(404, "novel not found")
    return novel


def require_public(novel: Novel, what: str) -> None:
    """Reviews and comments exist only on public books."""
    if novel.visibility != "public":
        raise HTTPException(403, f"{what} are only available on public books.")
