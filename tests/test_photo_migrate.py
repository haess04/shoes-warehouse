"""Second-batch tests use only synthetic temporary media and temporary databases."""
from contextlib import closing
from datetime import date
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.database import get_session
from app.models import Pallet, Shoe, ShoePhoto
from tools import photo_archive as archive, photo_migrate as migration
from tools.offline_lock import Gate, MARKER, claim, marker


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.external = self.base / "data", self.base / "external"
        self.external.mkdir()
        self.config = {"TESTING": True, "DATA_ROOT": self.root, "AUTH_DISABLED": True, "WTF_CSRF_ENABLED": False}
        app = create_app(self.config)
        with app.app_context(), get_session() as db:
            p = Pallet(code="P1", delivery_date=date(2026, 1, 2), purchase_gross=123.45, notes="unchanged")
            db.add(p)
            db.flush()
            s = Shoe(pallet_id=p.id, internal_id="S1", name="Synthetic", description="unchanged", sale_price=87.65)
            db.add(s)
            db.flush()
            db.add_all([ShoePhoto(shoe_id=s.id, file_path="PALETY/P1/S1/a.jpg", sort_order=8),
                        ShoePhoto(shoe_id=s.id, file_path="PALETY\\P1\\S1\\a.jpg", sort_order=9),
                        ShoePhoto(shoe_id=s.id, file_path="P1/S1/legacy.jpg", sort_order=12)])
            db.commit()
        app.extensions["inventory_db"]["engine"].dispose()
        app.extensions["offline_gate"].close()
        self.image("PALETY/P1/S1/a.jpg")
        self.image("PALETY/P1/S1/a.png")
        self.image("P1/S1/legacy.jpg")
        self.image("PALETY/unusual/deeper/than/sync/extra.png")
        self.image("PALETY/P1/S1/existing.webp")
        self.idle = patch.object(archive, "worker_pids", return_value=[])
        self.idle.start()
        self.addCleanup(self.idle.stop)
        output = patch("sys.stdout", new_callable=io.StringIO)
        output.start()
        self.addCleanup(output.stop)

    def image(self, relative, size=(1000, 700), **options):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (100, 140, 180)).save(path, **options)
        return path

    def plan(self):
        self.ar = archive.create_run(self.root, self.external)
        archive.execute(self.ar)
        result = migration.plan(self.root, self.ar, True)
        self.run = Path(result["run"])
        return self.run

    def rows(self):
        with closing(migration.ro(self.run / "journal.sqlite3")) as db:
            db.row_factory = sqlite3.Row
            return db.execute("SELECT * FROM files ORDER BY path").fetchall()

    def ready(self):
        self.plan()
        return migration.prepare(self.run)

    def fail(self, name):
        def hook(stage):
            if stage == name:
                raise RuntimeError("synthetic crash at " + stage)
        return patch.object(migration, "checkpoint", side_effect=hook)

    def assert_originals(self):
        for row in self.rows():
            self.assertEqual(archive.digest(self.root / row["path"]), row["sha"])
            if row["new_path"]:
                self.assertFalse((self.root / row["new_path"]).exists())
        with closing(migration.ro(self.root / "inventory.db")) as a, closing(migration.ro(self.run / "planning.db")) as b:
            self.assertEqual(migration.logical(a), migration.logical(b))
        self.assertIsNone(marker(self.root))

    def test_end_to_end_shared_refs_collision_unrelated_rows_no_sync_duplicates_and_serving(self):
        result = self.ready()
        self.assertEqual(result["decisions"], {"convert": 4, "existing_webp": 1})
        names = [r["new_path"] for r in self.rows() if r["decision"] == "convert"]
        self.assertEqual(len(set(names)), 4)
        final = migration.apply(self.run)
        self.assertEqual(final["removed"], 4)
        self.assertEqual(final["state"], "complete")
        self.assertGreater(final["savings_bytes"], 0)
        self.assertEqual(migration.verify(self.run)["state"], "complete")
        with closing(migration.ro(self.root / "inventory.db")) as db:
            refs = db.execute("SELECT id,file_path,sort_order FROM shoe_photos ORDER BY id").fetchall()
            self.assertEqual(refs[0][1], refs[1][1])
            self.assertEqual([r[2] for r in refs], [8, 9, 12])
        app = create_app(self.config)
        try:
            for _, path, _ in refs:
                response = app.test_client().get("/media/" + path)
                self.assertEqual(response.status_code, 200)
                response.close()
            from app.main import sync_shoe_photos
            with app.app_context(), get_session() as db:
                before = db.query(ShoePhoto).count()
                sync_shoe_photos(db, db.get(Pallet, 1), db.get(Shoe, 1))
                # Unregistered existing WebP + converted PNG can be discovered once,
                # but no deleted original can become a duplicate.
                db.commit()
                after = db.query(ShoePhoto).count()
                sync_shoe_photos(db, db.get(Pallet, 1), db.get(Shoe, 1))
                db.commit()
                self.assertEqual(db.query(ShoePhoto).count(), after)
                self.assertGreaterEqual(after, before)
        finally:
            app.extensions["inventory_db"]["engine"].dispose()
            app.extensions["offline_gate"].close()

    def test_default_plan_is_readonly(self):
        self.plan()
        before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        result = migration.plan(self.root, self.ar)
        self.assertTrue(result["dry_run"])
        self.assertEqual(before, {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()})

    def test_cli_help_does_not_import_app(self):
        result = subprocess.run([sys.executable, "-c", "import sys; import tools.photo_migrate; assert 'app' not in sys.modules"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_database_from_planning_refused_before_claim(self):
        self.plan()
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("UPDATE shoes SET description='changed'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "Database differs"):
            migration.prepare(self.run)
        self.assertIsNone(marker(self.root))

    def test_changed_source_same_fingerprint_hash_refused_persistent(self):
        self.plan()
        path = self.root / "PALETY/P1/S1/a.jpg"
        fp = archive.fingerprint(path)
        path.write_bytes(b"x" * fp[0])
        os.utime(path, ns=(fp[1], fp[1]))
        with self.assertRaisesRegex(ValueError, "Source changed"):
            migration.prepare(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_changed_archive_refused_persistent(self):
        self.plan()
        (self.ar / "originals/PALETY/P1/S1/a.jpg").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "archive hash"):
            migration.prepare(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_corrupt_manifest_refused(self):
        self.plan()
        with closing(sqlite3.connect(self.ar / "manifest.sqlite3")) as db:
            db.execute("UPDATE meta SET value='modified' WHERE key='state'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            migration.prepare(self.run)

    def test_claim_crash_resume_prepare(self):
        self.plan()
        with self.fail("claimed"), self.assertRaises(RuntimeError):
            migration.prepare(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.prepare(self.run)
        migration.apply(self.run)

    def test_encode_crash_resume_prepare(self):
        self.plan()
        with self.fail("encoded"), self.assertRaises(RuntimeError):
            migration.prepare(self.run)
        migration.prepare(self.run)
        migration.apply(self.run)

    def test_published_crash_resume(self):
        self.ready()
        with self.fail("published"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.apply(self.run)

    def test_before_commit_rollback(self):
        self.ready()
        with self.fail("before_db_commit"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        migration.rollback(self.run)
        self.assert_originals()

    def test_after_commit_resume(self):
        self.ready()
        with self.fail("after_db_commit"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        migration.apply(self.run)
        migration.verify(self.run)

    def test_after_removal_resume(self):
        self.ready()
        with self.fail("after_remove"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.apply(self.run)

    def test_after_removal_rollback_restores_exact_sources(self):
        self.ready()
        with self.fail("after_remove"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        migration.rollback(self.run)
        self.assert_originals()

    def test_complete_rollback_and_interrupted_rollback_resume(self):
        self.ready()
        migration.apply(self.run)
        with self.fail("restored"), self.assertRaises(RuntimeError):
            migration.rollback(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.rollback(self.run)
        self.assert_originals()

    def test_archive_disconnect_during_removal_persistent(self):
        self.ready()
        def hook(stage):
            if stage == "before_remove":
                raise OSError("drive disconnected")
        with patch.object(migration, "checkpoint", side_effect=hook), self.assertRaises(OSError):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.rollback(self.run)
        self.assert_originals()

    def test_output_corruption_never_removes_source(self):
        self.ready()
        row = next(r for r in self.rows() if r["decision"] == "convert")
        (self.root / row["new_path"]).write_bytes(b"conflict")
        with self.assertRaisesRegex(ValueError, "collision"):
            migration.apply(self.run)
        self.assertTrue((self.root / row["path"]).is_file())
        self.assertIsNotNone(marker(self.root))

    def test_path_escape_rejected(self):
        for relative in ("../x.jpg", "C:/x.jpg", "/x.jpg", "a//x.jpg", "a/./x.jpg", "a:x.jpg",
                         "a /x.jpg", "a./x.jpg", "CON.jpg", "a?/x.jpg"):
            with self.assertRaises(ValueError):
                migration.source_path(self.root, relative)

    def test_symlink_or_reparse_rejected(self):
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                migration.source_path(self.root, "PALETY/P1/S1/a.jpg")
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaises(ValueError):
                migration.source_path(self.root, "PALETY/P1/S1/a.jpg")

    def test_active_legacy_process_fails_before_claim(self):
        self.plan()
        with patch.object(archive, "worker_pids", return_value=[999]), self.assertRaises(RuntimeError):
            migration.prepare(self.run)
        self.assertIsNone(marker(self.root))

    def test_app_lifetime_os_lock_blocks_migration_and_new_process(self):
        self.plan()
        app = create_app(self.config)
        try:
            with self.assertRaises(RuntimeError):
                migration.prepare(self.run)
            script = "from pathlib import Path; from tools.offline_lock import Gate; Gate(Path(" + repr(str(self.root)) + "))"
            result = subprocess.run([sys.executable, "-c", script], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        finally:
            app.extensions["inventory_db"]["engine"].dispose()
            app.extensions["offline_gate"].close()

    def test_maintenance_blocks_startup_before_db_and_all_requests(self):
        app = create_app(self.config)
        try:
            claim(self.root, self.external)
            with patch("app.init_database") as initialize, self.assertRaises(RuntimeError):
                create_app(self.config)
            initialize.assert_not_called()
            for method, path in (("get", "/health"), ("get", "/login"), ("post", "/login"), ("post", "/shoes/1/photos/sync")):
                self.assertEqual(getattr(app.test_client(), method)(path).status_code, 503)
        finally:
            app.extensions["inventory_db"]["engine"].dispose()
            app.extensions["offline_gate"].close()

    def test_owner_mismatch_refused(self):
        self.plan()
        claim(self.root, self.external)
        with self.assertRaises(RuntimeError):
            migration.prepare(self.run)

    def test_no_space_safe_persistent(self):
        self.plan()
        with patch.object(migration, "reserve", side_effect=RuntimeError("no space")), self.assertRaises(RuntimeError):
            migration.prepare(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.rollback(self.run)
        self.assert_originals()

    def test_no_upscale_orientation_white_metadata_stripped(self):
        source = self.image("orientation.jpg", (40, 80), exif=self.exif())
        target = self.external / "small.webp"
        self.assertEqual(migration.encode(source, target), ("convert", (80, 40)))
        migration.validate_output(target, (80, 40))
        transparent = self.root / "alpha.png"
        Image.new("RGBA", (1000, 700), (0, 0, 0, 0)).save(transparent)
        self.assertEqual(migration.encode(transparent, self.external / "alpha.webp")[0], "convert")
        with Image.open(self.external / "alpha.webp") as image:
            self.assertGreater(min(image.getpixel((10, 10))), 245)

    @staticmethod
    def exif():
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "private synthetic metadata"
        return exif

    def test_max1600_aspect(self):
        source = self.image("large.jpg", (2400, 1200))
        self.assertEqual(migration.encode(source, self.external / "large.webp"), ("convert", (1600, 800)))

    def test_webp_corrupt_animation_and_huge_kept(self):
        target = self.external / "out.webp"
        self.assertEqual(migration.encode(self.root / "PALETY/P1/S1/existing.webp", target)[0], "existing_webp")
        bad = self.root / "bad.jpg"
        bad.write_bytes(b"corrupt")
        self.assertEqual(migration.encode(bad, target)[0], "corrupt")
        animated = self.root / "animated.png"
        Image.new("RGB", (10, 10), "red").save(animated, save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")])
        self.assertEqual(migration.encode(animated, target)[0], "animated")
        with patch.object(migration, "MAX_FILE", 1):
            self.assertEqual(migration.encode(self.root / "PALETY/P1/S1/a.jpg", target)[0], "oversize_bytes")

    def test_not_smaller_keeps_original(self):
        source = self.root / "tiny.png"
        Image.new("RGB", (1, 1)).save(source, optimize=True)
        # Force an output larger than this tiny source while retaining valid decode.
        real = Image.Image.save
        def padded(image, fp, *args, **kwargs):
            real(image, fp, *args, **kwargs)
            with open(fp, "ab") as stream:
                stream.write(b"padding" * 100)
        with patch.object(Image.Image, "save", padded):
            self.assertEqual(migration.encode(source, self.external / "tiny.webp")[0], "not_smaller")

    def test_unrelated_db_change_after_prepare_refused(self):
        self.ready()
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("UPDATE pallets SET notes='outside writer'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "Database changed"):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_extra_photo_blocks_final_release(self):
        self.ready()
        self.image("PALETY/new-unplanned.jpg")
        with self.assertRaisesRegex(ValueError, "Final inventory differs"):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_before_release_crash_resume(self):
        self.ready()
        with self.fail("before_release"), self.assertRaises(RuntimeError):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.apply(self.run)
        self.assertIsNone(marker(self.root))

    def test_changed_source_after_prepare_refused(self):
        self.ready()
        (self.root / "PALETY/P1/S1/a.jpg").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_changed_archive_after_prepare_refused(self):
        self.ready()
        (self.ar / "originals/PALETY/P1/S1/a.jpg").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "archive hash"):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))

    def test_atomic_publish_failure_no_removal(self):
        self.ready()
        with patch.object(migration.os, "link", side_effect=OSError("disconnected")), self.assertRaises(OSError):
            migration.apply(self.run)
        self.assertIsNotNone(marker(self.root))
        migration.rollback(self.run)
        self.assert_originals()

    def test_verify_dryrun_does_not_create_locks_or_write_journal(self):
        self.ready()
        before = archive.digest(self.run / "journal.sqlite3")
        result = subprocess.run([sys.executable, "-m", "tools.photo_migrate", "verify", "--run", str(self.run)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["dry_run"])
        self.assertEqual(archive.digest(self.run / "journal.sqlite3"), before)

    def test_windows_case_alias_updates_every_reference(self):
        if os.name != "nt":
            self.skipTest("Windows case-insensitive filesystem semantics")
        with closing(sqlite3.connect(self.root / "inventory.db")) as db:
            db.execute("UPDATE shoe_photos SET file_path='palety/p1/s1/A.JPG' WHERE id=2")
            db.commit()
        self.ready()
        migration.apply(self.run)
        with closing(migration.ro(self.root / "inventory.db")) as db:
            paths = db.execute("SELECT file_path FROM shoe_photos WHERE id IN (1,2)").fetchall()
        self.assertEqual(paths[0], paths[1])


if __name__ == "__main__":
    unittest.main()
