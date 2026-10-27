import io
import json
import logging

from readmore import create_app
from readmore.logging_config import JsonLogFormatter


def test_request_id_is_returned_and_validated(client):
    supplied = client.get("/health", headers={"X-Request-ID": "bookypedia-test-42"})
    assert supplied.headers["X-Request-ID"] == "bookypedia-test-42"
    assert supplied.get_json()["version"] == client.application.config["BUILD_VERSION"]

    generated = client.get("/health", headers={"X-Request-ID": "invalid id with spaces"})
    assert generated.headers["X-Request-ID"] != "invalid id with spaces"
    assert len(generated.headers["X-Request-ID"]) == 32


def test_structured_logs_do_not_include_book_content(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "logging.db"),
            "LOG_LEVEL": "INFO",
        }
    )
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    app.logger.handlers[:] = [handler]

    response = app.test_client().post(
        "/api/books",
        json={
            "title": "Nicht ins Log schreiben",
            "authors": ["Vertrauliche Autorin"],
            "isbn": "9781234567897",
            "status": "read",
            "rating": 5,
            "review": "Sehr privater Bewertungstext",
        },
        headers={"X-Request-ID": "privacy-test"},
    )

    assert response.status_code == 201
    entries = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert {entry["event"] for entry in entries} == {"book_created", "http_request"}
    assert entries[-1]["request_id"] == "privacy-test"
    assert entries[-1]["duration_ms"] >= 0
    output = stream.getvalue()
    assert "Nicht ins Log schreiben" not in output
    assert "Vertrauliche Autorin" not in output
    assert "9781234567897" not in output
    assert "Sehr privater Bewertungstext" not in output
