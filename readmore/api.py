import json
import math
import sqlite3
import unicodedata
from urllib.parse import urlparse
from collections import OrderedDict
from datetime import date
from difflib import SequenceMatcher
from threading import Lock
from time import monotonic
from time import time

from flask import Blueprint, current_app, g, jsonify, request

from .cover_cache import attach_cached_cover_urls
from .db import get_db
from .metadata_cache import enqueue_metadata_lookup, metadata_lookup_status
from .providers import KNOWN_PROVIDERS, PrimaryFallbackProvider, get_provider
from .providers.base import ProviderUnavailable
from .providers.tmdb import TMDBProvider
from .search_cache import cached_catalogue_search
from .series_cache import enqueue_series_lookup, get_cached_series, wake_series_worker
from .text import identity_key, normalize_text
from .tmdb_cache import (
    cached_movie_collection,
    cached_tmdb_search,
    cached_tv_season,
    cached_tv_series,
)


api = Blueprint("api", __name__)
VALID_STATUSES = {"want_to_read", "unread", "reading", "read"}
VALID_BOOK_FILTERS = VALID_STATUSES | {"owned"}
VALID_MEDIA_STATUSES = {"watchlist", "watching", "completed", "dropped"}
MEDIA_STATUS_TIMESTAMP_COLUMNS = {
    "watchlist": "watchlist_at",
    "watching": "watching_at",
    "completed": "completed_at",
    "dropped": "dropped_at",
}
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


def serialize_media(row):
    media = dict(row)
    media.pop("user_id", None)
    media["tmdb_id"] = int(media["tmdb_id"])
    media["vote_count"] = int(media.get("vote_count") or 0)
    media["vote_average"] = (
        float(media["vote_average"]) if media.get("vote_average") is not None else None
    )
    media["rating"] = int(media["rating"]) if media.get("rating") is not None else None
    media["review"] = media.get("review") or ""
    media["cover_url"] = media.pop("poster_url", None)
    return media


def serialize_saved_season(row):
    season = dict(row)
    season.pop("user_id", None)
    season["item_type"] = "season"
    season["media_type"] = "tv"
    season["tv_tmdb_id"] = int(season["tv_tmdb_id"])
    season["season_number"] = int(season["season_number"])
    season["episode_count"] = int(season.get("episode_count") or 0)
    season["title"] = f"{season['series_title']} – Staffel {season['season_number']}"
    season["overview"] = season.pop("season_overview", None)
    season["cover_url"] = season.pop("poster_url", None)
    season["series_cover_url"] = season.pop("series_poster_url", None)
    return season


