"""Only synthetic images and standalone temporary SQLite databases are used."""

import hashlib
from contextlib import closing
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from tools import photo_storage as storage


class PhotoStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "data"
        self.root.mkdir()
        self.private = self.base / ".photo-audit"
        self.patch = patch.object(storage, "PRIVATE", self.private)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def image(self, relative="PALETY/BOX/ITEM/photo.jpg", size=(240, 120), **options):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", size, "red")
        image.save(path, **options)
        image.close()
        return path

    def database(self, paths):
        path = self.root / "inventory.db"
        with closing(sqlite3.connect(path)) as db:
            db.executescript("CREATE TABLE pallets(id INTEGER, code TEXT);"
                             "CREATE TABLE shoes(id INTEGER, pallet_id INTEGER, internal_id TEXT);"
                             "CREATE TABLE shoe_photos(shoe_id INTEGER, file_path TEXT);"
                             "INSERT INTO pallets VALUES(1, 'BOX');"
                             "INSERT INTO shoes VALUES(1, 1, 'ITEM');")
            db.executemany("INSERT INTO shoe_photos VALUES(1, ?)", [(p,) for p in paths])
            db.commit()
        return path

    def fingerprint(self):
        return {p.relative_to(self.root).as_posix():
                (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in self.root.rglob("*") if p.is_file()}

    def test_empty_root_never_creates_database_or_auth(self):
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["count"], 0)
        self.assertEqual(report["database"], "missing")
        self.assertFalse(report["normal_root_exists"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_root_refused(self):
        with self.assertRaises(ValueError):
            storage.audit(self.root / "missing")

    def test_normal_and_registered_legacy_deduplicated_readonly(self):
        self.image()
        self.image("BOX/ITEM/legacy.png")
        self.image("OTHER/ITEM/unregistered.jpg")
        self.database(["PALETY/BOX/ITEM/photo.jpg", "BOX/ITEM/legacy.png"])
        before = self.fingerprint()
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["count"], 2)
        self.assertEqual(report["summary"]["legacy_count"], 1)
        self.assertEqual(report["registered_rows"], 2)
        self.assertEqual(before, self.fingerprint())

    def test_legacy_without_normal_root(self):
        self.image("BOX/ITEM/legacy.jpg")
        self.database(["BOX/ITEM/legacy.jpg"])
        report = storage.audit(self.root)
        self.assertFalse(report["normal_root_exists"])
        self.assertEqual(report["summary"]["legacy_count"], 1)

    def test_unregistered_images_in_known_legacy_folder_are_counted(self):
        self.image("BOX/ITEM/not-yet-synced.jpg")
        self.image("OTHER/ITEM/not-known.jpg")
        self.database([])
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["legacy_count"], 1)
        self.assertEqual(report["legacy_folders_checked"], 1)
        self.assertEqual(report["legacy_folders_found"], 1)
        self.assertEqual(report["registered_rows"], 0)

    def test_rollback_journal_refused_without_side_effects(self):
        self.database([])
        (self.root / "inventory.db-journal").write_bytes(b"placeholder")
        before = self.fingerprint()
        self.assertEqual(storage.audit(self.root)["database"], "failed")
        self.assertEqual(before, self.fingerprint())

    def test_header_audit_does_not_load_pixels(self):
        path = self.image()
        with patch.object(Image.Image, "load", side_effect=AssertionError("No pixel load")):
            report = storage.audit(self.root)
        self.assertEqual(report["files"][0]["width"], 240)
        self.assertEqual(report["summary"]["bytes"], path.stat().st_size)

    def test_invalid_registered_paths_and_missing_reported(self):
        self.database(["../outside.jpg", "C:/outside.jpg", "/outside.jpg", "BOX/WRONG/photo.jpg",
                       "BOX/ITEM/missing.jpg", "BOX//ITEM/x.jpg", "BOX/ITEM/a.txt"])
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["count"], 0)
        self.assertEqual(len(report["errors"]), 7)

    def test_corrupt_header_counted_and_skipped(self):
        path = self.image()
        path.write_bytes(b"not an image")
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["header_failures"], 1)
        self.assertEqual(storage.select_sample(report["files"], 36), [])

    def test_wal_refused_without_creation_or_modification(self):
        self.database([])
        (self.root / "inventory.db-wal").write_bytes(b"placeholder")
        before = self.fingerprint()
        report = storage.audit(self.root)
        self.assertEqual(report["database"], "failed")
        self.assertEqual(before, self.fingerprint())

    def test_bad_database_reports_failure(self):
        (self.root / "inventory.db").write_bytes(b"bad database")
        self.assertEqual(storage.audit(self.root)["database"], "failed")

    def test_symlink_rejected(self):
        target = self.image()
        link = target.with_name("link.jpg")
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        report = storage.audit(self.root)
        self.assertEqual(report["summary"]["count"], 1)
        self.assertTrue(report["errors"])

    def test_link_components_refused_even_when_resolving_inside(self):
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                storage.source_path(self.root, "BOX/ITEM/a.jpg")

    def test_junction_components_refused(self):
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaises(ValueError):
                storage.no_links(self.root)

    def test_run_name_overwrite_and_traversal_refused(self):
        storage.new_run("safe", self.root)
        with self.assertRaises(FileExistsError):
            storage.new_run("safe", self.root)
        for name in ("../bad", "a/b", "", ".", "C:bad"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                storage.new_run(name, self.root)

    def test_output_inside_normal_or_legacy_scope_refused(self):
        for relative in ("PALETY/.photo-audit", "BOX/ITEM/.photo-audit"):
            with patch.object(storage, "PRIVATE", self.root / relative):
                with self.assertRaises(ValueError):
                    storage.new_run("safe", self.root)

    def test_free_space_checked_before_creating_output(self):
        with patch.object(shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10, 9, 1)):
            with self.assertRaises(ValueError):
                storage.new_run("no-space", self.root)
        self.assertFalse(self.private.exists())

    def test_atomic_new_does_not_overwrite_and_cleans_own_temporary(self):
        path = self.base / "result"
        storage.atomic_new(path, b"first")
        with self.assertRaises(FileExistsError):
            storage.atomic_new(path, b"second")
        self.assertEqual(path.read_bytes(), b"first")
        self.assertEqual(list(self.base.glob(".writing-*")), [])

    def test_samples_orientation_no_upscale_no_metadata_sources_unchanged(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "private owner"
        exif[34853] = {1: "N", 2: (50.0, 0.0, 0.0)}
        self.image(exif=exif)
        self.database(["PALETY/BOX/ITEM/photo.jpg"])
        before = self.fingerprint()
        report = storage.audit(self.root)
        run = storage.new_run("orientation", self.root)
        samples = storage.compress_samples(report, run, 1)
        self.assertEqual(samples["completed"], 1)
        self.assertEqual(len(samples["outputs"]), 6)
        for output in samples["outputs"]:
            with Image.open(run / output["file"]) as image:
                self.assertEqual(image.size, (120, 240))
                self.assertEqual(dict(image.getexif()), {})
                self.assertFalse(any(k in image.info for k in ("exif", "icc_profile", "xmp")))
        self.assertEqual(before, self.fingerprint())

    def test_resize_preserves_aspect(self):
        self.image(size=(2400, 1200))
        report = storage.audit(self.root)
        samples = storage.compress_samples(report, storage.new_run("resize", self.root), 1)
        sizes = {(o["width"], o["height"]) for o in samples["outputs"]}
        self.assertEqual(sizes, {(2400, 1200), (1600, 800), (2000, 1000)})

    def test_transparency_composited_on_white(self):
        path = self.root / "PALETY/BOX/ITEM/alpha.png"
        path.parent.mkdir(parents=True)
        with Image.new("RGBA", (20, 10), (0, 0, 0, 0)) as image:
            image.save(path)
        samples = storage.compress_samples(storage.audit(self.root), storage.new_run("alpha", self.root), 1)
        with Image.open(self.private / "alpha" / samples["outputs"][0]["file"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_count_and_output_budget_enforced(self):
        self.image()
        report = storage.audit(self.root)
        run = storage.new_run("budget", self.root)
        for count in (0, 49):
            with self.assertRaises(ValueError):
                storage.compress_samples(report, run, count)
        samples = storage.compress_samples(report, run, 1, budget=1)
        self.assertEqual(samples["bytes_written"], 0)
        self.assertTrue(samples["stopped"])
        self.assertEqual(list(run.iterdir()), [])

    def test_changed_source_is_not_sampled(self):
        path = self.image()
        report = storage.audit(self.root)
        path.write_bytes(b"changed")
        samples = storage.compress_samples(report, storage.new_run("changed", self.root), 1)
        self.assertEqual(samples["outputs"], [])
        self.assertEqual(len(samples["errors"]), 1)

    def test_selection_deterministic_and_skips_oversize_animation(self):
        records = [{"path": str(n), "extension": ".jpg", "bytes": n + 1,
                    "width": 200, "height": 100} for n in range(100)]
        records += [{"path": "huge", "extension": ".png", "bytes": 2,
                     "width": 10000, "height": 10000},
                    {"path": "animated", "extension": ".webp", "bytes": 2,
                     "width": 100, "height": 100, "frames": 2}]
        selected = storage.select_sample(records, 36)
        self.assertEqual(len(selected), 36)
        self.assertEqual(selected, storage.select_sample(list(reversed(records)), 36))
        self.assertTrue(all(r["path"] not in {"huge", "animated"} for r in selected))

    def test_private_report_gallery_and_measured_summary(self):
        self.image()
        report = storage.audit(self.root)
        run = storage.new_run("report", self.root)
        report["samples"] = storage.compress_samples(report, run, 1)
        report["comparison"] = storage.comparison_summary(report["samples"])
        storage.save_report(run, report)
        self.assertEqual(json.loads((run / "report.json").read_text())["summary"], report["summary"])
        self.assertIn("Original (local only)", (run / "comparison.html").read_text())
        self.assertEqual(len(report["comparison"]), 6)
        for variant in report["comparison"].values():
            self.assertEqual(variant["count"], 1)

    def test_selection_covers_rare_formats_without_overweighting_them(self):
        records = [{"path": f"jpeg-{n}", "extension": ".jpg", "bytes": n + 1,
                    "width": 4000, "height": 3000} for n in range(1000)]
        records += [{"path": f"png-{n}", "extension": ".png", "bytes": n + 1,
                     "width": 400, "height": 300} for n in range(3)]
        records += [{"path": f"webp-{n}", "extension": ".webp", "bytes": n + 1,
                     "width": 400, "height": 300} for n in range(25)]
        selected = storage.select_sample(records, 36)
        self.assertGreaterEqual(sum(r["extension"] == ".jpg" for r in selected), 33)
        self.assertEqual({r["extension"] for r in selected}, {".jpg", ".png", ".webp"})

    def test_case_collisions_and_non_sync_depth_reported(self):
        self.image("PALETY/Box/ITEM/one.jpg")
        self.image("PALETY/BOX/ITEM/two.jpg")
        self.image("PALETY/outside.jpg")
        report = storage.audit(self.root)
        # Windows merges case-only directories; Linux keeps both. Either way,
        # registered-case checks below cover the portability mismatch.
        self.assertEqual(report["summary"]["count"], 3)
        self.assertTrue(any(r["kind"] == "outside_sync_depth" for r in report["portability_warnings"]))
        names = [p.name for p in (self.root / "PALETY").iterdir()]
        if "BOX" in names and "Box" in names:
            self.assertTrue(report["case_collisions"])

    def test_registered_case_mismatch_is_flagged_on_windows(self):
        path = self.image("BOX/ITEM/Upper.jpg")
        self.database(["BOX/ITEM/upper.jpg"])
        report = storage.audit(self.root)
        if path.with_name("upper.jpg").exists():
            self.assertTrue(any(r["kind"] == "registered_case_mismatch"
                                for r in report["portability_warnings"]))
            self.assertEqual(report["summary"]["count"], 1)
        else:
            self.assertTrue(report["errors"])

    def test_cli_audit_sample_report_modes(self):
        self.image()
        before = self.fingerprint()
        for mode, name in (("audit", "audit-cli"), ("sample", "sample-cli"), ("report", "sample-cli")):
            output = io.StringIO()
            args = ["photo_storage.py", mode, "--run", name, "--data-root", str(self.root), "--count", "1"]
            with patch.object(sys, "argv", args), redirect_stdout(output):
                storage.main()
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["summary"]["count"], 1)
            self.assertNotIn(str(self.root), output.getvalue())
        self.assertEqual(before, self.fingerprint())

    def test_cli_invalid_count_refuses_before_output(self):
        with patch.object(sys, "argv", ["photo_storage.py", "sample", "--run", "bad", "--count", "49"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                storage.main()
        self.assertFalse(self.private.exists())


if __name__ == "__main__":
    unittest.main()
