"""Confine media access to images, including explicitly registered legacy files."""

from pathlib import PurePosixPath, PureWindowsPath

from flask import current_app

from app.database import get_session
from app.models import Pallet, Shoe, ShoePhoto


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def safe_media_path(rel_path):
    try:
        normalized = rel_path.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (not normalized or "\x00" in normalized or path.is_absolute()
                or PureWindowsPath(normalized).drive
                or any(part in {"..", ".", ""} for part in normalized.split("/"))
                or any(":" in part for part in path.parts)
                or path.suffix.lower() not in IMAGE_EXTENSIONS):
            return None
        root = current_app.config["DATA_ROOT"].resolve()
        target = (root / normalized).resolve()
        photos = current_app.config["PHOTOS_ROOT"].resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return None
        if photos != root and photos.is_relative_to(root) and target.is_relative_to(photos):
            return target
        # Legacy support only for a registered image in its actual pallet/shoe folder.
        if len(path.parts) == 3:
            with get_session() as session:
                row = (session.query(ShoePhoto.id).join(Shoe).join(Pallet)
                       .filter(ShoePhoto.file_path == normalized,
                               Pallet.code == path.parts[0], Shoe.internal_id == path.parts[1]).first())
                legacy = (root / path.parts[0] / path.parts[1]).resolve()
                if (row and legacy == root / path.parts[0] / path.parts[1]
                        and target.is_relative_to(legacy)):
                    return target
    except (OSError, ValueError, RuntimeError):
        return None
    return None
