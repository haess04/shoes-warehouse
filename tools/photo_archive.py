"""Stage 1 only: resumable, verified copies. Never converts, edits DB refs or deletes sources.

No application imports. Private SQLite manifest lives on the external archive drive.
Refuses detected application/Python workers; never stops processes. This is a
read-only archive, NOT an exclusive offline gate suitable for a migration.
"""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

try:
    from tools.photo_storage import EXTENSIONS, no_links, source_path
except ModuleNotFoundError:
    from photo_storage import EXTENSIONS, no_links, source_path


RESERVE = 2 * 1024**3
CHUNK = 1024**2


def worker_pids():
    """Conservative Windows process check, without importing/starting the app."""
    if os.name != "nt":
        raise RuntimeError("Live archive process inspection requires Windows")
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(kernel, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        fn.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        while ok:
            name = entry.szExeFile.lower()
            if entry.th32ProcessID != os.getpid() and (
                    name.startswith(("python", "pypy", "uvicorn", "gunicorn", "waitress", "flask", "magazynier"))):
                found.append(entry.th32ProcessID)
            ok = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    return found


def require_idle():
    if worker_pids():
        raise RuntimeError("Application/other Python worker detected; stop archive, do not kill processes")


def archive_path(run, relative):
    parts = relative.replace("\\", "/").split("/")
    if any(p in {"", ".", ".."} or ":" in p for p in parts):
        raise ValueError("Unsafe archive path")
    target = no_links(run.joinpath(*parts))
    if not target.is_relative_to(run):
        raise ValueError("Archive path escape")
    return target


def fingerprint(path):
    st = no_links(path).stat()
    if not path.is_file():
        raise ValueError("Not a regular file")
    return [st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino]


def digest(path):
    h = hashlib.sha256()
    with no_links(path).open("rb") as stream:
        while data := stream.read(CHUNK):
            h.update(data)
    return h.hexdigest()


@contextmanager
def run_lock(run):
    """OS-released advisory lock excludes simultaneous archive workers, not the app."""
    with no_links(run / ".worker.lock").open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def copy_verified(source, target, expected):
    """Never overwrite. An interrupted published copy is adopted only after hashing."""
    if fingerprint(source) != expected:
        raise ValueError("Source fingerprint changed; start a fresh archive run")
    no_links(target.parent).mkdir(parents=True, exist_ok=True)
    if target.exists():
        sha = digest(source)
        if fingerprint(source) != expected or digest(target) != sha:
            raise ValueError("Existing destination/source mismatch; refusing overwrite")
        return sha
    if shutil.disk_usage(target.parent).free < expected[0] + RESERVE:
        raise ValueError("Archive drive has insufficient free space")
    fd, temporary = tempfile.mkstemp(prefix=".copy-", dir=target.parent)
    try:
        copied = hashlib.sha256()
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            while data := src.read(CHUNK):
                dst.write(data)
                copied.update(data)
            dst.flush()
            os.fsync(dst.fileno())
        sha = copied.hexdigest()
        if (fingerprint(source) != expected or digest(source) != sha
                or fingerprint(source) != expected or digest(Path(temporary)) != sha):
            raise ValueError("Source changed or copied bytes failed verification")
        os.link(temporary, target)  # atomic, fails if another file exists
        if digest(target) != sha:
            raise ValueError("Published archive failed verification")
        return sha
    finally:
        os.unlink(temporary)


def snapshot(source, target):
    """SQLite online backup API: consistent single-DB snapshot, no app initialization."""
    no_links(source)
    if not source.is_file():
        raise ValueError("Required SQLite source missing")
    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=target.parent)
    os.close(fd)
    deadline = time.monotonic() + 120

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded 120 seconds")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.1)
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Snapshot integrity check failed")
        with open(temporary, "r+b") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, target)
        return digest(target)
    finally:
        os.unlink(temporary)


