import importlib
import sqlite3

from readmore import create_app


BOOK = {
    "title": "Die linke Hand der Dunkelheit",
    "authors": ["Ursula K. Le Guin"],
    "isbn": "9783453314552",
    "provider_book_id": "/works/OL24320W",
    "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
    "page_count": 304,
    "status": "want_to_read",
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


def test_frontend_exposes_all_appearance_palettes(client):
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Epiloguehouse Startseite"' in html
    assert "Hello, Test User" in html
    assert 'data-book-info-symbol="!"' in html
    assert 'classList.add("platform-mobile")' in html
    assert 'id="appearance-button"' in html
    assert 'id="search-suggestions"' in html
    assert 'aria-controls="search-suggestions"' in html
    assert 'id="delete-dialog"' in html
    assert 'id="confirm-delete"' in html
    assert 'id="book-dialog"' in html
    assert 'id="series-content"' in html
    assert 'id="grouping-button"' in html
    assert 'id="collection-dialog"' in html
    assert 'id="collection-book-list"' in html
    assert 'id="sort-button"' in html
    assert 'data-sort-option="rating_desc"' in html
    assert 'data-sort-option="rating_asc"' in html
    assert 'data-sort-option="title_asc"' in html
    assert 'data-sort-option="title_desc"' in html
    assert 'data-sort-option="added_desc"' in html
    assert 'data-sort-option="added_asc"' in html
    assert 'id="reading-history"' in html
    assert 'id="reading-history-list"' in html
    assert 'id="open-settings"' in html
    assert 'id="settings-dialog"' in html
    assert 'id="settings-theme"' in html
    assert 'id="settings-search-limit"' in html
    assert 'id="settings-start-view"' in html
    assert 'id="settings-mobile-text-size"' in html
    assert 'data-filter="unread"' in html
    assert '<span>Ungelesen</span>' in html
    assert '<span>Lese ich</span>' in html
    assert '<span>Gelesen</span>' in html
    assert '<span>Wunschliste</span>' in html
    assert '<span>Im Besitz</span>' in html
    assert 'id="book-dialog-original"' in html
    assert 'id="book-dialog-info"' in html
    assert 'id="book-dialog-main-view"' in html
    assert 'id="book-dialog-info-view"' in html
    assert 'id="book-info-back"' in html
    assert 'id="book-description-toggle"' in html
    assert 'aria-controls="book-description-copy"' in html
    assert 'id="book-dialog-back"' not in html
    assert 'id="book-dialog-status"' not in html
    assert 'id="book-dialog-save"' not in html
    assert 'id="book-dialog-review"' not in html
    assert "automatisch zu „Gelesen“ verschoben" in html
    for theme in ("red", "blue-white", "green", "brown", "cozy", "light"):
        assert f'data-theme-option="{theme}"' in html

    config = client.get("/static/config.json").get_json()
    assert config["defaults"] == {
        "theme": "blue-white",
        "searchResultLimit": 4,
        "startView": "all",
        "mobileTextSize": 3,
    }
    assert config["options"]["searchResultLimits"] == [4, 6, 8, 12]
    assert [size["value"] for size in config["options"]["mobileTextSizes"]] == [1, 2, 3, 4, 5]
    assert [view["value"] for view in config["options"]["startViews"]] == [
        "all",
        "unread",
        "reading",
        "read",
        "want_to_read",
        "owned",
    ]

