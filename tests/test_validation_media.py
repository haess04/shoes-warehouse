from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app
from app.database import get_session
from app.media import safe_media_path
from app.models import Pallet, Shoe, ShoePhoto
from app.validation import identifier, money


class ValidationMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app({"TESTING": True, "DATA_ROOT": self.root / "data"})
        self.addCleanup(self.app.extensions["inventory_db"]["engine"].dispose)
        self.client = self.app.test_client()
        with self.app.app_context(), get_session() as session:
            pallet = Pallet(code="BOX_A", delivery_date=date.today(), purchase_gross=100)
            session.add(pallet)
            session.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id="A001", name="Original")
            session.add(shoe)
            session.commit()
            self.pid, self.sid = pallet.id, shoe.id

    def pallet_data(self):
        return dict(code="BOX_B", delivery_date="2026-01-01", purchase_gross="125,50", notes="Keep notes")

    def photo(self, relative="PALETY/BOX_A/A001/1.jpg", registered=False):
        path = self.app.config["DATA_ROOT"] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test image")
        if registered:
            with self.app.app_context(), get_session() as session:
                session.add(ShoePhoto(shoe_id=self.sid, file_path=relative))
                session.commit()
        return path

    def test_money_accepts_comma_and_dot(self):
        for value in ("12,50", "12.50", "0", " 12.50 "):
            with self.subTest(value=value):
                self.assertGreaterEqual(money(value, "Kwota"), 0)
        response = self.client.post("/pallets", data=self.pallet_data())
        self.assertEqual(response.status_code, 302)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(Pallet).filter_by(code="BOX_B").one().purchase_gross, 125.50)

    def test_bad_money_is_rejected_by_all_money_forms(self):
        for value in ("", "-1", "nan", "NaN", "inf", "Infinity", "1e9", "12.345", "1,2,3", "10000000000", "abc"):
            for path, data in (
                ("/pallets", {**self.pallet_data(), "purchase_gross": value}),
                (f"/pallets/{self.pid}/price", {"purchase_gross": value}),
                (f"/shoes/{self.sid}/toggle-status", {"sale_price": value, "sale_date": "2026-01-01"}),
                (f"/shoes/{self.sid}/sale", {"sale_price": value, "sale_date": "2026-01-01"}),
            ):
                with self.subTest(value=value, path=path):
                    response = self.client.post(path, data=data)
                    self.assertEqual(response.status_code, 422)
                    self.assertIn("Nie zapisano zmian", response.get_data(as_text=True))
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(Pallet).count(), 1)
            self.assertEqual(session.get(Pallet, self.pid).purchase_gross, 100)
            self.assertEqual(session.get(Shoe, self.sid).status, "available")

    def test_dates_reject_invalid_and_preserve_input(self):
        for value in ("", "2026-02-30", "2026-1-1", "0000-01-01", "2026-13-01"):
            with self.subTest(value=value):
                data = {**self.pallet_data(), "delivery_date": value}
                response = self.client.post("/pallets", data=data)
                self.assertEqual(response.status_code, 422)
                html = response.get_data(as_text=True)
                self.assertIn('value="BOX_B"', html)
                self.assertIn(f'value="{value}"', html)
                self.assertIn('value="125,50"', html)
                self.assertIn("Keep notes", html)

    def test_multiple_errors_and_missing_fields_do_not_crash(self):
        response = self.client.post("/pallets", data={})
        self.assertEqual(response.status_code, 422)
        html = response.get_data(as_text=True)
        for label in ("Kod palety", "Data dostawy", "Koszt zakupu"):
            self.assertIn(label, html)
        response = self.client.post(f"/pallets/{self.pid}/shoes", data={})
        self.assertEqual(response.status_code, 422)

    def test_duplicate_pallet_preserves_form(self):
        response = self.client.post("/pallets", data={**self.pallet_data(), "code": "BOX_A"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("takim kodzie już istnieje", response.get_data(as_text=True))
        self.assertIn("Keep notes", response.get_data(as_text=True))

    def test_duplicate_shoe_and_edit_preserve_values(self):
        response = self.client.post(f"/pallets/{self.pid}/shoes", data={
            "internal_id": "A001", "name": "Keep name", "description": "Keep description",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn('value="Keep name"', response.get_data(as_text=True))
        response = self.client.post(f"/shoes/{self.sid}/details", data={
            "internal_id": "A002", "name": "", "description": "Keep description",
        })
        self.assertEqual(response.status_code, 422)
        html = response.get_data(as_text=True)
        self.assertIn('value="A002"', html)
        self.assertIn("Keep description", html)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.get(Shoe, self.sid).internal_id, "A001")

    def test_text_limits(self):
        response = self.client.post(f"/pallets/{self.pid}/shoes", data={"internal_id": "A002", "name": "x" * 256})
        self.assertEqual(response.status_code, 422)
        response = self.client.post(f"/pallets/{self.pid}/notes", data={"notes": "x" * 10001})
        self.assertEqual(response.status_code, 422)

    def test_windows_identifiers(self):
        for value in ("../other", "A/B", "A\\B", "C:foo", "CON", "nul.jpg", "COM1", "LPT9", "..", "A.", "A\x00B", "A\nB"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                identifier(value, "ID")
        self.assertEqual(identifier("BOX_ŁÓDŹ-1", "Kod"), "BOX_ŁÓDŹ-1")

    def test_missing_parent_does_not_create_orphan(self):
        response = self.client.post("/pallets/99999/shoes", data={"internal_id": "X001", "name": "Test"})
        self.assertEqual(response.status_code, 404)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(Shoe).count(), 1)

    def test_commit_conflict_rolls_back_and_shows_error(self):
        with self.assertLogs(self.app.logger, level="WARNING"), patch(
            "sqlalchemy.orm.Session.commit", side_effect=IntegrityError("test", {}, Exception("duplicate"))
        ):
            response = self.client.post(f"/shoes/{self.sid}/details", data={"internal_id": "A009", "name": "New name"})
        self.assertEqual(response.status_code, 422)
        self.assertIn('value="New name"', response.get_data(as_text=True))
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.get(Shoe, self.sid).name, "Original")

    def test_sale_errors_do_not_erase_existing_sale(self):
        data = {"sale_price": "123,45", "sale_date": "2026-01-01"}
        self.assertEqual(self.client.post(f"/shoes/{self.sid}/toggle-status", data=data).status_code, 302)
        response = self.client.post(f"/shoes/{self.sid}/sale", data={"sale_price": "99,00", "sale_date": "2026-02-30"})
        self.assertEqual(response.status_code, 422)
        self.assertIn('value="99,00"', response.get_data(as_text=True))
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.get(Shoe, self.sid).sale_price, 123.45)

    def test_success_message_appears_once(self):
        response = self.client.post(f"/pallets/{self.pid}/notes", data={"notes": "Saved"}, follow_redirects=True)
        self.assertIn("Zapisano notatki", response.get_data(as_text=True))
        self.assertNotIn("Zapisano notatki", self.client.get(f"/pallets/{self.pid}").get_data(as_text=True))

    def test_private_files_and_traversal_are_blocked(self):
        self.photo("private.jpg")
        for path in ("inventory.db", ".session-key", "private.jpg", "../private.jpg", "PALETY/../private.jpg",
                     "PALETY/../../private.jpg", "C:/private.jpg", "//server/share/private.jpg",
                     "PALETY/x.jpg:secret", "PALETY/./x.jpg", "PALETY/%2e%2e/private.jpg"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/media/" + path).status_code, 404)
        with self.app.app_context():
            self.assertIsNone(safe_media_path(str(self.app.config["DATABASE_PATH"])))
            self.assertIsNone(safe_media_path("..\\private.jpg"))

    def test_regular_images_can_be_viewed_and_registered(self):
        self.photo()
        response = self.client.get("/media/PALETY/BOX_A/A001/1.jpg")
        self.assertEqual(response.status_code, 200)
        response.close()
        data = {"file_path": "PALETY\\BOX_A\\A001\\1.jpg"}
        self.assertEqual(self.client.post(f"/shoes/{self.sid}/photos", data=data).status_code, 302)
        self.assertEqual(self.client.post(f"/shoes/{self.sid}/photos", data=data).status_code, 422)

    def test_invalid_photo_path_preserved_without_write(self):
        response = self.client.post(f"/shoes/{self.sid}/photos", data={"file_path": "../private.jpg"})
        self.assertEqual(response.status_code, 422)
        self.assertIn('value="../private.jpg"', response.get_data(as_text=True))
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(ShoePhoto).count(), 0)

    def test_only_registered_legacy_images_are_served(self):
        self.photo("BOX_A/A001/1.jpg", registered=True)
        self.photo("BOX_A/A001/2.jpg")
        response = self.client.get("/media/BOX_A/A001/1.jpg")
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get("/media/BOX_A/A001/2.jpg").status_code, 404)

    def test_sync_reports_changes_and_missing_folder(self):
        response = self.client.post(f"/shoes/{self.sid}/photos/sync", follow_redirects=True)
        self.assertIn("Nie znaleziono folderu", response.get_data(as_text=True))
        self.photo()
        response = self.client.post(f"/shoes/{self.sid}/photos/sync", follow_redirects=True)
        self.assertIn("dodano 1", response.get_data(as_text=True))

    def test_sync_failure_rolls_back_and_keeps_old_photos(self):
        self.photo(registered=True)
        with self.assertLogs(self.app.logger, level="ERROR"), patch(
            "pathlib.Path.iterdir", side_effect=PermissionError("test error")
        ):
            response = self.client.post(f"/shoes/{self.sid}/photos/sync")
        self.assertEqual(response.status_code, 422)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(ShoePhoto).count(), 1)

    def test_error_content_is_escaped(self):
        response = self.client.post(f"/pallets/{self.pid}/shoes", data={"internal_id": "", "name": '<script>alert("x")</script>'})
        html = response.get_data(as_text=True)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;script&gt;", html)

    def test_signing_key_is_stable_between_restarts(self):
        other = create_app({"TESTING": True, "DATA_ROOT": self.app.config["DATA_ROOT"]})
        self.addCleanup(other.extensions["inventory_db"]["engine"].dispose)
        self.assertEqual(self.app.secret_key, other.secret_key)

    def test_database_failure_has_safe_error_and_rolls_back(self):
        with self.assertLogs(self.app.logger, level="ERROR"), patch(
            "sqlalchemy.orm.Session.commit", side_effect=OperationalError("private SQL", {}, Exception("locked"))
        ):
            response = self.client.post(f"/pallets/{self.pid}/notes", data={"notes": "New notes"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private SQL", response.get_data(as_text=True))
        with self.app.app_context(), get_session() as session:
            self.assertIsNone(session.get(Pallet, self.pid).notes)

    def test_resolved_path_cannot_escape_media_root(self):
        inside = self.photo()
        outside = self.root / "private.jpg"
        outside.write_bytes(b"private bytes")
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            # Simulate a symlink even on Windows accounts without symlink privileges.
            return outside if path == inside else original(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            self.assertEqual(self.client.get("/media/PALETY/BOX_A/A001/1.jpg").status_code, 404)

    def test_pallet_sync_rolls_back_earlier_additions_on_later_error(self):
        self.photo()
        with self.app.app_context(), get_session() as session:
            session.add(Shoe(pallet_id=self.pid, internal_id="../unsafe", name="Legacy unsafe ID"))
            session.commit()
        response = self.client.post(f"/pallets/{self.pid}/photos/sync-all")
        self.assertEqual(response.status_code, 422)
        with self.app.app_context(), get_session() as session:
            self.assertEqual(session.query(ShoePhoto).count(), 0)

    def test_notes_failure_does_not_clear_other_forms(self):
        response = self.client.post(f"/pallets/{self.pid}/notes", data={"notes": "x" * 10001})
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 422)
        self.assertIn('value="100.00"', html)
        self.assertIn('value="A002"', html)

    def test_confirmation_uses_data_not_inline_javascript(self):
        with self.app.app_context(), get_session() as session:
            session.get(Shoe, self.sid).name = "'); alert('injected'); //"
            session.commit()
        html = self.client.get(f"/shoes/{self.sid}").get_data(as_text=True)
        self.assertNotIn("onsubmit=", html)
        self.assertIn("data-confirm=", html)


if __name__ == "__main__":
    unittest.main()