def inventory(root, database):
    """Recursive standard photos + all registered paths + known direct legacy files."""
    paths = set()
    refs = []
    photos = no_links(root / "PALETY")
    if photos.exists():
        def fail(exc):
            raise exc
        for directory, dirs, files in os.walk(photos, followlinks=False, onerror=fail):
            for name in dirs:
                no_links(Path(directory) / name)
            for name in files:
                p = Path(directory) / name
                if p.suffix.lower() in EXTENSIONS:
                    paths.add(source_path(root, p.relative_to(root).as_posix()))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        for row_id, relative in db.execute("SELECT id, file_path FROM shoe_photos ORDER BY id"):
            p = source_path(root, relative)
            paths.add(p)
            refs.append((row_id, relative, p.relative_to(root).as_posix()))
        for pallet, shoe in db.execute("SELECT p.code,s.internal_id FROM shoes s JOIN pallets p ON p.id=s.pallet_id"):
            if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v)
                       for v in (pallet, shoe)):
                raise ValueError("Unsafe legacy identifiers")
            folder = no_links(root / pallet / shoe)
            if folder.is_dir():
                for p in folder.iterdir():
                    if p.suffix.lower() in EXTENSIONS:
                        paths.add(source_path(root, p.relative_to(root).as_posix()))
    return [(p.relative_to(root).as_posix(), fingerprint(p)) for p in sorted(paths)], refs


