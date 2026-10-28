import importlib

import pytest


def test_sqlite_search_cache_reuses_exact_provider_results(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    provider_module = importlib.import_module("readmore.providers")
    api_module._SEARCH_CACHE.clear()
    calls = []

    class FakeProvider:
        def search(self, query, limit):
            calls.append(("search", query, limit))
            return [{"title": query, "authors": ["Cache Author"], "provider": "open_library"}]

    monkeypatch.setattr(provider_module, "create_provider", lambda _name: FakeProvider())
    url = (
        "/api/search?q=Persistent%20Cache%20Novel&limit=4"
        "&primary_provider=open_library&fallback_provider=open_library"
    )

    first = client.get(url).get_json()["results"]
    api_module._SEARCH_CACHE.clear()
    second = client.get(url).get_json()["results"]

    assert second == first
    assert calls == [("search", "Persistent Cache Novel", 4)]
    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        row = db.execute(
            "SELECT query_hash, search_kind, result_limit FROM catalogue_search_cache"
        ).fetchone()
    assert len(row["query_hash"]) == 64
    assert "persistent" not in row["query_hash"]
    assert row["search_kind"] == "search"
    assert row["result_limit"] == 4


def test_suggestions_and_full_search_have_separate_l2_entries(client, monkeypatch):
    api_module = importlib.import_module("readmore.api")
    provider_module = importlib.import_module("readmore.providers")
    api_module._SEARCH_CACHE.clear()

    class FakeProvider:
        def search(self, query, limit):
            return [{"title": query, "authors": [], "provider": "open_library"}]

        def suggest(self, query, limit):
            return [{"title": query, "authors": [], "provider": "open_library"}]

    monkeypatch.setattr(provider_module, "create_provider", lambda _name: FakeProvider())
    base = (
        "/api/search?q=Separate%20Cache"
        "&primary_provider=open_library&fallback_provider=open_library"
    )
    assert client.get(f"{base}&suggest=1").status_code == 200
    assert client.get(f"{base}&limit=4").status_code == 200

    with client.application.app_context():
        db = importlib.import_module("readmore.db").get_db()
        kinds = {
            row["search_kind"]
            for row in db.execute("SELECT search_kind FROM catalogue_search_cache").fetchall()
        }
    assert kinds == {"suggest", "search"}


def test_empty_l2_result_expires_after_short_ttl(app, monkeypatch):
    cache_module = importlib.import_module("readmore.search_cache")
    now = [1000]
    calls = []

    class EmptyProvider:
        def search(self, query, limit):
            calls.append((query, limit))
            return []

    monkeypatch.setattr(cache_module, "time", lambda: now[0])
    with app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        provider = EmptyProvider()
        assert cache_module.cached_catalogue_search(
            db, "open_library", provider, "search", "No Result", 4
        ) == []
        now[0] += cache_module.EMPTY_TTL_SECONDS - 1
        assert cache_module.cached_catalogue_search(
            db, "open_library", provider, "search", "No Result", 4
        ) == []
        now[0] += 2
        assert cache_module.cached_catalogue_search(
            db, "open_library", provider, "search", "No Result", 4
        ) == []

    assert calls == [("No Result", 4), ("No Result", 4)]


def test_provider_errors_are_not_cached(app):
    cache_module = importlib.import_module("readmore.search_cache")
    unavailable = importlib.import_module("readmore.providers.base").ProviderUnavailable

    class FailingProvider:
        def search(self, query, limit):
            raise unavailable("temporary")

    with app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        with pytest.raises(unavailable):
            cache_module.cached_catalogue_search(
                db, "open_library", FailingProvider(), "search", "Failure", 4
            )
        count = db.execute("SELECT COUNT(*) FROM catalogue_search_cache").fetchone()[0]

    assert count == 0


def test_l2_cache_removes_oldest_entries_above_limit(app, monkeypatch):
    cache_module = importlib.import_module("readmore.search_cache")
    now = [1000]

    class Provider:
        def search(self, query, limit):
            return [{"title": query}]

    monkeypatch.setattr(cache_module, "MAX_CACHE_ENTRIES", 2)
    monkeypatch.setattr(cache_module, "time", lambda: now[0])
    with app.app_context():
        db = importlib.import_module("readmore.db").get_db()
        for query in ("First", "Second", "Third"):
            cache_module.cached_catalogue_search(
                db, "open_library", Provider(), "search", query, 4
            )
            now[0] += 1
        rows = db.execute(
            "SELECT fetched_at FROM catalogue_search_cache ORDER BY fetched_at"
        ).fetchall()

    assert [row["fetched_at"] for row in rows] == [1001, 1002]
