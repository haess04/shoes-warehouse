"""Offline second batch. Default CLI is read-only; --execute enables durable work.

Invoke with python -m tools.photo_migrate. No application or ORM initialization.
All live writes require the same OS gate used by the application factory, plus
a persistent owner marker. A crash releases only the OS gate, never ownership.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import warnings

from PIL import Image, ImageOps

from tools import photo_archive as archive
from tools.photo_storage import no_links, source_path, MAX_FILE, MAX_PIXELS
from tools.offline_lock import Gate, claim, release, marker

RESERVE = 2 * 1024**3


def checkpoint(name):
    """Synthetic tests inject process failures at durable boundaries."""


def ro(path):
    return sqlite3.connect(no_links(path).as_uri() + "?mode=ro", uri=True)


def logical(db, replacements=None):
    """Hash every schema object and every value; only explicitly mapped paths differ."""
    replacements = replacements or {}
    h = hashlib.sha256()
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    h.update(repr(schema).encode())
    for kind, name, _, _ in schema:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [r[1] for r in db.execute("PRAGMA table_info(" + quoted + ")")]
        rows = db.execute("SELECT * FROM " + quoted).fetchall()
        if name == "shoe_photos":
            idx, path = columns.index("id"), columns.index("file_path")
            changed = []
            for row in rows:
                row = list(row)
                if row[idx] in replacements:
                    row[path] = replacements[row[idx]]
                changed.append(tuple(row))
            rows = changed
        h.update(name.encode())
        for row in sorted(rows, key=repr):
            h.update(repr(row).encode())
    return h.hexdigest()


def reserve(path, size=0):
    if shutil.disk_usage(no_links(path)).free < RESERVE + size:
        raise RuntimeError("Insufficient disk reserve")


def validate_output(path, size):
    with Image.open(no_links(path)) as image:
        image.load()
        if (image.format != "WEBP" or image.size != tuple(size)
                or getattr(image, "n_frames", 1) != 1 or image.mode != "RGB"
                or any(k in image.info for k in ("exif", "icc_profile", "xmp"))):
            raise ValueError("Output decode/dimensions/metadata verification failed")


def encode(source, target):
    """Same policy as approved samples; bounded single image, new RGB canvas."""
    if source.suffix.lower() == ".webp":
        return "existing_webp", None
    if source.stat().st_size > MAX_FILE:
        return "oversize_bytes", None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if getattr(image, "n_frames", 1) != 1:
                    return "animated", None
                if image.width * image.height > MAX_PIXELS:
                    return "oversize_pixels", None
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgba = oriented.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                clean.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                size = clean.size
                clean.save(target, format="WEBP", quality=82, method=4)
        with target.open("r+b") as stream:
            os.fsync(stream.fileno())
        validate_output(target, size)
        if target.stat().st_size >= source.stat().st_size:
            target.unlink()
            return "not_smaller", None
        return "convert", size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "oversize_pixels", None
    except (OSError, SyntaxError, ValueError) as exc:
        # Decode failures may be kept, but IO/output failures must never masquerade
        # as corrupt input: independently decode the source before deciding.
        try:
            with Image.open(source) as image:
                image.load()
        except (OSError, SyntaxError, ValueError):
            if target.exists():
                target.unlink()
            return "corrupt", None
        raise exc


def inspect(root, archive_run):
    root, archive_run = no_links(root), no_links(archive_run)
    if root.is_relative_to(archive_run) or archive_run.is_relative_to(root):
        raise ValueError("Archive and data roots overlap")
    with closing(ro(archive_run / "manifest.sqlite3")) as manifest:
        meta = dict(manifest.execute("SELECT key,value FROM meta"))
        if meta.get("state") != "archive_verified" or Path(meta["data_root"]) != root:
            raise ValueError("Archive is not verified for this DATA_ROOT")
        files = manifest.execute("SELECT path,fingerprint,archive_path,sha256,state FROM files ORDER BY path").fetchall()
        if any(r[4] != "verified" or not r[3] for r in files):
            raise ValueError("Archive has unverified entries")
    # Snapshot consistency is tested under an SQLite read transaction.
    with closing(ro(root / "inventory.db")) as db:
        db.execute("BEGIN")
        signature = logical(db)
        refs = db.execute("SELECT id,file_path FROM shoe_photos ORDER BY id").fetchall()
        live, _ = archive.inventory(root, root / "inventory.db")
        if dict(live) != {p: json.loads(fp) for p, fp, *_ in files}:
            raise ValueError("Live file inventory/fingerprints differ from permanent archive")
        for _, relative in refs:
            source_path(root, relative)
    return files, refs, signature


def plan(root, archive_run, execute=False):
    root, archive_run = no_links(root).resolve(), no_links(archive_run).resolve()
    files, refs, signature = inspect(root, archive_run)
    canonical = {r[0].casefold(): r[0] for r in files}
    if len(canonical) != len(files):
        raise ValueError("Case-insensitive source collision")
    if not execute:
        return {"dry_run": True, "files": len(files), "refs": len(refs), "db_signature": signature}
    reserve(archive_run)
    run = archive_run / ("migration-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
    run.mkdir()
    (run / "stage").mkdir()
    with closing(sqlite3.connect(run / "journal.sqlite3")) as j:
        j.executescript("""
            PRAGMA synchronous=FULL;
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE files(path TEXT PRIMARY KEY,fp TEXT NOT NULL,arch TEXT NOT NULL,
              sha TEXT NOT NULL,decision TEXT,new_path TEXT UNIQUE,new_sha TEXT,
              new_bytes INTEGER,size TEXT,removed INTEGER NOT NULL DEFAULT 0,arch_fp TEXT NOT NULL);
            CREATE TABLE refs(id INTEGER PRIMARY KEY,original TEXT NOT NULL,path TEXT NOT NULL);
        """)
        j.executemany("INSERT INTO meta VALUES(?,?)", [
            ("root", str(root)), ("archive", str(archive_run)), ("run", str(run)),
            ("state", "planning"), ("signature", signature),
            ("manifest_sha", archive.digest(archive_run / "manifest.sqlite3"))])
        j.executemany("INSERT INTO files(path,fp,arch,sha,arch_fp) VALUES(?,?,?,?,?)",
                      [(*r[:4], json.dumps(archive.fingerprint(archive.archive_path(archive_run, r[2])))) for r in files])
        j.executemany("INSERT INTO refs VALUES(?,?,?)", [
            (i, p, canonical[source_path(root, p).relative_to(root).as_posix().casefold()])
            for i, p in refs])
        j.commit()
        archive.snapshot(root / "inventory.db", run / "planning.db")
        with closing(ro(run / "planning.db")) as backup:
            if logical(backup) != signature:
                raise ValueError("Database changed while planning")
        put(j, "planning_sha", archive.digest(run / "planning.db"))
        put(j, "state", "planned")
    return {"run": str(run), "files": len(files), "state": "planned"}


def put(j, key, value):
    j.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
    j.commit()


@contextmanager
def opened(run, audit=True):
    run = no_links(run).resolve()
    with closing(sqlite3.connect(no_links(run / "journal.sqlite3"))) as j:
        j.row_factory = sqlite3.Row
        j.execute("PRAGMA synchronous=FULL")
        meta = dict(j.execute("SELECT key,value FROM meta"))
        root, ar = no_links(Path(meta["root"])), no_links(Path(meta["archive"]))
        if str(run) != meta["run"] or not run.is_relative_to(ar) or root.is_relative_to(ar) or ar.is_relative_to(root):
            raise ValueError("Journal location/root mismatch")
        if meta["state"] == "planning":
            raise ValueError("Incomplete plan: create a new plan; no maintenance was claimed")
        if audit:
            archive.require_idle()  # conservative legacy workers, before and after OS gate
        with Gate(root):
            if audit:
                archive.require_idle()
            if archive.digest(ar / "manifest.sqlite3") != meta["manifest_sha"]:
                raise ValueError("Permanent archive manifest changed")
            if archive.digest(run / "planning.db") != meta["planning_sha"]:
                raise ValueError("Planning snapshot changed")
            yield j, meta, root, ar


def original(row, root, ar, allow_missing=False):
    src = source_path(root, row["path"])
    saved = archive.archive_path(ar, row["arch"])
    if (archive.fingerprint(saved) != json.loads(row["arch_fp"])
            or archive.digest(saved) != row["sha"]
            or archive.fingerprint(saved) != json.loads(row["arch_fp"])):
        raise ValueError("Permanent archive hash mismatch")
    if src.exists():
        if (archive.fingerprint(src) != json.loads(row["fp"]) or archive.digest(src) != row["sha"]
                or archive.fingerprint(src) != json.loads(row["fp"])):
            raise ValueError("Source changed since planning")
    elif not allow_missing:
        raise ValueError("Source missing")
    return src, saved


def mappings(j):
    return dict(j.execute("SELECT r.id,f.new_path FROM refs r JOIN files f ON f.path=r.path WHERE f.decision='convert'"))


def expected_signature(j, run, switched):
    with closing(ro(run / "planning.db")) as db:
        return logical(db, mappings(j) if switched else None)


def check_db(j, root, run, switched):
    with closing(ro(root / "inventory.db")) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Database integrity failed")
        if logical(db) != expected_signature(j, run, switched):
            raise ValueError("Database differs from exact expected snapshot")


def prepare(run, audit=True):
    run = no_links(run).resolve()
    with opened(run, audit) as (j, meta, root, ar):
        if meta["state"] not in {"planned", "preparing", "prepared"}:
            raise ValueError("Prepare requires planned/preparing/prepared state")
        check_db(j, root, run, False)
        claim(root, run)
        put(j, "state", "preparing")
        checkpoint("claimed")
        if not (run / "before.db").exists():
            archive.snapshot(root / "inventory.db", run / "before.db")
        with closing(ro(run / "before.db")) as db:
            if logical(db) != meta["signature"]:
                raise ValueError("Fresh offline backup mismatch")
        put(j, "before_sha", archive.digest(run / "before.db"))
        live, _ = archive.inventory(root, root / "inventory.db")
        if dict(live) != {r["path"]: json.loads(r["fp"]) for r in j.execute("SELECT * FROM files")}:
            raise ValueError("Inventory changed since planning")
        for n, row in enumerate(j.execute("SELECT * FROM files ORDER BY path").fetchall(), 1):
            if audit:
                archive.require_idle()
            src, _ = original(row, root, ar)
            key = hashlib.sha256(row["path"].encode()).hexdigest()
            stage = no_links(run / "stage" / (key + ".webp"))
            if row["decision"]:
                if row["decision"] == "convert":
                    if archive.digest(stage) != row["new_sha"]:
                        raise ValueError("Staged output changed")
                    validate_output(stage, json.loads(row["size"]))
                continue
            reserve(run, MAX_FILE * 8)
            if stage.exists():
                stage.unlink()  # unpublished incomplete stage, never a live output
            decision, size = encode(src, stage)
            # Rehash after decoding as well; archive must stay attached throughout.
            original(row, root, ar)
            new = src.with_name(src.stem + ".m82-" + key + ".webp").relative_to(root).as_posix()
            target = source_path(root, new)
            if target.exists():
                raise ValueError("Deterministic output name already exists: refusing collision")
            sha = archive.digest(stage) if decision == "convert" else None
            count = stage.stat().st_size if decision == "convert" else None
            checkpoint("encoded")
            j.execute("UPDATE files SET decision=?,new_path=?,new_sha=?,new_bytes=?,size=? WHERE path=?",
                      (decision, new if sha else None, sha, count, json.dumps(size), row["path"]))
            j.commit()
            if n % 25 == 0:
                print(json.dumps({"prepare": n, "total": len(live)}), flush=True)
        check_db(j, root, run, False)
        put(j, "state", "prepared")
        return summary(j, run)


def publish(stage, target, sha):
    """Cross-volume stage -> local durable temporary -> atomic NTFS no-clobber link."""
    if target.exists():
        if archive.digest(target) != sha:
            raise ValueError("Published output collision/mismatch")
        return
    reserve(target.parent, stage.stat().st_size)
    fd, tmp = tempfile.mkstemp(prefix=".migration-", suffix=".tmp", dir=no_links(target.parent))
    try:
        with stage.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, 1024**2)
            dst.flush()
            os.fsync(dst.fileno())
        if archive.digest(Path(tmp)) != sha:
            raise ValueError("Local temporary output hash mismatch")
        os.link(tmp, target)
    finally:
        os.unlink(tmp)


def switch(j, root, run, forward):
    changes = mappings(j) if forward else dict(j.execute("SELECT id,original FROM refs"))
    with closing(sqlite3.connect(root / "inventory.db")) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        actual = logical(db)
        before = expected_signature(j, run, not forward)
        after = expected_signature(j, run, forward)
        if actual == after:
            db.rollback()  # recover commit before journal write
            return
        if actual != before:
            raise ValueError("Database changed: refusing transactional switch")
        db.executemany("UPDATE shoe_photos SET file_path=? WHERE id=?", [(p, i) for i, p in changes.items()])
        if logical(db) != after:
            raise ValueError("Unexpected database delta")
        checkpoint("before_db_commit")
        db.commit()
        checkpoint("after_db_commit")


def apply(run, audit=True):
    run = no_links(run).resolve()
    with opened(run, audit) as (j, meta, root, ar):
        if meta["state"] not in {"prepared", "publishing", "switched", "removing", "verified"}:
            raise ValueError("Apply requires prepared run (or interrupted apply)")
        claim(root, run)
        if archive.digest(run / "before.db") != meta["before_sha"]:
            raise ValueError("Fresh offline backup changed")
        rows = j.execute("SELECT * FROM files ORDER BY path").fetchall()
        if meta["state"] in {"prepared", "publishing"}:
            # Accept only the two exact DB states, including commit-before-journal crash.
            with closing(ro(root / "inventory.db")) as db:
                if logical(db) not in {expected_signature(j, run, False), expected_signature(j, run, True)}:
                    raise ValueError("Database changed since plan")
            put(j, "state", "publishing")
            for row in rows:
                if audit:
                    archive.require_idle()
                original(row, root, ar)
                if row["decision"] != "convert":
                    continue
                stage = run / "stage" / (hashlib.sha256(row["path"].encode()).hexdigest() + ".webp")
                if archive.digest(stage) != row["new_sha"]:
                    raise ValueError("Stage hash changed")
                validate_output(stage, json.loads(row["size"]))
                target = source_path(root, row["new_path"])
                publish(stage, target, row["new_sha"])
                checkpoint("published")
            switch(j, root, run, True)
            put(j, "state", "switched")
        check_db(j, root, run, True)
        put(j, "state", "removing")
        for n, row in enumerate(rows, 1):
            if audit:
                archive.require_idle()
            src, _ = original(row, root, ar, allow_missing=row["decision"] == "convert")
            if row["decision"] != "convert":
                continue
            target = source_path(root, row["new_path"])
            if archive.digest(target) != row["new_sha"]:
                raise ValueError("Output hash mismatch before source removal")
            validate_output(target, json.loads(row["size"]))
            # original() rehashed archive and live source immediately above.
            if src.exists():
                checkpoint("before_remove")
                src.unlink()
            checkpoint("after_remove")
            j.execute("UPDATE files SET removed=1 WHERE path=?", (row["path"],))
            j.commit()
            if n % 25 == 0:
                print(json.dumps({"apply": n, "total": len(rows)}), flush=True)
        verify_inside(j, root, ar, run)
        put(j, "state", "verified")
        checkpoint("before_release")
        release(root, run)
        put(j, "state", "complete")
        return summary(j, run)


def verify_inside(j, root, ar, run):
    check_db(j, root, run, True)
    for row in j.execute("SELECT * FROM files ORDER BY path"):
        src, _ = original(row, root, ar, allow_missing=row["decision"] == "convert")
        if row["decision"] == "convert":
            if src.exists():
                raise ValueError("Converted original still present (sync duplicate)")
            target = source_path(root, row["new_path"])
            if archive.digest(target) != row["new_sha"]:
                raise ValueError("Final output hash mismatch")
            validate_output(target, json.loads(row["size"]))
    # Registered root and legacy paths remain in the same supported media scope.
    with closing(ro(root / "inventory.db")) as db:
        for (relative,) in db.execute("SELECT file_path FROM shoe_photos"):
            if not source_path(root, relative).is_file():
                raise ValueError("Missing registered media")
    expected = {r["new_path"] if r["decision"] == "convert" else r["path"]
                for r in j.execute("SELECT * FROM files")}
    actual, _ = archive.inventory(root, root / "inventory.db")
    if {p for p, _ in actual} != expected:
        raise ValueError("Final inventory differs: extra/missing photos or sync duplicates")


def verify(run, audit=True):
    run = no_links(run).resolve()
    with opened(run, audit) as (j, meta, root, ar):
        if meta["state"] not in {"complete", "verified"}:
            raise ValueError("Verify requires complete/verified run; use apply to resume")
        verify_inside(j, root, ar, run)
        return summary(j, run)


def rollback(run, audit=True):
    run = no_links(run).resolve()
    with opened(run, audit) as (j, meta, root, ar):
        claim(root, run)
        put(j, "state", "rolling_back")
        for row in j.execute("SELECT * FROM files ORDER BY path").fetchall():
            if audit:
                archive.require_idle()
            if row["decision"] != "convert":
                original(row, root, ar)
                continue
            src = source_path(root, row["path"])
            saved = archive.archive_path(ar, row["arch"])
            if archive.digest(saved) != row["sha"]:
                raise ValueError("Archive mismatch during rollback")
            if src.exists() and archive.digest(src) != row["sha"]:
                raise ValueError("Rollback source collision")
            publish(saved, src, row["sha"])
            os.utime(src, ns=(json.loads(row["fp"])[1], json.loads(row["fp"])[1]))
            checkpoint("restored")
        switch(j, root, run, False)
        for row in j.execute("SELECT * FROM files WHERE decision='convert'"):
            target = source_path(root, row["new_path"])
            if target.exists():
                if archive.digest(target) != row["new_sha"]:
                    raise ValueError("Rollback output changed: refusing removal")
                target.unlink()
        check_db(j, root, run, False)
        put(j, "state", "rolled_back")
        release(root, run)
        return summary(j, run)


def summary(j, run):
    decisions = dict(j.execute("SELECT coalesce(decision,'pending'),count(*) FROM files GROUP BY decision"))
    rows = j.execute("SELECT fp,decision,new_bytes,removed FROM files").fetchall()
    incoming = sum(json.loads(r[0])[0] for r in rows)
    outgoing = sum(r[2] if r[1] == "convert" else json.loads(r[0])[0] for r in rows)
    meta = dict(j.execute("SELECT key,value FROM meta"))
    return {"run": str(run), "archive": meta["archive"], "state": meta["state"],
            "decisions": decisions, "input_bytes": incoming, "output_bytes": outgoing,
            "savings_bytes": incoming - outgoing, "removed": sum(r[3] for r in rows),
            "refs": j.execute("SELECT count(*) FROM refs").fetchone()[0],
            "free": {"source": shutil.disk_usage(meta["root"]).free,
                     "archive": shutil.disk_usage(meta["archive"]).free}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "prepare", "apply", "verify", "rollback"))
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--execute", action="store_true", help="Enable durable writes; default is dry-run")
    args = parser.parse_args()
    if args.command == "plan":
        if not args.data_root or not args.archive:
            parser.error("plan requires --data-root and --archive")
        result = plan(args.data_root, args.archive, args.execute)
    elif not args.run:
        parser.error("--run required")
    elif not args.execute:
        # Strictly read-only: do not open a writable journal or acquire/create lock.
        with closing(ro(args.run / "journal.sqlite3")) as j:
            result = {"dry_run": True, "command": args.command, "meta": dict(j.execute("SELECT key,value FROM meta"))}
    else:
        result = globals()[args.command](args.run)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
