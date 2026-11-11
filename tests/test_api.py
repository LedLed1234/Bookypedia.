import importlib
import sqlite3
from pathlib import Path

from readmore import create_app
from readmore.auth import create_user


BOOK = {
    "title": "Die linke Hand der Dunkelheit",
    "authors": ["Ursula K. Le Guin"],
    "isbn": "9783453314552",
    "provider_book_id": "/works/OL24320W",
    "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
    "page_count": 304,
    "status": "want_to_read",
}

MEDIA = {
    "provider": "tmdb",
    "tmdb_id": 70523,
    "media_type": "tv",
    "title": "Dark",
    "original_title": None,
    "overview": "Vier Familien suchen nach Antworten.",
    "release_date": "2017-12-01",
    "release_year": 2017,
    "original_language": "de",
    "cover_url": "https://image.tmdb.org/t/p/w500/dark.jpg",
    "backdrop_url": "https://image.tmdb.org/t/p/w780/dark-backdrop.jpg",
    "vote_average": 8.4,
    "vote_count": 7957,
}


def test_complete_book_lifecycle(client):
    created = client.post("/api/books", json=BOOK)
    assert created.status_code == 201
    book_id = created.get_json()["book"]["id"]

    changed = client.patch(f"/api/books/{book_id}", json={"status": "reading"})
    assert changed.status_code == 200
    assert changed.get_json()["book"]["status"] == "reading"

    reviewed = client.patch(
        f"/api/books/{book_id}", json={"status": "read", "rating": 5, "review": "Still und großartig."}
    )
    assert reviewed.status_code == 200
    assert reviewed.get_json()["book"]["rating"] == 5
    assert reviewed.get_json()["book"]["review"] == "Still und großartig."

    removed_review = client.patch(f"/api/books/{book_id}", json={"rating": None, "review": ""})
    assert removed_review.get_json()["book"]["rating"] is None
    assert removed_review.get_json()["book"]["review"] == ""

    assert client.delete(f"/api/books/{book_id}").status_code == 204
    assert client.get("/api/books").get_json()["books"] == []


