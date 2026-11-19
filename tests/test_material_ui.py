from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from app import create_app


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
