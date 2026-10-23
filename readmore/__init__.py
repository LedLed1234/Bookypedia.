import os

from flask import Flask, jsonify, render_template

from .api import api
from .db import get_db, init_app as init_database
from .logging_config import configure_logging, register_request_logging
from .metadata_cache import enqueue_existing_metadata
from .series_cache import enqueue_existing_books, start_series_worker


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "readmore.db")),
        BOOK_PROVIDER=os.environ.get("BOOK_PROVIDER", "open_library"),
        SERIES_WORKER_ENABLED=os.environ.get("SERIES_WORKER_ENABLED", "1") != "0",
        SERIES_WORKER_POLL_INTERVAL=1.0,
        LOG_LEVEL=os.environ.get("LOG_LEVEL", "INFO"),
        LOG_FORMAT=os.environ.get("LOG_FORMAT", "json"),
        JSON_SORT_KEYS=False,
    )

    if test_config:
        app.config.update(test_config)
    if app.config.get("TESTING") and not (test_config and "SERIES_WORKER_ENABLED" in test_config):
        app.config["SERIES_WORKER_ENABLED"] = False

    configure_logging(app)
    register_request_logging(app)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    init_database(app)
    with app.app_context():
        queued_books = enqueue_existing_books(get_db(), provider=app.config["BOOK_PROVIDER"])
        queued_metadata = enqueue_existing_metadata(
            get_db(), provider=app.config["BOOK_PROVIDER"]
        )
    app.register_blueprint(api, url_prefix="/api")

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/service-worker.js")
    def service_worker():
        response = app.send_static_file("service-worker.js")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    if app.config["SERIES_WORKER_ENABLED"]:
        start_series_worker(app)

    app.logger.info(
        "Bookypedia wurde gestartet",
        extra={
            "event": "app_started",
            "provider": app.config["BOOK_PROVIDER"],
            "queued_books": queued_books,
            "queued_metadata": queued_metadata,
            "worker_enabled": app.config["SERIES_WORKER_ENABLED"],
        },
    )

    return app

