"""File-hash, path-containment and cleanup lookups shared by every API module."""

import hashlib
from pathlib import Path

from sqlalchemy import select

from training.data import sha

from .models import ImageCleanup

__all__ = ["HIGH_DEPTH_MODES", "HashMismatch", "active_cleanup", "digest", "inside", "read_verified", "sha"]

# PIL modes that need min/max normalisation before they can be shown as 8-bit.
HIGH_DEPTH_MODES = {"I", "F", "I;16", "I;16B", "I;16L"}


class HashMismatch(ValueError):
    """The bytes on disk no longer match the hash registered in the database."""


def digest(path: Path) -> str:
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def inside(path, root) -> bool:
    """True when `path` resolves to a location under `root` (symlinks resolved)."""
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def read_verified(path, expected_hash: str) -> bytes:
    """Read a file and guarantee it still matches the registered SHA256."""
    content = Path(path).read_bytes()
    if sha(content) != expected_hash:
        raise HashMismatch(f"{Path(path).name}: file content changed since registration")
    return content


def active_cleanup(db, image_id):
    return db.scalar(select(ImageCleanup).where(ImageCleanup.image_id == image_id, ImageCleanup.active.is_(True)))
