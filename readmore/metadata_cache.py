import json
import sqlite3
import time
from time import monotonic


STALE_LOCK_SECONDS = 5 * 60
MAX_RETRY_DELAY_SECONDS = 6 * 60 * 60


def _connect(database_path):
    db = sqlite3.connect(database_path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def enqueue_metadata_lookup(db, book_id, provider="open_library"):
    db.execute(
        """
        INSERT INTO metadata_lookups (book_id, provider, status, next_attempt_at)
        VALUES (?, ?, 'pending', 0)
        ON CONFLICT(book_id) DO UPDATE SET
            status = CASE
                WHEN metadata_lookups.status = 'running'
                     AND COALESCE(metadata_lookups.locked_at, 0) < ?
                THEN 'pending'
                ELSE metadata_lookups.status
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (book_id, provider, int(time.time()) - STALE_LOCK_SECONDS),
    )
    db.commit()


def enqueue_existing_metadata(db, provider="open_library"):
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO metadata_lookups (
            book_id, provider, status, next_attempt_at
        )
        SELECT id, ?, 'pending', 0
        FROM books
        WHERE provider_book_id IS NOT NULL AND provider_book_id != ''
        """,
        (provider,),
    )
    db.commit()
    return max(cursor.rowcount, 0)


def metadata_lookup_status(db, book_id):
    row = db.execute(
        "SELECT status FROM metadata_lookups WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    return row["status"] if row else "missing"


def _claim_next_job(db):
    now = int(time.time())
    db.execute("BEGIN IMMEDIATE")
    job = db.execute(
        """
        SELECT l.book_id, l.provider, l.attempts,
               b.provider_book_id, b.provider_edition_id
        FROM metadata_lookups l
        JOIN books b ON b.id = l.book_id
        WHERE (
            l.status IN ('pending', 'retry') AND l.next_attempt_at <= ?
        ) OR (
            l.status = 'running' AND COALESCE(l.locked_at, 0) <= ?
        )
        ORDER BY l.next_attempt_at, l.updated_at
        LIMIT 1
        """,
        (now, now - STALE_LOCK_SECONDS),
    ).fetchone()
    if job is None:
        db.commit()
        return None
    db.execute(
        """
        UPDATE metadata_lookups
        SET status = 'running', locked_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE book_id = ?
        """,
        (now, job["book_id"]),
    )
    db.commit()
    return dict(job)


def _clean_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    result = {}
    for field in (
        "provider_edition_id",
        "isbn",
        "publisher",
        "publish_date",
        "page_count",
        "language",
        "description",
        "physical_format",
        "subtitle",
    ):
        value = metadata.get(field)
        if value not in (None, ""):
            result[field] = value
    subjects = metadata.get("subjects")
    if isinstance(subjects, list):
        result["subjects"] = [str(subject).strip() for subject in subjects if str(subject).strip()][:10]
    return result


def persist_metadata_result(db, job, metadata):
    metadata = _clean_metadata(metadata)
    columns = {
        "provider_edition_id": "provider_edition_id",
        "isbn": "isbn",
        "publisher": "publisher",
        "publish_date": "publish_date",
        "page_count": "page_count",
        "language": "language",
        "description": "description",
        "physical_format": "physical_format",
        "subtitle": "subtitle",
    }
    updates = []
    values = []
    for field, column in columns.items():
        if field in metadata:
            updates.append(f"{column} = ?")
            values.append(metadata[field])
    if "subjects" in metadata:
        updates.append("subjects_json = ?")
        values.append(json.dumps(metadata["subjects"], ensure_ascii=False))
    if updates:
        values.append(job["book_id"])
        try:
            db.execute(
                f"UPDATE books SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        except sqlite3.IntegrityError:
            # Eine ISBN kann bereits zu einer anderen Ausgabe gehören. Die
            # übrigen Metadaten bleiben davon unabhängig speicherbar.
            if "isbn = ?" in updates:
                isbn_index = updates.index("isbn = ?")
                del updates[isbn_index]
                del values[isbn_index]
                if updates:
                    db.execute(
                        f"UPDATE books SET {', '.join(updates)} WHERE id = ?",
                        values,
                    )

    cached_edition_id = metadata.get("provider_edition_id") or job.get("provider_edition_id")
    cache_key = f"{job['provider']}:{job['provider_book_id']}:{cached_edition_id or ''}"
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
            job["provider"],
            job["provider_book_id"],
            cached_edition_id,
            json.dumps(metadata, ensure_ascii=False),
            int(time.time()),
        ),
    )
    db.execute(
        """
        UPDATE metadata_lookups
        SET status = 'ready', attempts = 0, next_attempt_at = 0,
            locked_at = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE book_id = ?
        """,
        (job["book_id"],),
    )
    db.commit()


def _mark_retry(db, job, error):
    attempts = int(job.get("attempts") or 0) + 1
    delay = min(MAX_RETRY_DELAY_SECONDS, 2 ** min(attempts, 12) * 2)
    db.execute(
        """
        UPDATE metadata_lookups
        SET status = 'retry', attempts = ?, next_attempt_at = ?, locked_at = NULL,
            last_error = ?, updated_at = CURRENT_TIMESTAMP
        WHERE book_id = ?
        """,
        (attempts, int(time.time()) + delay, str(error)[:500], job["book_id"]),
    )
    db.commit()
    return attempts, delay


def process_next_metadata_job(database_path, provider, logger=None):
    db = _connect(database_path)
    try:
        job = _claim_next_job(db)
        if job is None:
            return False
        started_at = monotonic()
        try:
            cache_key = f"{job['provider']}:{job['provider_book_id']}:{job.get('provider_edition_id') or ''}"
            cached = db.execute(
                "SELECT metadata_json FROM book_metadata_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            try:
                metadata = json.loads(cached["metadata_json"]) if cached else None
            except (TypeError, ValueError):
                metadata = None
            if not metadata:
                metadata = provider.metadata(
                    job["provider_book_id"],
                    job.get("provider_edition_id"),
                )
            persist_metadata_result(db, job, metadata)
            if logger:
                logger.info(
                    "Buchmetadaten im Hintergrund gespeichert",
                    extra={
                        "event": "metadata_lookup_completed",
                        "book_id": job["book_id"],
                        "provider": job["provider"],
                        "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    },
                )
        except Exception as error:
            attempts, delay = _mark_retry(db, job, error)
            if logger:
                logger.warning(
                    "Metadatenabfrage fehlgeschlagen; neuer Versuch wurde eingeplant",
                    extra={
                        "event": "metadata_lookup_retry_scheduled",
                        "book_id": job["book_id"],
                        "provider": job["provider"],
                        "attempt": attempts,
                        "retry_in_seconds": delay,
                        "error_type": type(error).__name__,
                    },
                )
        return True
    finally:
        db.close()
