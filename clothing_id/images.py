"""Image loading, downscaling and base64 packing for the vision request."""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Iterable, List

MAX_EDGE = 1568  # Claude downsamples above this; sending more just costs tokens
MAX_IMAGES = 8
JPEG_QUALITY = 88

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class ImageError(ValueError):
    pass


def _media_type(path: Path) -> str:
    media = MEDIA_TYPES.get(path.suffix.lower())
    if media is None:
        raise ImageError(f"Unsupported image type: {path.name}")
    return media


def encode_image(data: bytes, media_type: str = "image/jpeg") -> dict:
    """Build an Anthropic image content block from raw bytes."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def prepare_bytes(data: bytes, media_type: str = "image/jpeg") -> dict:
    """Downscale oversized images, then encode. Falls back to raw bytes without Pillow."""
    try:
        from PIL import Image  # imported lazily so the CLI works without Pillow
    except ImportError:  # pragma: no cover - depends on the environment
        return encode_image(data, media_type)

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # pragma: no cover - malformed upload
        raise ImageError(f"Could not decode image: {exc}") from exc

    if max(img.size) <= MAX_EDGE and media_type in MEDIA_TYPES.values():
        return encode_image(data, media_type)

    img = img.convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return encode_image(buf.getvalue(), "image/jpeg")


def load_images(paths: Iterable[os.PathLike | str]) -> List[dict]:
    """Read image files from disk into Anthropic image blocks."""
    blocks: List[dict] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise ImageError(f"No such image: {path}")
        blocks.append(prepare_bytes(path.read_bytes(), _media_type(path)))
        if len(blocks) >= MAX_IMAGES:
            break
    if not blocks:
        raise ImageError("At least one photo is required.")
    return blocks
