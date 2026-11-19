"""Shared validation and form error handling (no writes on invalid input)."""

from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps
import re

from flask import abort, current_app, flash, g, render_template, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class FormError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


def text(value, label, maximum, required=True):
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label}: uzupełnij to pole.")
    if len(value) > maximum:
        raise ValueError(f"{label}: maksymalnie {maximum} znaków.")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{label}: niedozwolone znaki sterujące.")
    return value


def identifier(value, label):
    value = text(value, label, 100)
    # Safe Windows directory components; preserve Unicode and spaces inside names.
    if (value in {".", ".."} or value.endswith((".", " "))
            or any(c in value for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in value)
            or value.split(".")[0].upper() in {
                "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                *(f"COM{i}" for i in "123456789¹²³"), *(f"LPT{i}" for i in "123456789¹²³"),
            }):
        raise ValueError(f"{label}: niedozwolona nazwa katalogu. Nie używaj separatorów ani znaków specjalnych Windows.")
    return value


def money(value, label):
    value = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        raise ValueError(f"{label}: podaj nieujemną kwotę, maksymalnie dwa miejsca po przecinku.")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{label}: niepoprawna kwota.") from None
    if not amount.is_finite() or amount > Decimal("9999999999.99"):
        raise ValueError(f"{label}: kwota jest zbyt duża.")
    return float(amount)  # Existing schema stays unchanged in this batch.


def calendar_date(value, label):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label}: podaj datę w formacie RRRR-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}: taka data nie istnieje.") from None


def read_form(spec):
    values, errors = {}, {}
    for field, parser in spec.items():
        try:
            values[field] = parser(request.form.get(field, ""))
        except ValueError as exc:
            errors[field] = str(exc)
    if errors:
        raise FormError(errors)
    return values


def form_value(field, default=""):
    if getattr(g, "form_errors", None) and field in getattr(g, "form_fields", {}):
        return request.form.get(field, "")
    return default


def form_handler(view, success, spec=None, conflict_field=None):
    """Re-render the correct GET view on failure; keep submitted data out of cookies."""
    def decorate(function):
        @wraps(function)
        def wrapped(**kwargs):
            from app.database import get_session
            from app.models import Pallet, Shoe, ShoePhoto

            # Missing parents/records must never create orphaned rows.
            with get_session() as session:
                for key, model in (("pallet_id", Pallet), ("shoe_id", Shoe), ("photo_id", ShoePhoto)):
                    if key in kwargs and session.get(model, kwargs[key]) is None:
                        abort(404)
            try:
                g.form_fields = spec or {}
                g.validated = read_form(spec or {})
                result = function(**kwargs)
            except (FormError, IntegrityError, OSError) as exc:
                if isinstance(exc, FormError):
                    g.form_errors = exc.errors
                elif isinstance(exc, OSError):
                    current_app.logger.exception("Filesystem operation failed at %s", request.endpoint)
                    g.form_errors = {"_form": "Nie udało się odczytać plików. Sprawdź uprawnienia i dostępność folderu. Nic nie zapisano."}
                else:
                    current_app.logger.warning("Rejected conflicting write at %s", request.endpoint)
                    field = conflict_field or "_form"
                    g.form_errors = {field: "Taka wartość już istnieje lub dane zmieniły się w międzyczasie. Sprawdź formularz."}
                target_kwargs = {key: kwargs[key] for key in ("pallet_id", "shoe_id") if key in kwargs}
                return current_app.view_functions[f"inventory.{view}"](**target_kwargs), 422
            except SQLAlchemyError:
                current_app.logger.exception("Database operation failed at %s", request.endpoint)
                return render_template("error.html", status=503,
                                       message="Nie udało się potwierdzić zapisu w bazie. Odśwież dane przed ponowną próbą."), 503
            flash(getattr(g, "success_message", success), "success")
            return result
        return wrapped
    return decorate
