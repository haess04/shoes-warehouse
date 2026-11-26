"""Synthetic temporary data only; never imports/initializes the application."""
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import photo_archive as archive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        idle = patch.object(archive, "worker_pids", return_value=[])
        idle.start()
        self.addCleanup(idle.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "data"
        self.external = self.base / "external"
        self.root.mkdir()
        self.external.mkdir()
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.executescript("""
                CREATE TABLE pallets(id INTEGER PRIMARY KEY,code TEXT);
                CREATE TABLE shoes(id INTEGER PRIMARY KEY,pallet_id INTEGER,internal_id TEXT,price INTEGER);
                CREATE TABLE shoe_photos(id INTEGER PRIMARY KEY,shoe_id INTEGER,file_path TEXT,sort_order INTEGER);
                INSERT INTO pallets VALUES(1,'P1');
                INSERT INTO shoes VALUES(1,1,'S1',123);
                INSERT INTO shoe_photos VALUES(1,1,'PALETY/P1/S1/a.jpg',8);
                INSERT INTO shoe_photos VALUES(2,1,'PALETY/P1/S1/a.jpg',9);
            """)
            db.commit()
        self.photo("PALETY/P1/S1/a.jpg", b"first-original")
        self.photo("PALETY/unusual/deep/folder/extra.png", b"unregistered")
        self.photo("P1/S1/legacy.jpeg", b"legacy-original")
        (self.root / ".session-key").write_bytes(b"private-key")
        self.output = patch("sys.stdout", new_callable=io.StringIO)
        self.output.start()
        self.addCleanup(self.output.stop)

    def photo(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def run_new(self):
        return archive.create_run(self.root, self.external)

    def test_archive_all_depths_legacy_shared_refs_and_unchanged_sources(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        run = self.run_new()
        result = archive.execute(run)
        self.assertEqual(result["verified_count"], 3)
        self.assertEqual(result["snapshot_refs"], 2)
        self.assertEqual(result["sources_removed"], 0)
        self.assertEqual(result["converted"], 0)
        for rel, data in before.items():
            self.assertEqual((self.root / rel).read_bytes(), data)
        with closing(archive.connect_manifest(run)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM files WHERE new_path IS NOT NULL").fetchone()[0], 0)
        with closing(sqlite3.connect(run / "snapshots/inventory.db")) as db:
            self.assertEqual(db.execute("SELECT price FROM shoes").fetchone(), (123,))
        self.assertEqual((run / "snapshots/.session-key").read_bytes(), b"private-key")

    def test_batch_resume_idempotent(self):
        run = self.run_new()
        self.assertEqual(archive.execute(run, 1)["state"], "partial")
        self.assertEqual(archive.execute(run, 1)["verified_count"], 2)
        self.assertEqual(archive.execute(run)["verified_count"], 3)
        self.assertEqual(archive.execute(run)["verified_count"], 3)

    def test_unique_run_never_overwrites(self):
        a, b = self.run_new(), self.run_new()
        self.assertNotEqual(a, b)
        self.assertTrue((a / "manifest.sqlite3").exists())

    def test_source_changed_before_copy(self):
        run = self.run_new()
        self.photo("P1/S1/legacy.jpeg", b"different")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            archive.execute(run)

    def test_verified_source_change_stops_resume(self):
        run = self.run_new()
        archive.execute(run)
        self.photo("P1/S1/legacy.jpeg", b"different")
        with self.assertRaisesRegex(ValueError, "changed"):
            archive.execute(run)

    def test_corrupt_archive_stops(self):
        run = self.run_new()
        archive.execute(run)
        (run / "originals/P1/S1/legacy.jpeg").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "changed"):
            archive.execute(run)

    def test_corrupt_snapshot_stops(self):
        run = self.run_new()
        (run / "snapshots/.session-key").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Snapshot"):
            archive.execute(run)

    def test_publish_interruption_resume_adopts_only_equal_bytes(self):
        run = self.run_new()
        with closing(archive.connect_manifest(run)) as db:
            rel, fp, dest = db.execute("SELECT path,fingerprint,archive_path FROM files ORDER BY path LIMIT 1").fetchone()
        sha = archive.copy_verified(self.root / rel, run / dest, json.loads(fp))
        self.assertEqual(archive.digest(run / dest), sha)
        self.assertEqual(archive.execute(run)["verified_count"], 3)

    def test_conflicting_destination_not_overwritten(self):
        source = self.root / "P1/S1/legacy.jpeg"
        dest = self.external / "exists.jpeg"
        dest.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            archive.copy_verified(source, dest, archive.fingerprint(source))
        self.assertEqual(dest.read_bytes(), b"keep")

    def test_same_stem_mixed_extensions_preserved(self):
        self.photo("PALETY/P1/S1/a.png", b"second-format")
        run = self.run_new()
        self.assertEqual(archive.execute(run)["verified_count"], 4)
        self.assertEqual((run / "originals/PALETY/P1/S1/a.png").read_bytes(), b"second-format")

    def test_arbitrary_registered_safe_path_included(self):
        self.photo("other/place/image.jpg", b"registered")
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("INSERT INTO shoe_photos VALUES(3,1,'other/place/image.jpg',10)")
            db.commit()
        self.assertEqual(archive.execute(self.run_new())["verified_count"], 4)

    def test_registered_escape_rejected(self):
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("UPDATE shoe_photos SET file_path='../private.jpg'")
            db.commit()
        with self.assertRaises(ValueError):
            self.run_new()

    def test_missing_registered_source_rejected(self):
        (self.root / "PALETY/P1/S1/a.jpg").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_new()

    def test_overlapping_archive_rejected(self):
        for p in (self.root, self.root / "archive", self.base):
            with self.assertRaises(ValueError):
                archive.create_run(self.root, p)

    def test_no_space_prevents_copy(self):
        source = self.root / "P1/S1/legacy.jpeg"
        with patch.object(archive.shutil, "disk_usage") as usage:
            usage.return_value.free = 0
            with self.assertRaisesRegex(ValueError, "space"):
                archive.copy_verified(source, self.external / "new.jpeg", archive.fingerprint(source))
        self.assertFalse((self.external / "new.jpeg").exists())

    def test_write_error_leaves_source_intact_and_no_published_file(self):
        source = self.root / "P1/S1/legacy.jpeg"
        with patch.object(archive.os, "link", side_effect=OSError("drive disconnected")):
            with self.assertRaises(OSError):
                archive.copy_verified(source, self.external / "new.jpeg", archive.fingerprint(source))
        self.assertEqual(source.read_bytes(), b"legacy-original")
        self.assertFalse((self.external / "new.jpeg").exists())
        self.assertEqual(list(self.external.iterdir()), [])

    def test_archive_paths_reject_escape(self):
        for value in ("../x", "/x", "C:/x", "a//b", "a/./b", "a/../../b"):
            with self.assertRaises(ValueError):
                archive.archive_path(self.external, value)

    def test_wal_snapshot_uses_committed_online_backup(self):
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("UPDATE shoes SET price=456")
            db.commit()
            target = self.external / "snapshot.db"
            archive.snapshot(self.root / "inventory.db", target)
            with closing(sqlite3.connect(target)) as backup:
                self.assertEqual(backup.execute("SELECT price FROM shoes").fetchone(), (456,))

    def test_snapshot_no_clobber(self):
        dest = self.external / "snapshot.db"
        dest.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            archive.snapshot(self.root / "inventory.db", dest)
        self.assertEqual(dest.read_bytes(), b"existing")

    def test_initializing_run_cannot_resume(self):
        run = self.run_new()
        with closing(archive.connect_manifest(run)) as db:
            db.execute("UPDATE meta SET value='initializing' WHERE key='state'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "initialization"):
            archive.execute(run)

    def test_active_worker_prevents_run_without_creating_archive(self):
        with patch.object(archive, "worker_pids", return_value=[999]):
            with self.assertRaisesRegex(RuntimeError, "worker detected"):
                self.run_new()
        self.assertEqual(list(self.external.iterdir()), [])

    def test_worker_appearing_during_copy_stops_without_removing_sources(self):
        run = self.run_new()
        with patch.object(archive, "worker_pids", side_effect=[[], [], [999]]):
            with self.assertRaisesRegex(RuntimeError, "worker detected"):
                archive.execute(run)
        with closing(archive.connect_manifest(run)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM files WHERE state='verified'").fetchone()[0], 1)
            self.assertEqual(dict(db.execute("SELECT key,value FROM meta"))["state"], "verifying")
        self.assertTrue((self.root / "P1/S1/legacy.jpeg").exists())
        self.assertEqual(archive.execute(run)["verified_count"], 3)

    def test_new_unregistered_file_prevents_complete_status(self):
        run = self.run_new()
        self.photo("PALETY/unusual/new.jpg", b"new-original")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            archive.execute(run)
        with closing(archive.connect_manifest(run)) as db:
            self.assertEqual(dict(db.execute("SELECT key,value FROM meta"))["state"], "verifying")

    def test_hash_detects_source_change_with_restored_fingerprint(self):
        run = self.run_new()
        archive.execute(run)
        source = self.root / "P1/S1/legacy.jpeg"
        expected = archive.fingerprint(source)
        source.write_bytes(b"x" * expected[0])
        import os
        os.utime(source, ns=(source.stat().st_atime_ns, expected[1]))
        self.assertEqual(archive.fingerprint(source), expected)
        with self.assertRaisesRegex(ValueError, "changed"):
            archive.execute(run)

    def test_concurrent_worker_lock_refused(self):
        run = self.run_new()
        with archive.run_lock(run):
            with self.assertRaises(OSError):
                archive.execute(run)

    def test_link_rejected(self):
        p = self.external / "link"
        try:
            p.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(ValueError):
            archive.create_run(p, self.external)


if __name__ == "__main__":
    unittest.main()
