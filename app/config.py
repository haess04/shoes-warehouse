"""Stable data paths; importing configuration never creates files."""

from pathlib import Path
import os
import secrets


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def configure_paths(app):
    root = Path(app.config.get("DATA_ROOT", PROJECT_ROOT)).expanduser()
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root = root.resolve()
    # Tests must explicitly select their own storage instead of the real inventory.
    if app.testing and root == PROJECT_ROOT:
        raise ValueError("TESTING requires a separate DATA_ROOT")
    app.config["DATA_ROOT"] = root
    app.config["DATABASE_PATH"] = root / "inventory.db"
    app.config["PHOTOS_ROOT"] = root / "PALETY"


def configure_session(app):
    """Persist a private signing key for flash messages; no hardcoded secret."""
    if not app.config.get("SECRET_KEY"):
        path = app.config["DATA_ROOT"] / ".session-key"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(secrets.token_hex(32))
        key = path.read_text(encoding="ascii").strip()
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid .session-key; configure a valid SECRET_KEY")
        app.config["SECRET_KEY"] = key
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