def normalize_tmdb_image_url(value):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "image.tmdb.org"
        or not parsed.path.startswith("/t/p/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return text[:1000]


def normalize_media_number(value, *, integer=False, minimum=0, maximum=None):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number < minimum or (maximum is not None and number > maximum):
        return None
    return number


def normalize_media_rating(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
        rating = int(numeric)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric != rating or not 1 <= rating <= 5:
        return None
    return rating


def validation_error(message, status=400):
    return jsonify(error=message), status


def review_length_error(review):
    limit = int(current_app.config["REVIEW_MAX_LENGTH"])
    if len(review) <= limit:
        return None
    formatted_limit = f"{limit:,}".replace(",", ".")
    return validation_error(
        f"Der Bewertungstext darf höchstens {formatted_limit} Zeichen lang sein."
    )


def search_rate_limit_error(db):
    limit = int(current_app.config["SEARCH_RATE_LIMIT_PER_MINUTE"])
    window_seconds = 60
    now = int(time())
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT window_started_at, request_count FROM search_rate_limits WHERE user_id = ?",
        (g.user["id"],),
    ).fetchone()
    if row is None or now - int(row["window_started_at"]) >= window_seconds:
        db.execute(
            """
            INSERT INTO search_rate_limits (user_id, window_started_at, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                window_started_at = excluded.window_started_at,
                request_count = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (g.user["id"], now),
        )
        db.commit()
        return None
    if int(row["request_count"]) >= limit:
        retry_after = max(1, window_seconds - (now - int(row["window_started_at"])))
        db.commit()
        response = jsonify(
            error="Zu viele Suchanfragen. Bitte warte kurz und versuche es erneut."
        )
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    db.execute(
        """
        UPDATE search_rate_limits
        SET request_count = request_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (g.user["id"],),
    )
    db.commit()
    return None


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

    if isinstance(provider, PrimaryFallbackProvider):
        provider.search_callback = lambda name, instance, method, value, result_limit: (
            cached_catalogue_search(
                get_db(),
                name,
                instance,
                method,
                value,
                result_limit,
                logger=current_app.logger,
            )
        )

    results = (
        provider.suggest(query, limit=limit)
        if suggestions
        else provider.search(query, limit=limit)
    )
    # Leere Antworten bleiben aus dem längeren L1-Cache heraus. Der persistente
    # L2-Cache hält sie lediglich 30 Sekunden, um Wiederholungen beim Tippen zu
    # dämpfen, ohne vorhandene Bücher länger unsichtbar zu machen.
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
    if len(query) > current_app.config["SEARCH_MAX_LENGTH"]:
        return validation_error(
            f"Die Suche darf höchstens {current_app.config['SEARCH_MAX_LENGTH']} Zeichen lang sein."
        )
    suggestions = request.args.get("suggest") == "1"
    if suggestions:
        limit = 6
    else:
        try:
            limit = int(request.args.get("limit", SEARCH_RESULT_LIMIT))
        except (TypeError, ValueError):
            limit = SEARCH_RESULT_LIMIT
        limit = min(20, max(1, limit))
    primary_provider = request.args.get("primary_provider", "").strip()
    fallback_provider = request.args.get("fallback_provider", "").strip()
    if primary_provider and primary_provider not in KNOWN_PROVIDERS:
        return validation_error("Ungültiger Hauptanbieter.")
    if fallback_provider and fallback_provider not in KNOWN_PROVIDERS:
        return validation_error("Ungültiger Fallback-Anbieter.")
    db = get_db()
    if error := search_rate_limit_error(db):
        return error
    selected_primary = primary_provider or current_app.config["BOOK_PROVIDER"]
    selected_fallback = fallback_provider or current_app.config["BOOK_FALLBACK_PROVIDER"]
    try:
        provider = (
            PrimaryFallbackProvider(
                selected_primary,
                selected_fallback,
            )
            if primary_provider or fallback_provider
            else get_provider()
        )
        results = cached_provider_search(provider, query, suggestions=suggestions, limit=limit)
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "Buchsuche beim Anbieter fehlgeschlagen",
            extra={
                "event": "book_search_failed",
                "provider": selected_primary,
                "fallback_provider": selected_fallback,
                "error_type": type(error).__name__,
            },
        )
        return validation_error(str(error), 503)
    prepared_results = prioritize_series_results(query, results, limit)
    return jsonify(results=attach_cached_cover_urls(db, prepared_results))


@api.get("/media/search")
def search_media():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return validation_error("Bitte mindestens zwei Zeichen eingeben.")
    if len(query) > current_app.config["SEARCH_MAX_LENGTH"]:
        return validation_error(
            f"Die Suche darf höchstens {current_app.config['SEARCH_MAX_LENGTH']} Zeichen lang sein."
        )
    try:
        limit = int(request.args.get("limit", SEARCH_RESULT_LIMIT))
    except (TypeError, ValueError):
        limit = SEARCH_RESULT_LIMIT
    limit = min(20, max(1, limit))
    if error := search_rate_limit_error(get_db()):
        return error

    provider = TMDBProvider(current_app.config.get("TMDB_READ_ACCESS_TOKEN"))
    try:
        results = cached_tmdb_search(
            get_db(), provider, query, limit, logger=current_app.logger
        )
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "Mediensuche bei TMDB fehlgeschlagen",
            extra={
                "event": "media_search_failed",
                "provider": "tmdb",
                "error_type": type(error).__name__,
            },
        )
        return validation_error(str(error), 503)
    return jsonify(results=results, provider="tmdb")


@api.get("/media")
def list_media():
    status = request.args.get("status", "").strip()
    if status and status not in VALID_MEDIA_STATUSES:
        return validation_error("Ungültiger Wiedergabestatus.")
    values = [g.user["id"]]
    where = "user_id = ?"
    if status:
        where += " AND status = ?"
        values.append(status)
    rows = get_db().execute(
        f"SELECT * FROM media_items WHERE {where} ORDER BY updated_at DESC, id DESC",
        values,
    ).fetchall()
    return jsonify(media=[serialize_media(row) for row in rows])


