from datetime import date, datetime
import os
import re
import sys
from pathlib import Path

# Allow running both as module: `python -m app.main`
# and as file: `python app/main.py`
if __package__ is None or __package__ == "":
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import case, func, or_
from sqlalchemy.orm import joinedload

from app.database import get_session
from app.models import Pallet, Shoe, ShoePhoto
from app.media import IMAGE_EXTENSIONS, safe_media_path
from app.validation import FormError, calendar_date, form_handler, identifier, money, text
from app.analytics import PERIOD_OPTIONS, build_sales_analytics, valid_sale_price


routes = Blueprint("inventory", __name__)

PALLET_FORM = {
    "code": lambda v: identifier(v, "Kod palety"),
    "delivery_date": lambda v: calendar_date(v, "Data dostawy"),
    "purchase_gross": lambda v: money(v, "Koszt zakupu"),
    "notes": lambda v: text(v, "Notatki", 10000, False),
}
SHOE_FORM = {
    "internal_id": lambda v: identifier(v, "ID buta"),
    "name": lambda v: text(v, "Nazwa", 255),
    "description": lambda v: text(v, "Opis", 10000, False),
}
SALE_FORM = {
    "sale_price": lambda v: money(v, "Cena sprzedaży"),
    "sale_date": lambda v: calendar_date(v, "Data sprzedaży"),
}


def expected_shoe_dir(pallet_code: str, shoe_internal_id: str) -> Path:
    return current_app.config["PHOTOS_ROOT"] / pallet_code / shoe_internal_id


def next_internal_id_for_pallet(pallet_code: str, internal_ids: list[str]) -> str:
    raw_prefix = (pallet_code.split("_")[-1] if "_" in pallet_code else pallet_code).strip()
    prefix = raw_prefix.upper() if raw_prefix else "X"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)

    max_num = 0
    for item in internal_ids:
        match = pattern.match((item or "").strip())
        if match:
            max_num = max(max_num, int(match.group(1)))

    return f"{prefix}{max_num + 1:03d}"


def to_rel_path(path_obj: Path) -> str:
    return path_obj.relative_to(current_app.config["DATA_ROOT"]).as_posix()


def is_supported_image(path_obj: Path) -> bool:
    return path_obj.is_file() and path_obj.suffix.lower() in IMAGE_EXTENSIONS


def sync_shoe_photos(session, pallet: Pallet, shoe: Shoe) -> dict:
    try:
        identifier(pallet.code, "Kod palety")
        identifier(shoe.internal_id, "ID buta")
    except ValueError as exc:
        raise FormError({"_form": str(exc)}) from exc
    folder = expected_shoe_dir(pallet.code, shoe.internal_id)
    if not folder.exists() or not folder.is_dir():
        legacy_folder = current_app.config["DATA_ROOT"] / pallet.code / shoe.internal_id
        if legacy_folder.exists() and legacy_folder.is_dir():
            folder = legacy_folder
        else:
            return {"added": 0, "removed": 0, "missing": 1}

    root = current_app.config["DATA_ROOT"].resolve()
    if not folder.resolve().is_relative_to(root) or folder.resolve() != folder:
        raise FormError({"_form": "Folder zdjęć wychodzi poza dozwolony katalog."})
    disk_photos = sorted([p for p in folder.iterdir()
                          if is_supported_image(p) and p.resolve().is_relative_to(folder.resolve())],
                         key=lambda x: x.name.lower())
    disk_rel_paths = [to_rel_path(p) for p in disk_photos]

    existing = session.query(ShoePhoto).filter(ShoePhoto.shoe_id == shoe.id).all()
    existing_map = {photo.file_path: photo for photo in existing}
    disk_rel_path_set = set(disk_rel_paths)
    added = removed = 0

    for index, rel_path in enumerate(disk_rel_paths):
        if rel_path in existing_map:
            existing_map[rel_path].sort_order = index
        else:
            session.add(ShoePhoto(shoe_id=shoe.id, file_path=rel_path, sort_order=index))
            added += 1

    for old_path, photo in existing_map.items():
        if old_path not in disk_rel_path_set:
            session.delete(photo)
            removed += 1
    return {"added": added, "removed": removed, "missing": 0}


