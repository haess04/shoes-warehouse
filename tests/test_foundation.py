"""Foundation regression tests. No test opens the real inventory database."""

from contextlib import closing
from datetime import date
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from flask import Flask

from app import create_app
from app.config import PROJECT_ROOT, configure_paths
from app.database import get_session
from app.models import Pallet, Shoe


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.make_app(self.root / "inventory")
        self.client = self.app.test_client()

    def make_app(self, root):
        app = create_app({"TESTING": True, "DATA_ROOT": root, "AUTH_DISABLED": True, "WTF_CSRF_ENABLED": False})
        self.addCleanup(app.extensions["inventory_db"]["engine"].dispose)
        self.addCleanup(app.extensions["offline_gate"].close)
        return app

    def seed(self, app=None):
        with (app or self.app).app_context(), get_session() as session:
            pallet = Pallet(code="PALETA_A", delivery_date=date.today(), purchase_gross=100)
            session.add(pallet)
            session.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id="A001", name="Test shoe")
            session.add(shoe)
            session.commit()
            return pallet.id, shoe.id

    def test_default_paths_do_not_depend_on_working_directory(self):
        app = Flask("config_test")
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            configure_paths(app)
        finally:
            os.chdir(previous)
        self.assertEqual(app.config["DATABASE_PATH"], PROJECT_ROOT / "inventory.db")
        self.assertEqual(app.config["PHOTOS_ROOT"], PROJECT_ROOT / "PALETY")
        self.assertFalse((self.root / "inventory.db").exists())

    def test_testing_requires_separate_storage(self):
        with self.assertRaisesRegex(ValueError, "separate DATA_ROOT"):
            create_app({"TESTING": True})

    def test_both_startup_methods_use_factory_without_starting_server(self):
        for method in ("module", "file"):
            with self.subTest(method=method):
                code = (
                    "from unittest.mock import patch; import runpy; import app; "
                    "from flask import Flask; "
                    "original=app.create_app; "
                    "factory=lambda: original({'TESTING': True, 'DATA_ROOT': "
                    + repr(str(self.root / method)) + "}); "
                    "patch.object(app, 'create_app', factory).start(); "
                    "server=patch.object(Flask, 'run'); mocked=server.start(); "
                    + ("runpy.run_module('app.main', run_name='__main__'); " if method == "module"
                       else "runpy.run_path(" + repr(str(PROJECT_ROOT / "app" / "main.py"))
                       + ", run_name='__main__'); ")
                    + "mocked.assert_called_once(); "
                    "assert mocked.call_args.kwargs['port'] == 5000"
                )
                env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONDONTWRITEBYTECODE="1")
                subprocess.run([sys.executable, "-c", code], cwd=self.root, env=env, check=True)

    def test_static_assets_remain_available(self):
        for path in ("/static/styles.css", "/static/favicon.svg"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_import_has_no_database_or_filesystem_side_effects(self):
        # Fail on any attempted engine initialization, even for an existing DB.
        code = (
            "from unittest.mock import patch; "
            "import pathlib; "
            "a=patch('sqlalchemy.create_engine', side_effect=AssertionError('engine on import')); "
            "b=patch.object(pathlib.Path, 'mkdir', side_effect=AssertionError('mkdir on import')); "
            "a.start(); b.start(); "
            "import app; import app.main; import app.database; import app.models"
        )
        env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([sys.executable, "-c", code], cwd=self.root, env=env, check=True)

    def test_applications_use_independent_databases(self):
        self.seed()
        other = self.make_app(self.root / "other")
        with other.app_context(), get_session() as session:
            self.assertEqual(session.query(Shoe).count(), 0)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(Shoe).count(), 1)

    def test_views_and_redirects_keep_existing_urls(self):
        pallet_id, shoe_id = self.seed()
        for path in ("/health", "/", "/db-inspector", f"/pallets/{pallet_id}", f"/shoes/{shoe_id}"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post(f"/pallets/{pallet_id}/notes", data={"notes": "Saved"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/pallets/{pallet_id}")
        self.assertEqual(self.client.get("/shoes/99999").headers["Location"], "/")

    def test_create_edit_and_sell(self):
        response = self.client.post("/pallets", data={
            "code": "BOX_B", "delivery_date": "2026-01-01", "purchase_gross": "125.50",
        })
        self.assertEqual(response.headers["Location"], "/")
        with self.app.app_context(), get_session() as session:
            pallet_id = session.query(Pallet).one().id
        self.client.post(f"/pallets/{pallet_id}/shoes", data={"internal_id": "B001", "name": "Before"})
        with self.app.app_context(), get_session() as session:
            shoe_id = session.query(Shoe).one().id
        self.client.post(f"/shoes/{shoe_id}/details", data={"internal_id": "B002", "name": "After"})
        response = self.client.post(f"/shoes/{shoe_id}/toggle-status", data={
            "sale_price": "85.50", "sale_date": "2026-01-02",
        })
        self.assertEqual(response.headers["Location"], f"/shoes/{shoe_id}")
        with self.app.app_context(), get_session() as session:
            shoe = session.query(Shoe).one()
            self.assertEqual((shoe.internal_id, shoe.name, shoe.status), ("B002", "After", "sold"))
            self.assertEqual(shoe.sale_price, 85.50)

    def test_photos_work_after_changing_working_directory(self):
        pallet_id, shoe_id = self.seed()
        folder = self.app.config["PHOTOS_ROOT"] / "PALETA_A" / "A001"
        folder.mkdir(parents=True)
        image = b"test image bytes"
        (folder / "1.jpg").write_bytes(image)
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            response = self.client.post(f"/pallets/{pallet_id}/photos/sync-all")
            self.assertEqual(response.status_code, 302)
            response = self.client.get("/media/PALETY/PALETA_A/A001/1.jpg")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, image)
            response.close()
            self.assertIn(b"PALETY/PALETA_A/A001/1.jpg", self.client.get(f"/shoes/{shoe_id}").data)
        finally:
            os.chdir(previous)

    def test_existing_records_survive_reinitialization(self):
        self.seed()
        recreated = self.make_app(self.app.config["DATA_ROOT"])
        with recreated.app_context(), get_session() as session:
            self.assertEqual(session.query(Pallet).one().code, "PALETA_A")
            self.assertEqual(session.query(Shoe).one().internal_id, "A001")

    def test_legacy_sales_columns_are_added_without_losing_data(self):
        root = self.root / "legacy"
        root.mkdir()
        with closing(sqlite3.connect(root / "inventory.db")) as conn:
            with conn:
                conn.execute("CREATE TABLE shoes (id INTEGER PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO shoes VALUES (1, 'Legacy record')")
        self.make_app(root)
        with closing(sqlite3.connect(root / "inventory.db")) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(shoes)")}
            self.assertTrue({"sale_price", "sale_date"}.issubset(columns))
            self.assertEqual(conn.execute("SELECT name FROM shoes").fetchone()[0], "Legacy record")

    def test_failed_transaction_rolls_back(self):
        with self.app.app_context():
            with self.assertRaises(RuntimeError):
                with get_session() as session:
                    session.add(Pallet(code="ROLLBACK", delivery_date=date.today(), purchase_gross=1))
                    session.flush()
                    raise RuntimeError("Simulated failure")
            with get_session() as session:
                self.assertEqual(session.query(Pallet).count(), 0)


if __name__ == "__main__":
    unittest.main()