@api.post("/media")
def add_media():
    payload = request.get_json(silent=True) or {}
    tmdb_id = normalize_media_number(payload.get("tmdb_id"), integer=True, minimum=1)
    media_type = str(payload.get("media_type") or "").strip()
    title = str(payload.get("title") or "").strip()
    status = str(payload.get("status") or "watchlist").strip()
    if tmdb_id is None:
        return validation_error("Eine gültige TMDB-ID fehlt.")
    if media_type not in {"movie", "tv"}:
        return validation_error("Der Medientyp muss Film oder Serie sein.")
    if not title:
        return validation_error("Ein Titel ist erforderlich.")
    if len(title) > current_app.config["BOOK_TITLE_MAX_LENGTH"]:
        return validation_error(
            f"Der Titel darf höchstens {current_app.config['BOOK_TITLE_MAX_LENGTH']} Zeichen lang sein."
        )
    if status not in VALID_MEDIA_STATUSES:
        return validation_error("Ungültiger Wiedergabestatus.")

    release_year = normalize_media_number(
        payload.get("release_year"), integer=True, minimum=1870, maximum=3000
    )
    release_date = normalize_metadata_text(payload.get("release_date"), 32)
    if release_year is None and release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        release_year = normalize_media_number(
            release_date[:4], integer=True, minimum=1870, maximum=3000
        )
    timestamp_column = MEDIA_STATUS_TIMESTAMP_COLUMNS[status]
    values = {
        "user_id": g.user["id"],
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "original_title": normalize_metadata_text(payload.get("original_title"), 500),
        "overview": normalize_metadata_text(payload.get("overview"), 10000),
        "release_date": release_date,
        "release_year": release_year,
        "original_language": normalize_metadata_text(payload.get("original_language"), 16),
        "poster_url": normalize_tmdb_image_url(payload.get("cover_url")),
        "backdrop_url": normalize_tmdb_image_url(payload.get("backdrop_url")),
        "vote_average": normalize_media_number(
            payload.get("vote_average"), minimum=0, maximum=10
        ),
        "vote_count": normalize_media_number(
            payload.get("vote_count"), integer=True, minimum=0
        ) or 0,
        "status": status,
    }
    db = get_db()
    try:
        cursor = db.execute(
            f"""
            INSERT INTO media_items (
                user_id, provider, tmdb_id, media_type, title, original_title,
                overview, release_date, release_year, original_language,
                poster_url, backdrop_url, vote_average, vote_count, status,
                {timestamp_column}
            ) VALUES (
                :user_id, 'tmdb', :tmdb_id, :media_type, :title, :original_title,
                :overview, :release_date, :release_year, :original_language,
                :poster_url, :backdrop_url, :vote_average, :vote_count, :status,
                CURRENT_TIMESTAMP
            )
            """,
            values,
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        existing = db.execute(
            """
            SELECT * FROM media_items
            WHERE user_id = ? AND provider = 'tmdb' AND media_type = ? AND tmdb_id = ?
            """,
            (g.user["id"], media_type, tmdb_id),
        ).fetchone()
        if existing:
            return jsonify(error="Dieser Titel ist bereits gespeichert.", media=serialize_media(existing)), 409
        return validation_error("Der Titel konnte nicht gespeichert werden.", 409)
    row = db.execute("SELECT * FROM media_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(media=serialize_media(row)), 201


def tmdb_collection_response(movie_tmdb_id, **log_context):
    provider = TMDBProvider(current_app.config.get("TMDB_READ_ACCESS_TOKEN"))
    try:
        collection = cached_movie_collection(
            get_db(), provider, movie_tmdb_id, logger=current_app.logger
        )
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "TMDB-Filmreihe konnte nicht geladen werden",
            extra={
                "event": "media_collection_failed",
                "provider": "tmdb",
                "error_type": type(error).__name__,
                **log_context,
            },
        )
        return validation_error(str(error), 503)
    return jsonify(collection=collection)


@api.get("/media/movie/<int:tmdb_id>/collection")
def catalogue_media_collection(tmdb_id):
    if tmdb_id <= 0:
        return validation_error("Ungültige TMDB-ID.")
    return tmdb_collection_response(tmdb_id, tmdb_id=tmdb_id)


@api.get("/media/<int:media_id>/collection")
def media_collection(media_id):
    row = get_db().execute(
        "SELECT tmdb_id, media_type FROM media_items WHERE id = ? AND user_id = ?",
        (media_id, g.user["id"]),
    ).fetchone()
    if row is None:
        return validation_error("Titel nicht gefunden.", 404)
    if row["media_type"] != "movie":
        return jsonify(collection=None)
    return tmdb_collection_response(row["tmdb_id"], media_id=media_id)


@api.get("/media/seasons")
def list_saved_seasons():
    status = request.args.get("status", "").strip()
    if status and status not in VALID_MEDIA_STATUSES:
        return validation_error("Ungültiger Wiedergabestatus.")
    values = [g.user["id"]]
    where = "user_id = ?"
    if status:
        where += " AND status = ?"
        values.append(status)
    rows = get_db().execute(
        f"SELECT * FROM saved_seasons WHERE {where} ORDER BY updated_at DESC, id DESC",
        values,
    ).fetchall()
    return jsonify(seasons=[serialize_saved_season(row) for row in rows])


@api.post("/media/seasons")
def add_saved_season():
    payload = request.get_json(silent=True) or {}
    tv_tmdb_id = normalize_media_number(payload.get("tv_tmdb_id"), integer=True, minimum=1)
    season_number = normalize_media_number(payload.get("season_number"), integer=True, minimum=1)
    series_title = str(payload.get("series_title") or "").strip()
    season_title = str(payload.get("season_title") or "").strip()
    status = str(payload.get("status") or "watchlist").strip()
    if tv_tmdb_id is None or season_number is None:
        return validation_error("Eine gültige Serie und Staffel sind erforderlich.")
    if not series_title or not season_title:
        return validation_error("Serien- und Staffeltitel sind erforderlich.")
    if len(series_title) > current_app.config["BOOK_TITLE_MAX_LENGTH"]:
        return validation_error("Der Serientitel ist zu lang.")
    if len(season_title) > current_app.config["BOOK_TITLE_MAX_LENGTH"]:
        return validation_error("Der Staffeltitel ist zu lang.")
    if status not in VALID_MEDIA_STATUSES:
        return validation_error("Ungültiger Wiedergabestatus.")
    air_date = normalize_metadata_text(payload.get("air_date"), 32)
    release_year = None
    if air_date and len(air_date) >= 4 and air_date[:4].isdigit():
        release_year = normalize_media_number(
            air_date[:4], integer=True, minimum=1870, maximum=3000
        )
    timestamp_column = MEDIA_STATUS_TIMESTAMP_COLUMNS[status]
    values = {
        "user_id": g.user["id"],
        "tv_tmdb_id": tv_tmdb_id,
        "season_number": season_number,
        "series_title": series_title,
        "season_title": season_title,
        "series_overview": normalize_metadata_text(payload.get("series_overview"), 10000),
        "season_overview": normalize_metadata_text(payload.get("season_overview"), 10000),
        "air_date": air_date,
        "release_year": release_year,
        "original_language": normalize_metadata_text(payload.get("original_language"), 16),
        "poster_url": normalize_tmdb_image_url(payload.get("cover_url")),
        "series_poster_url": normalize_tmdb_image_url(payload.get("series_cover_url")),
        "backdrop_url": normalize_tmdb_image_url(payload.get("backdrop_url")),
        "episode_count": normalize_media_number(
            payload.get("episode_count"), integer=True, minimum=0
        ) or 0,
        "status": status,
    }
    db = get_db()
    try:
        cursor = db.execute(
            f"""
            INSERT INTO saved_seasons (
                user_id, provider, tv_tmdb_id, season_number, series_title,
                season_title, series_overview, season_overview, air_date,
                release_year, original_language, poster_url, series_poster_url,
                backdrop_url, episode_count, status, {timestamp_column}
            ) VALUES (
                :user_id, 'tmdb', :tv_tmdb_id, :season_number, :series_title,
                :season_title, :series_overview, :season_overview, :air_date,
                :release_year, :original_language, :poster_url, :series_poster_url,
                :backdrop_url, :episode_count, :status, CURRENT_TIMESTAMP
            )
            """,
            values,
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        existing = db.execute(
            """
            SELECT * FROM saved_seasons
            WHERE user_id = ? AND provider = 'tmdb'
              AND tv_tmdb_id = ? AND season_number = ?
            """,
            (g.user["id"], tv_tmdb_id, season_number),
        ).fetchone()
        if existing:
            return jsonify(
                error="Diese Staffel ist bereits gespeichert.",
                season=serialize_saved_season(existing),
            ), 409
        return validation_error("Die Staffel konnte nicht gespeichert werden.", 409)
    row = db.execute("SELECT * FROM saved_seasons WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(season=serialize_saved_season(row)), 201


@api.patch("/media/seasons/<int:season_id>")
def update_saved_season(season_id):
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip()
    if status not in VALID_MEDIA_STATUSES:
        return validation_error("Ungültiger Wiedergabestatus.")
    timestamp_column = MEDIA_STATUS_TIMESTAMP_COLUMNS[status]
    db = get_db()
    cursor = db.execute(
        f"""
        UPDATE saved_seasons
        SET status = ?, {timestamp_column} = COALESCE({timestamp_column}, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (status, season_id, g.user["id"]),
    )
    db.commit()
    if cursor.rowcount == 0:
        return validation_error("Staffel nicht gefunden.", 404)
    row = db.execute("SELECT * FROM saved_seasons WHERE id = ?", (season_id,)).fetchone()
    return jsonify(season=serialize_saved_season(row))


@api.delete("/media/seasons/<int:season_id>")
def delete_saved_season(season_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM saved_seasons WHERE id = ? AND user_id = ?",
        (season_id, g.user["id"]),
    )
    db.commit()
    if cursor.rowcount == 0:
        return validation_error("Staffel nicht gefunden.", 404)
    return "", 204


def tmdb_series_response(series_tmdb_id):
    provider = TMDBProvider(current_app.config.get("TMDB_READ_ACCESS_TOKEN"))
    try:
        series = cached_tv_series(
            get_db(), provider, series_tmdb_id, logger=current_app.logger
        )
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "TMDB-Staffeln konnten nicht geladen werden",
            extra={
                "event": "media_seasons_failed",
                "provider": "tmdb",
                "tmdb_id": series_tmdb_id,
                "error_type": type(error).__name__,
            },
        )
        return validation_error(str(error), 503)
    return jsonify(series=series)


@api.get("/media/tv/<int:tmdb_id>/seasons")
def catalogue_tv_seasons(tmdb_id):
    if tmdb_id <= 0:
        return validation_error("Ungültige TMDB-ID.")
    return tmdb_series_response(tmdb_id)


@api.get("/media/tv/<int:tmdb_id>/seasons/<int:season_number>")
def catalogue_tv_season(tmdb_id, season_number):
    if tmdb_id <= 0 or season_number <= 0:
        return validation_error("Ungültige Staffel.")
    provider = TMDBProvider(current_app.config.get("TMDB_READ_ACCESS_TOKEN"))
    try:
        season = cached_tv_season(
            get_db(), provider, tmdb_id, season_number, logger=current_app.logger
        )
    except ProviderUnavailable as error:
        current_app.logger.warning(
            "TMDB-Episoden konnten nicht geladen werden",
            extra={
                "event": "media_episodes_failed",
                "provider": "tmdb",
                "tmdb_id": tmdb_id,
                "season_number": season_number,
                "error_type": type(error).__name__,
            },
        )
        return validation_error(str(error), 503)
    if season is None:
        return validation_error("Staffel nicht gefunden.", 404)
    rows = get_db().execute(
        """
        SELECT episode_number, rating
        FROM episode_ratings
        WHERE user_id = ? AND tv_tmdb_id = ? AND season_number = ?
        """,
        (g.user["id"], tmdb_id, season_number),
    ).fetchall()
    ratings = {int(row["episode_number"]): int(row["rating"]) for row in rows}
    for episode in season["episodes"]:
        episode["user_rating"] = ratings.get(episode["episode_number"])
    return jsonify(season=season)


@api.patch(
    "/media/tv/<int:tmdb_id>/seasons/<int:season_number>/episodes/"
    "<int:episode_number>/rating"
)
def update_episode_rating(tmdb_id, season_number, episode_number):
    if tmdb_id <= 0 or season_number <= 0 or episode_number <= 0:
        return validation_error("Ungültige Episode.")
    payload = request.get_json(silent=True) or {}
    if "rating" not in payload:
        return validation_error("Keine Bewertung angegeben.")
    raw_rating = payload.get("rating")
    db = get_db()
    if raw_rating in (None, ""):
        db.execute(
            """
            DELETE FROM episode_ratings
            WHERE user_id = ? AND tv_tmdb_id = ?
              AND season_number = ? AND episode_number = ?
            """,
            (g.user["id"], tmdb_id, season_number, episode_number),
        )
        db.commit()
        return jsonify(rating=None)
    rating = normalize_media_rating(raw_rating)
    if rating is None:
        return validation_error("Die Bewertung muss zwischen 1 und 5 Sternen liegen.")
    db.execute(
        """
        INSERT INTO episode_ratings (
            user_id, tv_tmdb_id, season_number, episode_number, rating
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, tv_tmdb_id, season_number, episode_number)
        DO UPDATE SET rating = excluded.rating, updated_at = CURRENT_TIMESTAMP
        """,
        (g.user["id"], tmdb_id, season_number, episode_number, rating),
    )
    db.commit()
    return jsonify(rating=rating)


@api.patch("/media/<int:media_id>")
def update_media(media_id):
    payload = request.get_json(silent=True) or {}
    allowed_fields = {"status", "rating", "review"}
    if not any(field in payload for field in allowed_fields):
        return validation_error("Keine Änderung angegeben.")

    status = None
    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        if status not in VALID_MEDIA_STATUSES:
            return validation_error("Ungültiger Wiedergabestatus.")

    rating = None
    if "rating" in payload and payload.get("rating") not in (None, ""):
        rating = normalize_media_rating(payload.get("rating"))
        if rating is None:
            return validation_error("Die Bewertung muss zwischen 1 und 5 Sternen liegen.")

    review = None
    if "review" in payload:
        review = str(payload.get("review") or "").strip()
        if error := review_length_error(review):
            return error
    db = get_db()
    row = db.execute(
        "SELECT * FROM media_items WHERE id = ? AND user_id = ?",
        (media_id, g.user["id"]),
    ).fetchone()
    if row is None:
        return validation_error("Titel nicht gefunden.", 404)
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values = []
    if status is not None:
        timestamp_column = MEDIA_STATUS_TIMESTAMP_COLUMNS[status]
        assignments.extend([
            "status = ?",
            f"{timestamp_column} = COALESCE({timestamp_column}, CURRENT_TIMESTAMP)",
        ])
        values.append(status)
    if "rating" in payload:
        assignments.append("rating = ?")
        values.append(rating)
    if review is not None:
        assignments.append("review = ?")
        values.append(review)
    values.extend([media_id, g.user["id"]])
    db.execute(
        f"UPDATE media_items SET {', '.join(assignments)} WHERE id = ? AND user_id = ?",
        values,
    )
    db.commit()
    updated = db.execute("SELECT * FROM media_items WHERE id = ?", (media_id,)).fetchone()
    return jsonify(media=serialize_media(updated))


@api.delete("/media/<int:media_id>")
def delete_media(media_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM media_items WHERE id = ? AND user_id = ?",
        (media_id, g.user["id"]),
    )
    db.commit()
    if cursor.rowcount == 0:
        return validation_error("Titel nicht gefunden.", 404)
    return "", 204


@api.get("/media/watch-history")
def media_watch_history():
    user_id = g.user["id"]
    rows = get_db().execute(
        """
        WITH titles AS (
            SELECT id, media_type AS kind, title, completed_at
            FROM media_items WHERE user_id = ?
            UNION ALL
            SELECT id, 'season', series_title || ' – ' || season_title, completed_at
            FROM saved_seasons WHERE user_id = ?
        )
        SELECT kind, title, completed_at AS watched_at, 0 AS rewatch
        FROM titles WHERE completed_at IS NOT NULL AND completed_at != ''
        UNION ALL
        SELECT kind, title, rewatches.watched_on, 1
        FROM titles
        JOIN media_rewatches AS rewatches
          ON (titles.kind = 'season' AND rewatches.season_id = titles.id)
          OR (titles.kind != 'season' AND rewatches.media_id = titles.id)
        ORDER BY watched_at DESC, title
        """,
        (user_id, user_id),
    ).fetchall()
    return jsonify(events=[{**dict(row), "rewatch": bool(row["rewatch"])} for row in rows])


@api.route("/media/<int:item_id>/rewatches", methods=["GET", "POST"])
@api.route("/media/seasons/<int:item_id>/rewatches", defaults={"season": True}, methods=["GET", "POST"])
def media_rewatches(item_id, season=False):
    table, foreign_key = ("saved_seasons", "season_id") if season else ("media_items", "media_id")
    db = get_db()
    user_id = g.user["id"]
    item = db.execute(
        f"SELECT status FROM {table} WHERE id = ? AND user_id = ?", (item_id, user_id)
    ).fetchone()
    if item is None:
        return validation_error("Eintrag nicht gefunden.", 404)

    if request.method == "POST":
        payload = request.get_json(silent=True)
        watched_on = payload.get("watched_on") if isinstance(payload, dict) else None
        try:
            if date.fromisoformat(watched_on).isoformat() != watched_on:
                raise ValueError
        except (TypeError, ValueError):
            return validation_error("Bitte gib ein gültiges Datum an.")

        saved = db.execute(
            f"""
            INSERT INTO media_rewatches ({foreign_key}, watched_on)
            SELECT id, ? FROM {table}
            WHERE id = ? AND user_id = ? AND status = 'completed'
            """,
            (watched_on, item_id, user_id),
        )
        db.commit()
        if not saved.rowcount:
            return validation_error("Setze den Eintrag zuerst auf Completed.", 409)

    rows = db.execute(
        f"""
        SELECT rewatches.watched_on
        FROM media_rewatches AS rewatches
        JOIN {table} AS item ON item.id = rewatches.{foreign_key}
        WHERE item.id = ? AND item.user_id = ?
        ORDER BY rewatches.watched_on DESC, rewatches.id DESC
        """,
        (item_id, user_id),
    ).fetchall()
    return jsonify(rewatches=[row["watched_on"] for row in rows]), 201 if request.method == "POST" else 200


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
    books = [serialize_book(row) for row in rows]
    return jsonify(books=attach_cached_cover_urls(db, books))


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
    return jsonify(series=attach_cached_cover_urls(db, result), status=status)


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
    return jsonify(series=attach_cached_cover_urls(db, result), status=status)


@api.post("/books")
def create_book():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title") or "").strip()
    authors = normalize_authors(payload.get("authors"))
    status = payload.get("status", "want_to_read")
    if not title:
        return validation_error("Ein Titel ist erforderlich.")
    if len(title) > current_app.config["BOOK_TITLE_MAX_LENGTH"]:
        return validation_error(
            f"Der Titel darf höchstens {current_app.config['BOOK_TITLE_MAX_LENGTH']} Zeichen lang sein."
        )
    if len(authors) > current_app.config["BOOK_AUTHORS_MAX_LENGTH"]:
        return validation_error(
            "Die Autorenangabe darf höchstens "
            f"{current_app.config['BOOK_AUTHORS_MAX_LENGTH']} Zeichen lang sein."
        )
    if status not in VALID_STATUSES:
        return validation_error("Ungültiger Lesestatus.")

    rating = payload.get("rating")
    if rating in ("", None):
        rating = None
    elif isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return validation_error("Die Bewertung muss zwischen 1 und 5 Sternen liegen.")
    review = str(payload.get("review") or "").strip()
    if error := review_length_error(review):
        return error

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
        book = attach_cached_cover_urls(db, serialize_book(duplicate))
        return jsonify(error="Dieses Buch ist bereits in deiner Sammlung.", book=book), 409

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
    return jsonify(book=attach_cached_cover_urls(db, serialize_book(row))), 201


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
        if error := review_length_error(review):
            return error
        updates.append("review = ?")
        values.append(review)
        changed_fields.append("review")

    if not updates:
        return jsonify(book=attach_cached_cover_urls(db, serialize_book(existing)))

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
    return jsonify(book=attach_cached_cover_urls(db, serialize_book(row)))


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