def safe_abs_from_rel(rel_path: str) -> Path | None:
    return safe_media_path(rel_path)


def local_today() -> date:
    return datetime.now().astimezone().date()


@routes.get("/health")
def health():
    return {"status": "ok"}


@routes.get("/media/<path:rel_path>", merge_slashes=False)
def media_file(rel_path: str):
    abs_path = safe_abs_from_rel(rel_path)
    if not abs_path or not abs_path.exists() or not abs_path.is_file():
        abort(404)
    response = send_file(abs_path)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@routes.get("/")
def home():
    shoe_q = request.args.get("shoe_q", "").strip()
    requested_period = request.args.get("period", request.form.get("period", "month"))

    with get_session() as session:
        pallets = session.query(Pallet).order_by(Pallet.id.desc()).all()

        sales_by_pallet = {
            pallet_id: {
                "total_count": total_count,
                "sold_count": sold_count,
                "sold_value": float(sold_value or 0.0),
            }
            for pallet_id, total_count, sold_count, sold_value in (
                session.query(
                    Shoe.pallet_id,
                    func.count(Shoe.id).label("total_count"),
                    func.sum(case((Shoe.status == "sold", 1), else_=0)).label("sold_count"),
                    func.sum(case((Shoe.status == "sold", Shoe.sale_price), else_=0.0)).label("sold_value"),
                )
                .group_by(Shoe.pallet_id)
                .all()
            )
        }

        pallet_returns = {}
        for pallet in pallets:
            sales = sales_by_pallet.get(pallet.id, {"total_count": 0, "sold_count": 0, "sold_value": 0.0})
            purchase_cost = float(pallet.purchase_gross or 0.0)
            sold_value = sales["sold_value"]
            return_percent = (sold_value / purchase_cost * 100.0) if purchase_cost > 0 else 0.0
            pallet_returns[pallet.id] = {
                "total_count": sales["total_count"],
                "sold_count": sales["sold_count"],
                "sold_value": sold_value,
                "return_percent": return_percent,
                "bar_percent": min(return_percent, 100.0),
            }

        all_shoes = (
            session.query(Shoe)
            .options(joinedload(Shoe.pallet))
            .order_by(Shoe.id.desc())
            .all()
        )
        sold_shoes = [shoe for shoe in all_shoes if shoe.status == "sold"]
        available_shoes = [shoe for shoe in all_shoes if shoe.status != "sold"]
        sold_prices = [price for shoe in sold_shoes if (price := valid_sale_price(shoe.sale_price)) is not None]

        total_purchase_cost = sum(float(pallet.purchase_gross or 0.0) for pallet in pallets)
        total_sales_value = float(sum(sold_prices))
        financial_surplus = total_sales_value - total_purchase_cost
        global_return_percent = (
            total_sales_value / total_purchase_cost * 100.0 if total_purchase_cost > 0 else 0.0
        )
        sold_share_percent = len(sold_shoes) / len(all_shoes) * 100.0 if all_shoes else 0.0

        inventory_summary = {
            "total_purchase_cost": total_purchase_cost,
            "total_sales_value": total_sales_value,
            "financial_surplus": financial_surplus,
            "global_return_percent": global_return_percent,
            "total_shoes": len(all_shoes),
            "sold_shoes": len(sold_shoes),
            "available_shoes": len(available_shoes),
            "sold_share_percent": sold_share_percent,
        }

        today = local_today()
        analytics = build_sales_analytics(all_shoes, requested_period, today)
        top_sold_shoes = analytics["top_shoes"]
        month_summary = analytics if analytics["period"].key == "month" else build_sales_analytics(all_shoes, "month", today)
        polish_months = (
            "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
            "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
        )
        monthly_statistics = {
            "current": {"value": month_summary["current"]["revenue"], "count": month_summary["current"]["count"]},
            "current_label": f"{polish_months[today.month - 1]} {today.year}",
        }

        dashboard_shoe_ids = [shoe.id for shoe in top_sold_shoes]
        dashboard_photos = (
            session.query(ShoePhoto)
            .filter(ShoePhoto.shoe_id.in_(dashboard_shoe_ids))
            .order_by(ShoePhoto.sort_order.asc(), ShoePhoto.id.asc())
            .all()
            if dashboard_shoe_ids
            else []
        )
        dashboard_first_photo_by_shoe = {}
        for photo in dashboard_photos:
            dashboard_first_photo_by_shoe.setdefault(photo.shoe_id, photo)

        global_shoes = []
        first_photo_by_shoe = {}
        if shoe_q:
            global_shoes = (
                session.query(Shoe)
                .options(joinedload(Shoe.pallet))
                .join(Pallet)
                .filter(
                    or_(
                        Shoe.internal_id.ilike(f"%{shoe_q}%"),
                        Shoe.name.ilike(f"%{shoe_q}%"),
                        Pallet.code.ilike(f"%{shoe_q}%"),
                    )
                )
                .order_by(Shoe.id.desc())
                .limit(100)
                .all()
            )

            shoe_ids = [s.id for s in global_shoes]
            photos = (
                session.query(ShoePhoto)
                .filter(ShoePhoto.shoe_id.in_(shoe_ids))
                .order_by(ShoePhoto.sort_order.asc(), ShoePhoto.id.asc())
                .all()
                if shoe_ids
                else []
            )

            photos_by_shoe = {}
            for photo in photos:
                photos_by_shoe.setdefault(photo.shoe_id, []).append(photo)

            first_photo_by_shoe = {
                shoe_id: shoe_photos[0] for shoe_id, shoe_photos in photos_by_shoe.items() if shoe_photos
            }

    return render_template(
        "home.html",
        pallets=pallets,
        shoe_q=shoe_q,
        global_shoes=global_shoes,
        first_photo_by_shoe=first_photo_by_shoe,
        pallet_returns=pallet_returns,
        inventory_summary=inventory_summary,
        analytics=analytics,
        period_options=PERIOD_OPTIONS,
        top_sold_shoes=top_sold_shoes,
        dashboard_first_photo_by_shoe=dashboard_first_photo_by_shoe,
        monthly_statistics=monthly_statistics,
    )


