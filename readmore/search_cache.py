import hashlib
import json
import unicodedata
from time import time


SUGGESTION_TTL_SECONDS = 24 * 60 * 60
SEARCH_TTL_SECONDS = 7 * 24 * 60 * 60
EMPTY_TTL_SECONDS = 30
MAX_CACHE_ENTRIES = 2000
CACHE_FORMAT_VERSION = 1


def cached_catalogue_search(db, provider_name, provider, method, query, limit, logger=None):
    search_kind = "suggest" if method == "suggest" else "search"
    query_hash = _query_hash(query)
    now = int(time())
    row = db.execute(
        """
        SELECT results_json, is_empty, fetched_at
        FROM catalogue_search_cache
        WHERE provider = ? AND query_hash = ? AND search_kind = ? AND result_limit = ?
        """,
        (provider_name, query_hash, search_kind, limit),
    ).fetchone()
    if row is not None:
        ttl = _ttl(search_kind, bool(row["is_empty"]))
        if now - int(row["fetched_at"]) < ttl:
            try:
                results = json.loads(row["results_json"])
            except (TypeError, ValueError):
                results = None
            if isinstance(results, list):
                _debug_log(logger, "catalogue_search_l2_hit", provider_name, search_kind)
                return results
        db.execute(
            """
            DELETE FROM catalogue_search_cache
            WHERE provider = ? AND query_hash = ? AND search_kind = ? AND result_limit = ?
            """,
            (provider_name, query_hash, search_kind, limit),
        )
        db.commit()

    _debug_log(logger, "catalogue_search_l2_miss", provider_name, search_kind)
    results = getattr(provider, method)(query, limit=limit)
    results = results if isinstance(results, list) else list(results or [])
    db.execute(
        """
        INSERT INTO catalogue_search_cache (
            provider, query_hash, search_kind, result_limit,
            results_json, is_empty, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, query_hash, search_kind, result_limit) DO UPDATE SET
            results_json = excluded.results_json,
            is_empty = excluded.is_empty,
            fetched_at = excluded.fetched_at
        """,
        (
            provider_name,
            query_hash,
            search_kind,
            limit,
            json.dumps(results, ensure_ascii=False, separators=(",", ":")),
            int(not results),
            now,
        ),
    )
    _trim_cache(db)
    db.commit()
    return results


def _query_hash(query):
    normalized = unicodedata.normalize("NFKC", str(query or "")).casefold()
    normalized = " ".join(normalized.split())
    payload = f"{CACHE_FORMAT_VERSION}\0{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ttl(search_kind, is_empty):
    if is_empty:
        return EMPTY_TTL_SECONDS
    return SUGGESTION_TTL_SECONDS if search_kind == "suggest" else SEARCH_TTL_SECONDS


def _trim_cache(db):
    count = db.execute("SELECT COUNT(*) FROM catalogue_search_cache").fetchone()[0]
    overflow = int(count) - MAX_CACHE_ENTRIES
    if overflow <= 0:
        return
    db.execute(
        """
        DELETE FROM catalogue_search_cache
        WHERE rowid IN (
            SELECT rowid
            FROM catalogue_search_cache
            ORDER BY fetched_at ASC, rowid ASC
            LIMIT ?
        )
        """,
        (overflow,),
    )


def _debug_log(logger, event, provider, search_kind):
    if logger is None:
        return
    logger.debug(
        "Persistenter Buchsuchcache",
        extra={
            "event": event,
            "provider": provider,
            "cache_layer": "sqlite",
            "search_kind": search_kind,
        },
    )
