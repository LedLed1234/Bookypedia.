import hashlib
import hmac
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlsplit

import click
from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.cli import with_appcontext
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db


auth = Blueprint("auth", __name__)
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,39}$")
MIN_PASSWORD_LENGTH = 12
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_BLOCK_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
DUMMY_PASSWORD_HASH = generate_password_hash(
    "bookypedia-dummy-password-for-constant-work", method="scrypt"
)


def normalize_username(value):
    return str(value or "").strip().casefold()


def validate_username(value):
    username = normalize_username(value)
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Der Benutzername muss 3–40 Zeichen lang sein und darf nur Buchstaben, "
            "Zahlen, Punkt, Bindestrich und Unterstrich enthalten."
        )
    return username


def validate_password(value):
    password = str(value or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    if len(password) > 256:
        raise ValueError("Das Passwort ist zu lang.")
    return password


def create_user(username, password, display_name=None, require_password_change=True):
    username = validate_username(username)
    password = validate_password(password)
    display_name = str(display_name or username).strip()[:80] or username
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        cursor = db.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash, password_change_required
            ) VALUES (?, ?, ?, ?)
            """,
            (
                username,
                display_name,
                generate_password_hash(password, method="scrypt"),
                int(bool(require_password_change)),
            ),
        )
        user_id = cursor.lastrowid
        # Bei der ersten Kontoanlage gehört der unangetastete Bestand aus der
        # früheren Einbenutzer-Version diesem ersten Besitzer.
        previous_user_count = db.execute(
            "SELECT COUNT(*) AS count FROM users WHERE id != ?", (user_id,)
        ).fetchone()["count"]
        adopted_books = 0
        if previous_user_count == 0:
            adopted_books = db.execute(
                "UPDATE books SET user_id = ? WHERE user_id IS NULL", (user_id,)
            ).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    return user_id, max(adopted_books, 0)


def ensure_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _safe_next_url(value):
    value = str(value or "")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return url_for("index")
    return value


def _throttle_key(username):
    address = request.remote_addr or "unknown"
    value = f"{normalize_username(username)}\0{address}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _blocked_seconds(db, key):
    row = db.execute(
        "SELECT blocked_until FROM login_attempts WHERE throttle_key = ?", (key,)
    ).fetchone()
    if not row:
        return 0
    return max(0, int(row["blocked_until"]) - int(time.time()))


def _record_login_failure(db, key):
    now = int(time.time())
    row = db.execute(
        "SELECT failures, window_started_at FROM login_attempts WHERE throttle_key = ?",
        (key,),
    ).fetchone()
    if not row or now - int(row["window_started_at"]) > LOGIN_WINDOW_SECONDS:
        failures = 1
        window_started_at = now
    else:
        failures = int(row["failures"]) + 1
        window_started_at = int(row["window_started_at"])
    blocked_until = now + LOGIN_BLOCK_SECONDS if failures >= LOGIN_MAX_FAILURES else 0
    db.execute(
        """
        INSERT INTO login_attempts (
            throttle_key, failures, window_started_at, blocked_until
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(throttle_key) DO UPDATE SET
            failures = excluded.failures,
            window_started_at = excluded.window_started_at,
            blocked_until = excluded.blocked_until,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, failures, window_started_at, blocked_until),
    )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Bitte melde dich an."), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(**kwargs)

    return wrapped


def init_auth(app):
    app.register_blueprint(auth)

    @app.before_request
    def load_logged_in_user():
        g.user = None
        user_id = session.get("user_id")
        auth_version = session.get("auth_version")
        if user_id is None and current_app.config.get("TEST_AUTO_LOGIN"):
            user_id = current_app.config.get("TEST_USER_ID")
            row = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
            ).fetchone()
            g.user = row
            return
        if user_id is None:
            return
        row = get_db().execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        if row is None or int(row["auth_version"]) != auth_version:
            session.clear()
            return
        g.user = row

    @app.before_request
    def protect_unsafe_requests():
        if not app.config.get("CSRF_ENABLED", True) or request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        expected = session.get("_csrf_token")
        received = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if expected and received and hmac.compare_digest(str(expected), str(received)):
            return
        app.logger.warning(
            "Anfrage wegen ungültigem CSRF-Token abgewiesen",
            extra={"event": "csrf_rejected"},
        )
        if request.path.startswith("/api/"):
            return jsonify(error="Die Sitzung ist abgelaufen. Bitte lade die Seite neu."), 400
        return render_template("login.html", error="Die Sitzung ist abgelaufen. Bitte versuche es erneut."), 400

    @app.context_processor
    def inject_auth_context():
        return {"csrf_token": ensure_csrf_token, "current_user": g.get("user")}

    app.cli.add_command(user_cli)


