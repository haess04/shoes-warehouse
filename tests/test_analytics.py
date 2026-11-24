from datetime import date, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import create_app
from app.analytics import build_sales_analytics, resolve_period, valid_sale_price
from app.database import get_session
from app.models import Pallet, Shoe


def sale(identifier, day, price, status="sold"):
    return SimpleNamespace(id=identifier, sale_date=day, sale_price=price, status=status)


class AnalyticsCalculationTests(unittest.TestCase):
    def test_today_is_snapshot_without_day_to_day_comparison(self):
        period = resolve_period("today", date(2026, 1, 1))
        self.assertEqual((period.start, period.end), (date(2026, 1, 1),) * 2)
        self.assertIsNone(period.previous_start)
        self.assertIsNone(period.previous_end)
        self.assertIsNone(build_sales_analytics([], 'today', date(2026, 1, 1))['comparison'])

    def test_seven_days_are_inclusive_and_previous_does_not_overlap(self):
        today = date(2026, 11, 24)
        period = resolve_period("week", today)
        self.assertEqual((period.end - period.start).days, 6)
        self.assertEqual((period.previous_end - period.previous_start).days, 6)
        self.assertEqual(period.previous_end + timedelta(days=1), period.start)
        records = [sale(i, today - timedelta(days=i), 10) for i in range(15)]
        data = build_sales_analytics(records, "week", today)
        self.assertEqual(data["current"]["count"], 7)
        self.assertEqual(data["previous"]["count"], 7)

    def test_month_compares_same_calendar_day(self):
        period = resolve_period("month", date(2026, 11, 12))
        self.assertEqual((period.start, period.end), (date(2026, 11, 1), date(2026, 11, 12)))
        self.assertEqual((period.previous_start, period.previous_end), (date(2026, 10, 1), date(2026, 10, 12)))

    def test_month_end_clamps_and_handles_leap_year(self):
        for today, expected in ((date(2026, 3, 31), date(2026, 2, 28)),
                                (date(2024, 3, 31), date(2024, 2, 29)),
                                (date(2026, 5, 31), date(2026, 4, 30)),
                                (date(2026, 1, 15), date(2025, 12, 15))):
            with self.subTest(today=today):
                self.assertEqual(resolve_period("month", today).previous_end, expected)

    def test_month_does_not_include_later_days_of_previous_month(self):
        records = [sale(1, date(2026, 11, 10), 100), sale(2, date(2026, 10, 10), 40), sale(3, date(2026, 10, 20), 900)]
        data = build_sales_analytics(records, "month", date(2026, 11, 12))
        self.assertEqual(data["current"]["revenue"], Decimal("100.00"))
        self.assertEqual(data["previous"]["revenue"], Decimal("40.00"))
        self.assertEqual(data["comparison"]["revenue_delta"], Decimal("60.00"))
        self.assertEqual(data["comparison"]["revenue_percent"], Decimal("150"))

    def test_statistics_use_decimal_and_correct_median(self):
        today = date(2026, 11, 24)
        records = [sale(i, today, price) for i, price in enumerate((0.1, 0.2, 10, 30))]
        data = build_sales_analytics(records, "today", today)["current"]
        self.assertEqual(data["revenue"], Decimal("40.30"))
        self.assertEqual(data["average"], Decimal("10.08"))
        self.assertEqual(data["median"], Decimal("5.10"))

    def test_zero_price_is_valid_but_missing_price_is_not_zero(self):
        today = date(2026, 11, 24)
        records = [sale(1, today, 0), sale(2, today, None), sale(3, today, 100)]
        data = build_sales_analytics(records, "today", today)
        self.assertEqual(data["current"]["count"], 3)
        self.assertEqual(data["current"]["priced_count"], 2)
        self.assertEqual(data["current"]["missing_prices"], 1)
        self.assertEqual(data["current"]["average"], Decimal("50.00"))
        self.assertEqual([shoe.id for shoe in data["top_shoes"]], [3, 1])

    def test_invalid_legacy_prices_are_excluded(self):
        for value in (None, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                self.assertIsNone(valid_sale_price(value))
        self.assertEqual(valid_sale_price(12.345), Decimal("12.35"))

    def test_undated_and_future_sales_only_in_all(self):
        today = date(2026, 11, 24)
        records = [sale(1, None, 80), sale(2, today + timedelta(days=1), 90), sale(3, today, 10)]
        current = build_sales_analytics(records, "month", today)
        self.assertEqual(current["current"]["count"], 1)
        self.assertEqual(current["missing_dates"], 1)
        self.assertEqual(current["future_dates"], 1)
        all_time = build_sales_analytics(records, "all", today)
        self.assertEqual(all_time["current"]["revenue"], Decimal("180.00"))
        self.assertIsNone(all_time["previous"])
        self.assertIsNone(all_time["comparison"])

    def test_late_entry_uses_sale_date_not_record_creation_date(self):
        today = date(2026, 11, 24)
        record = sale(1, today - timedelta(days=3), 120)
        record.created_at = today
        self.assertEqual(build_sales_analytics([record], 'today', today)['current']['count'], 0)
        self.assertEqual(build_sales_analytics([record], 'week', today)['current']['count'], 1)

    def test_zero_previous_revenue_has_no_percent(self):
        today = date(2026, 11, 24)
        data = build_sales_analytics([sale(1, today, 100)], "month", today)
        self.assertIsNone(data["comparison"]["revenue_percent"])
        self.assertEqual(data["comparison"]["revenue_delta"], Decimal("100.00"))
        self.assertEqual(data["comparison"]["count_delta"], 1)

    def test_negative_comparison_and_available_records_excluded(self):
        today = date(2026, 11, 24)
        data = build_sales_analytics([sale(1, today, 40), sale(2, today - timedelta(days=7), 100),
                                      sale(3, today, 999, "available")], "week", today)
        self.assertEqual(data["comparison"]["revenue_delta"], Decimal("-60.00"))
        self.assertEqual(data["comparison"]["revenue_percent"], Decimal("-60"))
        self.assertEqual(data["current"]["count"], 1)

    def test_empty_and_invalid_period_are_predictable(self):
        data = build_sales_analytics([], "unexpected", date(2026, 11, 24))
        self.assertEqual(data["period"].key, "month")
        self.assertEqual(data["current"]["revenue"], Decimal("0.00"))
        self.assertIsNone(data["current"]["average"])
        self.assertIsNone(data["current"]["median"])
        self.assertEqual(data["top_shoes"], [])

    def test_top_ten_is_scoped_to_period_and_ties_are_stable(self):
        today = date(2026, 11, 24)
        records = [sale(i, today, i) for i in range(1, 13)] + [sale(99, date(2025, 1, 1), 999)]
        data = build_sales_analytics(records, "today", today)
        self.assertEqual([shoe.id for shoe in data["top_shoes"]], list(range(12, 2, -1)))
        data = build_sales_analytics([sale(1, today, 10), sale(2, today, 10)], "today", today)
        self.assertEqual([shoe.id for shoe in data["top_shoes"]], [2, 1])


class AnalyticsViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({"TESTING": True, "DATA_ROOT": self.temp.name, "AUTH_DISABLED": True, "WTF_CSRF_ENABLED": False})
        self.addCleanup(self.app.extensions["inventory_db"]["engine"].dispose)
        self.client = self.app.test_client()
        self.today = date(2026, 11, 24)
        patcher = patch("app.main.local_today", return_value=self.today)
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.app.app_context(), get_session() as db:
            pallet = Pallet(code="PERIOD_BOX", delivery_date=date(2026, 1, 1), purchase_gross=500)
            db.add(pallet)
            db.flush()
            fixtures = (("NOW", self.today, 125), ("OLD", date(2026, 10, 2), 900), ("UNDATED", None, 50))
            for code, day, price in fixtures:
                db.add(Shoe(pallet_id=pallet.id, internal_id=code, name=f"Analytics {code}", status="sold", sale_date=day, sale_price=price))
            db.commit()

    def test_period_controls_metrics_and_ranking(self):
        html = self.client.get("/?period=today").get_data(as_text=True)
        self.assertIn('data-period="today"', html)
        self.assertIn('id="period-count">1</strong>', html)
        self.assertIn('NOW - Analytics NOW', html)
        self.assertNotIn('OLD - Analytics OLD', html)
        html = self.client.get("/?period=all").get_data(as_text=True)
        self.assertIn('id="period-count">3</strong>', html)
        self.assertIn('OLD - Analytics OLD', html)
        self.assertIn('UNDATED - Analytics UNDATED', html)

    def test_period_links_keep_search_and_search_keeps_period(self):
        html = self.client.get("/?period=week&shoe_q=Analytics").get_data(as_text=True)
        self.assertIn('name="period" value="week"', html)
        self.assertIn('period=all', html)
        self.assertIn('shoe_q=Analytics', html)
        self.assertIn('aria-current="true">Ostatnie 7 dni', html)

    def test_current_inventory_does_not_change_with_period(self):
        for period in ("today", "week", "month", "all"):
            with self.subTest(period=period):
                html = self.client.get(f"/?period={period}").get_data(as_text=True)
                self.assertIn('1075.00 zł', html)
                self.assertIn('Cała historia', html)

    def test_old_all_month_comparison_removed(self):
        html = self.client.get("/?period=month").get_data(as_text=True)
        self.assertIn('01.10.2026 – 24.10.2026', html)
        self.assertIn('01.11.2026 – 24.11.2026', html)
        self.assertNotIn('Miesiąc do miesiąca', html)

    def test_invalid_period_defaults_to_month(self):
        response = self.client.get('/?period=%3Cscript%3E')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-period="month"', response.get_data(as_text=True))

    def test_invalid_pallet_form_preserves_selected_sales_period(self):
        response = self.client.post('/pallets', data={'period': 'week'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('data-period="week"', response.get_data(as_text=True))

    def test_all_warns_about_undated_and_has_no_comparison(self):
        html = self.client.get('/?period=all').get_data(as_text=True)
        self.assertIn('sprzedaży bez daty', html)
        self.assertIn('Całość nie ma poprzedniego okresu', html)


if __name__ == '__main__':
    unittest.main()
