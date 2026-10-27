import json
import sqlite3
import unicodedata
from collections import OrderedDict
from difflib import SequenceMatcher
from threading import Lock
from time import monotonic
from time import time

from flask import Blueprint, current_app, g, jsonify, request

from .db import get_db
from .metadata_cache import enqueue_metadata_lookup, metadata_lookup_status
from .providers import KNOWN_PROVIDERS, get_provider
from .providers.base import ProviderUnavailable
from .series_cache import enqueue_series_lookup, get_cached_series, wake_series_worker
from .text import identity_key, normalize_text


api = Blueprint("api", __name__)
VALID_STATUSES = {"want_to_read", "unread", "reading", "read"}
VALID_BOOK_FILTERS = VALID_STATUSES | {"owned"}
STATUS_TIMESTAMP_COLUMNS = {
    "want_to_read": "want_to_read_at",
    "unread": "owned_at",
    "reading": "reading_at",
    "read": "read_at",
}
TIMESTAMP_FIELDS = {
    "created_at",
    "updated_at",
    *STATUS_TIMESTAMP_COLUMNS.values(),
}
SEARCH_RESULT_LIMIT = 4
SEARCH_CACHE_TTL = 5 * 60
SEARCH_CACHE_MAX_ENTRIES = 128
METADATA_CACHE_TTL = 180 * 24 * 60 * 60
_SEARCH_CACHE = OrderedDict()
_SEARCH_CACHE_LOCK = Lock()


@api.before_request
def require_authenticated_user():
    if g.user is None:
        return jsonify(error="Bitte melde dich an."), 401
    if g.user["password_change_required"]:
        return jsonify(error="Bitte ändere zuerst dein vorläufiges Passwort."), 403


def normalize_isbn(value):
    if not value:
        return None
    isbn = "".join(character for character in str(value).upper() if character.isdigit() or character == "X")
    return isbn if len(isbn) in (10, 13) else None


def normalize_authors(value):
    if isinstance(value, list):
        authors = [str(author).strip() for author in value if str(author).strip()]
        return ", ".join(authors[:6])
    return str(value or "").strip()


