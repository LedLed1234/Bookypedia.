import hashlib
import os
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app, redirect, send_file


MAX_COVER_BYTES = 8 * 1024 * 1024
DOWNLOAD_TIMEOUT = (3.05, 12)
_DOWNLOAD_LOCKS = [Lock() for _index in range(16)]


def _allowed_source(source_url):
    try:
        parsed = urlparse(str(source_url or "").strip())
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        return False
    if port not in (None, 443):
        return False
    return (
        hostname == "covers.openlibrary.org"
        or hostname == "books.google.com"
        or hostname == "books.googleusercontent.com"
        or hostname.endswith(".googleusercontent.com")
    )


def _allowed_download_response(response_url):
    if _allowed_source(response_url):
        return True
    try:
        parsed = urlparse(str(response_url or "").strip())
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
        and (hostname == "archive.org" or hostname.endswith(".archive.org"))
    )


def _cache_key(source_url):
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def attach_cached_cover_urls(db, payload):
    """Add local cover URLs without replacing the provider's original URL."""
    assets = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        source_url = str(value.get("cover_url") or "").strip()
        if source_url:
            if _allowed_source(source_url):
                key = _cache_key(source_url)
                value["cover_src"] = f"/covers/{key}"
                assets[key] = source_url
            else:
                value["cover_src"] = source_url
        for child in value.values():
            visit(child)

    visit(payload)
    if assets:
        db.executemany(
            """
            INSERT INTO cover_cache (cache_key, source_url)
            VALUES (?, ?)
            ON CONFLICT(cache_key) DO NOTHING
            """,
            assets.items(),
        )
        db.commit()
    return payload


def _detected_image_type(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _download_cover(source_url):
    response = None
    request_url = source_url
    for _redirect in range(6):
        response = requests.get(
            request_url,
            headers={"User-Agent": "Epiloguehouse/1.0 (cover cache)"},
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            break
        redirect_url = urljoin(response.url, response.headers.get("Location", ""))
        response.close()
        if not _allowed_download_response(redirect_url):
            raise ValueError("Cover-Weiterleitung zeigt auf einen nicht erlaubten Host.")
        request_url = redirect_url
    else:
        raise ValueError("Cover wurde zu häufig weitergeleitet.")
    response.raise_for_status()
    if not _allowed_download_response(response.url):
        raise ValueError("Cover-Weiterleitung zeigt auf einen nicht erlaubten Host.")
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_COVER_BYTES:
        raise ValueError("Cover ist zu groß.")
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_COVER_BYTES:
            raise ValueError("Cover ist zu groß.")
        chunks.append(chunk)
    content = b"".join(chunks)
    image_type = _detected_image_type(content)
    if not content or image_type is None:
        raise ValueError("Die Cover-Antwort ist kein unterstütztes Bild.")
    return content, image_type


def _cached_response(cache_directory, row):
    filename = str(row["filename"] or "")
    if not filename.startswith(f"{row['cache_key']}."):
        return None
    path = cache_directory / filename
    if not path.is_file():
        return None
    response = send_file(path, mimetype=row["content_type"], conditional=True)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def serve_cached_cover(db, cache_key):
    row = db.execute(
        "SELECT * FROM cover_cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    if row is None:
        return "Cover nicht gefunden.", 404

    cache_directory = Path(current_app.config["COVER_CACHE_DIRECTORY"])
    cached = _cached_response(cache_directory, row)
    if cached is not None:
        return cached

    download_lock = _DOWNLOAD_LOCKS[int(cache_key[:2], 16) % len(_DOWNLOAD_LOCKS)]
    with download_lock:
        row = db.execute(
            "SELECT * FROM cover_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        cached = _cached_response(cache_directory, row)
        if cached is not None:
            return cached
        try:
            content, (extension, content_type) = _download_cover(row["source_url"])
            cache_directory.mkdir(parents=True, exist_ok=True)
            filename = f"{cache_key}.{extension}"
            temporary_path = cache_directory / f".{cache_key}.{os.getpid()}.tmp"
            temporary_path.write_bytes(content)
            temporary_path.replace(cache_directory / filename)
            db.execute(
                """
                UPDATE cover_cache
                SET filename = ?, content_type = ?, fetched_at = unixepoch(),
                    updated_at = CURRENT_TIMESTAMP
                WHERE cache_key = ?
                """,
                (filename, content_type, cache_key),
            )
            db.commit()
            row = db.execute(
                "SELECT * FROM cover_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            return _cached_response(cache_directory, row)
        except (OSError, ValueError, requests.RequestException) as error:
            current_app.logger.warning(
                "Cover konnte nicht lokal gespeichert werden",
                extra={
                    "event": "cover_cache_failed",
                    "cache_key": cache_key,
                    "error_type": type(error).__name__,
                    "error": str(error)[:250],
                },
            )
            response = redirect(row["source_url"], code=302)
            response.headers["Cache-Control"] = "no-store"
            return response
