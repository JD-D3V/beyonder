"""Cover image validation and normalisation.

Anything we store has been decoded by Pillow (so extension and content-type are
never trusted), stripped of metadata, and re-encoded as a bounded WebP.
"""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_BOX = (600, 900)
TARGET_BYTES = 300 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class CoverError(ValueError):
    """The bytes are not an acceptable cover image."""


@dataclass
class ProcessedCover:
    data: bytes
    width: int
    height: int
    content_type: str = "image/webp"


def _process(raw: bytes) -> ProcessedCover:
    if not raw:
        raise CoverError("empty image")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CoverError("image is larger than 5 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise CoverError("unsupported image type; use JPEG, PNG, WebP or GIF")
        w, h = img.size
        if w < 1 or h < 1 or w * h > MAX_PIXELS:
            raise CoverError("image dimensions are too large")
        img.seek(0)  # first frame of animated GIF/WebP
        img.load()
    except CoverError:
        raise
    except (
        UnidentifiedImageError, Image.DecompressionBombError,
        OSError, SyntaxError, ValueError, EOFError,
    ) as e:
        raise CoverError("not a readable image") from e

    has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    img = img.convert("RGBA" if has_alpha else "RGB")
    img.thumbnail(MAX_BOX, Image.Resampling.LANCZOS)  # keeps aspect, never upscales

    data = b""
    for quality in (82, 72, 62, 50, 40):
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=quality, method=4)  # no exif/icc passed
        data = out.getvalue()
        if len(data) <= TARGET_BYTES:
            break
    return ProcessedCover(data=data, width=img.width, height=img.height)


async def process_cover(raw: bytes) -> ProcessedCover:
    """Validate and normalise off the event loop. Raises ``CoverError``."""
    return await asyncio.to_thread(_process, raw)