@auth.route("/login", methods=("GET", "POST"))
def login():
    if g.user is not None:
        target = "auth.change_password" if g.user["password_change_required"] else "index"
        return redirect(url_for(target))

    error = None
    username = ""
    if request.method == "POST":
        username = normalize_username(request.form.get("username"))
        password = request.form.get("password", "")
        db = get_db()
        throttle_key = _throttle_key(username)
        blocked_for = _blocked_seconds(db, throttle_key)
        if blocked_for:
            error = "Zu viele fehlgeschlagene Versuche. Bitte warte einige Minuten."
            current_app.logger.warning(
                "Anmeldung vorübergehend blockiert",
                extra={"event": "login_throttled"},
            )
        else:
            user = db.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            password_matches = check_password_hash(
                user["password_hash"] if user else DUMMY_PASSWORD_HASH,
                password,
            )
            valid = bool(user and user["is_active"] and password_matches)
            if not valid:
                _record_login_failure(db, throttle_key)
                error = "Benutzername oder Passwort ist nicht korrekt."
                current_app.logger.warning(
                    "Anmeldung fehlgeschlagen",
                    extra={"event": "login_failed"},
                )
            else:
                db.execute("DELETE FROM login_attempts WHERE throttle_key = ?", (throttle_key,))
                db.execute(
                    "DELETE FROM login_attempts WHERE updated_at < datetime('now', '-30 days')"
                )
                db.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (user["id"],),
                )
                db.commit()
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                session["auth_version"] = int(user["auth_version"])
                ensure_csrf_token()
                current_app.logger.info(
                    "Anmeldung erfolgreich",
                    extra={"event": "login_succeeded", "user_id": user["id"]},
                )
                if user["password_change_required"]:
                    return redirect(url_for("auth.change_password"))
                return redirect(_safe_next_url(request.form.get("next")))

    return render_template(
        "login.html",
        error=error,
        username=username,
        next_url=_safe_next_url(request.args.get("next") or request.form.get("next")),
    )


@auth.route("/account/password", methods=("GET", "POST"))
@login_required
def change_password():
    error = None
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirmation = request.form.get("password_confirmation", "")
        if not check_password_hash(g.user["password_hash"], current_password):
            error = "Das aktuelle Passwort ist nicht korrekt."
        elif new_password != confirmation:
            error = "Die neuen Passwörter stimmen nicht überein."
        else:
            try:
                validate_password(new_password)
            except ValueError as exception:
                error = str(exception)
        if error is None:
            new_version = int(g.user["auth_version"]) + 1
            db = get_db()
            db.execute(
                """
                UPDATE users
                SET password_hash = ?, password_change_required = 0, auth_version = ?
                WHERE id = ?
                """,
                (generate_password_hash(new_password, method="scrypt"), new_version, g.user["id"]),
            )
            db.commit()
            session.clear()
            session.permanent = True
            session["user_id"] = g.user["id"]
            session["auth_version"] = new_version
            ensure_csrf_token()
            current_app.logger.info(
                "Passwort geändert",
                extra={"event": "password_changed", "user_id": g.user["id"]},
            )
            return redirect(url_for("index"))
    return render_template(
        "change_password.html",
        error=error,
        forced=bool(g.user["password_change_required"]),
    )


