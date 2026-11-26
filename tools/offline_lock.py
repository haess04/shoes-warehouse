"""Cooperative lifetime lock shared by every factory/CLI start; no app imports."""
import json
import os
from pathlib import Path
import weakref

from tools.photo_storage import no_links, atomic_new

_apps = weakref.WeakValueDictionary()
MARKER = ".photo-maintenance.json"


class Gate:
    def __init__(self, root):
        self.root = no_links(Path(root))
        self.stream = no_links(self.root / ".photo-offline.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.stream.close()
            raise RuntimeError("Offline exclusion unavailable: application/maintenance already active")

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def marker(root):
    path = no_links(Path(root) / MARKER)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def claim(root, run):
    owner = marker(root)
    expected = {"run": str(run), "version": 1}
    if owner is None:
        atomic_new(Path(root) / MARKER, json.dumps(expected).encode())
    elif owner != expected:
        raise RuntimeError("Persistent maintenance belongs to a different run")


def release(root, run):
    if marker(root) != {"run": str(run), "version": 1}:
        raise RuntimeError("Maintenance ownership mismatch")
    no_links(Path(root) / MARKER).unlink()


def init_gate(app):
    """Before session/auth/database initialization; all requests guarded, including GET sync."""
    from flask import abort
    root = app.config["DATA_ROOT"]
    if marker(root) is not None:
        raise RuntimeError("Persistent photo maintenance: resume/rollback its journal before startup")
    key = str(root)
    gate = _apps.get(key)
    if gate is None or gate.stream.closed:
        root.mkdir(parents=True, exist_ok=True)
        gate = Gate(root)
        _apps[key] = gate
    app.extensions["offline_gate"] = gate
    # Check again while holding the OS lock, closing the startup race.
    if marker(root) is not None:
        raise RuntimeError("Photo maintenance active")

    @app.before_request
    def maintenance_guard():
        try:
            active = gate.stream.closed or marker(root) is not None
        except Exception:
            active = True
        if active:
            abort(503)
