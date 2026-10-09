"""Per-user shelves: reading / plan / completed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth.deps import current_user
from ..storage.db import get_session
from ..storage.models import User
from ..storage.repository import get_novel, remove_shelf, set_shelf, shelf_rows
from .novels import _novel_out
from .schemas import LibraryItemOut, LibraryOut, ShelfIn

router = APIRouter()


@router.get("/library", response_model=LibraryOut)
async def get_library(user: User = Depends(current_user)) -> LibraryOut:
    out: dict[str, list[LibraryItemOut]] = {
        "reading": [], "plan": [], "completed": [],
    }
    with get_session() as s:
        for shelf, r, current in shelf_rows(s, user.id):
            if shelf not in out:
                continue
            base = _novel_out(
                r.novel, r.chapter_count, r.char_count, r.translated_count,
                r.rating_avg, r.rating_count,
            )
            out[shelf].append(
                LibraryItemOut(**base.model_dump(), current_chapter=current)
            )
    return LibraryOut(**out)


@router.put("/library/{novel_id}")
async def put_library(
    novel_id: int, body: ShelfIn, user: User = Depends(current_user)
) -> dict:
    with get_session() as s:
        if get_novel(s, novel_id) is None:
            raise HTTPException(404, "novel not found")
        set_shelf(s, user.id, novel_id, body.shelf)
    return {"ok": True, "novel_id": novel_id, "shelf": body.shelf}


@router.delete("/library/{novel_id}", status_code=204)
async def delete_library(
    novel_id: int, user: User = Depends(current_user)
) -> Response:
    with get_session() as s:
        remove_shelf(s, user.id, novel_id)
    return Response(status_code=204)