@routes.post("/")
def home_post():
    return redirect(url_for("inventory.home"), code=303)


@routes.get("/db-inspector")
def db_inspector():
    with get_session() as session:
        pallets = session.query(Pallet).order_by(Pallet.id.asc()).all()
        shoes = session.query(Shoe).order_by(Shoe.id.asc()).all()
        photos = session.query(ShoePhoto).order_by(ShoePhoto.id.asc()).all()

        stats = {
            "pallets_count": len(pallets),
            "shoes_count": len(shoes),
            "photos_count": len(photos),
            "sold_shoes_count": sum(1 for s in shoes if s.status == "sold"),
            "sold_total": sum((s.sale_price or 0.0) for s in shoes if s.status == "sold"),
        }

    return render_template(
        "db_inspector.html",
        pallets=pallets,
        shoes=shoes,
        photos=photos,
        stats=stats,
    )


@routes.get("/pallets/<int:pallet_id>")
def pallet_detail(pallet_id: int):
    query_text = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all").strip().lower()

    with get_session() as session:
        pallet = session.query(Pallet).filter(Pallet.id == pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        shoes_query = session.query(Shoe).filter(Shoe.pallet_id == pallet_id)
        if status_filter in {"available", "sold"}:
            shoes_query = shoes_query.filter(Shoe.status == status_filter)
        if query_text:
            shoes_query = shoes_query.filter(
                or_(
                    Shoe.internal_id.ilike(f"%{query_text}%"),
                    Shoe.name.ilike(f"%{query_text}%"),
                )
            )

        shoes = shoes_query.order_by(Shoe.id.desc()).all()

        all_shoes_in_pallet = session.query(Shoe).filter(Shoe.pallet_id == pallet_id).all()
        default_internal_id = next_internal_id_for_pallet(
            pallet.code,
            [s.internal_id for s in all_shoes_in_pallet],
        )
        total_shoes_count = len(all_shoes_in_pallet)
        sold_shoes_count = sum(1 for item in all_shoes_in_pallet if item.status == "sold")
        sold_value = sum((item.sale_price or 0.0) for item in all_shoes_in_pallet if item.status == "sold")
        sold_value_label = f"{sold_value:.2f} zł"

        shoe_ids = [s.id for s in shoes]
        photos = (
            session.query(ShoePhoto)
            .filter(ShoePhoto.shoe_id.in_(shoe_ids))
            .order_by(ShoePhoto.sort_order.asc(), ShoePhoto.id.asc())
            .all()
            if shoe_ids
            else []
        )

        photos_by_shoe = {}
        for photo in photos:
            photos_by_shoe.setdefault(photo.shoe_id, []).append(photo)

        first_photo_by_shoe = {
            shoe_id: shoe_photos[0] for shoe_id, shoe_photos in photos_by_shoe.items() if shoe_photos
        }

        expected_dirs = {s.id: str(expected_shoe_dir(pallet.code, s.internal_id)) for s in shoes}

    return render_template(
        "pallet_detail.html",
        pallet=pallet,
        shoes=shoes,
        q=query_text,
        status_filter=status_filter,
        first_photo_by_shoe=first_photo_by_shoe,
        default_internal_id=default_internal_id,
        total_shoes_count=total_shoes_count,
        sold_shoes_count=sold_shoes_count,
        sold_value_label=sold_value_label,
    )


@routes.get("/shoes/<int:shoe_id>")
def shoe_detail(shoe_id: int):
    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        pallet = session.query(Pallet).filter(Pallet.id == shoe.pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        photos = (
            session.query(ShoePhoto)
            .filter(ShoePhoto.shoe_id == shoe.id)
            .order_by(ShoePhoto.sort_order.asc(), ShoePhoto.id.asc())
            .all()
        )

        expected_dir = str(expected_shoe_dir(pallet.code, shoe.internal_id))

    return render_template(
        "shoe_detail.html",
        shoe=shoe,
        pallet=pallet,
        photos=photos,
        expected_dir=expected_dir,
        default_sale_date=local_today().isoformat(),
    )


@routes.post("/pallets")
@form_handler("home", "Dodano paletę.", PALLET_FORM, "code")
def create_pallet():
    code = g.validated["code"]
    delivery_date = g.validated["delivery_date"]
    purchase_gross = g.validated["purchase_gross"]
    notes = g.validated["notes"] or None

    with get_session() as session:
        if session.query(Pallet.id).filter(Pallet.code == code).first():
            raise FormError({"code": "Paleta o takim kodzie już istnieje."})
        pallet = Pallet(
            code=code,
            delivery_date=delivery_date,
            purchase_gross=purchase_gross,
            notes=notes,
        )
        session.add(pallet)
        session.commit()

    return redirect(url_for("inventory.home"))


@routes.post("/pallets/<int:pallet_id>/delete")
@form_handler("pallet_detail", "Usunięto paletę i jej rekordy z bazy. Pliki zdjęć pozostały na dysku.")
def delete_pallet(pallet_id: int):
    with get_session() as session:
        pallet = session.query(Pallet).filter(Pallet.id == pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        session.delete(pallet)
        session.commit()

    return redirect(url_for("inventory.home"))


@routes.post("/pallets/<int:pallet_id>/price")
@form_handler("pallet_detail", "Zapisano koszt zakupu.", {"purchase_gross": PALLET_FORM["purchase_gross"]})
def update_pallet_price(pallet_id: int):
    price = g.validated["purchase_gross"]

    with get_session() as session:
        pallet = session.query(Pallet).filter(Pallet.id == pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        pallet.purchase_gross = price
        session.commit()

    return redirect(url_for("inventory.pallet_detail", pallet_id=pallet_id))


@routes.post("/pallets/<int:pallet_id>/notes")
@form_handler("pallet_detail", "Zapisano notatki.", {"notes": PALLET_FORM["notes"]})
def update_pallet_notes(pallet_id: int):
    notes = g.validated["notes"] or None

    with get_session() as session:
        pallet = session.query(Pallet).filter(Pallet.id == pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        pallet.notes = notes
        session.commit()

    return redirect(url_for("inventory.pallet_detail", pallet_id=pallet_id))


@routes.post("/pallets/<int:pallet_id>/shoes")
@form_handler("pallet_detail", "Dodano buta.", SHOE_FORM, "internal_id")
def create_shoe(pallet_id: int):
    internal_id = g.validated["internal_id"]
    name = g.validated["name"]
    description = g.validated["description"] or None

    with get_session() as session:
        exists = session.query(Shoe).filter(Shoe.internal_id == internal_id).first()
        if exists:
            raise FormError({"internal_id": "But o takim ID już istnieje. Wybierz inny identyfikator."})

        shoe = Shoe(
            pallet_id=pallet_id,
            internal_id=internal_id,
            name=name,
            description=description,
            status="available",
        )
        session.add(shoe)
        session.commit()

    return redirect(url_for("inventory.pallet_detail", pallet_id=pallet_id))


@routes.post("/shoes/<int:shoe_id>/details")
@form_handler("shoe_detail", "Zapisano dane buta.", SHOE_FORM, "internal_id")
def update_shoe_details(shoe_id: int):
    internal_id = g.validated["internal_id"]
    name = g.validated["name"]
    description = g.validated["description"] or None

    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        duplicate = session.query(Shoe).filter(Shoe.internal_id == internal_id, Shoe.id != shoe_id).first()
        if duplicate:
            raise FormError({"internal_id": "But o takim ID już istnieje."})

        shoe.internal_id = internal_id
        shoe.name = name
        shoe.description = description
        session.commit()

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


@routes.post("/pallets/<int:pallet_id>/photos/sync-all")
@form_handler("pallet_detail", "Zakończono synchronizację zdjęć.")
def sync_all_photos_in_pallet(pallet_id: int):
    with get_session() as session:
        pallet = session.query(Pallet).filter(Pallet.id == pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        shoes = session.query(Shoe).filter(Shoe.pallet_id == pallet_id).all()
        totals = {"added": 0, "removed": 0, "missing": 0}
        for shoe in shoes:
            stats = sync_shoe_photos(session, pallet, shoe)
            for key in totals:
                totals[key] += stats[key]

        session.commit()
        g.success_message = (f"Synchronizacja: dodano {totals['added']}, usunięto powiązania {totals['removed']}. "
                             f"Brak folderu dla {totals['missing']} produktów. Plików nie usunięto z dysku.")

    return redirect(url_for("inventory.pallet_detail", pallet_id=pallet_id))


@routes.post("/shoes/<int:shoe_id>/toggle-status")
@form_handler("shoe_detail", "Zmieniono status buta.")
def toggle_shoe_status(shoe_id: int):
    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        if shoe.status == "available":
            from app.validation import read_form

            g.form_fields = SALE_FORM
            values = read_form(SALE_FORM)
            sale_price, sale_date = values["sale_price"], values["sale_date"]

            shoe.status = "sold"
            shoe.sale_price = sale_price
            shoe.sale_date = sale_date
        else:
            shoe.status = "available"
            shoe.sale_price = None
            shoe.sale_date = None

        pallet_id = shoe.pallet_id
        session.commit()

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


@routes.post("/shoes/<int:shoe_id>/sale")
@form_handler("shoe_detail", "Zapisano dane sprzedaży.", SALE_FORM)
def update_shoe_sale_details(shoe_id: int):

    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        if shoe.status != "sold":
            raise FormError({"_form": "Najpierw oznacz buta jako sprzedanego."})

        shoe.sale_price = g.validated["sale_price"]
        shoe.sale_date = g.validated["sale_date"]
        session.commit()

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


@routes.post("/shoes/<int:shoe_id>/delete")
@form_handler("shoe_detail", "Usunięto buta z bazy. Pliki zdjęć pozostały na dysku.")
def delete_shoe(shoe_id: int):
    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        pallet_id = shoe.pallet_id
        session.delete(shoe)
        session.commit()

    return redirect(url_for("inventory.pallet_detail", pallet_id=pallet_id))


@routes.post("/shoes/<int:shoe_id>/photos/sync")
@form_handler("shoe_detail", "Zakończono synchronizację zdjęć.")
def sync_photos_for_shoe(shoe_id: int):
    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        pallet = session.query(Pallet).filter(Pallet.id == shoe.pallet_id).first()
        if not pallet:
            return redirect(url_for("inventory.home"))

        stats = sync_shoe_photos(session, pallet, shoe)
        session.commit()
        g.success_message = ("Nie znaleziono folderu zdjęć. Nic nie zmieniono." if stats["missing"] else
                             f"Zdjęcia: dodano {stats['added']}, usunięto powiązania {stats['removed']}. Plików nie usunięto z dysku.")
        pallet_id = pallet.id

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


@routes.post("/shoes/<int:shoe_id>/photos")
@form_handler("shoe_detail", "Dodano zdjęcie.", {"file_path": lambda v: text(v, "Ścieżka zdjęcia", 1000)})
def add_photo_path(shoe_id: int):
    file_path = g.validated["file_path"].replace("\\", "/")
    if safe_abs_from_rel(file_path) is None:
        raise FormError({"file_path": "Wskaż istniejący obraz w katalogu PALETY. Ścieżki poza magazynem są zabronione."})
    with get_session() as session:
        shoe = session.query(Shoe).filter(Shoe.id == shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        if file_path:
            exists = (
                session.query(ShoePhoto)
                .filter(ShoePhoto.shoe_id == shoe.id, ShoePhoto.file_path == file_path)
                .first()
            )
            if exists:
                raise FormError({"file_path": "To zdjęcie jest już przypisane do buta."})
            if not exists:
                max_order = (
                    session.query(ShoePhoto.sort_order)
                    .filter(ShoePhoto.shoe_id == shoe.id)
                    .order_by(ShoePhoto.sort_order.desc())
                    .first()
                )
                next_order = (max_order[0] + 1) if max_order else 0
                session.add(ShoePhoto(shoe_id=shoe.id, file_path=file_path, sort_order=next_order))
                session.commit()

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


@routes.post("/shoe-photos/<int:photo_id>/delete")
@form_handler("home", "Usunięto powiązanie zdjęcia. Plik pozostał na dysku.")
def delete_photo_path(photo_id: int):
    with get_session() as session:
        photo = session.query(ShoePhoto).filter(ShoePhoto.id == photo_id).first()
        if not photo:
            return redirect(url_for("inventory.home"))

        shoe = session.query(Shoe).filter(Shoe.id == photo.shoe_id).first()
        if not shoe:
            return redirect(url_for("inventory.home"))

        shoe_id = shoe.id
        session.delete(photo)
        session.commit()

    return redirect(url_for("inventory.shoe_detail", shoe_id=shoe_id))


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)

