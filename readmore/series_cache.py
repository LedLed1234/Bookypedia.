import re
import sqlite3
import threading
import time
import unicodedata
from time import monotonic

from .metadata_cache import process_next_metadata_job
from .providers import create_provider


PROVIDER_NAME = "open_library"
NO_SERIES_RECHECK_SECONDS = 30 * 24 * 60 * 60
STALE_LOCK_SECONDS = 5 * 60
MAX_RETRY_DELAY_SECONDS = 6 * 60 * 60
SERIES_METADATA_VERSION = 5


def _connect(database_path):
    db = sqlite3.connect(database_path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def _authors_text(authors):
    if isinstance(authors, str):
        return authors.strip()
    return ", ".join(str(author).strip() for author in (authors or []) if str(author).strip())


def _series_identity(series):
    provider_series_id = str(series.get("provider_series_id") or "").strip()
    if provider_series_id:
        return f"id:{provider_series_id}"
    name = unicodedata.normalize("NFKD", str(series.get("name") or ""))
    name = "".join(character for character in name if not unicodedata.combining(character))
    return f"name:{re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')}"


def _position_key(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip().casefold()
    return str(int(number)) if number.is_integer() else str(number)


def _series_book_sort_key(book):
    try:
        position = float(book.get("series_position"))
    except (TypeError, ValueError):
        position = float("inf")
    return (
        position,
        book.get("first_publish_year") is None,
        book.get("first_publish_year") or 0,
        str(book.get("title") or "").casefold(),
    )


def _merge_cached_incomplete_members(db, series_id, books):
    """Do not let a partial provider response delete previously found volumes."""
    merged = list(books)
    seen_ids = {
        str(book.get("provider_book_id") or "").strip()
        for book in merged
        if book.get("provider_book_id")
    }
    seen_positions = {
        key for key in (_position_key(book.get("series_position")) for book in merged) if key
    }
    cached = db.execute(
        "SELECT * FROM series_members WHERE series_id = ? ORDER BY sort_order",
        (series_id,),
    ).fetchall()
    for member in cached:
        member_id = str(member["provider_book_id"] or "").strip()
        position_key = _position_key(member["position"])
        if member_id in seen_ids or (position_key and position_key in seen_positions):
            continue
        merged.append(
            {
                "provider_book_id": member_id,
                "provider_edition_id": member["provider_edition_id"],
                "title": member["title"],
                "authors": [
                    author.strip() for author in member["authors"].split(",") if author.strip()
                ],
                "isbn": member["isbn"],
                "cover_url": member["cover_url"],
                "first_publish_year": member["first_publish_year"],
                "publish_date": member["publish_date"],
                "page_count": member["page_count"],
                "series_position": member["position"],
            }
        )
        seen_ids.add(member_id)
        if position_key:
            seen_positions.add(position_key)
    merged.sort(key=_series_book_sort_key)
    return merged


def enqueue_series_lookup(db, provider_book_id, authors=None, provider=PROVIDER_NAME):
    provider_book_id = str(provider_book_id or "").strip()
    if not provider_book_id:
        return False
    db.execute(
        """
        INSERT INTO series_lookups (
            provider, provider_book_id, authors, status, next_attempt_at
        ) VALUES (?, ?, ?, 'pending', 0)
        ON CONFLICT(provider, provider_book_id) DO UPDATE SET
            authors = CASE
                WHEN series_lookups.authors = '' THEN excluded.authors
                ELSE series_lookups.authors
            END,
            status = CASE
                WHEN series_lookups.status = 'running'
                     AND COALESCE(series_lookups.locked_at, 0) < ?
                THEN 'pending'
                ELSE series_lookups.status
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            provider,
            provider_book_id,
            _authors_text(authors),
            int(time.time()) - STALE_LOCK_SECONDS,
        ),
    )
    db.commit()
    return True


def enqueue_existing_books(db, provider=PROVIDER_NAME):
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO series_lookups (
            provider, provider_book_id, authors, status, next_attempt_at
        )
        SELECT COALESCE(NULLIF(provider, ''), ?), provider_book_id, authors, 'pending', 0
        FROM books
        WHERE provider_book_id IS NOT NULL AND provider_book_id != ''
        """,
        (provider,),
    )
    db.commit()
    return max(cursor.rowcount, 0)


def get_cached_series(db, provider_book_id, provider=PROVIDER_NAME):
    lookup = db.execute(
        """
        SELECT status, series_id, current_position, attempts, last_error
        FROM series_lookups
        WHERE provider = ? AND provider_book_id = ?
        """,
        (provider, provider_book_id),
    ).fetchone()
    if lookup is None:
        return None, "missing"
    if lookup["series_id"] is None:
        return None, lookup["status"]

    series = db.execute("SELECT * FROM series WHERE id = ?", (lookup["series_id"],)).fetchone()
    if series is None:
        # Selbstheilung, falls ein Cache-Datensatz manuell entfernt oder beschädigt wurde.
        db.execute(
            """
            UPDATE series_lookups
            SET status = 'pending', series_id = NULL, current_position = NULL,
                next_attempt_at = 0, locked_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE provider = ? AND provider_book_id = ?
            """,
            (provider, provider_book_id),
        )
        db.commit()
        return None, "missing"
    members = db.execute(
        """
        SELECT sm.*,
               COALESCE(
                   sm.page_count,
                   (SELECT MAX(b.page_count)
                    FROM books b
                    WHERE b.provider = ? AND b.provider_book_id = sm.provider_book_id)
               ) AS resolved_page_count
        FROM series_members sm
        WHERE sm.series_id = ?
        ORDER BY sm.sort_order, sm.provider_book_id
        """,
        (provider, series["id"]),
    ).fetchall()
    books = []
    for member in members:
        books.append(
            {
                "provider": provider,
                "provider_book_id": member["provider_book_id"],
                "provider_edition_id": member["provider_edition_id"],
                "title": member["title"],
                "authors": [
                    author.strip() for author in member["authors"].split(",") if author.strip()
                ],
                "isbn": member["isbn"],
                "cover_url": member["cover_url"],
                "first_publish_year": member["first_publish_year"],
                "publish_date": member["publish_date"],
                "page_count": member["resolved_page_count"],
                "series_position": member["position"],
            }
        )
    return (
        {
            "name": series["name"],
            "provider_series_id": series["provider_series_id"],
            "current_position": lookup["current_position"],
            "source": series["source"],
            "incomplete": bool(series["incomplete"]),
            "books": books,
        },
        lookup["status"],
    )


def persist_series_result(db, provider_book_id, authors, result, provider=PROVIDER_NAME):
    now = int(time.time())
    if not result:
        db.execute(
            """
            UPDATE series_lookups
            SET status = 'no_series', series_id = NULL, current_position = NULL,
                attempts = 0, next_attempt_at = ?, locked_at = NULL,
                last_error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE provider = ? AND provider_book_id = ?
            """,
            (now + NO_SERIES_RECHECK_SECONDS, provider, provider_book_id),
        )
        db.commit()
        return

    identity = _series_identity(result)
    db.execute(
        """
        INSERT INTO series (
            provider, identity_key, provider_series_id, name, source,
            incomplete, metadata_version, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, identity_key) DO UPDATE SET
            provider_series_id = excluded.provider_series_id,
            name = excluded.name,
            source = excluded.source,
            incomplete = excluded.incomplete,
            metadata_version = excluded.metadata_version,
            fetched_at = excluded.fetched_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            provider,
            identity,
            result.get("provider_series_id"),
            str(result.get("name") or "Unbenannte Reihe"),
            str(result.get("source") or "unknown"),
            int(bool(result.get("incomplete"))),
            SERIES_METADATA_VERSION,
            now,
        ),
    )
    series_id = db.execute(
        "SELECT id FROM series WHERE provider = ? AND identity_key = ?",
        (provider, identity),
    ).fetchone()["id"]
    result_books = list(result.get("books") or [])
    if result.get("incomplete"):
        result_books = _merge_cached_incomplete_members(db, series_id, result_books)
    db.execute("DELETE FROM series_members WHERE series_id = ?", (series_id,))

    members = []
    seen = set()
    for sort_order, book in enumerate(result_books):
        member_id = str(book.get("provider_book_id") or "").strip()
        title = str(book.get("title") or "").strip()
        if not member_id or not title or member_id in seen:
            continue
        seen.add(member_id)
        member = (
            series_id,
            member_id,
            title,
            _authors_text(book.get("authors") or authors),
            book.get("isbn"),
            book.get("provider_edition_id"),
            book.get("cover_url"),
            book.get("first_publish_year"),
            book.get("publish_date"),
            book.get("page_count"),
            str(book.get("series_position")) if book.get("series_position") is not None else None,
            sort_order,
        )
        members.append(member)
    db.executemany(
        """
        INSERT INTO series_members (
            series_id, provider_book_id, title, authors, isbn, provider_edition_id,
            cover_url, first_publish_year, publish_date, page_count, position, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        members,
    )

    current_position = result.get("current_position")
    db.execute(
        """
        UPDATE series_lookups
        SET status = 'ready', series_id = ?, current_position = ?, attempts = 0,
            next_attempt_at = 0, locked_at = NULL, last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE provider = ? AND provider_book_id = ?
        """,
        (series_id, current_position, provider, provider_book_id),
    )

    for member in members:
        member_id = member[1]
        member_authors = member[3]
        member_position = member[10]
        db.execute(
            """
            INSERT INTO series_lookups (
                provider, provider_book_id, authors, status, series_id,
                current_position, attempts, next_attempt_at
            ) VALUES (?, ?, ?, 'ready', ?, ?, 0, 0)
            ON CONFLICT(provider, provider_book_id) DO UPDATE SET
                authors = excluded.authors,
                status = 'ready',
                series_id = excluded.series_id,
                current_position = excluded.current_position,
                attempts = 0,
                next_attempt_at = 0,
                locked_at = NULL,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider, member_id, member_authors, series_id, member_position),
        )

    saved_books = db.execute(
        """
        SELECT b.id, l.current_position
        FROM books b
        JOIN series_lookups l
          ON l.provider = ? AND l.provider = b.provider
         AND l.provider_book_id = b.provider_book_id
        WHERE l.series_id = ?
        """,
        (provider, series_id),
    ).fetchall()
    for book in saved_books:
        db.execute(
            """
            INSERT INTO book_series (book_id, series_id, position)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id, series_id) DO UPDATE SET position = excluded.position
            """,
            (book["id"], series_id, book["current_position"]),
        )
    db.commit()


def _claim_next_job(db):
    now = int(time.time())
    stale_before = now - STALE_LOCK_SECONDS
    db.execute("BEGIN IMMEDIATE")
    job = db.execute(
        """
        SELECT provider, provider_book_id, authors, attempts
        FROM series_lookups
        WHERE (
            status IN ('pending', 'retry', 'no_series') AND next_attempt_at <= ?
        ) OR (
            status = 'running' AND COALESCE(locked_at, 0) <= ?
        )
        ORDER BY next_attempt_at, updated_at
        LIMIT 1
        """,
        (now, stale_before),
    ).fetchone()
    if job is None:
        db.commit()
        return None
    db.execute(
        """
        UPDATE series_lookups
        SET status = 'running', locked_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE provider = ? AND provider_book_id = ?
        """,
        (now, job["provider"], job["provider_book_id"]),
    )
    db.commit()
    return dict(job)


def _mark_retry(db, job, error):
    attempts = int(job.get("attempts") or 0) + 1
    delay = min(MAX_RETRY_DELAY_SECONDS, 2 ** min(attempts, 12) * 2)
    db.execute(
        """
        UPDATE series_lookups
        SET status = 'retry', attempts = ?, next_attempt_at = ?, locked_at = NULL,
            last_error = ?, updated_at = CURRENT_TIMESTAMP
        WHERE provider = ? AND provider_book_id = ?
        """,
        (
            attempts,
            int(time.time()) + delay,
            str(error)[:500],
            job["provider"],
            job["provider_book_id"],
        ),
    )
    db.commit()
    return attempts, delay


def process_next_series_job(database_path, provider, logger=None):
    db = _connect(database_path)
    try:
        job = _claim_next_job(db)
        if job is None:
            return False
        started_at = monotonic()
        if logger:
            logger.debug(
                "Reihenabfrage gestartet",
                extra={
                    "event": "series_lookup_started",
                    "provider": job["provider"],
                    "provider_book_id": job["provider_book_id"],
                    "attempt": int(job.get("attempts") or 0) + 1,
                },
            )
        try:
            selected_provider = provider(job["provider"]) if callable(provider) else provider
            result = selected_provider.series(
                job["provider_book_id"],
                authors=[author.strip() for author in job["authors"].split(",") if author.strip()],
                limit=24,
            )
            persist_series_result(
                db,
                job["provider_book_id"],
                job["authors"],
                result,
                provider=job["provider"],
            )
            if logger:
                logger.info(
                    "Reihenabfrage abgeschlossen",
                    extra={
                        "event": "series_lookup_completed",
                        "provider": job["provider"],
                        "provider_book_id": job["provider_book_id"],
                        "lookup_status": "ready" if result else "no_series",
                        "member_count": len(result.get("books") or []) if result else 0,
                        "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    },
                )
        except Exception as error:
            attempts, delay = _mark_retry(db, job, error)
            if logger:
                logger.warning(
                    "Reihenabfrage fehlgeschlagen; neuer Versuch wurde eingeplant",
                    extra={
                        "event": "series_lookup_retry_scheduled",
                        "provider": job["provider"],
                        "provider_book_id": job["provider_book_id"],
                        "attempt": attempts,
                        "retry_in_seconds": delay,
                        "duration_ms": round((monotonic() - started_at) * 1000, 2),
                        "error_type": type(error).__name__,
                    },
                )
        return True
    finally:
        db.close()


class SeriesWorker:
    def __init__(self, app):
        self.database_path = app.config["DATABASE"]
        self.provider_name = app.config.get("BOOK_PROVIDER", PROVIDER_NAME)
        self.fallback_provider_name = app.config.get("BOOK_FALLBACK_PROVIDER")
        self.poll_interval = app.config.get("SERIES_WORKER_POLL_INTERVAL", 1.0)
        self.logger = app.logger
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="bookypedia-series-worker",
            daemon=True,
        )

    def start(self):
        self._thread.start()
        self.logger.info(
            "Hintergrund-Worker für Buchreihen gestartet",
            extra={
                "event": "series_worker_started",
                "provider": self.provider_name,
                "fallback_provider": self.fallback_provider_name,
            },
        )

    def wake(self):
        self._wake_event.set()

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()

    def _run(self):
        providers = {}

        def provider_for(name):
            if name not in providers:
                providers[name] = create_provider(name)
            return providers[name]

        while not self._stop_event.is_set():
            try:
                processed_metadata = process_next_metadata_job(
                    self.database_path, provider_for, logger=self.logger
                )
                processed_series = process_next_series_job(
                    self.database_path, provider_for, logger=self.logger
                )
                processed = processed_metadata or processed_series
            except Exception as error:
                self.logger.exception(
                    "Der Hintergrundjob für Buchdaten ist fehlgeschlagen",
                    extra={
                        "event": "series_worker_error",
                        "provider": self.provider_name,
                        "error_type": type(error).__name__,
                    },
                )
                processed = False
            if processed:
                continue
            self._wake_event.wait(self.poll_interval)
            self._wake_event.clear()


def start_series_worker(app):
    worker = SeriesWorker(app)
    app.extensions["series_worker"] = worker
    worker.start()
    return worker


def wake_series_worker(app):
    worker = app.extensions.get("series_worker")
    if worker is not None:
        worker.wake()
