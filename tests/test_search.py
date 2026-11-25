"""Search regressions using only a temporary, synthetic inventory."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flask import template_rendered

from app import create_app
from app.database import get_session
from app.models import Pallet, Shoe, ShoePhoto


class SearchTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = create_app({
            "TESTING": True, "DATA_ROOT": Path(temp.name),
            "AUTH_DISABLED": True, "WTF_CSRF_ENABLED": False,
        })
        self.addCleanup(self.app.extensions["inventory_db"]["engine"].dispose)
        self.client = self.app.test_client()
        with self.app.app_context(), get_session() as db:
            pallet = Pallet(code="BOX_ALPHA", delivery_date=date(2026, 1, 1), purchase_gross=100)
            other = Pallet(code="BOX_OTHER", delivery_date=date(2026, 1, 1), purchase_gross=100)
            db.add_all([pallet, other])
            db.flush()
            self.pid, self.other_pid = pallet.id, other.id
            records = [
                (pallet.id, "A043", "Pier One buty sztyblety czarne 43", "available"),
                (pallet.id, "A042", "Pier One buty sztyblety czarne 42", "available"),
                (pallet.id, "A000", "Pier One buty sztyblety czarne", "available"),
                (pallet.id, "S043", "Pier One buty sztyblety czarne 43", "sold"),
                (other.id, "O043", "Pier One buty sztyblety czarne 43", "available"),
                (pallet.id, "LITERAL", "Promo 50% under_score bang! path\\end", "available"),
                (pallet.id, "DECOY", "Promo 500 underXscore bang pathXend", "available"),
            ]
            self.ids = {}
            for pallet_id, internal_id, name, status in records:
                shoe = Shoe(pallet_id=pallet_id, internal_id=internal_id, name=name, status=status,
                            description="description-only-token")
                db.add(shoe)
                db.flush()
                self.ids[internal_id] = shoe.id
            db.add_all([
                ShoePhoto(shoe_id=self.ids["A043"], file_path="synthetic/second.jpg", sort_order=2),
                ShoePhoto(shoe_id=self.ids["A043"], file_path="synthetic/first.jpg", sort_order=1),
            ])
            db.commit()

    def search(self, query, *, pallet=False, **params):
        context = {}

        def capture(sender, template, **extra):
            context.update(extra["context"])

        params["q" if pallet else "shoe_q"] = query
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get(f"/pallets/{self.pid}" if pallet else "/", query_string=params)
        self.assertEqual(response.status_code, 200)
        shoes = context["shoes" if pallet else "global_shoes"]
        ids = [shoe.internal_id for shoe in shoes]
        self.assertEqual(len(ids), len(set(ids)), "No duplicate products")
        self.assertEqual([shoe.id for shoe in shoes], sorted((shoe.id for shoe in shoes), reverse=True))
        return ids, context, response.get_data(as_text=True)

    def test_all_words_any_order_and_contiguous_legacy_match(self):
        for pallet in (False, True):
            expected = {"A043", "S043"} if pallet else {"A043", "S043", "O043"}
            for query in ("pier one 43", "43 sztyblety Pier One", "Pier One", "sztyblety czarne 43"):
                with self.subTest(pallet=pallet, query=query):
                    ids, _, _ = self.search(query, pallet=pallet)
                    self.assertEqual(set(ids), expected if query != "Pier One" else expected | {"A042", "A000"})

    def test_missing_terms_excluded_and_numbers_remain_substrings(self):
        for pallet in (False, True):
            self.assertEqual(self.search("pier one 42", pallet=pallet)[0], ["A042"])
            self.assertEqual(self.search("pier one missing", pallet=pallet)[0], [])
            self.assertIn("A043", self.search("ier ne 3", pallet=pallet)[0])

    def test_terms_can_span_global_id_title_and_pallet(self):
        self.assertEqual(self.search("alpha A043 sztyblety")[0], ["A043"])
        self.assertEqual(self.search("sztyblety A043 alpha")[0], ["A043"])

    def test_pallet_fields_and_restrictions(self):
        self.assertEqual(self.search("sztyblety A043", pallet=True)[0], ["A043"])
        self.assertEqual(self.search("alpha sztyblety", pallet=True)[0], [])
        self.assertEqual(self.search("pier one 43", pallet=True, status="available")[0], ["A043"])
        self.assertEqual(self.search("pier one 43", pallet=True, status="sold")[0], ["S043"])
        for pallet in (False, True):
            self.assertEqual(self.search("description-only-token", pallet=pallet)[0], [])

    def test_whitespace_and_duplicate_terms(self):
        for pallet in (False, True):
            expected = self.search("pier one 43", pallet=pallet)[0]
            self.assertEqual(self.search(" \t pier\t one\n43  pier\u2003one \r", pallet=pallet)[0], expected)

    def test_empty_and_whitespace_only_keep_existing_behavior(self):
        for query in ("", " \t\r\n\u2003 "):
            ids, context, _ = self.search(query)
            self.assertEqual(ids, [])
            self.assertEqual(context["shoe_q"], "")
            ids, context, _ = self.search(query, pallet=True)
            self.assertEqual(set(ids), set(self.ids) - {"O043"})
            self.assertEqual(context["q"], "")
            self.assertEqual(self.search(query, pallet=True, status="sold")[0], ["S043"])

    def test_like_wildcards_escape_character_and_backslash_are_literal(self):
        for pallet in (False, True):
            for query in ("%", "under_score", "!", "50% under_score", "bang!", "path\\end"):
                with self.subTest(pallet=pallet, query=query):
                    self.assertEqual(self.search(query, pallet=pallet)[0], ["LITERAL"])
            self.assertEqual(self.search("%' OR 1=1 --", pallet=pallet)[0], [])
        # Global search also sees the literal underscore in every fixture pallet code.
        self.assertEqual(set(self.search("_")[0]), set(self.ids))
        self.assertEqual(self.search("_", pallet=True)[0], ["LITERAL"])

    def test_literal_matching_also_applies_to_id_and_pallet_code(self):
        with self.app.app_context(), get_session() as db:
            db.get(Shoe, self.ids["LITERAL"]).internal_id = "ID%_!"
            db.get(Pallet, self.pid).code = "PAL%_!"
            db.commit()
        for pallet in (False, True):
            self.assertEqual(self.search("ID%_!", pallet=pallet)[0], ["ID%_!"])
        self.assertEqual(set(self.search("PAL%_!")[0]), (set(self.ids) - {"O043", "LITERAL"}) | {"ID%_!"})
        self.assertEqual(self.search("PAL%_!", pallet=True)[0], [])

    def test_photo_selection_and_search_state_are_preserved(self):
        for pallet in (False, True):
            _, context, html = self.search("pier one 43", pallet=pallet, period="week", status="available")
            self.assertEqual(context["first_photo_by_shoe"][self.ids["A043"]].file_path, "synthetic/first.jpg")
            self.assertIn('value="pier one 43"', html)
            if pallet:
                self.assertEqual(context["status_filter"], "available")
                self.assertIn(f'href="/pallets/{self.pid}">Wyczyść', html)
            else:
                self.assertEqual(context["analytics"]["period"].key, "week")
                self.assertIn('name="period" value="week"', html)
                self.assertIn('period=month&amp;shoe_q=pier+one+43#inventory-dashboard', html)
                self.assertIn('href="/?period=week">Wyczyść', html)

    def test_global_limit_and_pallet_unlimited_order_are_preserved(self):
        with self.app.app_context(), get_session() as db:
            db.add_all([Shoe(pallet_id=self.pid, internal_id=f"LIMIT{i:03}", name="limit sample")
                        for i in range(105)])
            db.commit()
        self.assertEqual(self.search("sample limit")[0], [f"LIMIT{i:03}" for i in range(104, 4, -1)])
        self.assertEqual(len(self.search("sample limit", pallet=True)[0]), 105)


if __name__ == "__main__":
    unittest.main()