def normalize_page_count(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        pages = int(value)
    except (TypeError, ValueError):
        return None
    return pages if pages > 0 else None


def normalize_metadata_text(value, limit=50000):
    return str(value or "").strip()[:limit] or None


def normalize_subjects(value):
    if not isinstance(value, list):
        return []
    return [str(subject).strip() for subject in value if str(subject).strip()][:10]


def _known_metadata(book):
    fields = (
        "provider_edition_id",
        "isbn",
        "publisher",
        "publish_date",
        "page_count",
        "language",
        "description",
        "physical_format",
        "subtitle",
        "subjects",
    )
    return {
        field: book.get(field)
        for field in fields
        if book.get(field) not in (None, "", [])
    }


def _cached_book_metadata(db, provider_name, provider_book_id, provider_edition_id=None):
    edition_id = str(provider_edition_id or "").strip()
    cache_key = f"{provider_name}:{provider_book_id}:{edition_id}"
    row = db.execute(
        "SELECT metadata_json, fetched_at FROM book_metadata_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row and int(time()) - row["fetched_at"] < METADATA_CACHE_TTL:
        try:
            return json.loads(row["metadata_json"])
        except (TypeError, ValueError):
            pass

    provider = get_provider(provider_name)
    metadata = provider.metadata(provider_book_id, edition_id or None)
    metadata = metadata if isinstance(metadata, dict) else {}
    db.execute(
        """
        INSERT INTO book_metadata_cache (
            cache_key, provider, provider_book_id, provider_edition_id,
            metadata_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            metadata_json = excluded.metadata_json,
            fetched_at = excluded.fetched_at
        """,
        (
            cache_key,
            provider_name,
            provider_book_id,
            edition_id or None,
            json.dumps(metadata, ensure_ascii=False),
            int(time()),
        ),
    )
    db.commit()
    return metadata


def serialize_book(row):
    book = dict(row)
    book.pop("user_id", None)
    if book["status"] == "want_to_read" and book.get("is_owned"):
        book["status"] = "unread"
    book["is_owned"] = bool(book.get("is_owned"))
    book["authors"] = [author.strip() for author in book["authors"].split(",") if author.strip()]
    book["original_authors"] = [
        author.strip() for author in book.get("original_authors", "").split(",") if author.strip()
    ]
    raw_subjects = book.pop("subjects_json", "[]")
    try:
        book["subjects"] = json.loads(raw_subjects or "[]")
    except (TypeError, ValueError):
        book["subjects"] = []
    for field in TIMESTAMP_FIELDS:
        value = book.get(field)
        if value and "T" not in value:
            book[field] = f"{value.replace(' ', 'T')}Z"
    return book


def validation_error(message, status=400):
    return jsonify(error=message), status


def cached_provider_search(provider, query, suggestions=False, limit=SEARCH_RESULT_LIMIT):
    provider_name = getattr(
        provider,
        "cache_identity",
        f"{type(provider).__module__}.{type(provider).__qualname__}",
    )
    normalized_query = unicodedata.normalize("NFKC", query).casefold()
    key = (provider_name, suggestions, limit, normalized_query)
    now = monotonic()
    with _SEARCH_CACHE_LOCK:
        cached = _SEARCH_CACHE.get(key)
        if cached and now - cached[0] < SEARCH_CACHE_TTL:
            _SEARCH_CACHE.move_to_end(key)
            return cached[1]
        if cached:
            del _SEARCH_CACHE[key]

    results = (
        provider.suggest(query, limit=limit)
        if suggestions
        else provider.search(query, limit=limit)
    )
    # Leere Antworten können bei Open Library vorübergehend auftreten. Würden
    # wir sie cachen, bliebe ein vorhandenes Buch trotz späterer Erholung des
    # Anbieters mehrere Minuten unsichtbar.
    if results:
        with _SEARCH_CACHE_LOCK:
            _SEARCH_CACHE[key] = (monotonic(), results)
            _SEARCH_CACHE.move_to_end(key)
            while len(_SEARCH_CACHE) > SEARCH_CACHE_MAX_ENTRIES:
                _SEARCH_CACHE.popitem(last=False)
    return results


def prioritize_series_results(query, results, limit):
    """Place known series siblings after an exact title hit without hiding the hit itself."""
    if not results:
        return results
    lead = results[0]
    normalized_query = normalize_text(query)
    normalized_title = normalize_text(lead.get("title"))
    close_title_match = (
        normalized_query == normalized_title
        or (
            len(normalized_query) >= 4
            and (
                normalized_title.startswith(normalized_query)
                or SequenceMatcher(None, normalized_query, normalized_title).ratio() >= 0.88
            )
        )
    )
    if not close_title_match:
        return results
    provider_book_id = lead.get("provider_book_id")
    if not provider_book_id:
        return results
    db = get_db()
    provider_name = lead.get("provider") or current_app.config["BOOK_PROVIDER"]
    series, status = get_cached_series(db, provider_book_id, provider=provider_name)
    if status == "missing":
        enqueue_series_lookup(db, provider_book_id, lead.get("authors") or [], provider=provider_name)
        wake_series_worker(current_app._get_current_object())
    if not series or not series.get("books"):
        return results

    merged = []
    seen = set()

    def append(book):
        identity = book.get("provider_book_id") or identity_key(
            book.get("title"), normalize_authors(book.get("authors"))
        )
        if identity in seen:
            return
        seen.add(identity)
        merged.append(book)

    append(lead)
    original_by_id = {
        book.get("provider_book_id"): book
        for book in results
        if book.get("provider_book_id")
    }
    for book in series["books"]:
        richer = original_by_id.get(book.get("provider_book_id"))
        append({**book, **richer} if richer else book)
    for book in results[1:]:
        append(book)
    return merged[:limit]


@api.get("/search")
def search_books():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return validation_error("Bitte mindestens zwei Zeichen eingeben.")
    suggestions = request.args.get("suggest") == "1"
    if suggestions:
        limit = 6
    else:
        try:
            limit = int(request.args.get("limit", SEARCH_RESULT_LIMIT))
        except (TypeError, ValueError):
            limit = SEARCH_RESULT_LIMIT
        limit = min(20, max(1, limit))
    try:
        provider = get_provider()
        results = cached_provider_search(provider, query, suggestions=suggestions, limit=limit)
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "Buchsuche beim Anbieter fehlgeschlagen",
            extra={
                "event": "book_search_failed",
                "provider": current_app.config["BOOK_PROVIDER"],
                "fallback_provider": current_app.config["BOOK_FALLBACK_PROVIDER"],
                "error_type": type(error).__name__,
            },
        )
        return validation_error(str(error), 503)
    return jsonify(results=prioritize_series_results(query, results, limit))


@api.get("/books")
def list_books():
    status = request.args.get("status")
    if status and status not in VALID_BOOK_FILTERS:
        return validation_error("Ungültiger Lesestatus.")
    db = get_db()
    if status == "owned":
        rows = db.execute(
            """
            SELECT * FROM books
            WHERE user_id = ? AND is_owned = 1
            ORDER BY updated_at DESC, id DESC
            """,
            (g.user["id"],),
        ).fetchall()
    elif status == "unread":
        rows = db.execute(
            """
            SELECT * FROM books
            WHERE user_id = ? AND status = 'want_to_read' AND is_owned = 1
            ORDER BY updated_at DESC, id DESC
            """,
            (g.user["id"],),
        ).fetchall()
    elif status == "want_to_read":
        rows = db.execute(
            """
            SELECT * FROM books
            WHERE user_id = ? AND status = 'want_to_read' AND is_owned = 0
            ORDER BY updated_at DESC, id DESC
            """,
            (g.user["id"],),
        ).fetchall()
    elif status:
        rows = db.execute(
            """
            SELECT * FROM books
            WHERE user_id = ? AND status = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (g.user["id"], status),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM books
            WHERE user_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (g.user["id"],),
        ).fetchall()
    return jsonify(books=[serialize_book(row) for row in rows])


@api.get("/books/<int:book_id>/series")
def book_series(book_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, g.user["id"]),
    ).fetchone()
    if row is None:
        return validation_error("Buch nicht gefunden.", 404)
    book = serialize_book(row)
    if not book.get("provider_book_id"):
        return jsonify(series=None, status="no_series")
    provider_name = book.get("provider") or current_app.config["BOOK_PROVIDER"]
    result, status = get_cached_series(db, book["provider_book_id"], provider=provider_name)
    if status == "missing":
        enqueue_series_lookup(db, book["provider_book_id"], book["authors"], provider=provider_name)
        wake_series_worker(current_app._get_current_object())
        status = "pending"
    return jsonify(series=result, status=status)


@api.get("/books/<int:book_id>/metadata")
def saved_book_metadata(book_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, g.user["id"]),
    ).fetchone()
    if row is None:
        return validation_error("Buch nicht gefunden.", 404)
    book = serialize_book(row)
    metadata = _known_metadata(book)
    if not book.get("provider_book_id"):
        return jsonify(metadata=metadata)
    status = metadata_lookup_status(db, book_id)
    if status == "missing":
        enqueue_metadata_lookup(db, book_id, provider=book.get("provider") or current_app.config["BOOK_PROVIDER"])
        wake_series_worker(current_app._get_current_object())
        status = "pending"
    return jsonify(metadata=metadata, status=status)


@api.get("/metadata")
def catalogue_book_metadata():
    provider_name = request.args.get("provider", current_app.config["BOOK_PROVIDER"]).strip()
    if provider_name not in KNOWN_PROVIDERS:
        return validation_error("Ungültiger Buchanbieter.")
    provider_book_id = request.args.get("provider_book_id", "").strip()
    provider_edition_id = request.args.get("provider_edition_id", "").strip() or None
    if not provider_book_id:
        return validation_error("Eine Buch-ID ist erforderlich.")
    try:
        metadata = _cached_book_metadata(
            get_db(),
            provider_name,
            provider_book_id,
            provider_edition_id,
        )
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "Katalogmetadaten beim Anbieter fehlgeschlagen",
            extra={
                "event": "catalogue_metadata_failed",
                "provider": provider_name,
                "error_type": type(error).__name__,
            },
        )
        return jsonify(metadata={}, status="unavailable")
    return jsonify(metadata=_known_metadata(metadata), status="ready")


@api.get("/series")
def catalogue_series():
    provider_name = request.args.get("provider", current_app.config["BOOK_PROVIDER"]).strip()
    if provider_name not in KNOWN_PROVIDERS:
        return validation_error("Ungültiger Buchanbieter.")
    provider_book_id = request.args.get("provider_book_id", "").strip()
    if not provider_book_id:
        return validation_error("Eine Buch-ID ist erforderlich.")
    authors = [author.strip() for author in request.args.getlist("author") if author.strip()][:6]
    db = get_db()
    result, status = get_cached_series(db, provider_book_id, provider=provider_name)
    if status == "missing":
        enqueue_series_lookup(db, provider_book_id, authors, provider=provider_name)
        wake_series_worker(current_app._get_current_object())
        status = "pending"
    return jsonify(series=result, status=status)


@api.post("/books")
def create_book():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title") or "").strip()
    authors = normalize_authors(payload.get("authors"))
    status = payload.get("status", "want_to_read")
    if not title:
        return validation_error("Ein Titel ist erforderlich.")
    if status not in VALID_STATUSES:
        return validation_error("Ungültiger Lesestatus.")

    rating = payload.get("rating")
    if rating in ("", None):
        rating = None
    elif isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return validation_error("Die Bewertung muss zwischen 1 und 5 Sternen liegen.")
    review = str(payload.get("review") or "").strip()
    if len(review) > 5000:
        return validation_error("Der Bewertungstext darf höchstens 5.000 Zeichen lang sein.")

    isbn = normalize_isbn(payload.get("isbn"))
    provider_book_id = str(payload.get("provider_book_id") or "").strip() or None
    provider_edition_id = str(payload.get("provider_edition_id") or "").strip() or None
    provider_name = str(payload.get("provider") or "").strip()
    if provider_book_id:
        provider_name = provider_name or current_app.config["BOOK_PROVIDER"]
        if provider_name not in KNOWN_PROVIDERS:
            return validation_error("Ungültiger Buchanbieter.")
    else:
        provider_name = "manual"
    cover_url = str(payload.get("cover_url") or "").strip() or None
    original_title = str(payload.get("original_title") or "").strip() or None
    original_authors = normalize_authors(payload.get("original_authors"))
    language = str(payload.get("language") or "").strip() or None
    page_count = normalize_page_count(payload.get("page_count"))
    publisher = normalize_metadata_text(payload.get("publisher"), 1000)
    publish_date = normalize_metadata_text(payload.get("publish_date"), 250)
    description = normalize_metadata_text(payload.get("description"))
    physical_format = normalize_metadata_text(payload.get("physical_format"), 250)
    subtitle = normalize_metadata_text(payload.get("subtitle"), 1000)
    subjects_json = json.dumps(normalize_subjects(payload.get("subjects")), ensure_ascii=False)
    key = identity_key(title, authors)
    db = get_db()

    duplicate = _find_duplicate(db, g.user["id"], isbn, provider_name, provider_book_id, key)
    if duplicate:
        return jsonify(error="Dieses Buch ist bereits in deiner Sammlung.", book=serialize_book(duplicate)), 409

    try:
        stored_status = "want_to_read" if status == "unread" else status
        is_owned = int(status != "want_to_read")
        status_timestamp_column = STATUS_TIMESTAMP_COLUMNS[status]
        cursor = db.execute(
            f"""
            INSERT INTO books (
                user_id, title, authors, isbn, provider, provider_book_id, provider_edition_id,
                cover_url, original_title, original_authors, language, page_count,
                publisher, publish_date, description, physical_format, subtitle,
                subjects_json, identity_key, status, is_owned, rating, review,
                {status_timestamp_column}
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                g.user["id"],
                title,
                authors,
                isbn,
                provider_name,
                provider_book_id,
                provider_edition_id,
                cover_url,
                original_title,
                original_authors,
                language,
                page_count,
                publisher,
                publish_date,
                description,
                physical_format,
                subtitle,
                subjects_json,
                key,
                stored_status,
                is_owned,
                rating,
                review,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return validation_error("Dieses Buch ist bereits in deiner Sammlung.", 409)
    row = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (cursor.lastrowid, g.user["id"]),
    ).fetchone()
    if provider_book_id:
        enqueue_metadata_lookup(
            db,
            row["id"],
            provider=provider_name,
        )
        enqueue_series_lookup(
            db,
            provider_book_id,
            authors,
            provider=provider_name,
        )
        wake_series_worker(current_app._get_current_object())
    current_app.logger.info(
        "Buch gespeichert",
        extra={
            "event": "book_created",
            "book_id": row["id"],
            "user_id": g.user["id"],
            "provider": provider_name,
        },
    )
    return jsonify(book=serialize_book(row)), 201


@api.patch("/books/<int:book_id>")
def update_book(book_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"status", "rating", "review"}
    if not payload or set(payload) - allowed:
        return validation_error("Die übermittelten Änderungen sind ungültig.")

    db = get_db()
    existing = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, g.user["id"]),
    ).fetchone()
    if existing is None:
        return validation_error("Buch nicht gefunden.", 404)

    updates = []
    values = []
    changed_fields = []
    if "status" in payload:
        if payload["status"] not in VALID_STATUSES:
            return validation_error("Ungültiger Lesestatus.")
        existing_status = (
            "unread"
            if existing["status"] == "want_to_read" and existing["is_owned"]
            else existing["status"]
        )
        if payload["status"] != existing_status:
            new_status = payload["status"]
            updates.append("status = ?")
            values.append("want_to_read" if new_status == "unread" else new_status)
            updates.append("is_owned = ?")
            values.append(int(new_status != "want_to_read"))
            updates.append(f"{STATUS_TIMESTAMP_COLUMNS[new_status]} = CURRENT_TIMESTAMP")
            if new_status == "want_to_read":
                updates.extend(("owned_at = NULL", "reading_at = NULL", "read_at = NULL"))
            elif new_status == "unread":
                updates.extend(("reading_at = NULL", "read_at = NULL"))
            elif new_status == "reading":
                updates.extend(("owned_at = COALESCE(owned_at, CURRENT_TIMESTAMP)", "read_at = NULL"))
            elif new_status == "read":
                updates.append("owned_at = COALESCE(owned_at, CURRENT_TIMESTAMP)")
            changed_fields.append("status")
    if "rating" in payload:
        rating = payload["rating"]
        if rating in ("", None):
            rating = None
        elif isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            return validation_error("Die Bewertung muss zwischen 1 und 5 Sternen liegen.")
        updates.append("rating = ?")
        values.append(rating)
        changed_fields.append("rating")
    if "review" in payload:
        review = str(payload["review"] or "").strip()
        if len(review) > 5000:
            return validation_error("Der Bewertungstext darf höchstens 5.000 Zeichen lang sein.")
        updates.append("review = ?")
        values.append(review)
        changed_fields.append("review")

    if not updates:
        return jsonify(book=serialize_book(existing))

    values.extend((book_id, g.user["id"]))
    cursor = db.execute(
        f"""
        UPDATE books
        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        values,
    )
    if cursor.rowcount == 0:
        return validation_error("Buch nicht gefunden.", 404)
    db.commit()
    row = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, g.user["id"]),
    ).fetchone()
    current_app.logger.info(
        "Buch aktualisiert",
        extra={
            "event": "book_updated",
            "book_id": book_id,
            "user_id": g.user["id"],
            "changed_fields": ",".join(sorted(changed_fields)),
        },
    )
    return jsonify(book=serialize_book(row))


@api.delete("/books/<int:book_id>")
def delete_book(book_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM books WHERE id = ? AND user_id = ?",
        (book_id, g.user["id"]),
    )
    if cursor.rowcount == 0:
        return validation_error("Buch nicht gefunden.", 404)
    db.commit()
    current_app.logger.info(
        "Buch entfernt",
        extra={"event": "book_deleted", "book_id": book_id, "user_id": g.user["id"]},
    )
    return "", 204


def _find_duplicate(db, user_id, isbn, provider, provider_book_id, key):
    conditions = ["identity_key = ?"]
    values = [key]
    if isbn:
        conditions.append("isbn = ?")
        values.append(isbn)
    if provider_book_id:
        conditions.append("(provider = ? AND provider_book_id = ?)")
        values.extend((provider, provider_book_id))
    return db.execute(
        f"SELECT * FROM books WHERE user_id = ? AND ({' OR '.join(conditions)}) LIMIT 1",
        [user_id, *values],
    ).fetchone()

