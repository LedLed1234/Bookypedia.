import hashlib
import json
import unicodedata
from time import time

from .providers.base import ProviderUnavailable


SEARCH_TTL_SECONDS = 24 * 60 * 60
MOVIE_COLLECTION_TTL_SECONDS = 7 * 24 * 60 * 60
TV_SERIES_TTL_SECONDS = 12 * 60 * 60
TV_SEASON_TTL_SECONDS = 24 * 60 * 60
STALE_FALLBACK_SECONDS = 30 * 24 * 60 * 60
MAX_CACHE_ENTRIES = 5000
CACHE_FORMAT_VERSION = 1


def cached_tmdb_search(db, provider, query, limit, logger=None):
    normalized = unicodedata.normalize("NFKC", str(query or "")).casefold()
    normalized = " ".join(normalized.split())
    digest = hashlib.sha256(
        f"{CACHE_FORMAT_VERSION}\0{normalized}".encode("utf-8")
    ).hexdigest()
    return cached_tmdb_resource(
        db,
        cache_key=f"search:{limit}:{digest}",
        resource_type="search",
        ttl_seconds=SEARCH_TTL_SECONDS,
        fetch=lambda: provider.search(query, limit=limit),
        logger=logger,
    )


def cached_movie_collection(db, provider, movie_id, logger=None):
    return cached_tmdb_resource(
        db,
        cache_key=f"movie_collection:{int(movie_id)}",
        resource_type="movie_collection",
        ttl_seconds=MOVIE_COLLECTION_TTL_SECONDS,
        fetch=lambda: provider.movie_collection(movie_id),
        logger=logger,
    )


def cached_tv_series(db, provider, series_id, logger=None):
    return cached_tmdb_resource(
        db,
        cache_key=f"tv_series:{int(series_id)}",
        resource_type="tv_series",
        ttl_seconds=TV_SERIES_TTL_SECONDS,
        fetch=lambda: provider.tv_seasons(series_id),
        logger=logger,
    )


def cached_tv_season(db, provider, series_id, season_number, logger=None):
    return cached_tmdb_resource(
        db,
        cache_key=f"tv_season:{int(series_id)}:{int(season_number)}",
        resource_type="tv_season",
        ttl_seconds=TV_SEASON_TTL_SECONDS,
        fetch=lambda: provider.tv_season(series_id, season_number),
        logger=logger,
    )


def cached_tmdb_resource(
    db,
    *,
    cache_key,
    resource_type,
    ttl_seconds,
    fetch,
    logger=None,
):
    now = int(time())
    row = db.execute(
        "SELECT payload_json, fetched_at FROM tmdb_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    cached_payload = _decode(row["payload_json"]) if row is not None else _MISSING
    age = now - int(row["fetched_at"]) if row is not None else None
    if cached_payload is not _MISSING and age < ttl_seconds:
        _log(logger, "tmdb_cache_hit", resource_type, cache_key, stale=False)
        return cached_payload

    _log(logger, "tmdb_cache_miss", resource_type, cache_key, stale=False)
    try:
        payload = fetch()
    except ProviderUnavailable:
        if (
            cached_payload is not _MISSING
            and age is not None
            and age < STALE_FALLBACK_SECONDS
        ):
            _log(logger, "tmdb_cache_hit", resource_type, cache_key, stale=True)
            return cached_payload
        raise

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    db.execute(
        """
        INSERT INTO tmdb_cache (cache_key, resource_type, payload_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            resource_type = excluded.resource_type,
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (cache_key, resource_type, encoded, now),
    )
    _trim_cache(db)
    db.commit()
    return payload


class _Missing:
    pass


_MISSING = _Missing()


def _decode(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return _MISSING


def _trim_cache(db):
    count = db.execute("SELECT COUNT(*) FROM tmdb_cache").fetchone()[0]
    overflow = int(count) - MAX_CACHE_ENTRIES
    if overflow <= 0:
        return
    db.execute(
        """
        DELETE FROM tmdb_cache
        WHERE cache_key IN (
            SELECT cache_key FROM tmdb_cache
            ORDER BY fetched_at ASC, cache_key ASC
            LIMIT ?
        )
        """,
        (overflow,),
    )


def _log(logger, event, resource_type, cache_key, *, stale):
    if logger is None:
        return
    logger.debug(
        "Persistenter TMDB-Cache",
        extra={
            "event": event,
            "provider": "tmdb",
            "cache_layer": "sqlite",
            "resource_type": resource_type,
            "cache_key": cache_key,
            "stale": stale,
        },
    )