@auth.post("/logout")
@login_required
def logout():
    user_id = g.user["id"]
    session.clear()
    current_app.logger.info(
        "Abmeldung erfolgreich", extra={"event": "logout", "user_id": user_id}
    )
    response = redirect(url_for("auth.login"))
    # Lokale Appearance-Einstellungen bleiben erhalten; Sitzung und private
    # Browser-Caches werden dagegen zuverlässig entfernt.
    response.headers["Clear-Site-Data"] = '"cache", "cookies"'
    return response


@click.group("user")
def user_cli():
    """Bookypedia-Konten verwalten."""


@user_cli.command("create")
@click.argument("username")
@click.option("--display-name", help="Anzeigename in Bookypedia.")
@click.option(
    "--no-password-change",
    is_flag=True,
    help="Beim ersten Login keinen Passwortwechsel verlangen.",
)
@with_appcontext
def create_user_command(username, display_name, no_password_change):
    """Ein neues Konto ohne öffentliche Registrierung anlegen."""
    password = click.prompt("Vorläufiges Passwort", hide_input=True, confirmation_prompt=True)
    try:
        user_id, adopted_books = create_user(
            username,
            password,
            display_name,
            require_password_change=not no_password_change,
        )
    except ValueError as exception:
        raise click.ClickException(str(exception)) from exception
    except Exception as exception:
        if "UNIQUE constraint failed" in str(exception):
            raise click.ClickException("Dieser Benutzername ist bereits vergeben.") from exception
        raise
    suffix = f" {adopted_books} vorhandene Bücher wurden zugeordnet." if adopted_books else ""
    click.echo(f"Konto #{user_id} wurde angelegt.{suffix}")


@user_cli.command("list")
@with_appcontext
def list_users_command():
    """Vorhandene Konten anzeigen (ohne geheime Daten)."""
    rows = get_db().execute(
        """
        SELECT u.id, u.username, u.display_name, u.is_active, u.created_at,
               u.last_login_at, COUNT(b.id) AS book_count
        FROM users u
        LEFT JOIN books b ON b.user_id = u.id
        GROUP BY u.id
        ORDER BY u.username COLLATE NOCASE
        """
    ).fetchall()
    if not rows:
        click.echo("Noch keine Konten vorhanden.")
        return
    for row in rows:
        status = "aktiv" if row["is_active"] else "deaktiviert"
        click.echo(
            f"{row['username']} ({row['display_name']}) — {status}, "
            f"{row['book_count']} Bücher"
        )


def _set_user_active(username, active):
    username = normalize_username(username)
    db = get_db()
    cursor = db.execute(
        """
        UPDATE users
        SET is_active = ?, auth_version = auth_version + 1
        WHERE username = ? COLLATE NOCASE
        """,
        (int(active), username),
    )
    db.commit()
    if cursor.rowcount == 0:
        raise click.ClickException("Konto nicht gefunden.")
    click.echo(f"Konto {username} wurde {'aktiviert' if active else 'deaktiviert'}.")


@user_cli.command("deactivate")
@click.argument("username")
@with_appcontext
def deactivate_user_command(username):
    """Ein Konto sperren und bestehende Sitzungen ungültig machen."""
    _set_user_active(username, False)


@user_cli.command("activate")
@click.argument("username")
@with_appcontext
def activate_user_command(username):
    """Ein gesperrtes Konto wieder aktivieren."""
    _set_user_active(username, True)


@user_cli.command("reset-password")
@click.argument("username")
@with_appcontext
def reset_password_command(username):
    """Passwort zurücksetzen und bestehende Sitzungen abmelden."""
    password = click.prompt("Neues vorläufiges Passwort", hide_input=True, confirmation_prompt=True)
    try:
        validate_password(password)
    except ValueError as exception:
        raise click.ClickException(str(exception)) from exception
    db = get_db()
    cursor = db.execute(
        """
        UPDATE users
        SET password_hash = ?, password_change_required = 1,
            auth_version = auth_version + 1
        WHERE username = ? COLLATE NOCASE
        """,
        (generate_password_hash(password, method="scrypt"), normalize_username(username)),
    )
    db.commit()
    if cursor.rowcount == 0:
        raise click.ClickException("Konto nicht gefunden.")
    click.echo("Passwort wurde zurückgesetzt. Alle bestehenden Sitzungen sind ungültig.")
