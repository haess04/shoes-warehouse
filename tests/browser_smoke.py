"""Optional real-browser UI checks: python tests/browser_smoke.py -v.

Requires Playwright and installed Microsoft Edge (or Playwright Chromium).
Only temporary inventory data is used. Screenshots contain synthetic fixtures.
"""

from datetime import date, timedelta
import os
import secrets
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

from app import create_app
from app.auth import set_owner_password
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
        cls.app = create_app({"TESTING": True, "DATA_ROOT": Path(cls.temp.name), "LOGIN_RATE_LIMIT": 500, "LOGIN_GLOBAL_RATE_LIMIT": 1000})
        cls.password = secrets.token_urlsafe(24)
        with cls.app.app_context():
            set_owner_password(cls.password, initialize=True)
        cls.addClassCleanup(cls.app.extensions["inventory_db"]["engine"].dispose)
        folder = cls.app.config["PHOTOS_ROOT"] / "BOX_A" / "A001"
        folder.mkdir(parents=True)
        Image.new("RGB", (640, 480), "#607d72").save(folder / "1.jpg")
        Image.new("RGB", (480, 640), "#657b9a").save(folder / "2.jpg")
        single = cls.app.config["PHOTOS_ROOT"] / "BOX_A" / "A002"
        single.mkdir(parents=True)
        Image.new("RGB", (320, 240), "#9a7865").save(single / "1.jpg")
        with cls.app.app_context(), get_session() as session:
            pallet = Pallet(code="BOX_A", delivery_date=date(2026, 1, 1), purchase_gross=100)
            session.add(pallet)
            session.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id="A001", name="But demonstracyjny — długa nazwa produktu do sprawdzenia układu",
                        status="sold", sale_price=125.50, sale_date=date.today())
            session.add(shoe)
            session.flush()
            available = Shoe(pallet_id=pallet.id, internal_id="A002", name="Dostępny produkt demonstracyjny")
            session.add(available)
            session.flush()
            session.add(ShoePhoto(shoe_id=shoe.id, file_path="PALETY/BOX_A/A001/1.jpg"))
            session.add(ShoePhoto(shoe_id=shoe.id, file_path="PALETY/BOX_A/A001/2.jpg", sort_order=1))
            session.add(ShoePhoto(shoe_id=available.id, file_path="PALETY/BOX_A/A002/1.jpg"))
            session.add(Pallet(code="BOX_BARDZO_DLUGI_IDENTYFIKATOR_TESTOWY_123456789", delivery_date=date.today(), purchase_gross=999.99))
            session.commit()
            cls.pid, cls.sid = pallet.id, shoe.id
            cls.available_sid = available.id
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
        self.login_page(self.page)

    @classmethod
    def login_page(cls, page):
        page.goto(cls.url + '/login')
        page.get_by_label('Hasło właściciela', exact=True).fill(cls.password)
        page.get_by_role('button', name='Zaloguj się', exact=True).click()
        page.wait_for_url(cls.url + '/')

    def test_pages_fit_mobile_tablet_and_desktop(self):
        for width in (320, 390, 768, 1440, 1920, 2560):
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
        button = self.page.get_by_role("button", name="Usuń paletę BOX_A", exact=True)
        button.focus()
        button.press("Enter")
        self.page.locator("#confirm-dialog").wait_for()
        self.assertEqual(self.page.evaluate("document.activeElement.value"), "cancel")
        self.page.keyboard.press("Escape")
        self.page.wait_for_function("!document.getElementById('confirm-dialog').open")
        self.assertEqual(self.page.url, self.url + "/")
        self.assertTrue(button.is_visible())

    def test_pallet_new_product_form_and_duplicate_error(self):
        self.page.goto(f"{self.url}/pallets/{self.pid}")
        self.assertTrue(self.page.locator("#new-shoe").evaluate("el => el.open"))
        self.page.get_by_role("link", name="Dodaj buta", exact=True).click()
        self.assertEqual(self.page.evaluate("document.activeElement.name"), "internal_id")
        self.page.locator('[name="internal_id"]').fill("A001")
        self.page.locator('[name="name"]').fill("Nie zgub tej nazwy")
        self.page.get_by_role("button", name="Dodaj buta", exact=True).click()
        self.page.locator("#form-errors").wait_for()
        self.assertTrue(self.page.locator("#new-shoe").evaluate("el => el.open"))
        self.assertEqual(self.page.locator('[name="name"]').input_value(), "Nie zgub tej nazwy")
        self.assertFalse(self.page.locator("#pallet-notes").evaluate("el => el.open"))
        self.assertEqual(self.errors, [])

    def test_native_product_form_works_without_javascript(self):
        page = self.browser.new_page(java_script_enabled=False)
        self.addCleanup(page.close)
        self.login_page(page)
        page.goto(f"{self.url}/pallets/{self.pid}")
        self.assertTrue(page.locator('[name="internal_id"]').is_visible())
        page.locator('[name="internal_id"]').fill("A001")
        page.locator('[name="name"]').fill("Dane bez JavaScriptu")
        page.get_by_role("button", name="Dodaj buta", exact=True).click()
        page.locator("#form-errors").wait_for()
        self.assertTrue(page.locator('[name="name"]').is_visible())
        self.assertEqual(page.locator('[name="name"]').input_value(), "Dane bez JavaScriptu")

    def test_sequential_product_additions_need_no_disclosure_click(self):
        self.page.goto(f"{self.url}/pallets/{self.pid}")
        for internal_id in ('BATCH001', 'BATCH002', 'BATCH003'):
            self.assertTrue(self.page.locator('[name="internal_id"]').is_visible())
            self.page.locator('[name="internal_id"]').fill(internal_id)
            self.page.locator('[name="name"]').fill('Kolejna para testowa')
            with self.page.expect_navigation():
                self.page.get_by_role('button', name='Dodaj buta', exact=True).click()
            self.assertTrue(self.page.locator('#new-shoe').evaluate('el => el.open'))
            self.assertTrue(self.page.locator('[name="internal_id"]').is_visible())
        # Remove only this test's fixtures; other browser tests share the pallet.
        with self.app.app_context(), get_session() as db:
            db.query(Shoe).filter(Shoe.internal_id.in_(('BATCH001', 'BATCH002', 'BATCH003'))).delete(synchronize_session=False)
            db.commit()
        self.assertEqual(self.errors, [])

    def test_pallet_product_filter(self):
        self.page.goto(f"{self.url}/pallets/{self.pid}")
        self.page.locator("#pallet-status").select_option("available")
        self.page.get_by_role("button", name="Szukaj", exact=True).click()
        self.page.wait_for_url("**/pallets/*?*")
        self.assertEqual(self.page.locator(".product-list tbody tr").count(), 1)
        self.assertIn("A002", self.page.locator(".product-list").inner_text())

    def test_all_terms_global_search_keeps_period_navigation(self):
        self.page.goto(self.url + '/?period=week')
        self.page.locator('#global-search').fill('BOX_A demonstracyjny A001 A001')
        self.page.get_by_role('button', name='Szukaj', exact=True).click()
        self.page.wait_for_url('**/?*shoe_q=*')
        self.assertEqual(self.page.locator('.search-card .shoes-table tbody tr').count(), 1)
        self.assertIn('A001', self.page.locator('.search-card .shoes-table').inner_text())
        self.assertEqual(self.page.locator('.search-card [name="period"]').input_value(), 'week')
        self.page.get_by_role('link', name='Ten miesiąc', exact=True).click()
        self.assertEqual(self.page.locator('#global-search').input_value(), 'BOX_A demonstracyjny A001 A001')
        self.assertEqual(self.page.locator('.search-card .shoes-table tbody tr').count(), 1)
        self.page.get_by_role('link', name='Wyczyść', exact=True).click()
        self.assertEqual(self.page.locator('#global-search').input_value(), '')
        self.assertIn('period=month', self.page.url)
        self.assertEqual(self.errors, [])

    def test_all_terms_pallet_search_keeps_status(self):
        self.page.goto(f'{self.url}/pallets/{self.pid}')
        self.page.locator('#pallet-search').fill('A002 produkt Dostępny')
        self.page.locator('#pallet-status').select_option('available')
        self.page.get_by_role('button', name='Szukaj', exact=True).click()
        self.page.wait_for_url('**/pallets/*?*')
        self.assertEqual(self.page.locator('.product-list tbody tr').count(), 1)
        self.assertIn('A002', self.page.locator('.product-list').inner_text())
        self.assertEqual(self.page.locator('#pallet-status').input_value(), 'available')
        self.page.locator('#pallet-status').select_option('sold')
        self.page.get_by_role('button', name='Szukaj', exact=True).click()
        self.page.wait_for_url('**status=sold')
        self.assertEqual(self.page.locator('.product-list tbody tr').count(), 0)
        self.assertEqual(self.errors, [])

    def test_sale_editor_error_stays_open(self):
        self.page.goto(f"{self.url}/shoes/{self.sid}")
        self.page.locator("#sale-edit summary").click()
        self.page.locator('#sale-edit [name="sale_price"]').fill("99,999")
        self.page.get_by_role("button", name="Zapisz dane sprzedaży", exact=True).click()
        self.page.locator("#form-errors").wait_for()
        self.assertTrue(self.page.locator("#sale-edit").evaluate("el => el.open"))
        self.assertFalse(self.page.locator("#product-edit").evaluate("el => el.open"))
        self.assertEqual(self.page.locator('#sale-edit [name="sale_price"]').input_value(), "99,999")
        self.assertIn("125.50", self.page.locator(".sale-amount").inner_text())
        self.assertEqual(self.errors, [])

    def test_available_sale_form_on_mobile(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.page.goto(f"{self.url}/shoes/{self.available_sid}")
        self.page.locator('.sale-panel [name="sale_price"]').fill("abc")
        self.page.get_by_role("button", name="Oznacz jako sprzedane", exact=True).click()
        self.page.locator("#form-errors").wait_for()
        self.assertEqual(self.page.locator('.sale-panel [name="sale_price"]').input_value(), "abc")
        self.assertFalse(self.page.locator("#product-edit").evaluate("el => el.open"))
        self.assertEqual(self.errors, [])

    def test_login_logout_and_private_photo(self):
        self.page.get_by_role('button', name='Wyloguj się', exact=True).click()
        self.page.wait_for_url(self.url + '/login')
        self.assertEqual(self.page.goto(self.url + '/media/PALETY/BOX_A/A001/1.jpg').status, 401)
        self.page.goto(self.url + '/db-inspector')
        self.assertTrue(self.page.url.startswith(self.url + '/login?next='), self.page.url)
        self.page.get_by_label('Hasło właściciela', exact=True).fill(self.password)
        self.page.get_by_role('button', name='Zaloguj się', exact=True).click()
        self.page.wait_for_url(self.url + '/db-inspector')
        self.assertIn('Inspektor danych', self.page.locator('h1').inner_text())
        self.assertEqual(self.errors, [])

    def test_login_screen_responsive_and_bad_password_not_echoed(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        output = Path(os.environ.get('UI_SCREENSHOT_DIR', '.ui-artifacts'))
        output.mkdir(parents=True, exist_ok=True)
        for width in (320, 390, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(self.url + '/login')
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'))
            self.assertEqual(page.get_by_role('link', name='Inspektor', exact=True).count(), 0)
            page.screenshot(path=str(output / f'login-{width}.png'), full_page=True)
        page.get_by_label('Hasło właściciela', exact=True).fill('wrong-test-password')
        page.get_by_role('button', name='Zaloguj się', exact=True).click()
        page.get_by_role('alert').wait_for()
        self.assertEqual(page.get_by_label('Hasło właściciela', exact=True).input_value(), '')
        self.assertIn('Nieprawidłowe hasło', page.get_by_role('alert').inner_text())

    def test_browser_write_without_csrf_is_rejected(self):
        status = self.page.evaluate("""async () => (await fetch('/pallets', {
            method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'code=SHOULD_NOT_EXIST&delivery_date=2026-01-01&purchase_gross=1'
        })).status""")
        self.assertEqual(status, 400)
        with self.app.app_context(), get_session() as db:
            self.assertIsNone(db.query(Pallet).filter_by(code='SHOULD_NOT_EXIST').first())

    def clipboard_contents(self):
        return self.page.evaluate('''async () => {
            const items = await navigator.clipboard.read();
            const types = items.flatMap(item => item.types);
            return {types, text: await navigator.clipboard.readText()};
        }''')

    def test_copy_button_writes_code_and_name_as_plain_text(self):
        self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.page.goto(f'{self.url}/shoes/{self.sid}')
        expected = self.page.locator('#product-copy-title').inner_text()
        self.assertTrue(expected.startswith('A001 - '))
        self.page.get_by_role('button', name='Kopiuj do Excela', exact=True).click()
        self.page.wait_for_function("document.querySelector('.copy-status').textContent.includes('Skopiowano')")
        clipboard = self.clipboard_contents()
        self.assertEqual(clipboard['text'], expected)
        self.assertIn('text/plain', clipboard['types'])
        self.assertNotIn('text/html', clipboard['types'])

    def test_ctrl_c_copies_title_without_html_or_extra_rows(self):
        self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.page.goto(f'{self.url}/shoes/{self.sid}')
        expected = self.page.locator('#product-copy-title').inner_text()
        for mode in ('contents', 'node'):
            with self.subTest(selection=mode):
                self.page.locator('#product-copy-title').evaluate('''(el, mode) => {
                    const range = document.createRange();
                    if (mode === 'node') range.selectNode(el); else range.selectNodeContents(el);
                    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
                }''', mode)
                self.page.keyboard.press('Control+c')
                clipboard = self.clipboard_contents()
                self.assertEqual(clipboard['text'], expected)
                self.assertNotIn('text/html', clipboard['types'])
                self.assertNotIn('\n', clipboard['text'])
                self.assertNotIn('\t', clipboard['text'])

    def test_copy_works_without_async_clipboard_for_http_lan(self):
        self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.page.goto(f'{self.url}/shoes/{self.sid}')
        expected = self.page.locator('#product-copy-title').inner_text()
        self.page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true})")
        self.page.get_by_role('button', name='Kopiuj do Excela', exact=True).click()
        self.page.wait_for_function("document.querySelector('.copy-status').textContent.includes('Skopiowano')")
        self.page.evaluate('delete navigator.clipboard')
        clipboard = self.clipboard_contents()
        self.assertEqual(clipboard['text'], expected)
        self.assertNotIn('text/html', clipboard['types'])

    def test_copy_normalizes_tabs_and_line_breaks_only_for_title(self):
        self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.page.goto(f'{self.url}/shoes/{self.sid}')
        self.page.locator('#product-copy-title').evaluate("el => el.textContent = 'A001 - Pull&Bear\\n40\\tczarne   botki'")
        self.page.get_by_role('button', name='Kopiuj do Excela', exact=True).click()
        self.page.wait_for_function("document.querySelector('.copy-status').textContent.includes('Skopiowano')")
        self.assertEqual(self.clipboard_contents()['text'], 'A001 - Pull&Bear 40 czarne botki')

    def test_available_and_sold_badges_have_distinct_colors(self):
        self.page.goto(f'{self.url}/pallets/{self.pid}')
        colors = self.page.evaluate('''() => ['available', 'sold'].map(status => {
            const style = getComputedStyle(document.querySelector(`.badge.${status}`));
            return {background: style.backgroundColor, color: style.color, border: style.borderTopColor};
        })''')
        self.assertNotEqual(colors[0]['background'], colors[1]['background'])
        self.assertNotEqual(colors[0]['border'], colors[1]['border'])
        self.assertNotEqual(colors[0]['color'], colors[1]['color'])

    def test_lightbox_keyboard_and_focus_restoration(self):
        self.page.goto(f"{self.url}/shoes/{self.sid}")
        self.page.locator(".js-gallery-open").first.click()
        self.assertEqual(self.page.locator("#image-lightbox").get_attribute("aria-hidden"), "false")
        self.page.keyboard.press("Tab")
        self.assertTrue(self.page.evaluate("!!document.activeElement.closest('#image-lightbox')"))
        self.page.keyboard.press("Escape")
        self.page.wait_for_function("document.getElementById('image-lightbox').getAttribute('aria-hidden') === 'true'")
        self.assertEqual(self.page.locator("#image-lightbox").get_attribute("aria-hidden"), "true")
        self.assertTrue(self.page.evaluate("document.activeElement.classList.contains('js-gallery-open')"))
        self.assertEqual(self.errors, [])

    def test_mobile_delete_and_restore_require_confirmation(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.page.goto(f"{self.url}/shoes/{self.sid}")
        self.page.get_by_role("button", name="Przywróć dostępność", exact=True).click()
        self.page.locator("#confirm-dialog").wait_for()
        self.assertIn("cena i data", self.page.locator("#confirm-description").inner_text())
        self.page.locator('#confirm-dialog [value="cancel"]').click()
        self.assertTrue(self.page.locator(".sale-amount").is_visible())
        self.page.locator("#product-more summary").click()
        self.page.get_by_role("button", name="Usuń buta", exact=True).click()
        self.page.locator("#confirm-dialog").wait_for()
        self.page.locator('#confirm-dialog [value="cancel"]').click()
        self.assertEqual(self.page.url, f"{self.url}/shoes/{self.sid}")
        self.assertEqual(self.errors, [])

    def test_confirm_dialog_submits_once_only_after_acceptance(self):
        with self.app.app_context(), get_session() as session:
            pallet = Pallet(code="DELETE_DIALOG_TEST", delivery_date=date.today(), purchase_gross=1)
            session.add(pallet)
            session.commit()
            pid = pallet.id
        posts = []
        self.page.on("request", lambda request: posts.append(request.url) if request.method == 'POST' and request.url.endswith(f'/pallets/{pid}/delete') else None)
        self.page.goto(self.url)
        trigger = self.page.get_by_role("button", name="Usuń paletę DELETE_DIALOG_TEST", exact=True)
        trigger.click()
        self.page.locator("#confirm-dialog").wait_for()
        self.page.locator('#confirm-dialog [value="cancel"]').click()
        self.assertEqual(posts, [])
        trigger.click()
        self.page.locator('#confirm-dialog [value="confirm"]').click()
        self.page.wait_for_load_state("load")
        self.page.wait_for_function("!document.getElementById('confirm-dialog').open")
        self.assertEqual(len(posts), 1)
        with self.app.app_context(), get_session() as session:
            self.assertIsNone(session.get(Pallet, pid))

    def test_gallery_navigation_buttons_keyboard_and_swipe(self):
        self.page.goto(f"{self.url}/shoes/{self.sid}")
        self.page.locator(".js-gallery-open").first.click()
        self.assertEqual(self.page.locator(".lightbox-counter").inner_text(), "1 / 2")
        self.page.get_by_role("button", name="Następne zdjęcie", exact=True).click()
        self.assertEqual(self.page.locator(".lightbox-counter").inner_text(), "2 / 2")
        self.page.keyboard.press("ArrowRight")
        self.assertEqual(self.page.locator(".lightbox-counter").inner_text(), "1 / 2")
        stage = self.page.locator(".lightbox-stage")
        stage.dispatch_event("pointerdown", {"pointerType": "touch", "isPrimary": True, "pointerId": 1, "clientX": 250, "clientY": 300})
        stage.dispatch_event("pointerup", {"pointerType": "touch", "isPrimary": True, "pointerId": 1, "clientX": 90, "clientY": 310})
        self.assertEqual(self.page.locator(".lightbox-counter").inner_text(), "2 / 2")
        self.page.keyboard.press("Escape")
        self.page.wait_for_function("!document.getElementById('image-lightbox').open")
        self.assertEqual(self.errors, [])

    def test_gallery_single_image_disables_navigation(self):
        self.page.goto(f"{self.url}/shoes/{self.available_sid}")
        self.page.locator(".js-gallery-open").first.click()
        self.assertTrue(self.page.get_by_role("button", name="Następne zdjęcie", exact=True).is_disabled())
        self.assertTrue(self.page.get_by_role("button", name="Poprzednie zdjęcie", exact=True).is_disabled())
        self.assertEqual(self.page.locator(".lightbox-counter").inner_text(), "1 / 1")

    def test_high_resolution_gallery_keeps_entire_original_in_view(self):
        folder = self.app.config['PHOTOS_ROOT'] / 'BOX_A' / 'A001'
        for name, size in (("fit-portrait", (3000, 4000)), ("fit-landscape", (4800, 3200)), ("fit-small", (240, 180))):
            fixture = Image.new('RGB', size, '#607d72')
            draw = ImageDraw.Draw(fixture)
            draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline='#f5ca63', width=max(4, size[0] // 40))
            fixture.save(folder / f'{name}.jpg')
            for width, height in ((1920, 900), (1440, 900), (390, 700)):
                with self.subTest(image=name, viewport=(width, height)):
                    self.page.set_viewport_size({'width': width, 'height': height})
                    self.page.goto(f'{self.url}/shoes/{self.sid}')
                    source = f'{self.url}/media/PALETY/BOX_A/A001/{name}.jpg'
                    self.page.locator('.js-gallery-open').first.evaluate('''(el, source) => {
                        el.href = el.dataset.src = source;
                        el.querySelector('img').src = source;
                    }''', source)
                    self.page.locator('.js-gallery-open').first.click()
                    self.page.locator('.image-lightbox-image').wait_for(state='visible')
                    geometry = self.page.evaluate('''() => {
                        const image = document.querySelector('.image-lightbox-image');
                        const stage = document.querySelector('.lightbox-stage');
                        const a = image.getBoundingClientRect(), b = stage.getBoundingClientRect();
                        return {src: image.currentSrc, naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
                                x: a.x, y: a.y, right: a.right, bottom: a.bottom, width: a.width, height: a.height,
                                stageX: b.x, stageY: b.y, stageRight: b.right, stageBottom: b.bottom};
                    }''')
                    self.assertEqual(geometry['src'], source)
                    self.assertEqual((geometry['naturalWidth'], geometry['naturalHeight']), size)
                    self.assertGreaterEqual(geometry['x'] + 1, geometry['stageX'])
                    self.assertGreaterEqual(geometry['y'] + 1, geometry['stageY'])
                    self.assertLessEqual(geometry['right'], geometry['stageRight'] + 1)
                    self.assertLessEqual(geometry['bottom'], geometry['stageBottom'] + 1)
                    self.assertLessEqual(geometry['width'], size[0] + 1)
                    self.assertLessEqual(geometry['height'], size[1] + 1)
                    self.assertAlmostEqual(geometry['width'] / geometry['height'], size[0] / size[1], places=2)
                    if width in (1920, 390):
                        output = Path(os.environ.get('UI_SCREENSHOT_DIR', '.ui-artifacts'))
                        output.mkdir(parents=True, exist_ok=True)
                        self.page.screenshot(path=str(output / f'{name}-{width}.png'))
                    if width == 1920:
                        self.page.set_viewport_size({'width': 390, 'height': 700})
                        self.page.wait_for_function('''() => {
                            const a = document.querySelector('.image-lightbox-image').getBoundingClientRect();
                            const b = document.querySelector('.lightbox-stage').getBoundingClientRect();
                            return a.right <= b.right + 1 && a.bottom <= b.bottom + 1 && a.x >= b.x - 1 && a.y >= b.y - 1;
                        }''')

    def test_wide_home_uses_space_for_summary_without_mobile_duplication(self):
        self.page.set_viewport_size({'width': 1920, 'height': 1000})
        self.page.goto(self.url)
        self.assertTrue(self.page.locator('.warehouse-sidebar').is_visible())
        bounds = self.page.locator('main.container').bounding_box()
        self.assertGreater(bounds['width'], 1600)
        self.assertLessEqual(bounds['width'], 1760)
        self.assertGreater(self.page.locator('.warehouse-sidebar').bounding_box()['x'], self.page.locator('.warehouse-main').bounding_box()['x'])
        self.page.set_viewport_size({'width': 390, 'height': 900})
        self.assertFalse(self.page.locator('.warehouse-sidebar').is_visible())
        self.assertTrue(self.page.locator('#inventory-dashboard').is_visible())

    def test_sales_period_updates_kpis_but_not_all_time_ranking_or_inventory(self):
        with self.app.app_context(), get_session() as db:
            record = Shoe(pallet_id=self.pid, internal_id='ANALYTICS_OLD', name='Dawna sprzedaż testowa',
                          status='sold', sale_date=date.today() - timedelta(days=40), sale_price=999)
            db.add(record)
            db.commit()
            sid = record.id
        def cleanup():
            with self.app.app_context(), get_session() as db:
                db.query(Shoe).filter(Shoe.id == sid).delete(synchronize_session=False)
                db.commit()
        self.addCleanup(cleanup)
        self.page.goto(self.url + '/?period=today#inventory-dashboard')
        self.assertEqual(self.page.locator('#period-count').inner_text(), '1')
        self.assertIn('ANALYTICS_OLD', self.page.locator('.top-sales-list').inner_text())
        ranking = self.page.locator('.top-sales-list').inner_text()
        inventory = self.page.locator('.inventory-summary').inner_text()
        self.page.get_by_role('link', name='Całość', exact=True).click()
        self.page.wait_for_url('**/?period=all**')
        self.assertEqual(self.page.locator('#period-count').inner_text(), '2')
        self.assertIn('ANALYTICS_OLD', self.page.locator('.top-sales-list').inner_text())
        self.assertEqual(self.page.locator('.top-sales-list').inner_text(), ranking)
        self.assertEqual(self.page.locator('.inventory-summary').inner_text(), inventory)
        self.assertEqual(self.errors, [])

    def test_period_and_search_state_survive_navigation(self):
        self.page.goto(self.url + '/?period=week&shoe_q=A001#inventory-dashboard')
        self.assertEqual(self.page.locator('.sales-summary').get_attribute('data-period'), 'week')
        self.page.get_by_role('link', name='Całość', exact=True).click()
        self.page.wait_for_url('**/?period=all**')
        self.assertEqual(self.page.locator('#global-search').input_value(), 'A001')
        self.page.locator('#global-search').fill('A002')
        self.page.locator('.search-card').get_by_role('button', name='Szukaj', exact=True).click()
        self.page.wait_for_load_state('load')
        self.assertEqual(self.page.locator('.sales-summary').get_attribute('data-period'), 'all')
        self.assertEqual(self.errors, [])

    def test_chart_point_details_and_accessible_table(self):
        self.page.goto(self.url + '/?period=week#inventory-dashboard')
        self.assertEqual(self.page.locator('[data-chart-point]').count(), 7)
        self.page.locator('[data-chart-point]').last.click()
        self.assertIn('125.50 zł', self.page.locator('[data-chart-output]').inner_text())
        self.page.locator('[data-chart-point]').first.focus()
        self.assertIn('0.00 zł', self.page.locator('[data-chart-output]').inner_text())
        self.page.locator('.chart-table-details > summary').click()
        self.assertEqual(self.page.locator('.chart-data-wrap tbody tr').count(), 7)
        self.assertFalse(self.page.get_by_text('Najstarsze niesprzedane buty', exact=True).count())
        self.assertFalse(self.page.get_by_text('Palety wymagające uwagi', exact=True).count())
        self.assertEqual(self.errors, [])

    def test_chart_scroll_stays_inside_mobile_page(self):
        self.page.set_viewport_size({'width': 390, 'height': 900})
        self.page.goto(self.url + '/?period=month#inventory-dashboard')
        scroll = self.page.locator('.chart-scroll')
        self.assertTrue(scroll.evaluate('el => el.scrollWidth > el.clientWidth'))
        self.page.wait_for_function("document.querySelector('.chart-scroll').scrollLeft > 0")
        scroll.evaluate('el => el.scrollLeft = el.scrollWidth')
        self.assertGreater(scroll.evaluate('el => el.scrollLeft'), 0)
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'))
        self.assertEqual(self.errors, [])

    def test_chart_table_works_without_javascript(self):
        page = self.browser.new_page(java_script_enabled=False)
        self.addCleanup(page.close)
        self.login_page(page)
        page.goto(self.url + '/?period=week#inventory-dashboard')
        page.locator('.chart-table-details > summary').click()
        self.assertTrue(page.locator('.chart-data-wrap').is_visible())
        self.assertEqual(page.locator('.chart-data-wrap tbody tr').count(), 7)

    def test_gallery_load_error_and_retry(self):
        self.page.route("**/media/PALETY/BOX_A/A001/2.jpg", lambda route: route.fulfill(status=404, body="missing"))
        self.page.goto(f"{self.url}/shoes/{self.sid}")
        self.page.locator(".js-gallery-open").nth(1).click()
        self.page.get_by_role("button", name="Spróbuj ponownie", exact=True).wait_for()
        self.assertIn("Nie udało się", self.page.locator(".lightbox-message").inner_text())
        self.page.unroute("**/media/PALETY/BOX_A/A001/2.jpg")
        self.page.get_by_role("button", name="Spróbuj ponownie", exact=True).click()
        self.page.locator(".image-lightbox-image").wait_for(state="visible")
        self.assertEqual(self.errors, [])

    def test_inspector_filter_and_empty_result(self):
        self.page.goto(self.url + "/db-inspector")
        self.page.locator("#filter-shoes").fill("A002")
        self.assertEqual(self.page.locator("#table-shoes tbody tr:visible").count(), 1)
        self.page.locator("#filter-shoes").fill("no_matching_fixture")
        self.assertEqual(self.page.locator("#table-shoes tbody tr:visible").count(), 0)
        self.assertIn("Brak pasujących", self.page.locator('[data-filter-status="table-shoes"]').inner_text())
        self.page.locator("#filter-shoes").fill("")
        self.assertGreaterEqual(self.page.locator("#table-shoes tbody tr:visible").count(), 2)

    def test_dialogs_fit_small_screens(self):
        output = Path(os.environ.get("UI_SCREENSHOT_DIR", ".ui-artifacts"))
        output.mkdir(parents=True, exist_ok=True)
        for width in (320, 390, 768):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 700})
                self.page.goto(self.url)
                self.page.get_by_role("button", name="Usuń paletę BOX_A", exact=True).click()
                dialog = self.page.locator("#confirm-dialog")
                dialog.wait_for()
                self.assertTrue(dialog.evaluate("el => el.matches(':modal')"))
                box = dialog.bounding_box()
                self.assertGreaterEqual(box['x'], 0)
                self.assertLessEqual(box['x'] + box['width'], width + 1)
                self.page.screenshot(path=str(output / f"confirmation-{width}.png"))
                self.page.keyboard.press("Escape")
                self.page.goto(f"{self.url}/shoes/{self.sid}")
                self.page.locator(".js-gallery-open").first.click()
                self.page.locator(".image-lightbox-image").wait_for(state="visible")
                self.assertTrue(self.page.locator("#image-lightbox").evaluate("el => el.matches(':modal')"))
                for selector in (".image-lightbox-close", ".image-lightbox-next", ".image-lightbox-prev"):
                    box = self.page.locator(selector).bounding_box()
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['y'] + box['height'], 701)
                self.page.screenshot(path=str(output / f"gallery-{width}.png"))
                self.page.keyboard.press("Escape")
        self.assertEqual(self.errors, [])

    def test_destructive_buttons_hidden_without_javascript(self):
        page = self.browser.new_page(java_script_enabled=False)
        self.addCleanup(page.close)
        self.login_page(page)
        page.goto(self.url)
        self.assertFalse(page.locator('form[data-confirm] button').first.is_visible())
        self.assertIn("włączonego JavaScriptu", page.locator('noscript').inner_text())

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
        for width in (1920, 1440, 390):
            self.page.set_viewport_size({"width": width, "height": 1000})
            for name, path in (("home", "/"), ("pallet", f"/pallets/{self.pid}"), ("shoe", f"/shoes/{self.sid}"), ("inspector", "/db-inspector")):
                self.page.goto(self.url + path)
                self.page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)
        self.assertEqual(external, [])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