def connect_manifest(run):
    db = sqlite3.connect(no_links(run / "manifest.sqlite3"))
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def create_run(root, archive):
    require_idle()
    root, archive = no_links(root).resolve(), no_links(archive).resolve()
    if archive.is_relative_to(root) or root.is_relative_to(archive):
        raise ValueError("Archive must be outside DATA_ROOT, with no overlap")
    if not archive.is_dir():
        raise ValueError("Archive base must already exist")
    if shutil.disk_usage(archive).free < RESERVE:
        raise ValueError("Archive drive reserve unavailable")
    run = archive / (datetime.now(timezone.utc).strftime("archive-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
    run.mkdir()  # never reuse existing archive
    (run / "snapshots").mkdir()
    (run / "originals").mkdir()
    with run_lock(run), closing(connect_manifest(run)) as db:
        db.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE files(path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,
                archive_path TEXT NOT NULL UNIQUE, sha256 TEXT,state TEXT NOT NULL,
                new_path TEXT,new_sha256 TEXT,new_bytes INTEGER);
            CREATE TABLE refs(id INTEGER PRIMARY KEY,original_path TEXT NOT NULL,path TEXT NOT NULL);
            CREATE TABLE snapshots(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL);
        """)
        db.executemany("INSERT INTO meta VALUES(?,?)", [
            ("version", "1"), ("data_root", str(root)), ("run_path", str(run)),
            ("state", "initializing"), ("created_utc", datetime.now(timezone.utc).isoformat()),
            ("free_before", json.dumps({"source": shutil.disk_usage(root).free,
                                        "archive": shutil.disk_usage(archive).free}))])
        db.commit()
        for name in ("inventory.db", ".auth.sqlite3"):
            require_idle()
            source = no_links(root / name)
            if name != "inventory.db" and not source.exists():
                continue
            target = run / "snapshots" / name
            sha = snapshot(source, target)
            db.execute("INSERT INTO snapshots VALUES(?,?)", (target.relative_to(run).as_posix(), sha))
            db.commit()
        key = no_links(root / ".session-key")
        if key.exists():
            sha = copy_verified(key, run / "snapshots" / key.name, fingerprint(key))
            db.execute("INSERT INTO snapshots VALUES(?,?)", ("snapshots/" + key.name, sha))
            db.commit()
        files, refs = inventory(root, run / "snapshots" / "inventory.db")
        total = sum(fp[0] for _, fp in files)
        if shutil.disk_usage(run).free < total + RESERVE:
            raise ValueError("Insufficient capacity for full archive plus reserve")
        db.executemany("INSERT INTO files(path,fingerprint,archive_path,state) VALUES(?,?,?,?)",
                       [(rel, json.dumps(fp), "originals/" + rel, "planned") for rel, fp in files])
        db.executemany("INSERT INTO refs VALUES(?,?,?)", refs)
        db.execute("UPDATE meta SET value='planned' WHERE key='state'")
        db.commit()
    print(json.dumps({"run": str(run), "planned_count": len(files), "planned_bytes": total}), flush=True)
    return run


def execute(run, limit=None):
    require_idle()
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    run = no_links(run).resolve()
    with run_lock(run), closing(connect_manifest(run)) as db:
        meta = dict(db.execute("SELECT key,value FROM meta"))
        if meta["state"] == "initializing" or meta["run_path"] != str(run):
            raise ValueError("Incomplete initialization or relocated run; refusing resume")
        root = no_links(Path(meta["data_root"]))
        if run.is_relative_to(root) or root.is_relative_to(run):
            raise ValueError("Unsafe archive location")
        db.execute("UPDATE meta SET value='verifying' WHERE key='state'")
        db.commit()
        for rel, sha in db.execute("SELECT path,sha256 FROM snapshots"):
            if digest(archive_path(run, rel)) != sha:
                raise ValueError("Snapshot checksum mismatch")
        rows = db.execute("SELECT path,fingerprint,archive_path,sha256,state FROM files ORDER BY path").fetchall()
        processed = 0
        for rel, fp, archived, sha, state in rows:
            require_idle()
            source = source_path(root, rel)
            target = archive_path(run, archived)
            expected = json.loads(fp)
            if state == "verified":
                if (fingerprint(source) != expected or digest(source) != sha
                        or fingerprint(source) != expected or digest(target) != sha):
                    raise ValueError("Previously verified source/archive changed")
                continue
            if limit is not None and processed >= limit:
                break
            sha = copy_verified(source, target, expected)
            db.execute("UPDATE files SET sha256=?,state='verified' WHERE path=?", (sha, rel))
            db.commit()  # durable after every independently verified photo
            processed += 1
            if processed % 100 == 0:
                print(json.dumps({"batch_verified": processed}), flush=True)
        count, total = db.execute("SELECT COUNT(*),COALESCE(SUM(json_extract(fingerprint,'$[0]')),0) FROM files WHERE state='verified'").fetchone()
        complete = count == len(rows)
        if complete:
            require_idle()
            current, refs = inventory(root, run / "snapshots" / "inventory.db")
            if dict(current) != {rel: json.loads(fp) for rel, fp, _, _, _ in rows}:
                raise ValueError("Source inventory changed; refusing complete status")
        db.execute("UPDATE meta SET value=? WHERE key='state'", ("archive_verified" if complete else "partial",))
        db.commit()
        result = {"run": str(run), "state": "archive_verified" if complete else "partial",
                  "verified_count": count, "verified_bytes": total, "planned_count": len(rows),
                  "snapshot_refs": db.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
                  "free_after": {"source": shutil.disk_usage(root).free, "archive": shutil.disk_usage(run).free},
                  "converted": 0, "sources_removed": 0,
                  "note": "Per-file verified copies, not a globally quiescent snapshot; revalidate offline before migration."}
        db.execute("INSERT OR REPLACE INTO meta VALUES('last_result',?)", (json.dumps(result),))
        db.execute("INSERT OR REPLACE INTO meta VALUES('verified_utc',?)", (datetime.now(timezone.utc).isoformat(),))
        db.commit()
        print(json.dumps(result), flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--data-root", type=Path, required=True)
    start.add_argument("--archive-base", type=Path, required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--run", type=Path, required=True)
    for p in (start, resume):
        p.add_argument("--limit", type=int, help="Maximum newly copied files this batch")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    run = create_run(args.data_root, args.archive_base) if args.command == "start" else args.run
    execute(run, args.limit)


if __name__ == "__main__":
    main()
