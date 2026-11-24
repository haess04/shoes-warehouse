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


def build_sales_chart(selected, period: SalesPeriod, today: date) -> dict:
    """Calendar buckets with zeros; cap long histories at 36 groups, never truncate."""
    dated = [shoe for shoe in selected if shoe.sale_date is not None]
    undated = [shoe for shoe in selected if shoe.sale_date is None]
    points = []
    stride = 1
    if period.key == "all":
        if dated:
            first = min(shoe.sale_date for shoe in dated).replace(day=1)
            last = max(today, max(shoe.sale_date for shoe in dated)).replace(day=1)
            start_index = first.year * 12 + first.month - 1
            last_index = last.year * 12 + last.month - 1
            months = last_index - start_index + 1
            stride = max(1, (months + 35) // 36)
            for index in range(start_index, last_index + 1, stride):
                end_index = min(index + stride - 1, last_index)
                start = date(index // 12, index % 12 + 1, 1)
                end = date(end_index // 12, end_index % 12 + 1, monthrange(end_index // 12, end_index % 12 + 1)[1])
                points.append({"start": start, "end": end,
                               "label": start.strftime('%m.%Y') if stride == 1 else f"{start:%m.%Y} – {end:%m.%Y}",
                               "short_label": start.strftime('%m.%y')})
        granularity = "Miesiące" if stride == 1 else f"Grupy po maks. {stride} miesięcy"
    else:
        for offset in range((period.end - period.start).days + 1):
            day = period.start + timedelta(days=offset)
            points.append({"start": day, "end": day, "label": day.strftime('%d.%m.%Y'), "short_label": day.strftime('%d.%m')})
        granularity = "Dni według dat sprzedaży"

    # Assign once rather than scanning the entire inventory for every column.
    buckets = [[] for _ in points]
    if points:
        for shoe in dated:
            if period.key == 'all':
                index = (shoe.sale_date.year * 12 + shoe.sale_date.month - 1 - start_index) // stride
            else:
                index = (shoe.sale_date - period.start).days
            buckets[index].append(shoe)
    for point, records in zip(points, buckets):
        summary = summarize_sales(records)
        point.update(revenue=summary['revenue'], count=summary['count'], missing_prices=summary['missing_prices'])
    maximum = max((point['revenue'] for point in points), default=Decimal('0.00'))
    for point in points:
        point['height_percent'] = float(point['revenue'] / maximum * 100) if maximum else 0.0
    return {
        "points": points, "granularity": granularity, "maximum": maximum,
        "revenue": sum((point['revenue'] for point in points), Decimal('0.00')),
        "count": len(dated), "undated_count": len(undated),
        "undated_revenue": summarize_sales(undated)['revenue'],
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
    # The price ranking is intentionally all-time, independent of the period.
    top = sorted((shoe for shoe in sold if valid_sale_price(shoe.sale_price) is not None),
                 key=lambda shoe: (valid_sale_price(shoe.sale_price), shoe.sale_date or date.min, shoe.id),
                 reverse=True)[:10]
    return {
        "period": period, "current": current, "previous": previous, "comparison": comparison,
        "top_shoes": top,
        "top_prices": {shoe.id: valid_sale_price(shoe.sale_price) for shoe in top},
        "chart": build_sales_chart(selected, period, today),
        "missing_dates": sum(shoe.sale_date is None for shoe in sold),
        "future_dates": sum(shoe.sale_date is not None and shoe.sale_date > today for shoe in sold),
    }
