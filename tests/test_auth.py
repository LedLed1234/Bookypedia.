import re

import pytest

from readmore import create_app
from readmore.auth import create_user


PASSWORD = "a-secure-test-passphrase"


def make_app(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "TEST_AUTO_LOGIN": False,
        "CSRF_ENABLED": False,
        "DATABASE": str(tmp_path / "auth.db"),
        "SERIES_WORKER_ENABLED": False,
    }
    config.update(overrides)
    return create_app(config)


def add_user(app, username, *, require_password_change=False):
    with app.app_context():
        return create_user(
            username,
            PASSWORD,
            username.title(),
            require_password_change=require_password_change,
        )[0]


def login(client, username, password=PASSWORD):
    return client.post(
        "/login",
        data={"username": username, "password": password, "next": "/"},
    )


def test_five_character_password_is_allowed(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        create_user("short-password", "abcde", require_password_change=False)
        with pytest.raises(ValueError, match="mindestens 5 Zeichen"):
            create_user("too-short", "abcd", require_password_change=False)

    assert login(app.test_client(), "short-password", "abcde").status_code == 302


def test_private_routes_require_login(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/search?q=Dune").status_code == 401
    assert client.get("/health").status_code == 200


def test_login_cookie_and_csrf_protection(tmp_path):
    app = make_app(tmp_path, CSRF_ENABLED=True, SESSION_COOKIE_SECURE=True)
    add_user(app, "alice")
    client = app.test_client()

    page = client.get("/login")
    token = re.search(
        rb'name="csrf_token" value="([^"]+)"', page.data
    ).group(1).decode()

    rejected = client.post(
        "/login", data={"username": "alice", "password": PASSWORD}
    )
    assert rejected.status_code == 400

    response = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "alice",
            "password": PASSWORD,
            "next": "/",
        },
    )
    assert response.status_code == 302
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie

    page = client.get("/")
    assert page.status_code == 200
    assert b"@alice" in page.data
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]


def test_each_user_has_an_isolated_library(tmp_path):
    app = make_app(tmp_path)
    add_user(app, "alice")
    add_user(app, "bob")
    alice = app.test_client()
    bob = app.test_client()
    assert login(alice, "alice").status_code == 302
    assert login(bob, "bob").status_code == 302

    book = {
        "title": "Red Rising",
        "authors": ["Pierce Brown"],
        "isbn": "9780345539786",
        "provider_book_id": "/works/OL17032059W",
        "status": "want_to_read",
    }
    alice_book = alice.post("/api/books", json=book)
    bob_book = bob.post("/api/books", json=book)
    assert alice_book.status_code == 201
    assert bob_book.status_code == 201
    alice_id = alice_book.get_json()["book"]["id"]
    bob_id = bob_book.get_json()["book"]["id"]
    assert alice_id != bob_id

    assert [item["id"] for item in alice.get("/api/books").get_json()["books"]] == [
        alice_id
    ]
    assert [item["id"] for item in bob.get("/api/books").get_json()["books"]] == [
        bob_id
    ]
    assert bob.patch(f"/api/books/{alice_id}", json={"status": "read"}).status_code == 404
    assert bob.delete(f"/api/books/{alice_id}").status_code == 404
    assert bob.get(f"/api/books/{alice_id}/metadata").status_code == 404
    assert bob.get(f"/api/books/{alice_id}/series").status_code == 404


def test_first_user_adopts_books_from_single_user_version(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        db = __import__("readmore.db", fromlist=["get_db"]).get_db()
        db.execute(
            """
            INSERT INTO books (title, authors, identity_key, status)
            VALUES ('Legacy', 'Autor', 'legacy|autor', 'read')
            """
        )
        db.commit()
        user_id, adopted = create_user(
            "owner", PASSWORD, "Owner", require_password_change=False
        )
        row = db.execute("SELECT user_id FROM books WHERE title = 'Legacy'").fetchone()

    assert adopted == 1
    assert row["user_id"] == user_id
    client = app.test_client()
    login(client, "owner")
    assert client.get("/api/books").get_json()["books"][0]["title"] == "Legacy"


def test_temporary_password_must_be_changed(tmp_path):
    app = make_app(tmp_path)
    add_user(app, "new-user", require_password_change=True)
    client = app.test_client()

    response = login(client, "new-user")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/password")
    assert client.get("/api/books").status_code == 403
    assert client.get("/").headers["Location"].endswith("/account/password")


def test_repeated_login_failures_are_throttled(tmp_path):
    app = make_app(tmp_path)
    add_user(app, "alice")
    client = app.test_client()

    for _ in range(5):
        response = login(client, "alice", "wrong-password")
        assert response.status_code == 200

    blocked = login(client, "alice")
    assert blocked.status_code == 200
    assert "Zu viele fehlgeschlagene Versuche" in blocked.get_data(as_text=True)
    assert client.get("/api/books").status_code == 401


def test_password_change_invalidates_other_sessions(tmp_path):
    app = make_app(tmp_path)
    add_user(app, "alice")
    first = app.test_client()
    second = app.test_client()
    login(first, "alice")
    login(second, "alice")

    response = first.post(
        "/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "a-new-secure-passphrase",
            "password_confirmation": "a-new-secure-passphrase",
        },
    )
    assert response.status_code == 302
    assert first.get("/api/books").status_code == 200
    assert second.get("/api/books").status_code == 401


def test_accounts_can_be_managed_only_through_cli(tmp_path):
    app = make_app(tmp_path)
    runner = app.test_cli_runner()

    created = runner.invoke(
        args=["user", "create", "charlie", "--display-name", "Charlie"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert created.exit_code == 0
    assert "wurde angelegt" in created.output

    listed = runner.invoke(args=["user", "list"])
    assert listed.exit_code == 0
    assert "charlie (Charlie) — aktiv" in listed.output
    assert PASSWORD not in listed.output

    deactivated = runner.invoke(args=["user", "deactivate", "charlie"])
    assert deactivated.exit_code == 0
    assert login(app.test_client(), "charlie").status_code == 200

    activated = runner.invoke(args=["user", "activate", "charlie"])
    assert activated.exit_code == 0
    assert login(app.test_client(), "charlie").status_code == 302
