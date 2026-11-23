"""Single-owner authentication, server-revocable sessions and durable throttling."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import os
import secrets
import sqlite3
import time
from urllib.parse import unquote, urlsplit

import click
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash


auth = Blueprint("auth", __name__)
csrf = CSRFProtect()


@contextmanager
def auth_db():
    connection = sqlite3.connect(current_app.config["AUTH_DATABASE_PATH"], timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def owner_record():
    with auth_db() as db:
        return db.execute("SELECT password_hash FROM owner WHERE id = 1").fetchone()


def safe_next(value):
    """Only absolute local paths, never URLs, backslashes or control characters."""
    decoded = unquote(value)
    if (not value or not decoded.startswith("/") or decoded.startswith("//")
            or "\\" in decoded or any(ord(c) < 32 for c in decoded)):
        return url_for("inventory.home")
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return url_for("inventory.home")
    if parsed.scheme or parsed.netloc or parsed.path in {"/login", "/logout"}:
        return url_for("inventory.home")
    return value


def set_owner_password(password, *, initialize=False):
    if len(password) < 12 or len(password) > 256 or password.isspace():
        raise ValueError("Hasło musi mieć od 12 do 256 znaków i nie może składać się z samych spacji.")
    hashed = generate_password_hash(password, method="scrypt")
    with auth_db() as db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT id FROM owner WHERE id = 1").fetchone()
        if initialize and exists:
            raise ValueError("Konto już istnieje. Użyj polecenia reset-owner-password.")
        if not initialize and not exists:
            raise ValueError("Najpierw utwórz konto poleceniem init-owner.")
        db.execute("INSERT INTO owner (id, password_hash) VALUES (1, ?) "
                   "ON CONFLICT(id) DO UPDATE SET password_hash=excluded.password_hash", (hashed,))
        db.execute("DELETE FROM auth_sessions")
        db.execute("DELETE FROM login_attempts")


def reserve_login_attempt():
    """Reserve before hashing: limits apply across threads, processes and restarts."""
    now = int(time.time())
    window = current_app.config["LOGIN_RATE_WINDOW"]
    buckets = (("ip:" + token_digest(request.remote_addr or "unknown"), current_app.config["LOGIN_RATE_LIMIT"]),
               ("global", current_app.config["LOGIN_GLOBAL_RATE_LIMIT"]))
    with auth_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM login_attempts WHERE window_started <= ?", (now - window,))
        for bucket, limit in buckets:
            row = db.execute("SELECT window_started, count FROM login_attempts WHERE bucket = ?", (bucket,)).fetchone()
            if row and row["count"] >= limit:
                return max(row["window_started"] + window - now, 1)
        for bucket, _ in buckets:
            db.execute("INSERT INTO login_attempts (bucket, window_started, count) VALUES (?, ?, 1) "
                       "ON CONFLICT(bucket) DO UPDATE SET count=count+1", (bucket, now))
    return 0


def create_login_session(password, remember):
    token = secrets.token_urlsafe(32)
    lifetime = current_app.config["REMEMBER_SESSION_SECONDS"] if remember else current_app.config["AUTH_SESSION_SECONDS"]
    with auth_db() as db:
        db.execute("BEGIN IMMEDIATE")
        # Serialize with password reset so a concurrent reset cannot mint an old login.
        row = db.execute("SELECT password_hash FROM owner WHERE id=1").fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return False
        now = int(time.time())
        db.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        db.execute("INSERT INTO auth_sessions(token_hash, expires_at) VALUES (?, ?)",
                   (token_digest(token), now + lifetime))
    session.clear()
    session["auth_token"] = token
    session.permanent = remember
    return True


@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.get("authenticated"):
        return redirect(url_for("inventory.home"))
    target = safe_next(request.form.get("next", "") if request.method == "POST" else request.args.get("next", ""))
    if not owner_record():
        return render_template("login.html", setup_required=True, next_url=target), 503
    error = None
    status = 200
    if request.method == "POST":
        retry_after = reserve_login_attempt()
        if retry_after:
            response = current_app.make_response((render_template("login.html", error="Za dużo prób logowania. Spróbuj ponownie za kilka minut.", next_url=target), 429))
            response.headers["Retry-After"] = str(retry_after)
            return response
        password = request.form.get("password", "")
        if 0 < len(password) <= 256 and create_login_session(password, request.form.get("remember") == "yes"):
            flash("Zalogowano do magazynu.", "success")
            return redirect(target, code=303)
        error, status = "Nieprawidłowe hasło.", 401
    return render_template("login.html", error=error, next_url=target), status


@auth.post("/logout")
def logout():
    token = session.get("auth_token")
    if token:
        with auth_db() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_digest(token),))
    session.clear()
    flash("Wylogowano z magazynu.", "success")
    return redirect(url_for("auth.login"), code=303)


def init_auth(app):
    if (app.config.get("AUTH_DISABLED") or app.config.get("WTF_CSRF_ENABLED") is False) and not app.testing:
        raise ValueError("Authentication and CSRF may only be disabled in isolated tests")
    app.config["AUTH_DATABASE_PATH"] = app.config["DATA_ROOT"] / ".auth.sqlite3"
    app.config.setdefault("AUTH_SESSION_SECONDS", 12 * 60 * 60)
    app.config.setdefault("REMEMBER_SESSION_SECONDS", 30 * 24 * 60 * 60)
    app.config.setdefault("LOGIN_RATE_WINDOW", 5 * 60)
    app.config.setdefault("LOGIN_RATE_LIMIT", 5)
    app.config.setdefault("LOGIN_GLOBAL_RATE_LIMIT", 30)
    app.config.update(SESSION_REFRESH_EACH_REQUEST=False,
                      PERMANENT_SESSION_LIFETIME=timedelta(seconds=app.config["REMEMBER_SESSION_SECONDS"]))
    try:
        descriptor = os.open(app.config["AUTH_DATABASE_PATH"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    with app.app_context(), auth_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY CHECK (id=1), password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts (bucket TEXT PRIMARY KEY, window_started INTEGER NOT NULL, count INTEGER NOT NULL);
        """)
    app.register_blueprint(auth)

    @app.before_request
    def authenticate_request():
        g.authenticated = False
        if app.testing and app.config.get("AUTH_DISABLED"):
            return
        token = session.get("auth_token")
        if isinstance(token, str) and len(token) <= 128:
            with auth_db() as db:
                row = db.execute("SELECT token_hash FROM auth_sessions WHERE token_hash=? AND expires_at>?",
                                 (token_digest(token), int(time.time()))).fetchone()
            g.authenticated = row is not None
        if request.endpoint in {"auth.login", "static", "inventory.health", None}:
            return
        if not g.authenticated:
            session.pop("auth_token", None)
            if request.method in {"GET", "HEAD"} and request.endpoint != "inventory.media_file":
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            abort(401)

    csrf.init_app(app)

    @app.after_request
    def privacy_headers(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.errorhandler(CSRFError)
    def csrf_failure(error):
        return render_template("error.html", status=400,
                               message="Formularz wygasł lub nie ma poprawnego zabezpieczenia. Odśwież stronę przed ponownym zapisem."), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return render_template("error.html", status=401, message="Zaloguj się, aby uzyskać dostęp do magazynu."), 401

    @app.errorhandler(sqlite3.Error)
    def auth_storage_failure(error):
        app.logger.exception("Authentication storage unavailable")
        return render_template("error.html", status=503, message="Magazyn jest chwilowo niedostępny. Sprawdź terminal aplikacji."), 503

    @app.cli.command("init-owner")
    @click.password_option(prompt="Hasło właściciela (min. 12 znaków)", confirmation_prompt="Powtórz hasło")
    def init_owner(password):
        """Create the single owner locally. Never overwrites an existing account."""
        try:
            set_owner_password(password, initialize=True)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo("Utworzono konto właściciela. Możesz uruchomić aplikację i zalogować się.")

    @app.cli.command("reset-owner-password")
    @click.password_option(prompt="Nowe hasło właściciela (min. 12 znaków)", confirmation_prompt="Powtórz hasło")
    def reset_owner(password):
        """Reset locally and revoke all sessions and remembered devices."""
        try:
            set_owner_password(password)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo("Zmieniono hasło. Wszystkie urządzenia zostały wylogowane.")
