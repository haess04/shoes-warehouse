from html.parser import HTMLParser
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from app import create_app
from app.database import get_session
from app.models import Pallet, Shoe


class DetailsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.panels = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "details":
            self.panels[attributes.get("id")] = "open" in attributes


class MaterialUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({"TESTING": True, "DATA_ROOT": self.temp.name})
        self.addCleanup(self.app.extensions["inventory_db"]["engine"].dispose)
        self.client = self.app.test_client()

    def seed_product(self, sold=False):
        with self.app.app_context(), get_session() as session:
            pallet = Pallet(code="BOX_UI", delivery_date=date.today(), purchase_gross=100)
            session.add(pallet)
            session.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id="UI001", name="UI test", status="sold" if sold else "available",
                        sale_price=125 if sold else None, sale_date=date.today() if sold else None)
            session.add(shoe)
            session.commit()
            return pallet.id, shoe.id

    def panels(self, response):
        parser = DetailsParser()
        parser.feed(response.get_data(as_text=True))
        return parser.panels

    def test_pallet_editors_are_collapsed(self):
        pid, _ = self.seed_product()
        panels = self.panels(self.client.get(f"/pallets/{pid}"))
        for panel in ("pallet-notes", "pallet-cost", "new-shoe"):
            self.assertFalse(panels[panel])

    def test_pallet_errors_open_only_matching_form(self):
        pid, _ = self.seed_product()
        cases = (("notes", {"notes": "x" * 10001}, "pallet-notes"),
                 ("price", {"purchase_gross": "bad"}, "pallet-cost"),
                 ("shoes", {"internal_id": "UI001", "name": "Duplicate"}, "new-shoe"))
        for endpoint, data, expected in cases:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(f"/pallets/{pid}/{endpoint}", data=data)
                self.assertEqual(response.status_code, 422)
                panels = self.panels(response)
                self.assertTrue(panels[expected])
                self.assertEqual(sum(panels.values()), 1)

    def test_product_editors_closed_and_sale_visible(self):
        _, sid = self.seed_product()
        response = self.client.get(f"/shoes/{sid}")
        panels = self.panels(response)
        for panel in ("product-edit", "photo-settings", "product-more"):
            self.assertFalse(panels[panel])
        self.assertIn("Oznacz jako sprzedane", response.get_data(as_text=True))

    def test_product_errors_open_only_matching_form(self):
        _, sid = self.seed_product(sold=True)
        cases = (("details", {"internal_id": "UI001", "name": ""}, "product-edit"),
                 ("photos", {"file_path": "../private.jpg"}, "photo-settings"),
                 ("sale", {"sale_price": "bad", "sale_date": "2026-01-01"}, "sale-edit"))
        for endpoint, data, expected in cases:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(f"/shoes/{sid}/{endpoint}", data=data)
                self.assertEqual(response.status_code, 422)
                panels = self.panels(response)
                self.assertTrue(panels[expected])
                self.assertEqual(sum(panels.values()), 1)

    def test_shared_ui_script_is_local_and_available(self):
        self.assertIn('src="/static/app-ui.js"', self.client.get("/").get_data(as_text=True))
        response = self.client.get("/static/app-ui.js")
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_confirmation_dialog_has_explicit_cancel_and_confirm(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('<dialog class="confirm-dialog"', html)
        self.assertIn('aria-describedby="confirm-description"', html)
        self.assertIn('value="cancel" autofocus', html)
        self.assertIn('value="confirm"', html)
        self.assertNotIn('window.confirm', html)

    def test_inspector_empty_states_and_read_only_notice(self):
        html = self.client.get("/db-inspector").get_data(as_text=True)
        for message in ("Tylko podgląd", "Brak zapisanych palet", "Brak zapisanych produktów", "Brak powiązań zdjęć"):
            self.assertIn(message, html)
        self.assertNotIn('method="post"', html)

    def test_inspector_links_records_and_exposes_filter(self):
        pid, sid = self.seed_product()
        html = self.client.get("/db-inspector").get_data(as_text=True)
        self.assertIn(f'href="/pallets/{pid}"', html)
        self.assertIn(f'href="/shoes/{sid}"', html)
        self.assertIn('data-filter-table="table-shoes"', html)

    def test_gallery_dialog_has_navigation_and_error_state(self):
        _, sid = self.seed_product()
        html = self.client.get(f"/shoes/{sid}").get_data(as_text=True)
        self.assertIn('<dialog class="image-lightbox"', html)
        for label in ("Poprzednie zdjęcie", "Następne zdjęcie", "Zamknij podgląd", "Spróbuj ponownie"):
            self.assertIn(label, html)

    def test_missing_page_has_safe_recovery_link(self):
        response = self.client.get("/missing-page-test")
        self.assertEqual(response.status_code, 404)
        html = response.get_data(as_text=True)
        self.assertIn("Powrót do magazynu", html)
        self.assertNotIn("Traceback", html)

    def test_new_pallet_form_closed_by_default(self):
        html = self.client.get("/").get_data(as_text=True)
        parser = DetailsParser()
        parser.feed(html)
        self.assertFalse(parser.panels["new-pallet"])
        self.assertIn('data-open-form="new-pallet"', html)

    def test_invalid_form_opens_and_preserves_values(self):
        response = self.client.post("/pallets", data={"code": "MY_BOX", "purchase_gross": "bad", "notes": "Keep me"})
        parser = DetailsParser()
        html = response.get_data(as_text=True)
        parser.feed(html)
        self.assertEqual(response.status_code, 422)
        self.assertTrue(parser.panels["new-pallet"])
        self.assertIn('value="MY_BOX"', html)
        self.assertIn("Keep me", html)

    def test_skip_link_and_local_icons(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="#main-content"', html)
        self.assertIn('aria-label="Nawigacja główna"', html)
        self.assertIn('<svg class="icon', html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("bg-glow", html)

    def test_important_text_color_pairs_have_aa_contrast(self):
        css = (Path(__file__).resolve().parent.parent / "app/static/styles.css").read_text(encoding="utf-8")
        tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6});", css))

        def luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
            return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))

        pairs = (("on-surface", "surface"), ("on-surface-variant", "surface-container-highest"),
                 ("on-primary", "primary"), ("on-primary-container", "primary-container"),
                 ("on-secondary-container", "secondary-container"), ("error", "error-container"),
                 ("success", "success-container"), ("warning", "warning-container"))
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                low, high = sorted((luminance(tokens[foreground]), luminance(tokens[background])))
                self.assertGreaterEqual((high + 0.05) / (low + 0.05), 4.5)
