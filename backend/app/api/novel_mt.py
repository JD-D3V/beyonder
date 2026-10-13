"""Per-book machine-translation status and (admin) re-run."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth.deps import current_user_optional, require_admin
from ..mt import job as mt_job
from ..mt.provider import get_provider
from ..storage.db import get_session
from ..storage.models import User
from .access import visible_novel_or_404
from .schemas import MtStatusOut

router = APIRouter()


@router.get("/novels/{novel_id}/mt", response_model=MtStatusOut)
async def get_mt_status(
    novel_id: int, user: User | None = Depends(current_user_optional)
) -> MtStatusOut:
    with get_session() as s:
        visible_novel_or_404(s, novel_id, user)
    return MtStatusOut(**mt_job.status_for(novel_id))


@router.post("/novels/{novel_id}/mt", response_model=MtStatusOut, status_code=202)
async def run_mt(
    novel_id: int, admin: User = Depends(require_admin)
) -> MtStatusOut:
    """(Re)run machine translation: translates whatever is still missing."""
    with get_session() as s:
        visible_novel_or_404(s, novel_id, admin)
    if get_provider() is None:
        raise HTTPException(
            409,
            detail={
                "code": "mt_disabled",
                "detail": "Machine translation is turned off on this server.",
            },
        )
    mt_job.enqueue(novel_id)
    return MtStatusOut(**mt_job.status_for(novel_id))
