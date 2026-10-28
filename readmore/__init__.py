import json
import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from .api import api
from .auth import create_user, init_auth, login_required
from .cover_cache import serve_cached_cover
from .db import get_db, init_app as init_database
from .logging_config import configure_logging, register_request_logging
from .metadata_cache import enqueue_existing_metadata
from .providers import KNOWN_PROVIDERS
from .series_cache import enqueue_existing_books, start_series_worker


def _build_version():
    configured = str(os.environ.get("APP_VERSION") or "").strip()
    if configured:
        return configured[:64]
    version_file = Path(__file__).resolve().parent.parent / ".build-version"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "development"
    return version[:64] or "development"


def _catalogue_settings():
    config_path = Path(__file__).resolve().parent / "static" / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"App-Konfiguration konnte nicht gelesen werden: {config_path}") from error
    catalogue = payload.get("catalogue") or {}
    mode = str(catalogue.get("mode") or "primary_fallback").strip()
    if mode != "primary_fallback":
        raise RuntimeError(f"Noch nicht unterstützter Buchkatalog-Modus: {mode}")
    primary = str(catalogue.get("primaryProvider") or "open_library").strip()
    fallback = str(catalogue.get("fallbackProvider") or primary).strip()
    primary = str(os.environ.get("BOOK_PROVIDER") or primary).strip()
    fallback = str(os.environ.get("BOOK_FALLBACK_PROVIDER") or fallback).strip()
    unknown = {name for name in (primary, fallback) if name not in KNOWN_PROVIDERS}
    if unknown:
        raise RuntimeError(f"Unbekannter Buchanbieter in config.json: {', '.join(sorted(unknown))}")
    defaults = payload.get("defaults") or {}

    def integer_default(name, default, minimum, maximum):
        try:
            value = int(defaults.get(name, default))
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"defaults.{name} muss eine ganze Zahl sein.") from error
        if not minimum <= value <= maximum:
            raise RuntimeError(
                f"defaults.{name} muss zwischen {minimum} und {maximum} liegen."
            )
        return value

    limits = {
        "review": integer_default("reviewMaxLength", 1000, 1, 50000),
        "search": integer_default("searchMaxLength", 250, 2, 1000),
        "title": integer_default("bookTitleMaxLength", 300, 1, 5000),
        "authors": integer_default("bookAuthorsMaxLength", 500, 1, 5000),
        "search_rate": integer_default("searchRateLimitPerMinute", 60, 1, 10000),
    }
    return mode, primary, fallback, limits