def test_complete_media_lifecycle(client):
    created_response = client.post("/api/media", json={**MEDIA, "status": "watchlist"})
    assert created_response.status_code == 201
    created = created_response.get_json()["media"]
    assert created["title"] == "Dark"
    assert created["status"] == "watchlist"
    assert created["cover_url"] == MEDIA["cover_url"]
    assert created["watchlist_at"] is not None
    assert created["completed_at"] is None

    listed = client.get("/api/media").get_json()["media"]
    assert [item["tmdb_id"] for item in listed] == [70523]

    changed = client.patch(f"/api/media/{created['id']}", json={"status": "watching"})
    assert changed.status_code == 200
    assert changed.get_json()["media"]["status"] == "watching"
    assert changed.get_json()["media"]["watching_at"] is not None

    reviewed = client.patch(
        f"/api/media/{created['id']}",
        json={"rating": 5, "review": "Düster, klug und großartig gespielt."},
    )
    assert reviewed.status_code == 200
    assert reviewed.get_json()["media"]["rating"] == 5
    assert reviewed.get_json()["media"]["review"] == "Düster, klug und großartig gespielt."

    cleared = client.patch(
        f"/api/media/{created['id']}", json={"rating": None, "review": ""}
    )
    assert cleared.get_json()["media"]["rating"] is None
    assert cleared.get_json()["media"]["review"] == ""

    filtered = client.get("/api/media?status=watching").get_json()["media"]
    assert [item["id"] for item in filtered] == [created["id"]]
    assert client.get("/api/media?status=read").status_code == 400

    completed = client.patch(f"/api/media/{created['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.get_json()["media"]["completed_at"] is not None

    duplicate = client.post("/api/media", json=MEDIA)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["media"]["id"] == created["id"]

    assert client.delete(f"/api/media/{created['id']}").status_code == 204
    assert client.get("/api/media").get_json()["media"] == []


def test_saved_season_lifecycle_is_independent_from_series_collection(client):
    payload = {
        "tv_tmdb_id": 1399,
        "season_number": 1,
        "series_title": "Game of Thrones",
        "season_title": "Staffel 1",
        "series_overview": "Der Kampf um Westeros.",
        "season_overview": "Der Winter naht.",
        "air_date": "2011-04-17",
        "original_language": "en",
        "cover_url": "https://image.tmdb.org/t/p/w342/season-one.jpg",
        "series_cover_url": "https://image.tmdb.org/t/p/w500/game-of-thrones.jpg",
        "backdrop_url": "https://image.tmdb.org/t/p/w780/game-of-thrones-backdrop.jpg",
        "episode_count": 10,
    }

    created_response = client.post("/api/media/seasons", json=payload)
    assert created_response.status_code == 201
    season = created_response.get_json()["season"]
    assert season["item_type"] == "season"
    assert season["title"] == "Game of Thrones – Staffel 1"
    assert season["release_year"] == 2011
    assert season["status"] == "watchlist"
    assert season["completed_at"] is None
    assert client.get("/api/media").get_json()["media"] == []

    listed = client.get("/api/media/seasons").get_json()["seasons"]
    assert [item["id"] for item in listed] == [season["id"]]

    changed = client.patch(
        f"/api/media/seasons/{season['id']}",
        json={"status": "watching"},
    )
    assert changed.status_code == 200
    assert changed.get_json()["season"]["status"] == "watching"
    assert changed.get_json()["season"]["watching_at"] is not None

    completed = client.patch(f"/api/media/seasons/{season['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.get_json()["season"]["completed_at"] is not None

    duplicate = client.post("/api/media/seasons", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["season"]["id"] == season["id"]

    assert client.delete(f"/api/media/seasons/{season['id']}").status_code == 204
    assert client.get("/api/media/seasons").get_json()["seasons"] == []


def test_completion_date_backfill_preserves_known_dates_and_skips_watchlist(client):
    database = client.application.config["DATABASE"]
    known_date = "2025-10-23 17:10:00"
    cases = (
        ("/api/media", "media", "media_items", "tmdb_id", MEDIA),
        (
            "/api/media/seasons", "season", "saved_seasons", "season_number",
            {"tv_tmdb_id": 1399, "series_title": "Game of Thrones", "season_title": "Staffel"},
        ),
    )
    for endpoint, key, table, identity, payload in cases:
        for number, status, date in (
            (1, "completed", None),
            (2, "completed", known_date),
            (3, "watchlist", None),
        ):
            response = client.post(endpoint, json={**payload, identity: number, "status": status})
            assert response.status_code == 201
            with sqlite3.connect(database) as db:
                db.execute(
                    f"UPDATE {table} SET completed_at = ? WHERE id = ?",
                    (date, response.get_json()[key]["id"]),
                )

    restarted = create_app({"TESTING": True, "DATABASE": database}).test_client()
    for endpoint, key, _, identity, _ in cases:
        items = restarted.get(endpoint).get_json()[key + "s" if key == "season" else "media"]
        assert {item[identity]: item["completed_at"] for item in items} == {
            1: "2026-01-01",
            2: known_date,
            3: None,
        }


def test_rewatches_persist_separately_for_movies_series_and_seasons(client):
    series = client.post("/api/media", json=MEDIA).get_json()["media"]
    movie = client.post(
        "/api/media", json={**MEDIA, "media_type": "movie", "tmdb_id": 11, "status": "completed"}
    ).get_json()["media"]
    season = client.post("/api/media/seasons", json={
        "tv_tmdb_id": MEDIA["tmdb_id"], "season_number": 1, "series_title": MEDIA["title"],
        "season_title": "Staffel 1", "status": "completed",
    }).get_json()["season"]
    series_url = f"/api/media/{series['id']}"
    movie_url = f"/api/media/{movie['id']}/rewatches"
    season_url = f"/api/media/seasons/{season['id']}/rewatches"
    assert client.post(f"{series_url}/rewatches", json={"watched_on": "2026-02-10"}).status_code == 409
    completed = client.patch(series_url, json={"status": "completed"}).get_json()["media"]
    assert client.post(f"{series_url}/rewatches", json={"watched_on": "2026-02-30"}).status_code == 400

    for endpoint, day in [
        (f"{series_url}/rewatches", "2026-06-10"),
        (f"{series_url}/rewatches", "2026-04-12"),
        (season_url, "2026-05-11"),
        (movie_url, "2026-05-12"),
    ]:
        assert client.post(endpoint, json={"watched_on": day}).status_code == 201

    restarted = create_app({"TESTING": True, "DATABASE": client.application.config["DATABASE"]})
    reader = restarted.test_client()
    assert reader.get(f"{series_url}/rewatches").get_json()["rewatches"] == ["2026-06-10", "2026-04-12"]
    assert reader.get(season_url).get_json()["rewatches"] == ["2026-05-11"]
    assert reader.get(movie_url).get_json()["rewatches"] == ["2026-05-12"]
    stored = next(item for item in reader.get("/api/media").get_json()["media"] if item["id"] == series["id"])
    assert stored["status"] == "completed"
    assert stored["completed_at"] == completed["completed_at"]


def test_rewatches_are_scoped_to_the_owner(client):
    movie = client.post("/api/media", json={**MEDIA, "status": "completed"}).get_json()["media"]
    endpoint = f"/api/media/{movie['id']}/rewatches"
    assert client.post(endpoint, json={"watched_on": "2026-07-03"}).status_code == 201
    with client.application.app_context():
        create_user("other-viewer", "another-test-password", require_password_change=False)
    other = create_app({
        "TESTING": True,
        "TEST_AUTO_LOGIN": False,
        "DATABASE": client.application.config["DATABASE"],
    }).test_client()
    assert other.post("/login", data={
        "username": "other-viewer", "password": "another-test-password",
    }).status_code == 302
    assert other.get(endpoint).status_code == 404
    assert other.post(endpoint, json={"watched_on": "2026-07-04"}).status_code == 404
    assert other.get("/api/media/watch-history").get_json() == {"events": []}
    assert client.get(endpoint).get_json()["rewatches"] == ["2026-07-03"]


def test_watch_history_includes_completions_and_separate_rewatches(client):
    series = client.post("/api/media", json={**MEDIA, "status": "completed"}).get_json()["media"]
    movie = client.post("/api/media", json={
        **MEDIA, "tmdb_id": 11, "media_type": "movie", "title": "Krieg der Sterne",
    }).get_json()["media"]
    season = client.post("/api/media/seasons", json={
        "tv_tmdb_id": MEDIA["tmdb_id"], "season_number": 1, "series_title": MEDIA["title"],
        "season_title": "Staffel 1", "status": "completed",
    }).get_json()["season"]
    series_url = f"/api/media/{series['id']}"
    assert client.post(f"{series_url}/rewatches", json={"watched_on": "2026-03-14"}).status_code == 201
    assert client.patch(series_url, json={"status": "watching"}).status_code == 200
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        db.execute("UPDATE media_items SET completed_at = ? WHERE id = ?", ("2025-12-20 14:00:00", series["id"]))
        db.execute("UPDATE saved_seasons SET completed_at = ? WHERE id = ?", ("2026-01-01", season["id"]))

    history = client.get("/api/media/watch-history")
    assert history.status_code == 200
    assert history.get_json()["events"] == [
        {"id": series["id"], "kind": "tv", "title": series["title"], "watched_at": "2026-03-14", "rewatch": True},
        {"id": season["id"], "kind": "season", "title": season["title"], "watched_at": "2026-01-01", "rewatch": False},
        {"id": series["id"], "kind": "tv", "title": series["title"], "watched_at": "2025-12-20 14:00:00", "rewatch": False},
    ]
    assert movie["completed_at"] is None


def test_media_rejects_invalid_identity_and_external_images(client):
    assert client.post("/api/media", json={"title": "Ohne TMDB"}).status_code == 400
    response = client.post(
        "/api/media",
        json={
            **MEDIA,
            "tmdb_id": 11,
            "media_type": "movie",
            "title": "Star Wars",
            "cover_url": "https://example.com/not-tmdb.jpg",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["media"]["cover_url"] is None


def test_media_rejects_invalid_rating(client):
    media = client.post("/api/media", json=MEDIA).get_json()["media"]
    assert client.patch(f"/api/media/{media['id']}", json={"rating": 0}).status_code == 400
    assert client.patch(f"/api/media/{media['id']}", json={"rating": 6}).status_code == 400
    assert client.patch(f"/api/media/{media['id']}", json={"rating": 3.5}).status_code == 400
    assert client.patch(f"/api/media/{media['id']}", json={}).status_code == 400


def test_provider_cover_is_downloaded_once_and_served_locally(client, monkeypatch):
    created = client.post("/api/books", json=BOOK).get_json()["book"]
    assert created["cover_url"] == BOOK["cover_url"]
    assert created["cover_src"].startswith("/covers/")

    image = b"\xff\xd8\xff\xe0cached-cover"
    calls = []

    class CoverResponse:
        url = BOOK["cover_url"]
        status_code = 200
        headers = {"Content-Length": str(len(image))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            calls.append(chunk_size)
            yield image

    cover_cache = importlib.import_module("readmore.cover_cache")
    monkeypatch.setattr(cover_cache.requests, "get", lambda *_args, **_kwargs: CoverResponse())

    first = client.get(created["cover_src"])
    assert first.status_code == 200
    assert first.data == image
    assert first.content_type == "image/jpeg"
    assert "immutable" in first.headers["Cache-Control"]
    assert calls == [64 * 1024]

    monkeypatch.setattr(
        cover_cache.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("erneuter Download")),
    )
    second = client.get(created["cover_src"])
    assert second.status_code == 200
    assert second.data == image
    assert len(list(Path(client.application.config["COVER_CACHE_DIRECTORY"]).glob("*.jpg"))) == 1


def test_open_library_archive_redirect_is_accepted_for_cover_download(client, monkeypatch):
    created = client.post(
        "/api/books",
        json={**BOOK, "cover_url": "https://covers.openlibrary.org/b/id/8407136-M.jpg"},
    ).get_json()["book"]
    image = b"\xff\xd8\xff\xe0archive-cover"

    class RedirectResponse:
        url = "https://covers.openlibrary.org/b/id/8407136-M.jpg"
        status_code = 302
        headers = {
            "Location": "https://ia800703.us.archive.org/view_archive.php?file=cover.jpg"
        }

        def close(self):
            return None

    class ArchiveResponse:
        url = "https://ia800703.us.archive.org/view_archive.php?file=cover.jpg"
        status_code = 200
        headers = {"Content-Length": str(len(image))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield image

    cover_cache = importlib.import_module("readmore.cover_cache")
    responses = iter((RedirectResponse(), ArchiveResponse()))
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["allow_redirects"]))
        return next(responses)

    monkeypatch.setattr(cover_cache.requests, "get", fake_get)

    response = client.get(created["cover_src"])

    assert response.status_code == 200
    assert response.data == image
    assert response.content_type == "image/jpeg"
    assert calls == [
        ("https://covers.openlibrary.org/b/id/8407136-M.jpg", False),
        ("https://ia800703.us.archive.org/view_archive.php?file=cover.jpg", False),
    ]
    assert len(list(Path(client.application.config["COVER_CACHE_DIRECTORY"]).glob("*.jpg"))) == 1


def test_review_length_limit_is_enforced_by_backend(tmp_path):
    database = tmp_path / "review-limit.db"
    app = create_app({
        "TESTING": True,
        "DATABASE": str(database),
        "REVIEW_MAX_LENGTH": 7,
    })
    client = app.test_client()

    rejected = client.post("/api/books", json={**BOOK, "review": "12345678"})
    assert rejected.status_code == 400
    assert "7 Zeichen" in rejected.get_json()["error"]

    created = client.post("/api/books", json={**BOOK, "review": "1234567"})
    assert created.status_code == 201
    book_id = created.get_json()["book"]["id"]
    rejected_update = client.patch(
        f"/api/books/{book_id}", json={"review": "abcdefgh"}
    )
    assert rejected_update.status_code == 400
    assert created.get_json()["book"]["review"] == "1234567"


def test_book_keeps_catalogue_provider_for_later_requests(client):
    created = client.post(
        "/api/books",
        json={
            **BOOK,
            "isbn": "9781234567897",
            "provider": "google_books",
            "provider_book_id": "google-volume-1",
            "provider_edition_id": "google-volume-1",
        },
    ).get_json()["book"]

    assert created["provider"] == "google_books"
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        assert db.execute(
            "SELECT provider FROM metadata_lookups WHERE book_id = ?", (created["id"],)
        ).fetchone()["provider"] == "google_books"
        assert db.execute(
            "SELECT provider FROM series_lookups WHERE provider_book_id = ?",
            ("google-volume-1",),
        ).fetchone()["provider"] == "google_books"


def test_wishlist_and_owned_unread_books_are_separate(client):
    wishlist = client.post("/api/books", json=BOOK).get_json()["book"]
    unread = client.post(
        "/api/books",
        json={
            **BOOK,
            "title": "Freie Geister",
            "isbn": "9780000000001",
            "provider_book_id": "/works/OWNED",
            "status": "unread",
        },
    ).get_json()["book"]

    assert wishlist["status"] == "want_to_read"
    assert wishlist["is_owned"] is False
    assert unread["status"] == "unread"
    assert unread["is_owned"] is True
    assert unread["owned_at"] is not None
    assert [book["id"] for book in client.get("/api/books?status=unread").get_json()["books"]] == [
        unread["id"]
    ]
    assert [
        book["id"] for book in client.get("/api/books?status=want_to_read").get_json()["books"]
    ] == [wishlist["id"]]
    assert [book["id"] for book in client.get("/api/books?status=owned").get_json()["books"]] == [
        unread["id"]
    ]

    moved = client.patch(
        f"/api/books/{wishlist['id']}", json={"status": "unread"}
    ).get_json()["book"]
    assert moved["status"] == "unread"
    assert moved["is_owned"] is True
    assert moved["owned_at"] is not None

    returned = client.patch(
        f"/api/books/{wishlist['id']}", json={"status": "want_to_read"}
    ).get_json()["book"]
    assert returned["status"] == "want_to_read"
    assert returned["is_owned"] is False
    assert returned["owned_at"] is None


def test_owned_is_an_aggregate_filter_not_a_book_status(client):
    owned_ids = []
    for index, status in enumerate(("unread", "reading", "read"), start=1):
        response = client.post(
            "/api/books",
            json={
                "title": f"Eigenes Buch {index}",
                "authors": ["Eine Person"],
                "status": status,
            },
        )
        assert response.status_code == 201
        owned_ids.append(response.get_json()["book"]["id"])

    wishlist = client.post(
        "/api/books",
        json={"title": "Nur gewünscht", "authors": ["Eine Person"], "status": "want_to_read"},
    ).get_json()["book"]

    owned = client.get("/api/books?status=owned").get_json()["books"]
    assert {book["id"] for book in owned} == set(owned_ids)
    assert wishlist["id"] not in {book["id"] for book in owned}
    assert client.post(
        "/api/books", json={"title": "Ungültig", "status": "owned"}
    ).status_code == 400
    assert client.patch(
        f"/api/books/{owned_ids[0]}", json={"status": "owned"}
    ).status_code == 400


def test_status_timestamps_follow_hierarchical_transitions(client):
    created = client.post("/api/books", json=BOOK).get_json()["book"]
    book_id = created["id"]
    assert created["want_to_read_at"] is not None
    assert created["reading_at"] is None
    assert created["read_at"] is None

    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        db.execute(
            "UPDATE books SET want_to_read_at = '2000-01-01 00:00:00' WHERE id = ?",
            (book_id,),
        )
        db.commit()

    unchanged = client.patch(
        f"/api/books/{book_id}", json={"status": "want_to_read"}
    ).get_json()["book"]
    assert unchanged["want_to_read_at"] == "2000-01-01T00:00:00Z"

    reading = client.patch(
        f"/api/books/{book_id}", json={"status": "reading"}
    ).get_json()["book"]
    assert reading["want_to_read_at"] == "2000-01-01T00:00:00Z"
    assert reading["reading_at"] is not None

    read = client.patch(f"/api/books/{book_id}", json={"status": "read"}).get_json()["book"]
    assert read["reading_at"] == reading["reading_at"]
    assert read["read_at"] is not None

    returned_to_reading = client.patch(
        f"/api/books/{book_id}", json={"status": "reading"}
    ).get_json()["book"]
    assert returned_to_reading["want_to_read_at"] == "2000-01-01T00:00:00Z"
    assert returned_to_reading["reading_at"] is not None
    assert returned_to_reading["read_at"] is None

    returned = client.patch(
        f"/api/books/{book_id}", json={"status": "want_to_read"}
    ).get_json()["book"]
    assert returned["want_to_read_at"] != "2000-01-01T00:00:00Z"
    assert returned["reading_at"] is None
    assert returned["read_at"] is None


def test_startup_repairs_history_that_conflicts_with_current_status(tmp_path):
    database = tmp_path / "hierarchy.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    created = first_app.test_client().post("/api/books", json=BOOK).get_json()["book"]
    with first_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        db.execute(
            """
            UPDATE books
            SET reading_at = '2020-01-01 00:00:00', read_at = '2021-01-01 00:00:00'
            WHERE id = ?
            """,
            (created["id"],),
        )
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    repaired = restarted_app.test_client().get("/api/books").get_json()["books"][0]

    assert repaired["status"] == "want_to_read"
    assert repaired["want_to_read_at"] is not None
    assert repaired["reading_at"] is None
    assert repaired["read_at"] is None


def test_existing_database_gets_empty_status_timestamps(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            authors TEXT NOT NULL DEFAULT '',
            isbn TEXT,
            provider_book_id TEXT,
            cover_url TEXT,
            identity_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'want_to_read',
            rating INTEGER,
            review TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO books (title, authors, cover_url, identity_key, status)
        VALUES (
            '地球星人', '村田沙耶香',
            'http://covers.openlibrary.org/b/id/123-M.jpg', '|', 'read'
        )
        """
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "DATABASE": str(database)})
    book = app.test_client().get("/api/books").get_json()["books"][0]

    assert book["status"] == "read"
    assert book["want_to_read_at"] is None
    assert book["reading_at"] is None
    assert book["read_at"] is None
    assert book["provider_edition_id"] is None
    assert book["original_title"] is None
    assert book["original_authors"] == []
    assert book["page_count"] is None
    assert book["publisher"] is None
    assert book["description"] is None
    assert book["subjects"] == []
    assert book["cover_url"] == "https://covers.openlibrary.org/b/id/123-M.jpg"
    with app.app_context():
        database_handle = importlib.import_module("readmore.db").get_db()
        identity = database_handle.execute(
            "SELECT identity_key FROM books WHERE id = 1"
        ).fetchone()["identity_key"]
        assert identity == "地球星人|村田沙耶香"
        indexes = {
            row["name"] for row in database_handle.execute("PRAGMA index_list(books)").fetchall()
        }
        assert "idx_books_identity_key" not in indexes
        assert "idx_books_user_identity" in indexes


def test_duplicate_is_rejected_by_catalogue_id_isbn_or_title(client):
    assert client.post("/api/books", json=BOOK).status_code == 201

    same_catalogue_book = {**BOOK, "isbn": "9780000000000", "title": "Other edition"}
    assert client.post("/api/books", json=same_catalogue_book).status_code == 409

    same_isbn = {**BOOK, "provider_book_id": "/works/OTHER", "title": "Deutscher Titel"}
    assert client.post("/api/books", json=same_isbn).status_code == 409

    same_identity = {**BOOK, "isbn": None, "provider_book_id": None, "title": "  DIE LINKE HAND DER DUNKELHEIT "}
    assert client.post("/api/books", json=same_identity).status_code == 409


def test_non_latin_titles_have_distinct_unicode_identities(client):
    first = {"title": "地球星人", "authors": ["村田沙耶香"], "status": "want_to_read"}
    second = {"title": "コンビニ人間", "authors": ["村田沙耶香"], "status": "want_to_read"}

    assert client.post("/api/books", json=first).status_code == 201
    assert client.post("/api/books", json=second).status_code == 201
    assert client.post("/api/books", json=first).status_code == 409


def test_manual_book_and_validation(client):
    response = client.post(
        "/api/books",
        json={
            "title": "Eigenes Buch",
            "authors": "Eine Person",
            "status": "reading",
            "isbn": "978-3-16-148410-0",
            "publisher": "Eigenverlag",
            "publish_date": "15. Oktober 2024",
            "page_count": 321,
            "language": "Deutsch",
            "physical_format": "Hardcover",
            "subtitle": "Eine Geschichte",
            "original_title": "An Original Story",
            "description": "Eine manuell erfasste Beschreibung.",
            "subjects": ["Fantasy", "Abenteuer"],
        },
    )
    assert response.status_code == 201
    book = response.get_json()["book"]
    assert book["cover_url"] is None
    assert book["isbn"] == "9783161484100"
    assert book["publisher"] == "Eigenverlag"
    assert book["publish_date"] == "15. Oktober 2024"
    assert book["page_count"] == 321
    assert book["language"] == "Deutsch"
    assert book["physical_format"] == "Hardcover"
    assert book["subtitle"] == "Eine Geschichte"
    assert book["original_title"] == "An Original Story"
    assert book["description"] == "Eine manuell erfasste Beschreibung."
    assert book["subjects"] == ["Fantasy", "Abenteuer"]
    assert client.post("/api/books", json={"title": ""}).status_code == 400
    assert client.patch("/api/books/1", json={"rating": 6}).status_code == 400


def test_book_can_be_created_directly_as_reviewed_library_entry(client):
    response = client.post(
        "/api/books",
        json={**BOOK, "status": "read", "rating": 4, "review": "Direkt bewertet."},
    )

    assert response.status_code == 201
    book = response.get_json()["book"]
    assert book["status"] == "read"
    assert book["rating"] == 4
    assert book["review"] == "Direkt bewertet."


def test_available_search_metadata_is_stored_immediately(client):
    response = client.post(
        "/api/books",
        json={
            **BOOK,
            "publisher": "Gollancz",
            "publish_date": "2014",
            "physical_format": "Paperback",
            "subtitle": "Book One",
            "subjects": ["Science fiction", "Dystopia"],
        },
    )

    assert response.status_code == 201
    book = response.get_json()["book"]
    assert book["publisher"] == "Gollancz"
    assert book["publish_date"] == "2014"
    assert book["physical_format"] == "Paperback"
    assert book["subtitle"] == "Book One"
    assert book["subjects"] == ["Science fiction", "Dystopia"]


def test_database_persists_across_app_restart(tmp_path):
    database = tmp_path / "persistent.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    assert first_app.test_client().post("/api/books", json=BOOK).status_code == 201

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    books = restarted_app.test_client().get("/api/books").get_json()["books"]
    assert len(books) == 1
    assert books[0]["title"] == BOOK["title"]


def test_search_uses_normalized_provider_results(client, monkeypatch):
    expected = [{"title": "Dune", "authors": ["Frank Herbert"], "provider_book_id": "/works/OL1W"}]
    api_module = importlib.import_module("readmore.api")

    class FakeProvider:
        def search(self, query, limit):
            assert query == "Dune"
            assert limit == api_module.SEARCH_RESULT_LIMIT
            return expected

    monkeypatch.setattr(api_module, "get_provider", lambda: FakeProvider())
    response = client.get("/api/search?q=Dune")
    assert response.status_code == 200
    assert response.get_json()["results"] == expected


def test_tmdb_provider_normalizes_movies_and_series(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.tmdb")
    request = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": 11,
                        "media_type": "movie",
                        "title": "Krieg der Sterne",
                        "original_title": "Star Wars",
                        "overview": "Eine weit entfernte Galaxis.",
                        "release_date": "1977-05-25",
                        "poster_path": "/star-wars.jpg",
                        "backdrop_path": "/space.jpg",
                        "original_language": "en",
                        "vote_average": 8.2,
                        "vote_count": 1234,
                        "popularity": 99.5,
                    },
                    {
                        "id": 1396,
                        "media_type": "tv",
                        "name": "Breaking Bad",
                        "original_name": "Breaking Bad",
                        "overview": "Ein Chemielehrer verändert sein Leben.",
                        "first_air_date": "2008-01-20",
                        "poster_path": "/breaking-bad.jpg",
                        "original_language": "en",
                        "vote_average": 8.9,
                        "vote_count": 15000,
                    },
                    {"id": 1, "media_type": "person", "name": "Nicht anzeigen"},
                ]
            }

    def fake_get(url, **kwargs):
        request.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch.setattr(provider_module.requests, "get", fake_get)
    results = provider_module.TMDBProvider("secret-token").search("Star", limit=8)

    assert [result["media_type"] for result in results] == ["movie", "tv"]
    assert results[0]["title"] == "Krieg der Sterne"
    assert results[0]["original_title"] == "Star Wars"
    assert results[0]["release_year"] == 1977
    assert results[0]["cover_url"] == "https://image.tmdb.org/t/p/w500/star-wars.jpg"
    assert results[1]["title"] == "Breaking Bad"
    assert results[1]["original_title"] is None
    assert request["params"]["language"] == "de-DE"
    assert request["params"]["region"] == "DE"
    assert request["headers"]["Authorization"] == "Bearer secret-token"


def test_tmdb_provider_loads_and_sorts_movie_collection(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.tmdb")
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/movie/11"):
            return FakeResponse(
                {"id": 11, "belongs_to_collection": {"id": 10, "name": "Star Wars Collection"}}
            )
        assert url.endswith("/collection/10")
        return FakeResponse(
            {
                "id": 10,
                "name": "Star Wars Collection",
                "overview": "Eine weit entfernte Galaxis.",
                "poster_path": "/collection.jpg",
                "parts": [
                    {
                        "id": 1891,
                        "title": "Das Imperium schlägt zurück",
                        "release_date": "1980-05-20",
                        "poster_path": "/empire.jpg",
                        "vote_average": 8.4,
                        "vote_count": 100,
                    },
                    {
                        "id": 11,
                        "title": "Krieg der Sterne",
                        "release_date": "1977-05-25",
                        "poster_path": "/star-wars.jpg",
                        "vote_average": 8.2,
                        "vote_count": 200,
                    },
                ],
            }
        )

    monkeypatch.setattr(provider_module.requests, "get", fake_get)
    collection = provider_module.TMDBProvider("secret-token").movie_collection(11)

    assert collection["tmdb_id"] == 10
    assert collection["name"] == "Star Wars Collection"
    assert [part["tmdb_id"] for part in collection["parts"]] == [11, 1891]
    assert [part["collection_position"] for part in collection["parts"]] == [1, 2]
    assert collection["parts"][0]["media_type"] == "movie"
    assert collection["parts"][0]["cover_url"].endswith("/w342/star-wars.jpg")
    assert [call[1]["params"]["language"] for call in calls] == ["de-DE", "de-DE"]


def test_tmdb_provider_loads_regular_seasons_and_episodes(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.tmdb")

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **_kwargs):
        if url.endswith("/tv/1399"):
            return FakeResponse(
                {
                    "id": 1399,
                    "name": "Game of Thrones",
                    "seasons": [
                        {"id": 90, "season_number": 0, "name": "Specials", "episode_count": 10},
                        {"id": 82, "season_number": 2, "name": "Staffel 2", "episode_count": 10},
                        {
                            "id": 81,
                            "season_number": 1,
                            "name": "Staffel 1",
                            "episode_count": 10,
                            "poster_path": "/season-one.jpg",
                        },
                    ],
                }
            )
        assert url.endswith("/tv/1399/season/1")
        return FakeResponse(
            {
                "id": 81,
                "name": "Staffel 1",
                "season_number": 1,
                "episodes": [
                    {
                        "id": 101,
                        "episode_number": 2,
                        "name": "Der Königsweg",
                        "air_date": "2011-04-24",
                        "runtime": 56,
                        "still_path": "/episode-two.jpg",
                        "vote_average": 8.6,
                        "vote_count": 100,
                    },
                    {"id": 100, "episode_number": 1, "name": "Der Winter naht"},
                ],
            }
        )

    monkeypatch.setattr(provider_module.requests, "get", fake_get)
    provider = provider_module.TMDBProvider("secret-token")
    series = provider.tv_seasons(1399)
    season = provider.tv_season(1399, 1)

    assert series["number_of_seasons"] == 2
    assert [item["season_number"] for item in series["seasons"]] == [1, 2]
    assert series["seasons"][0]["cover_url"].endswith("/w342/season-one.jpg")
    assert [item["episode_number"] for item in season["episodes"]] == [1, 2]
    assert season["episodes"][1]["still_url"].endswith("/w300/episode-two.jpg")
    assert season["episodes"][1]["runtime"] == 56


def test_media_collection_endpoint_is_movie_only_and_user_scoped(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    client.application.config["TMDB_READ_ACCESS_TOKEN"] = "server-only-token"
    movie = client.post(
        "/api/media",
        json={**MEDIA, "tmdb_id": 11, "media_type": "movie", "title": "Krieg der Sterne"},
    ).get_json()["media"]
    series = client.post("/api/media", json=MEDIA).get_json()["media"]
    received = []
    collection_calls = []

    class FakeTMDBProvider:
        def __init__(self, token):
            received.append(token)

        def movie_collection(self, movie_id):
            assert movie_id == 11
            collection_calls.append(movie_id)
            return {"tmdb_id": 10, "name": "Star Wars Collection", "parts": []}

    monkeypatch.setattr(api_module, "TMDBProvider", FakeTMDBProvider)
    response = client.get(f"/api/media/{movie['id']}/collection")

    assert response.status_code == 200
    assert response.get_json()["collection"]["tmdb_id"] == 10
    preview_response = client.get("/api/media/movie/11/collection")
    assert preview_response.status_code == 200
    assert preview_response.get_json()["collection"]["name"] == "Star Wars Collection"
    assert received == ["server-only-token", "server-only-token"]
    assert collection_calls == [11]
    assert client.get(f"/api/media/{series['id']}/collection").get_json() == {"collection": None}
    assert client.get("/api/media/999999/collection").status_code == 404


def test_tv_seasons_and_persistent_episode_ratings_work_without_saved_series(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    received = []
    season_calls = []

    class FakeTMDBProvider:
        def __init__(self, token):
            received.append(token)

        def tv_seasons(self, series_id):
            assert series_id == 1399
            season_calls.append((series_id, None))
            return {
                "tmdb_id": 1399,
                "name": "Game of Thrones",
                "number_of_seasons": 1,
                "seasons": [{"season_number": 1, "name": "Staffel 1", "episode_count": 1}],
            }

        def tv_season(self, series_id, season_number):
            assert (series_id, season_number) == (1399, 1)
            season_calls.append((series_id, season_number))
            return {
                "tmdb_id": 1399,
                "season_number": 1,
                "name": "Staffel 1",
                "episodes": [{"episode_number": 1, "name": "Der Winter naht"}],
            }

    client.application.config["TMDB_READ_ACCESS_TOKEN"] = "server-only-token"
    monkeypatch.setattr(api_module, "TMDBProvider", FakeTMDBProvider)

    seasons = client.get("/api/media/tv/1399/seasons")
    assert seasons.status_code == 200
    assert seasons.get_json()["series"]["seasons"][0]["season_number"] == 1

    initial = client.get("/api/media/tv/1399/seasons/1")
    assert initial.status_code == 200
    assert initial.get_json()["season"]["episodes"][0]["user_rating"] is None

    rated = client.patch(
        "/api/media/tv/1399/seasons/1/episodes/1/rating",
        json={"rating": 5},
    )
    assert rated.status_code == 200
    assert rated.get_json() == {"rating": 5}
    assert client.get("/api/media").get_json()["media"] == []
    assert client.get("/api/media/tv/1399/seasons/1").get_json()["season"]["episodes"][0]["user_rating"] == 5

    for invalid in (0, 6, 3.5, True):
        response = client.patch(
            "/api/media/tv/1399/seasons/1/episodes/1/rating",
            json={"rating": invalid},
        )
        assert response.status_code == 400

    cleared = client.patch(
        "/api/media/tv/1399/seasons/1/episodes/1/rating",
        json={"rating": None},
    )
    assert cleared.get_json() == {"rating": None}
    assert client.get("/api/media/tv/1399/seasons/1").get_json()["season"]["episodes"][0]["user_rating"] is None
    assert received == ["server-only-token"] * 4
    assert season_calls == [(1399, None), (1399, 1)]


def test_media_search_uses_tmdb_without_exposing_token(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    api_module._SEARCH_CACHE.clear()
    client.application.config["TMDB_READ_ACCESS_TOKEN"] = "server-only-token"
    received = []

    class FakeTMDBProvider:
        cache_identity = "tmdb:test"

        def __init__(self, token):
            received.append(token)

        def search(self, query, limit):
            assert query == "Dark"
            assert limit == 6
            return [{"provider": "tmdb", "tmdb_id": 70523, "media_type": "tv", "title": "Dark"}]

    monkeypatch.setattr(api_module, "TMDBProvider", FakeTMDBProvider)
    response = client.get("/api/media/search?q=Dark&limit=6")

    assert response.status_code == 200
    assert response.get_json() == {
        "provider": "tmdb",
        "results": [{"provider": "tmdb", "tmdb_id": 70523, "media_type": "tv", "title": "Dark"}],
    }
    assert received == ["server-only-token"]
    assert b"server-only-token" not in response.data


def test_tmdb_search_uses_persistent_cache_and_stale_fallback(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    cache_module = importlib.import_module("readmore.tmdb_cache")
    db_module = importlib.import_module("readmore.db")
    calls = []
    provider_fails = {"value": False}

    class FakeTMDBProvider:
        def __init__(self, _token):
            pass

        def search(self, query, limit):
            calls.append((query, limit))
            if provider_fails["value"]:
                raise api_module.ProviderUnavailable("TMDB ist gerade offline.")
            return [{"provider": "tmdb", "tmdb_id": 1399, "media_type": "tv", "title": "Game of Thrones"}]

    monkeypatch.setattr(api_module, "TMDBProvider", FakeTMDBProvider)

    first = client.get("/api/media/search?q=Game%20of%20Thrones&limit=4")
    second = client.get("/api/media/search?q=Game%20of%20Thrones&limit=4")
    assert first.status_code == second.status_code == 200
    assert calls == [("Game of Thrones", 4)]

    with client.application.app_context():
        db = db_module.get_db()
        cached = db.execute(
            "SELECT resource_type, payload_json FROM tmdb_cache"
        ).fetchone()
        assert cached["resource_type"] == "search"
        assert "Game of Thrones" in cached["payload_json"]
        db.execute(
            "UPDATE tmdb_cache SET fetched_at = unixepoch() - ?",
            (cache_module.SEARCH_TTL_SECONDS + 1,),
        )
        db.commit()

    provider_fails["value"] = True
    stale = client.get("/api/media/search?q=Game%20of%20Thrones&limit=4")
    assert stale.status_code == 200
    assert stale.get_json() == first.get_json()
    assert calls == [("Game of Thrones", 4), ("Game of Thrones", 4)]


def test_tmdb_provider_requires_read_access_token():
    provider_module = importlib.import_module("readmore.providers.tmdb")

    try:
        provider_module.TMDBProvider("").search("Dune")
    except provider_module.ProviderUnavailable as error:
        assert "Read Access Token" in str(error)
    else:
        raise AssertionError("TMDB-Suche ohne Token muss fehlschlagen")


def test_search_and_book_text_limits_are_enforced_by_backend(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    client.application.config.update(
        SEARCH_MAX_LENGTH=5,
        BOOK_TITLE_MAX_LENGTH=5,
        BOOK_AUTHORS_MAX_LENGTH=6,
    )
    monkeypatch.setattr(
        api_module,
        "get_provider",
        lambda: (_ for _ in ()).throw(AssertionError("Provider darf nicht aufgerufen werden")),
    )

    search = client.get("/api/search?q=123456")
    title = client.post("/api/books", json={"title": "123456", "authors": "Autor"})
    authors = client.post("/api/books", json={"title": "Buch", "authors": "1234567"})

    assert search.status_code == 400
    assert "5 Zeichen" in search.get_json()["error"]
    assert title.status_code == 400
    assert "5 Zeichen" in title.get_json()["error"]
    assert authors.status_code == 400
    assert "6 Zeichen" in authors.get_json()["error"]


def test_search_rate_limit_returns_retry_after(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    api_module._SEARCH_CACHE.clear()
    client.application.config["SEARCH_RATE_LIMIT_PER_MINUTE"] = 2

    class EmptyProvider:
        def search(self, _query, limit):
            return []

    monkeypatch.setattr(api_module, "get_provider", lambda: EmptyProvider())

    assert client.get("/api/search?q=RateOne").status_code == 200
    assert client.get("/api/search?q=RateTwo").status_code == 200
    blocked = client.get("/api/search?q=RateThree")

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert "Zu viele Suchanfragen" in blocked.get_json()["error"]


def test_primary_provider_uses_fallback_only_without_a_good_result(monkeypatch):
    provider_module = importlib.import_module("readmore.providers")
    calls = []

    class FakeProvider:
        def __init__(self, name, results):
            self.name = name
            self.results = results

        def search(self, query, limit):
            calls.append((self.name, query, limit))
            return self.results

    providers = {
        "open_library": FakeProvider("open_library", [{"title": "Etwas völlig anderes"}]),
        "google_books": FakeProvider("google_books", [{"title": "Legende vom Tränenvogel"}]),
    }
    monkeypatch.setattr(provider_module, "create_provider", providers.__getitem__)

    provider = provider_module.PrimaryFallbackProvider("open_library", "google_books")
    results = provider.search("Legende vom Tränenvogel", limit=4)

    assert results == [{"title": "Legende vom Tränenvogel"}]
    assert calls == [
        ("open_library", "Legende vom Tränenvogel", 4),
        ("google_books", "Legende vom Tränenvogel", 4),
    ]


def test_identical_primary_and_fallback_provider_disable_fallback(monkeypatch):
    provider_module = importlib.import_module("readmore.providers")
    creations = []

    class FakeProvider:
        def search(self, _query, limit):
            return [{"title": f"Treffer {limit}"}]

    def create(name):
        creations.append(name)
        return FakeProvider()

    monkeypatch.setattr(provider_module, "create_provider", create)
    provider = provider_module.PrimaryFallbackProvider("open_library", "open_library")

    assert provider.search("Unbekannt", limit=4) == [{"title": "Treffer 4"}]
    assert creations == ["open_library"]


def test_google_books_results_are_normalized(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.google_books")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [{
                    "id": "google-volume-1",
                    "volumeInfo": {
                        "title": "Legende vom Tränenvogel",
                        "authors": ["Kyung-sook Shin"],
                        "publisher": "HarperCollins",
                        "publishedDate": "2024-05-01",
                        "pageCount": 320,
                        "language": "de",
                        "industryIdentifiers": [
                            {"type": "ISBN_13", "identifier": "9781234567897"}
                        ],
                        "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"},
                    },
                }]
            }

    monkeypatch.setattr(provider_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    result = provider_module.GoogleBooksProvider().search("Legende vom Tränenvogel", 4)[0]

    assert result["provider"] == "google_books"
    assert result["provider_book_id"] == "google-volume-1"
    assert result["provider_edition_id"] == "google-volume-1"
    assert result["isbn"] == "9781234567897"
    assert result["page_count"] == 320
    assert result["cover_url"].startswith("https://")


def test_google_books_uses_structured_series_information(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.google_books")

    def volume(volume_id, title, position):
        return {
            "id": volume_id,
            "volumeInfo": {
                "title": title,
                "authors": ["Test Author"],
                "language": "de",
                "seriesInfo": {
                    "bookDisplayNumber": str(position),
                    "shortSeriesBookTitle": title.split(": ", 1)[-1],
                    "volumeSeries": [{
                        "seriesId": "google-series-1",
                        "orderNumber": position,
                    }],
                },
            },
        }

    first = volume("volume-1", "Die Testchroniken 1: Der Anfang", 1)
    second = volume("volume-2", "Die Testchroniken 2: Die Reise", 2)
    unrelated = volume("volume-x", "Andere Reihe 1: Fremdes Buch", 1)
    unrelated["volumeInfo"]["seriesInfo"]["volumeSeries"][0]["seriesId"] = "other-series"

    provider = provider_module.GoogleBooksProvider("key")
    monkeypatch.setattr(
        provider,
        "_get_json",
        lambda url, params=None: first if url.endswith("/volume-1") else {
            "items": [second, unrelated, first]
        },
    )

    series = provider.series("volume-1", ["Test Author"])

    assert series["name"] == "Die Testchroniken"
    assert series["provider_series_id"] == "google-series-1"
    assert series["current_position"] == 1
    assert series["source"] == "google_structured"
    assert [book["provider_book_id"] for book in series["books"]] == ["volume-1", "volume-2"]
    assert [book["series_position"] for book in series["books"]] == [1, 2]


def test_google_books_infers_tearbird_series_from_titles(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.google_books")
    titles = [
        "Das Blut der Herzlosen – Die Legende vom Tränenvogel 1",
        "Der träumende Krieger – Die Legende vom Tränenvogel 2",
        "Der Feuergeist – Die Legende vom Tränenvogel 3",
        "Die Suche nach dem König – Die Legende vom Tränenvogel 4",
    ]
    volumes = [
        {
            "id": f"tearbird-{position}",
            "volumeInfo": {
                "title": title,
                "authors": ["Young-do Lee"],
                "language": "de",
            },
        }
        for position, title in enumerate(titles, 1)
    ]
    # Google schreibt denselben Autor je nach Ausgabe unterschiedlich. Die
    # enge Titel+Autor-Suche findet dadurch nur einen Teil der Reihe; die
    # ergänzende Phrasensuche muss die fehlenden Bände liefern.
    volumes[1]["volumeInfo"]["authors"] = ["Yeong do I"]
    volumes[3]["volumeInfo"]["authors"] = ["Yeong-do Lee"]
    provider = provider_module.GoogleBooksProvider("key")
    search_queries = []

    def fake_get(url, params=None):
        if url.endswith("/tearbird-1"):
            return volumes[0]
        search_queries.append(params["q"])
        if "inauthor:" in params["q"]:
            return {"items": [volumes[0], volumes[2]]}
        return {"items": volumes}

    monkeypatch.setattr(provider, "_get_json", fake_get)

    series = provider.series("tearbird-1", ["Young-do Lee"])

    assert series["name"] == "Die Legende vom Tränenvogel"
    assert series["provider_series_id"] is None
    assert series["source"] == "google_title"
    assert [book["series_position"] for book in series["books"]] == [1, 2, 3, 4]
    assert len(search_queries) == 2
    assert "inauthor:" in search_queries[0]
    assert "inauthor:" not in search_queries[1]
    assert search_queries[1] == "Die Legende vom Tränenvogel"


def test_catalogue_metadata_uses_provider_from_result(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    calls = []

    class MetadataProvider:
        def metadata(self, provider_book_id, provider_edition_id):
            calls.append((provider_book_id, provider_edition_id))
            return {"page_count": 321}

    def provider_for(name=None):
        assert name == "google_books"
        return MetadataProvider()

    monkeypatch.setattr(api_module, "get_provider", provider_for)
    response = client.get(
        "/api/metadata?provider=google_books&provider_book_id=volume-7&provider_edition_id=volume-7"
    )

    assert response.status_code == 200
    assert response.get_json()["metadata"]["page_count"] == 321
    assert calls == [("volume-7", "volume-7")]


def test_search_result_limit_can_be_configured_per_request(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    api_module._SEARCH_CACHE.clear()
    expected = [
        {"title": f"Buch {index}", "authors": ["Eine Person"]}
        for index in range(8)
    ]

    class FakeProvider:
        def search(self, query, limit):
            assert query == "Bücher"
            assert limit == 8
            return expected

    monkeypatch.setattr(api_module, "get_provider", lambda: FakeProvider())

    response = client.get("/api/search?q=B%C3%BCcher&limit=8")

    assert response.status_code == 200
    assert len(response.get_json()["results"]) == 8


def test_search_provider_pair_can_be_selected_per_device(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    selected = []

    class FakeProviderPair:
        def __init__(self, primary, fallback):
            selected.append((primary, fallback))

        def search(self, query, limit):
            return [{"title": query, "authors": [], "provider": "google_books"}]

    monkeypatch.setattr(api_module, "PrimaryFallbackProvider", FakeProviderPair)
    response = client.get(
        "/api/search?q=Dune&primary_provider=google_books&fallback_provider=open_library"
    )

    assert response.status_code == 200
    assert response.get_json()["results"][0]["title"] == "Dune"
    assert selected == [("google_books", "open_library")]


def test_search_rejects_unknown_provider(client):
    response = client.get("/api/search?q=Dune&primary_provider=unknown")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Ungültiger Hauptanbieter."


def test_suggestions_use_provider_prefix_search(client, monkeypatch):
    expected = [{"title": "Elantris", "authors": ["Brandon Sanderson"]}]

    class FakeProvider:
        def suggest(self, query, limit):
            assert query == "elant"
            assert limit == 6
            return expected

    monkeypatch.setattr(importlib.import_module("readmore.api"), "get_provider", lambda: FakeProvider())
    response = client.get("/api/search?q=elant&suggest=1")
    assert response.status_code == 200
    assert response.get_json()["results"] == expected


def test_open_library_suggestions_fall_back_to_prefix_when_direct_search_is_empty(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    def fake_request(query, limit, **_kwargs):
        calls.append((query, limit))
        if query != "Elant":
            return [{"title": "Elantris", "authors": ["Brandon Sanderson"]}]
        return []

    monkeypatch.setattr(provider, "_request", fake_request)

    results = provider.suggest("Elant", limit=6)

    assert results[0]["title"] == "Elantris"
    assert calls == [
        ("Elant", 12),
        ("title:(Elan*) OR author:(Elan*) OR isbn:(Elan*)", 12),
    ]


def test_open_library_multiword_suggestions_prefer_direct_relevance_search(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []
    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit, **_kwargs: calls.append((query, limit)) or [{"title": "Red Rising"}],
    )

    provider.suggest("Red Rising", limit=6)

    assert calls == [("Red Rising", 12)]


def test_open_library_complete_title_suggestion_is_not_broadened_to_bab(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    def fake_request(query, limit, **_kwargs):
        calls.append((query, limit))
        return [
            {"title": "Babel", "authors": ["R. F. Kuang"]},
            {"title": "Babel 17", "authors": ["Samuel R. Delany"]},
        ]

    monkeypatch.setattr(provider, "_request", fake_request)

    results = provider.suggest("babel", limit=6)

    assert results[0]["title"] == "Babel"
    assert calls == [("babel", 12)]


def test_open_library_typo_search_uses_tolerant_prefix_fallback(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    def fake_request(query, limit):
        calls.append((query, limit))
        if query == "red risin":
            return []
        return [
            {"title": "Red Rising", "authors": ["Pierce Brown"]},
            {"title": "Golden Son", "authors": ["Pierce Brown"]},
        ]

    monkeypatch.setattr(provider, "_request", fake_request)

    results = provider.search("red risin", limit=4)

    assert [book["title"] for book in results] == ["Red Rising", "Golden Son"]
    assert calls == [
        ("red risin", 4),
        ("title:(red AND risi*) OR author:(red AND risi*) OR isbn:(red AND risi*)", 12),
    ]


def test_open_library_search_retries_when_direct_results_are_unrelated(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    def fake_request(query, limit):
        calls.append((query, limit))
        if query == "golden so":
            return [
                {"title": "Wings So Wicked", "authors": ["Emily Blackwood"]},
                {
                    "title": "I Was So Mad (Golden Look-Look Books)",
                    "authors": ["Mercer Mayer"],
                },
            ]
        return [
            {
                "title": "Golden Son",
                "authors": ["Pierce Brown"],
                "provider_book_id": "/works/OL2W",
            },
            {
                "title": "Red Rising",
                "authors": ["Pierce Brown"],
                "provider_book_id": "/works/OL1W",
            },
        ]

    monkeypatch.setattr(provider, "_request", fake_request)

    results = provider.search("golden so", limit=4)

    assert results[0]["title"] == "Golden Son"
    assert [book["title"] for book in results] == [
        "Golden Son",
        "Red Rising",
        "Wings So Wicked",
        "I Was So Mad (Golden Look-Look Books)",
    ]
    assert calls == [
        ("golden so", 4),
        ("title:(golden AND so*) OR author:(golden AND so*) OR isbn:(golden AND so*)", 12),
    ]


def test_open_library_close_direct_match_avoids_second_request(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []
    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit: calls.append((query, limit))
        or [{"title": "Golden Son", "authors": ["Pierce Brown"]}],
    )

    assert provider.search("Golden Son", limit=4)[0]["title"] == "Golden Son"
    assert calls == [("Golden Son", 4)]


def test_open_library_keeps_direct_results_when_fallback_times_out(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    def fake_request(query, limit):
        calls.append((query, limit))
        if len(calls) == 2:
            raise provider_module.ProviderUnavailable("Timeout")
        return [{"title": "Wings So Wicked", "authors": ["Emily Blackwood"]}]

    monkeypatch.setattr(provider, "_request", fake_request)

    assert provider.search("golden so", limit=4)[0]["title"] == "Wings So Wicked"
    assert len(calls) == 2


def test_exact_search_prioritizes_books_from_same_series(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    cache_module = importlib.import_module("readmore.series_cache")
    api_module._SEARCH_CACHE.clear()

    class SeriesProvider:
        def search(self, query, limit):
            assert query in {"Red Rising", "Red Risin"}
            return [
                {"title": "Red Rising", "authors": ["Pierce Brown"], "provider_book_id": "/works/OL1W"},
                {"title": "Red Storm Rising", "authors": ["Tom Clancy"], "provider_book_id": "/works/OL9W"},
            ]

    monkeypatch.setattr(api_module, "get_provider", lambda: SeriesProvider())
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        cache_module.enqueue_series_lookup(db, "/works/OL1W", ["Pierce Brown"])
        cache_module.persist_series_result(
            db,
            "/works/OL1W",
            ["Pierce Brown"],
            {
                "name": "Red Rising Trilogy",
                "provider_series_id": "/series/OL1L",
                "current_position": "1",
                "source": "structured",
                "incomplete": False,
                "books": [
                    {"title": "Red Rising", "authors": ["Pierce Brown"], "provider_book_id": "/works/OL1W"},
                    {"title": "Golden Son", "authors": ["Pierce Brown"], "provider_book_id": "/works/OL2W"},
                    {"title": "Morning Star", "authors": ["Pierce Brown"], "provider_book_id": "/works/OL3W"},
                ],
            },
        )
    response = client.get("/api/search?q=Red%20Rising")

    assert response.status_code == 200
    assert [book["title"] for book in response.get_json()["results"]] == [
        "Red Rising",
        "Golden Son",
        "Morning Star",
        "Red Storm Rising",
    ]

    typo_response = client.get("/api/search?q=Red%20Risin")
    assert [book["title"] for book in typo_response.get_json()["results"]] == [
        "Red Rising",
        "Golden Son",
        "Morning Star",
        "Red Storm Rising",
    ]


def test_repeated_search_uses_short_backend_cache(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    api_module._SEARCH_CACHE.clear()
    calls = []

    class CachedProvider:
        def search(self, query, limit):
            calls.append((query, limit))
            return [{"title": "Dune", "authors": ["Frank Herbert"]}]

    monkeypatch.setattr(api_module, "get_provider", lambda: CachedProvider())
    assert client.get("/api/search?q=Dune").status_code == 200
    assert client.get("/api/search?q=dune").status_code == 200
    assert calls == [("Dune", api_module.SEARCH_RESULT_LIMIT)]


def test_empty_search_result_is_not_cached(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    api_module._SEARCH_CACHE.clear()
    calls = []

    class TemporarilyEmptyProvider:
        def search(self, query, limit):
            calls.append((query, limit))
            if len(calls) == 1:
                return []
            return [{"title": "Dune", "authors": ["Frank Herbert"]}]

    provider = TemporarilyEmptyProvider()
    monkeypatch.setattr(api_module, "get_provider", lambda: provider)

    first = client.get("/api/search?q=Dune")
    second = client.get("/api/search?q=Dune")

    assert first.get_json()["results"] == []
    assert second.get_json()["results"][0]["title"] == "Dune"
    assert len(calls) == 2


def test_open_library_search_retries_transient_timeout(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    calls = []

    class SuccessfulResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "Dune",
                        "author_name": ["Frank Herbert"],
                    }
                ]
            }

    def flaky_get(*args, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise provider_module.requests.Timeout("temporary timeout")
        return SuccessfulResponse()

    monkeypatch.setattr(provider_module.requests, "get", flaky_get)

    results = provider._request("Dune", 4)

    assert results[0]["title"] == "Dune"
    assert calls == [(3.05, 8), (2, 4)]


def test_open_library_results_with_covers_rank_before_missing_covers():
    rank_books = importlib.import_module("readmore.providers.open_library")._rank_books
    books = [
        {"title": "Ohne Cover 1", "cover_url": None},
        {"title": "Mit Cover 1", "cover_url": "https://example.test/1.jpg"},
        {"title": "Mit Cover 2", "cover_url": "https://example.test/2.jpg"},
        {"title": "Ohne Cover 2", "cover_url": None},
    ]

    ranked = rank_books(books)

    assert [book["title"] for book in ranked] == [
        "Mit Cover 1",
        "Mit Cover 2",
        "Ohne Cover 1",
        "Ohne Cover 2",
    ]


def test_open_library_uses_matching_edition_title_cover_and_language(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "docs": [
                    {
                        "key": "OL20850400W",
                        "title": "地球星人",
                        "author_name": [
                            "村田沙耶香",
                            "Mathilde Tamae-Bouhon",
                            "Ginny Tapley Takemori",
                        ],
                        "author_alternative_name": [
                            "Ginny Tapley-Takemori",
                            "Murata Sayaka",
                            "Sayaka Murata",
                            "MURATA SAYAKA",
                        ],
                        "isbn": ["9780000000000"],
                        "first_publish_year": 2018,
                        "number_of_pages_median": 250,
                        "editions": {
                            "docs": [
                                {
                                    "key": "OL28830029M",
                                    "title": "Earthlings",
                                    "isbn": ["9780802157003"],
                                    "cover_i": 12345,
                                    "language": ["eng"],
                                    "number_of_pages": 256,
                                    "publisher": ["Granta Books"],
                                    "publish_date": ["1 October 2020"],
                                    "physical_format": ["Paperback"],
                                }
                            ]
                        },
                    }
                ]
            }

    monkeypatch.setattr(provider_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    result = provider_module.OpenLibraryProvider().search("Earthlings", limit=4)[0]

    assert result["provider_book_id"] == "/works/OL20850400W"
    assert result["provider_edition_id"] == "/books/OL28830029M"
    assert result["title"] == "Earthlings"
    assert result["original_title"] == "地球星人"
    assert result["authors"] == ["Sayaka Murata"]
    assert result["original_authors"][0] == "村田沙耶香"
    assert result["isbn"] == "9780802157003"
    assert result["cover_url"] == "https://covers.openlibrary.org/b/id/12345-M.jpg"
    assert result["language"] == "eng"
    assert result["page_count"] == 256
    assert result["publisher"] == "Granta Books"
    assert result["publish_date"] == "1 October 2020"
    assert result["physical_format"] == "Paperback"


def test_open_library_metadata_combines_work_and_edition(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    responses = {
        "/works/OL1W.json": {
            "description": {"type": "/type/text", "value": "Eine lange Beschreibung."},
            "first_publish_date": "2014",
            "subjects": ["Dystopia", "Science fiction"],
        },
        "/books/OL2M.json": {
            "isbn_13": ["9780345539793"],
            "publishers": ["Del Rey"],
            "publish_date": "Jan 28, 2014",
            "number_of_pages": 416,
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Hardcover",
            "subtitle": "A Novel",
        },
    }
    monkeypatch.setattr(provider, "_get_json", lambda path: responses[path])

    metadata = provider.metadata("/works/OL1W", "/books/OL2M")

    assert metadata == {
        "provider_edition_id": "/books/OL2M",
        "isbn": "9780345539793",
        "publisher": "Del Rey",
        "publish_date": "Jan 28, 2014",
        "page_count": 416,
        "language": "eng",
        "description": "Eine lange Beschreibung.",
        "physical_format": "Hardcover",
        "subtitle": "A Novel",
        "subjects": ["Dystopia", "Science fiction"],
    }


def test_open_library_metadata_selects_an_edition_when_series_book_has_none(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit: [{
            "provider_edition_id": "/books/OL9M",
            "isbn": "9780000000002",
            "page_count": 464,
            "publisher": "Del Rey",
        }],
    )
    monkeypatch.setattr(
        provider,
        "_get_json",
        lambda path: {
            "/works/OL8W.json": {"description": "Band zwei."},
            "/books/OL9M.json": {"number_of_pages": 464},
        }[path],
    )

    metadata = provider.metadata("/works/OL8W")

    assert metadata["provider_edition_id"] == "/books/OL9M"
    assert metadata["publisher"] == "Del Rey"
    assert metadata["page_count"] == 464
    assert metadata["description"] == "Band zwei."


def test_book_metadata_is_loaded_in_background_and_stored_on_book(client):
    created = client.post(
        "/api/books",
        json={**BOOK, "provider_edition_id": "/books/OL2M"},
    ).get_json()["book"]
    calls = []

    class MetadataProvider:
        def metadata(self, provider_book_id, provider_edition_id):
            calls.append((provider_book_id, provider_edition_id))
            return {
                "publisher": "Ace",
                "publish_date": "1969",
                "description": "Metadaten aus Open Library.",
                "subjects": ["Science fiction"],
            }

    pending = client.get(f"/api/books/{created['id']}/metadata").get_json()
    assert pending["status"] == "pending"
    assert pending["metadata"]["provider_edition_id"] == "/books/OL2M"
    assert pending["metadata"]["page_count"] == 304

    metadata_module = importlib.import_module("readmore.metadata_cache")
    assert metadata_module.process_next_metadata_job(
        client.application.config["DATABASE"], MetadataProvider()
    )

    first = client.get(f"/api/books/{created['id']}/metadata").get_json()
    second = client.get(f"/api/books/{created['id']}/metadata").get_json()

    assert first["status"] == "ready"
    assert first["metadata"]["page_count"] == 304
    assert first["metadata"]["publisher"] == "Ace"
    assert first["metadata"]["description"] == "Metadaten aus Open Library."
    assert second == first
    assert calls == [(BOOK["provider_book_id"], "/books/OL2M")]

    stored = client.get("/api/books").get_json()["books"][0]
    assert stored["publisher"] == "Ace"
    assert stored["publish_date"] == "1969"
    assert stored["description"] == "Metadaten aus Open Library."
    assert stored["subjects"] == ["Science fiction"]


def test_series_endpoint_is_immediate_then_uses_background_result(client):
    created = client.post("/api/books", json=BOOK).get_json()["book"]
    expected = {
        "name": "Earthsea",
        "current_position": "1",
        "source": "structured",
        "incomplete": False,
        "books": [{"title": "A Wizard of Earthsea", "provider_book_id": "/works/OL1W"}],
    }

    class FakeProvider:
        def series(self, provider_book_id, authors, limit):
            assert provider_book_id == BOOK["provider_book_id"]
            assert authors == BOOK["authors"]
            assert limit == 24
            return expected

    pending = client.get(f"/api/books/{created['id']}/series")
    assert pending.status_code == 200
    assert pending.get_json() == {"series": None, "status": "pending"}

    cache_module = importlib.import_module("readmore.series_cache")
    assert cache_module.process_next_series_job(
        client.application.config["DATABASE"], FakeProvider()
    )
    response = client.get(f"/api/books/{created['id']}/series")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["series"]["name"] == expected["name"]
    assert response.get_json()["series"]["books"][0]["title"] == "A Wizard of Earthsea"


def test_partial_google_refresh_does_not_remove_cached_series_members(client):
    cache_module = importlib.import_module("readmore.series_cache")
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        cache_module.enqueue_series_lookup(
            db, "tearbird-1", ["Young-do Lee"], provider="google_books"
        )
        cache_module.persist_series_result(
            db,
            "tearbird-1",
            ["Young-do Lee"],
            {
                "name": "Die Legende vom Tränenvogel",
                "current_position": 1,
                "source": "google_title",
                "incomplete": True,
                "books": [
                    {
                        "provider_book_id": "tearbird-1",
                        "title": "Das Blut der Herzlosen",
                        "authors": ["Young-do Lee"],
                        "series_position": 1,
                    },
                    {
                        "provider_book_id": "tearbird-2",
                        "title": "Der träumende Krieger",
                        "authors": ["Young-do Lee"],
                        "series_position": 2,
                    },
                ],
            },
            provider="google_books",
        )

        # Eine spätere Google-Antwort enthält zeitweise nur den aktuellen Band.
        cache_module.persist_series_result(
            db,
            "tearbird-2",
            ["Young-do Lee"],
            {
                "name": "Die Legende vom Tränenvogel",
                "current_position": 2,
                "source": "google_title",
                "incomplete": True,
                "books": [{
                    "provider_book_id": "tearbird-2",
                    "title": "Der träumende Krieger",
                    "authors": ["Young-do Lee"],
                    "series_position": 2,
                }],
            },
            provider="google_books",
        )
        series, status = cache_module.get_cached_series(
            db, "tearbird-2", provider="google_books"
        )

    assert status == "ready"
    assert [book["series_position"] for book in series["books"]] == ["1", "2"]


def test_better_series_source_replaces_stale_subject_members(client):
    cache_module = importlib.import_module("readmore.series_cache")
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        cache_module.enqueue_series_lookup(
            db, "/works/OL1W", ["Author"], provider="open_library"
        )
        cache_module.persist_series_result(
            db,
            "/works/OL1W",
            ["Author"],
            {
                "name": "Test Series",
                "source": "subject",
                "incomplete": True,
                "books": [
                    {"provider_book_id": "/works/OL1W", "title": "Book One"},
                    {"provider_book_id": "/works/STALEW", "title": "Stale Bundle"},
                ],
            },
            provider="open_library",
        )
        cache_module.persist_series_result(
            db,
            "/works/OL1W",
            ["Author"],
            {
                "name": "Test Series",
                "source": "edition",
                "incomplete": True,
                "books": [
                    {
                        "provider_book_id": "/works/OL1W",
                        "title": "Book One",
                        "series_position": 1,
                    },
                    {
                        "provider_book_id": "/works/OL2W",
                        "title": "Book Two",
                        "series_position": 2,
                    },
                ],
            },
            provider="open_library",
        )
        series, _status = cache_module.get_cached_series(
            db, "/works/OL1W", provider="open_library"
        )

    assert [book["provider_book_id"] for book in series["books"]] == [
        "/works/OL1W",
        "/works/OL2W",
    ]


def test_manual_book_has_no_catalogue_series(client):
    created = client.post(
        "/api/books", json={"title": "Eigenes Buch", "authors": "Eine Person", "status": "reading"}
    ).get_json()["book"]

    response = client.get(f"/api/books/{created['id']}/series")

    assert response.status_code == 200
    assert response.get_json() == {"series": None, "status": "no_series"}


def test_catalogue_series_supports_unsaved_search_result_in_background(client):
    expected = {
        "name": "Testreihe",
        "current_position": "1",
        "source": "structured",
        "incomplete": False,
        "books": [],
    }

    class FakeProvider:
        def series(self, provider_book_id, authors, limit):
            assert provider_book_id == "/works/OL99W"
            assert authors == ["Eine Autorin"]
            assert limit == 24
            return expected

    pending = client.get(
        "/api/series?provider_book_id=/works/OL99W&author=Eine%20Autorin"
    )
    assert pending.get_json() == {"series": None, "status": "pending"}

    cache_module = importlib.import_module("readmore.series_cache")
    assert cache_module.process_next_series_job(
        client.application.config["DATABASE"], FakeProvider()
    )
    response = client.get("/api/series?provider_book_id=/works/OL99W&author=Eine%20Autorin")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert response.get_json()["series"]["name"] == expected["name"]


def test_open_library_structured_series_is_normalized(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()
    responses = {
        "/works/OL1W.json": {
            "series": [{"series": {"key": "/series/OL7L"}, "position": "2"}]
        },
        "/series/OL7L.json": {"name": "Testreihe"},
        "/series/OL7L/seeds.json": {
            "entries": [
                {
                    "type": "work",
                    "url": "/works/OL2W",
                    "title": "Band eins",
                    "picture": {},
                    "number_of_pages": 320,
                },
                {
                    "type": "work",
                    "url": "/works/OL1W",
                    "title": "Band zwei",
                    "picture": {"url": "//covers.openlibrary.org/b/id/42-S.jpg"},
                },
            ]
        },
    }
    monkeypatch.setattr(provider, "_get_json", lambda path: responses[path])

    series = provider.series("/works/OL1W", ["Test Author"])

    assert series["name"] == "Testreihe"
    assert series["current_position"] == "2"
    assert series["books"][1]["series_position"] == "2"
    assert series["books"][1]["cover_url"] == "https://covers.openlibrary.org/b/id/42-M.jpg"
    assert series["books"][0]["authors"] == ["Test Author"]
    assert series["books"][0]["page_count"] == 320


def test_open_library_subject_series_uses_edition_positions(monkeypatch):
    provider_module = importlib.import_module("readmore.providers.open_library")
    provider = provider_module.OpenLibraryProvider()

    def book(position, title, work_id):
        return {
            "provider": "open_library",
            "provider_book_id": f"/works/{work_id}W",
            "provider_edition_id": f"/books/{work_id}M",
            "title": title,
            "authors": ["Brandon Sanderson"],
            "first_publish_year": 2009 + position,
            "cover_url": f"https://covers.example/{position}.jpg",
        }

    main_books = [
        book(1, "The Way of Kings", "OL1"),
        book(2, "Words of Radiance", "OL2"),
        book(3, "Oathbringer", "OL3"),
        book(4, "Rhythm of War", "OL4"),
        book(5, "Wind and Truth", "OL5"),
    ]
    edgedancer = book(2, "Edgedancer", "OL25")
    collection = book(6, "Stormlight Archive Series 6 Books Collection Set", "OL6")
    queries = []

    monkeypatch.setattr(
        provider,
        "_get_json",
        lambda path: {
            "title": "The Way of Kings",
            "subjects": ["series:Stormlight Archive"],
        },
    )

    def fake_request(query, limit, **_kwargs):
        queries.append(query)
        if query.startswith('subject:'):
            return [main_books[0], main_books[-1]]
        return [edgedancer, *main_books, collection]

    monkeypatch.setattr(provider, "_request", fake_request)
    details = {
        "/books/OL1M": {"key": "/books/OL1M", "title": "The Way of Kings (The Stormlight Archive #1)"},
        "/books/OL2M": {"key": "/books/OL2M", "subtitle": "Book Two of the Stormlight Archive"},
        "/books/OL3M": {"key": "/books/OL3M", "subtitle": "The Stormlight Archive Book Three"},
        "/books/OL4M": {"key": "/books/OL4M", "subtitle": "Book Four of The Stormlight Archive"},
        "/books/OL5M": {"key": "/books/OL5M", "subtitle": "Book Five of the Stormlight Archive"},
        "/books/OL25M": {"key": "/books/OL25M", "subtitle": "From the Stormlight Archive"},
        "/books/OL6M": {"key": "/books/OL6M", "title": collection["title"]},
    }
    monkeypatch.setattr(provider, "_edition_details", lambda books: details)

    series = provider.series("/works/OL1W", ["Brandon Sanderson"])

    assert series["name"] == "Stormlight Archive"
    assert series["source"] == "edition"
    assert series["current_position"] == 1
    assert [book["title"] for book in series["books"]] == [
        "The Way of Kings",
        "Words of Radiance",
        "Oathbringer",
        "Rhythm of War",
        "Wind and Truth",
    ]
    assert [book["series_position"] for book in series["books"]] == [1, 2, 3, 4, 5]
    assert queries == [
        'subject:"series:Stormlight Archive"',
        '"Stormlight Archive" author:"Brandon Sanderson"',
    ]


def test_series_cache_survives_app_restart(tmp_path):
    database = tmp_path / "series-cache.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    created = first_app.test_client().post("/api/books", json=BOOK).get_json()["book"]

    class FakeProvider:
        def series(self, provider_book_id, authors, limit):
            return {
                "name": "Hainish Cycle",
                "provider_series_id": "/series/OL42L",
                "current_position": "4",
                "source": "structured",
                "incomplete": False,
                "books": [
                    {
                        "title": BOOK["title"],
                        "authors": BOOK["authors"],
                        "provider_book_id": BOOK["provider_book_id"],
                        "provider_edition_id": "/books/OL42M",
                        "publish_date": "1 June 1974",
                        "page_count": 387,
                        "series_position": "4",
                    }
                ],
            }

    cache_module = importlib.import_module("readmore.series_cache")
    assert cache_module.process_next_series_job(str(database), FakeProvider())

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    response = restarted_app.test_client().get(f"/api/books/{created['id']}/series").get_json()
    assert response["status"] == "ready"
    assert response["series"]["name"] == "Hainish Cycle"
    assert response["series"]["books"][0]["provider_edition_id"] == "/books/OL42M"
    assert response["series"]["books"][0]["publish_date"] == "1 June 1974"
    assert response["series"]["books"][0]["page_count"] == 387


def test_failed_series_fetch_is_persisted_for_retry(client):
    client.post("/api/books", json=BOOK)
    cache_module = importlib.import_module("readmore.series_cache")
    provider_module = importlib.import_module("readmore.providers.open_library")

    class FailingProvider:
        def series(self, provider_book_id, authors, limit):
            raise provider_module.ProviderUnavailable("Temporär nicht erreichbar")

    assert cache_module.process_next_series_job(
        client.application.config["DATABASE"], FailingProvider()
    )
    response = client.get("/api/books/1/series").get_json()
    assert response["series"] is None
    assert response["status"] == "retry"
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        row = db.execute(
            "SELECT attempts, next_attempt_at, last_error FROM series_lookups"
        ).fetchone()
        assert row["attempts"] == 1
        assert row["next_attempt_at"] > 0
        assert "Temporär" in row["last_error"]

        db.execute("UPDATE series_lookups SET next_attempt_at = 0")
        db.commit()

    class RecoveredProvider:
        def series(self, provider_book_id, authors, limit):
            return {
                "name": "Earthsea",
                "current_position": "1",
                "source": "structured",
                "incomplete": False,
                "books": [],
            }

    assert cache_module.process_next_series_job(
        client.application.config["DATABASE"], RecoveredProvider()
    )
    recovered = client.get("/api/books/1/series").get_json()
    assert recovered["status"] == "ready"
    assert recovered["series"]["name"] == "Earthsea"


def test_existing_books_are_queued_when_app_starts(tmp_path):
    database = tmp_path / "backfill.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with first_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        db.execute(
            """
            INSERT INTO books (
                title, authors, provider_book_id, identity_key, status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("Altes Buch", "Eine Person", "/works/OL777W", "altes buch|eine person", "read"),
        )
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    response = restarted_app.test_client().get("/api/books/1/series").get_json()
    assert response == {"series": None, "status": "pending"}
    with restarted_app.app_context():
        metadata_status = importlib.import_module("readmore.db").get_db().execute(
            "SELECT status FROM metadata_lookups WHERE book_id = 1"
        ).fetchone()["status"]
    assert metadata_status == "pending"


def test_old_google_no_series_result_is_requeued_once_after_upgrade(tmp_path):
    database = tmp_path / "google-series-upgrade.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with first_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        db.execute(
            """
            INSERT INTO series_lookups (
                provider, provider_book_id, authors, status, next_attempt_at
            ) VALUES ('google_books', 'tearbird-1', 'Young-do Lee', 'no_series', 9999999999)
            """
        )
        db.execute("PRAGMA user_version = 0")
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with restarted_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        lookup = db.execute(
            "SELECT status, next_attempt_at FROM series_lookups WHERE provider_book_id = 'tearbird-1'"
        ).fetchone()
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]

    assert dict(lookup) == {"status": "pending", "next_attempt_at": 0}
    assert schema_version == 2


def test_cached_partial_google_series_is_requeued_after_matching_upgrade(tmp_path):
    database = tmp_path / "google-series-matching-upgrade.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with first_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        cursor = db.execute(
            """
            INSERT INTO series (
                provider, identity_key, name, source, incomplete,
                metadata_version, fetched_at
            ) VALUES ('google_books', 'name:tearbird', 'Tearbird',
                      'google_title', 1, 4, 1)
            """
        )
        db.execute(
            """
            INSERT INTO series_lookups (
                provider, provider_book_id, authors, status, series_id,
                next_attempt_at
            ) VALUES ('google_books', 'tearbird-1', 'Young-do Lee', 'ready', ?, 9999999999)
            """,
            (cursor.lastrowid,),
        )
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with restarted_app.app_context():
        lookup = importlib.import_module("readmore.db").get_db().execute(
            "SELECT status, next_attempt_at FROM series_lookups WHERE provider_book_id = 'tearbird-1'"
        ).fetchone()

    assert dict(lookup) == {"status": "pending", "next_attempt_at": 0}


def test_cached_subject_series_is_requeued_for_edition_upgrade(tmp_path):
    database = tmp_path / "open-library-series-upgrade.db"
    first_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with first_app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        cursor = db.execute(
            """
            INSERT INTO series (
                provider, identity_key, name, source, incomplete,
                metadata_version, fetched_at
            ) VALUES ('open_library', 'name:stormlight-archive',
                      'Stormlight Archive', 'subject', 1, 5, 1)
            """
        )
        db.execute(
            """
            INSERT INTO series_lookups (
                provider, provider_book_id, authors, status, series_id,
                next_attempt_at
            ) VALUES ('open_library', '/works/OL15358691W', 'Brandon Sanderson',
                      'ready', ?, 9999999999)
            """,
            (cursor.lastrowid,),
        )
        db.commit()

    restarted_app = create_app({"TESTING": True, "DATABASE": str(database)})
    with restarted_app.app_context():
        lookup = importlib.import_module("readmore.db").get_db().execute(
            "SELECT status, next_attempt_at FROM series_lookups WHERE provider_book_id = ?",
            ("/works/OL15358691W",),
        ).fetchone()

    assert dict(lookup) == {"status": "pending", "next_attempt_at": 0}


def test_frontend_exposes_all_appearance_palettes(client):
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Moviepedia Startseite"' in html
    assert "Hello, Test User" in html
    assert 'data-book-info-symbol="!"' in html
    assert 'classList.add("platform-mobile")' in html
    assert 'id="appearance-button"' in html
    assert 'id="delete-dialog"' in html
    assert 'id="confirm-delete"' in html
    assert 'id="media-grid"' in html
    assert 'id="sort-button"' in html
    assert 'id="media-type-button"' in html
    assert 'id="collection-grouping-button"' in html
    assert 'id="season-visibility-button"' in html
    assert 'aria-pressed="false"' in html
    assert 'data-media-type-option="movie"' in html
    assert 'data-media-type-option="tv"' in html
    assert 'id="media-preview-dialog"' in html
    assert 'id="media-collection-section"' in html
    assert 'id="media-series-section"' in html
    assert 'style="--season-tabs-per-row: 6"' in html
    assert 'id="media-season-tabs"' in html
    assert 'id="media-episodes-list"' in html
    assert 'id="media-season-add"' in html
    assert 'id="media-season-dialog"' in html
    assert 'id="media-season-dialog-content"' in html
    assert 'id="media-season-dialog-poster"' in html
    assert 'id="media-library-collection-dialog"' in html
    assert 'id="media-library-collection-saved"' in html
    assert 'id="media-library-collection-missing"' in html
    assert 'id="media-library-collection-missing-list"' in html
    assert 'id="media-rating-dialog"' in html
    assert 'data-sort-option="rating_desc"' in html
    script = client.get("/static/js/media-app.js").get_data(as_text=True)
    assert "/api/media/search?q=${encodeURIComponent(query)}&limit=${state.searchLimit}" in script
    assert 'api("/api/media"' in script
    assert "function libraryCard(media)" in script
    assert "function movieCollectionCard(collection, movies)" in script
    assert "function collectionPartRow(part)" in script
    assert "async function ensureMovieCollectionIndex(movies)" in script
    assert "function renderLibraryCollectionDialog(collectionKey)" in script
    assert "function openLibraryCollectionDialog(collectionKey)" in script
    assert "state.expandedMissingCollectionKeys.has(collectionKey)" in script
    assert 'addToWatchlist(part, add)' in script
    assert "visible.forEach((media) => mediaGrid.append(libraryCard(media)))" in script
    assert "function openMediaPreview(media, infoOnly = false, seasonNumber = null)" in script
    assert "openMediaPreview(media, true)" in script
    assert "async function loadMovieCollection(media)" in script
    assert "async function loadSeriesSeasons(media)" in script
    assert "async function loadSeasonEpisodes(media, season)" in script
    assert 'const initialTab = requestedTab || seasonOneTab || tabs.querySelector(".media-season-tab")' in script
    assert "if (Number(season.season_number) === 1) seasonOneTab = tab" in script
    assert "function usesMobileMediaLayout()" in script
    assert "function openMobileSeasonDialog(media, season)" in script
    assert "if (mobileSeasonFlow) activateSeasonTab(tabs, initialTab)" in script
    assert "function episodeRatingControl(episode, media, seasonNumber)" in script
    assert "async function addSeasonToCollection(media, season, button)" in script
    assert 'api("/api/media/seasons"' in script
    assert 'localStorage.setItem("moviepedia-show-seasons"' in script
    assert "`Film ${part.collection_position}`" in script
    assert "`/api/media/movie/${media.tmdb_id}/collection`" in script
    assert 'localStorage.setItem("moviepedia-media-type"' in script
    assert "dataset.bookInfoSymbol" in script
    assert "async function saveRating(event)" in script
    assert "function initializeDialogScrollLock()" in script
    assert 'localStorage.setItem("moviepedia-start-view"' in script
    assert 'data-sort-option="title_asc"' in html
    assert 'data-sort-option="title_desc"' in html
    assert 'data-sort-option="added_desc"' in html
    assert 'data-sort-option="added_asc"' in html
    assert 'id="open-settings"' in html
    assert 'id="settings-dialog"' in html
    assert 'id="settings-theme"' in html
    assert 'id="settings-search-limit"' in html
    assert 'id="settings-start-view"' in html
    assert 'id="search-input" name="q" type="search" minlength="2" maxlength="250"' in html
    assert 'class="settings-version"' in html
    assert client.application.config["BUILD_VERSION"] in html
    for status in ("watchlist", "watching", "completed", "dropped"):
        assert f'data-filter="{status}"' in html
        assert f'<span>{status.title()}</span>' in html
    assert "Alle Bücher" not in html
    assert "Ungelesen" not in html
    assert "Lese ich" not in html
    assert "Gelesen" not in html
    assert "Im Besitz" not in html
    for theme in ("red", "blue-white", "green", "brown", "cozy", "light"):
        assert f'data-theme-option="{theme}"' in html

    config = client.get("/static/config.json").get_json()
    assert config["catalogue"] == {
        "mode": "primary_fallback",
        "primaryProvider": "open_library",
        "fallbackProvider": "google_books",
    }
    assert config["defaults"] == {
        "theme": "blue-white",
        "searchResultLimit": 4,
        "startView": "all",
        "mobileTextSize": 3,
        "dateFormat": "DD-MM-YYYY",
        "reviewMaxLength": 2000,
        "seasonTabsPerRow": 6,
        "searchMaxLength": 250,
        "bookTitleMaxLength": 300,
        "bookAuthorsMaxLength": 500,
        "searchRateLimitPerMinute": 60,
    }
    assert config["options"]["searchResultLimits"] == [4, 6, 8, 12]
    assert [option["value"] for option in config["options"]["dateFormats"]] == [
        "DD-MM-YYYY",
        "DD.MM.YYYY",
        "YYYY-MM-DD",
        "MM/DD/YYYY",
    ]
    assert [provider["value"] for provider in config["options"]["bookProviders"]] == [
        "open_library",
        "google_books",
    ]
    assert [size["value"] for size in config["options"]["mobileTextSizes"]] == [1, 2, 3, 4, 5]
    assert [view["value"] for view in config["options"]["startViews"]] == [
        "all",
        "unread",
        "reading",
        "read",
        "want_to_read",
        "owned",
    ]

