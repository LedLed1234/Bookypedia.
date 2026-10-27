import json
import logging
import re
import sys
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from flask import g, has_request_context, request


EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "book_id",
    "user_id",
    "provider",
    "fallback_provider",
    "provider_book_id",
    "lookup_status",
    "attempt",
    "retry_in_seconds",
    "member_count",
    "changed_fields",
    "queued_books",
    "queued_metadata",
    "worker_enabled",
    "app_version",
    "error_type",
    "csrf_rejected",
)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "request_id") and has_request_context():
            request_id = getattr(g, "request_id", None)
            if request_id:
                record.request_id = request_id
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "process": record.process,
            "thread": record.threadName,
        }
        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class TextLogFormatter(logging.Formatter):
    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(
            timespec="milliseconds"
        )
        fields = []
        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                fields.append(f"{field}={value}")
        suffix = f" {' '.join(fields)}" if fields else ""
        message = f"{timestamp} {record.levelname} {record.name}: {record.getMessage()}{suffix}"
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return message


def configure_logging(app):
    level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = (
        JsonLogFormatter()
        if str(app.config.get("LOG_FORMAT", "json")).casefold() == "json"
        else TextLogFormatter()
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(level)
    app.logger.propagate = False

    # Unsere Request-Logs ersetzen die doppelten Development-Zugriffslogs.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.WARNING)


def register_request_logging(app):
    @app.before_request
    def start_request_timer():
        incoming_id = request.headers.get("X-Request-ID", "")
        g.request_id = incoming_id if REQUEST_ID_PATTERN.fullmatch(incoming_id) else uuid4().hex
        g.request_started_at = perf_counter()

    @app.after_request
    def log_completed_request(response):
        duration_ms = round((perf_counter() - g.request_started_at) * 1000, 2)
        route = request.url_rule.rule if request.url_rule else request.path
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING
        elif request.method == "GET":
            level = logging.DEBUG
        else:
            level = logging.INFO
        app.logger.log(
            level,
            "HTTP-Anfrage abgeschlossen",
            extra={
                "event": "http_request",
                "request_id": g.request_id,
                "method": request.method,
                "route": route,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = g.request_id
        return response
