"""Optional real-browser UI checks: python tests/browser_smoke.py -v.

Requires Playwright and installed Microsoft Edge (or Playwright Chromium).
Only temporary inventory data is used. Screenshots contain synthetic fixtures.
"""

from datetime import date
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

from app import create_app
from app.database import get_session
from app.models import Pallet, Shoe, ShoePhoto


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class BrowserSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.app = create_app({"TESTING": True, "DATA_ROOT": Path(cls.temp.name)})
        cls.addClassCleanup(cls.app.extensions["inventory_db"]["engine"].dispose)
        folder = cls.app.config["PHOTOS_ROOT"] / "BOX_A" / "A001"
        folder.mkdir(parents=True)
        Image.new("RGB", (640, 480), "#607d72").save(folder / "1.jpg")
        with cls.app.app_context(), get_session() as session:
            pallet = Pallet(code="BOX_A", delivery_date=date(2026, 1, 1), purchase_gross=100)
            session.add(pallet)
            session.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id="A001", name="But demonstracyjny — długa nazwa produktu do sprawdzenia układu",
                        status="sold", sale_price=125.50, sale_date=date.today())
            session.add(shoe)
            session.flush()
            session.add(ShoePhoto(shoe_id=shoe.id, file_path="PALETY/BOX_A/A001/1.jpg"))
            session.add(Pallet(code="BOX_BARDZO_DLUGI_IDENTYFIKATOR_TESTOWY_123456789", delivery_date=date.today(), purchase_gross=999.99))
            session.commit()
            cls.pid, cls.sid = pallet.id, shoe.id
        cls.server = make_server("127.0.0.1", 0, cls.app, request_handler=QuietHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(channel=os.environ.get("UI_BROWSER_CHANNEL", "msedge"), headless=True)
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def test_pages_fit_mobile_tablet_and_desktop(self):
        for width in (320, 390, 768, 1440):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path in ("/", f"/pallets/{self.pid}", f"/shoes/{self.sid}", "/db-inspector"):
                with self.subTest(width=width, path=path):
                    self.assertEqual(self.page.goto(self.url + path).status, 200)
                    overflow = self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                    diagnostics = self.page.evaluate("""() => Array.from(document.querySelectorAll('body *'))
                        .filter(el => el.getBoundingClientRect().right > innerWidth + 1)
                        .slice(0, 15).map(el => [el.tagName, el.className, Math.round(el.getBoundingClientRect().right)])""") if overflow else []
                    self.assertFalse(overflow, f"Horizontal page overflow at {width}: {path}: {diagnostics}")
        self.assertEqual(self.errors, [])

    def test_disclosure_focus_cancel_and_failed_submission(self):
        self.page.goto(self.url)
        panel = self.page.locator("#new-pallet")
        self.assertFalse(panel.evaluate("el => el.open"))
        self.page.get_by_role("link", name="Dodaj paletę", exact=True).click()
        self.assertTrue(panel.evaluate("el => el.open"))
        self.assertEqual(self.page.evaluate("document.activeElement.name"), "code")
        self.page.get_by_role("button", name="Anuluj", exact=True).click()
        self.assertFalse(panel.evaluate("el => el.open"))
        self.assertEqual(self.page.evaluate("document.activeElement.tagName"), "SUMMARY")
        panel.locator("summary").click()
        self.page.locator('[name="code"]').fill("BOX_A")
        self.page.locator('[name="delivery_date"]').fill("2026-01-01")
        self.page.locator('[name="purchase_gross"]').fill("123,45")
        self.page.locator('[name="notes"]').fill("Zachowaj tę notatkę")
        self.page.get_by_role("button", name="Zapisz paletę").click()
        self.page.locator("#form-errors").wait_for()
        self.assertTrue(self.page.locator("#new-pallet").evaluate("el => el.open"))
        self.assertEqual(self.page.locator('[name="notes"]').input_value(), "Zachowaj tę notatkę")
        self.assertEqual(self.page.locator('[name="code"]').get_attribute("aria-invalid"), "true")
        self.assertEqual(self.errors, [])

    def test_nested_delete_button_does_not_trigger_row_navigation(self):
        self.page.goto(self.url)
        self.page.on("dialog", lambda dialog: dialog.dismiss())
        button = self.page.get_by_role("button", name="Usuń paletę BOX_A", exact=True)
        button.focus()
        button.press("Enter")
        self.assertEqual(self.page.url, self.url + "/")
        self.assertTrue(button.is_visible())

    def test_keyboard_skip_link_and_reduced_motion(self):
        self.page.emulate_media(reduced_motion="reduce")
        self.page.goto(self.url)
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.evaluate("document.activeElement.className"), "skip-link")
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "main-content")
        duration = self.page.locator(".btn-primary").first.evaluate("el => getComputedStyle(el).transitionDuration")
        self.assertIn("1e-05s", duration.replace("0.00001s", "1e-05s"))

    def test_no_external_assets_and_screenshots(self):
        external = []
        self.page.on("request", lambda request: external.append(request.url) if request.url.startswith("http") and not request.url.startswith(self.url + "/") else None)
        output = Path(os.environ.get("UI_SCREENSHOT_DIR", ".ui-artifacts"))
        output.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390):
            self.page.set_viewport_size({"width": width, "height": 1000})
            self.page.goto(self.url)
            self.page.screenshot(path=str(output / f"home-{width}.png"), full_page=True)
        self.assertEqual(external, [])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
