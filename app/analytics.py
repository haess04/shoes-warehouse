"""Read-only sales calculations shared by the dashboard, ranking and comparisons."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median


PERIOD_OPTIONS = (("today", "Dziś"), ("week", "Ostatnie 7 dni"), ("month", "Ten miesiąc"), ("all", "Całość"))
CENT = Decimal("0.01")


@dataclass(frozen=True)
class SalesPeriod:
    key: str
    label: str
    start: date | None
    end: date | None
    previous_start: date | None
    previous_end: date | None
    comparison_label: str | None


def resolve_period(key: str, today: date) -> SalesPeriod:
    labels = dict(PERIOD_OPTIONS)
    key = key if key in labels else "month"
    if key == "all":
        return SalesPeriod(key, labels[key], None, None, None, None, None)
    if key == "today":
        # Batch entry makes day-to-day changes misleading; today is a snapshot.
        return SalesPeriod(key, labels[key], today, today, None, None, None)
    if key == "week":
        return SalesPeriod(key, labels[key], today - timedelta(days=6), today,
                           today - timedelta(days=13), today - timedelta(days=7), "Poprzednie 7 dni")
    previous_last = today.replace(day=1) - timedelta(days=1)
    previous_end = previous_last.replace(day=min(today.day, monthrange(previous_last.year, previous_last.month)[1]))
    return SalesPeriod(key, labels[key], today.replace(day=1), today,
                       previous_last.replace(day=1), previous_end, "Analogiczny zakres poprzedniego miesiąca")


def valid_sale_price(value) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            return None
        return result.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def summarize_sales(shoes) -> dict:
    prices = [price for shoe in shoes if (price := valid_sale_price(shoe.sale_price)) is not None]
    revenue = sum(prices, Decimal("0.00"))
    return {
        "count": len(shoes),
        "priced_count": len(prices),
        "missing_prices": len(shoes) - len(prices),
        "revenue": revenue,
        "average": (revenue / len(prices)).quantize(CENT, rounding=ROUND_HALF_UP) if prices else None,
        "median": median(prices).quantize(CENT, rounding=ROUND_HALF_UP) if prices else None,
        "minimum": min(prices) if prices else None,
        "maximum": max(prices) if prices else None,
    }


def build_sales_analytics(shoes, key: str, today: date) -> dict:
    period = resolve_period(key, today)
    sold = [shoe for shoe in shoes if shoe.status == "sold"]

    def in_range(start, end):
        return [shoe for shoe in sold if shoe.sale_date is not None and start <= shoe.sale_date <= end]

    # "All" includes every recorded sale, including legacy records without dates.
    # Date-based periods never silently assign an undated sale to today's date.
    selected = sold if period.key == "all" else in_range(period.start, period.end)
    current = summarize_sales(selected)
    previous = summarize_sales(in_range(period.previous_start, period.previous_end)) if period.previous_start else None
    comparison = None
    if previous is not None:
        delta = current["revenue"] - previous["revenue"]
        comparison = {
            "revenue_delta": delta,
            "count_delta": current["count"] - previous["count"],
            "revenue_percent": delta / previous["revenue"] * 100 if previous["revenue"] > 0 else None,
        }
    top = sorted((shoe for shoe in selected if valid_sale_price(shoe.sale_price) is not None),
                 key=lambda shoe: (valid_sale_price(shoe.sale_price), shoe.sale_date or date.min, shoe.id),
                 reverse=True)[:10]
    return {
        "period": period, "current": current, "previous": previous, "comparison": comparison,
        "top_shoes": top,
        "missing_dates": sum(shoe.sale_date is None for shoe in sold),
        "future_dates": sum(shoe.sale_date is not None and shoe.sale_date > today for shoe in sold),
    }