def create_app(test_config=None):
    app_environment = os.environ.get("APP_ENV", "development").casefold()
    configured_secret = os.environ.get("SECRET_KEY")
    if app_environment == "production" and not configured_secret:
        raise RuntimeError("SECRET_KEY muss in der Produktionsumgebung gesetzt sein.")
    provider_mode, primary_provider, fallback_provider, limits = _catalogue_settings()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=configured_secret or "bookypedia-local-development-only",
        DATABASE=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "readmore.db")),
        COVER_CACHE_DIRECTORY=os.environ.get(
            "COVER_CACHE_DIRECTORY",
            os.path.join(
                os.path.dirname(os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "readmore.db"))),
                "covers",
            ),
        ),
        BOOK_PROVIDER=primary_provider,
        BOOK_FALLBACK_PROVIDER=fallback_provider,
        BOOK_PROVIDER_MODE=provider_mode,
        REVIEW_MAX_LENGTH=limits["review"],
        SEARCH_MAX_LENGTH=limits["search"],
        BOOK_TITLE_MAX_LENGTH=limits["title"],
        BOOK_AUTHORS_MAX_LENGTH=limits["authors"],
        SEARCH_RATE_LIMIT_PER_MINUTE=limits["search_rate"],
        SERIES_WORKER_ENABLED=os.environ.get("SERIES_WORKER_ENABLED", "1") != "0",
        SERIES_WORKER_POLL_INTERVAL=1.0,
        LOG_LEVEL=os.environ.get("LOG_LEVEL", "INFO"),
        LOG_FORMAT=os.environ.get("LOG_FORMAT", "json"),
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=1024 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=50,
        APP_ENV=app_environment,
        BUILD_VERSION=_build_version(),
        CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get(
            "SESSION_COOKIE_SECURE", "1" if app_environment == "production" else "0"
        ) == "1",
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_REFRESH_EACH_REQUEST=False,
    )

    if test_config:
        app.config.update(test_config)
        if "DATABASE" in test_config and "COVER_CACHE_DIRECTORY" not in test_config:
            app.config["COVER_CACHE_DIRECTORY"] = os.path.join(
                os.path.dirname(app.config["DATABASE"]), "covers"
            )
    if app.config.get("TESTING") and not (test_config and "SERIES_WORKER_ENABLED" in test_config):
        app.config["SERIES_WORKER_ENABLED"] = False
    if app.config.get("TESTING") and not (test_config and "TEST_AUTO_LOGIN" in test_config):
        app.config["TEST_AUTO_LOGIN"] = True
    if app.config.get("TESTING") and not (test_config and "CSRF_ENABLED" in test_config):
        app.config["CSRF_ENABLED"] = False

    configure_logging(app)
    register_request_logging(app)
    if os.environ.get("TRUST_PROXY", "0") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    init_database(app)
    init_auth(app)
    if app.config.get("TEST_AUTO_LOGIN"):
        with app.app_context():
            row = get_db().execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if row is None:
                user_id, _ = create_user(
                    "test-user",
                    "test-password-only-for-tests",
                    "Test User",
                    require_password_change=False,
                )
            else:
                user_id = row["id"]
            app.config["TEST_USER_ID"] = user_id
    with app.app_context():
        queued_books = enqueue_existing_books(get_db(), provider=app.config["BOOK_PROVIDER"])
        queued_metadata = enqueue_existing_metadata(get_db(), provider=app.config["BOOK_PROVIDER"])
    app.register_blueprint(api, url_prefix="/api")

    @app.get("/")
    @login_required
    def index():
        if g.user["password_change_required"]:
            return redirect(url_for("auth.change_password"))
        return render_template(
            "index.html",
            build_version=app.config["BUILD_VERSION"],
            review_max_length=app.config["REVIEW_MAX_LENGTH"],
            search_max_length=app.config["SEARCH_MAX_LENGTH"],
            book_title_max_length=app.config["BOOK_TITLE_MAX_LENGTH"],
            book_authors_max_length=app.config["BOOK_AUTHORS_MAX_LENGTH"],
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok", version=app.config["BUILD_VERSION"])

    @app.get("/service-worker.js")
    def service_worker():
        response = app.send_static_file("service-worker.js")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/covers/<string:cache_key>")
    @login_required
    def cover_asset(cache_key):
        if len(cache_key) != 64 or any(character not in "0123456789abcdef" for character in cache_key):
            return "Cover nicht gefunden.", 404
        return serve_cached_cover(get_db(), cache_key)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests",
        )
        if request.is_secure and app.config["APP_ENV"] == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.path.startswith("/api/") or request.endpoint == "index" or request.blueprint == "auth":
            response.headers["Cache-Control"] = "no-store"
        return response

    if app.config["SERIES_WORKER_ENABLED"]:
        start_series_worker(app)

    app.logger.info(
        "Bookypedia wurde gestartet",
        extra={
            "event": "app_started",
            "provider": app.config["BOOK_PROVIDER"],
            "fallback_provider": app.config["BOOK_FALLBACK_PROVIDER"],
            "queued_books": queued_books,
            "queued_metadata": queued_metadata,
            "worker_enabled": app.config["SERIES_WORKER_ENABLED"],
            "app_version": app.config["BUILD_VERSION"],
        },
    )

    return app

