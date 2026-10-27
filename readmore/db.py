import sqlite3

from flask import current_app, g

from .text import identity_key


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    password_change_required INTEGER NOT NULL DEFAULT 1
        CHECK (password_change_required IN (0, 1)),
    auth_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    isbn TEXT,
    provider TEXT NOT NULL DEFAULT 'manual',
    provider_book_id TEXT,
    provider_edition_id TEXT,
    cover_url TEXT,
    original_title TEXT,
    original_authors TEXT NOT NULL DEFAULT '',
    language TEXT,
    page_count INTEGER CHECK (page_count IS NULL OR page_count > 0),
    publisher TEXT,
    publish_date TEXT,
    description TEXT,
    physical_format TEXT,
    subtitle TEXT,
    subjects_json TEXT NOT NULL DEFAULT '[]',
    identity_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'want_to_read'
        CHECK (status IN ('want_to_read', 'reading', 'read')),
    is_owned INTEGER NOT NULL DEFAULT 0 CHECK (is_owned IN (0, 1)),
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    review TEXT NOT NULL DEFAULT '',
    want_to_read_at TEXT,
    owned_at TEXT,
    reading_at TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    provider_series_id TEXT,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    incomplete INTEGER NOT NULL DEFAULT 0,
    metadata_version INTEGER NOT NULL DEFAULT 3,
    fetched_at INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, identity_key)
);

CREATE TABLE IF NOT EXISTS series_members (
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    provider_book_id TEXT NOT NULL,
    provider_edition_id TEXT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    isbn TEXT,
    cover_url TEXT,
    first_publish_year INTEGER,
    publish_date TEXT,
    page_count INTEGER,
    position TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (series_id, provider_book_id)
);

CREATE INDEX IF NOT EXISTS idx_series_members_provider_book
    ON series_members(provider_book_id);

CREATE TABLE IF NOT EXISTS book_series (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    position TEXT,
    PRIMARY KEY (book_id, series_id)
);

CREATE TABLE IF NOT EXISTS series_lookups (
    provider TEXT NOT NULL,
    provider_book_id TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'retry', 'ready', 'no_series')),
    series_id INTEGER REFERENCES series(id) ON DELETE SET NULL,
    current_position TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    locked_at INTEGER,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (provider, provider_book_id)
);

CREATE INDEX IF NOT EXISTS idx_series_lookups_queue
    ON series_lookups(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS book_metadata_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_book_id TEXT NOT NULL,
    provider_edition_id TEXT,
    metadata_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata_lookups (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'retry', 'ready')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    locked_at INTEGER,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metadata_lookups_queue
    ON metadata_lookups(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    throttle_key TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    window_started_at INTEGER NOT NULL,
    blocked_until INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 15000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    db.execute("BEGIN IMMEDIATE")
    columns = {row["name"] for row in db.execute("PRAGMA table_info(books)").fetchall()}
    # ALTER TABLE ergänzt bestehende Installationen, ohne unbekannte historische
    # Zeitpunkte aus created_at oder updated_at abzuleiten.
    migrations = {
        "user_id": "INTEGER REFERENCES users(id) ON DELETE CASCADE",
        "want_to_read_at": "TEXT",
        "is_owned": "INTEGER NOT NULL DEFAULT 0",
        "owned_at": "TEXT",
        "reading_at": "TEXT",
        "read_at": "TEXT",
        "provider": "TEXT NOT NULL DEFAULT 'manual'",
        "provider_edition_id": "TEXT",
        "original_title": "TEXT",
        "original_authors": "TEXT NOT NULL DEFAULT ''",
        "language": "TEXT",
        "page_count": "INTEGER",
        "publisher": "TEXT",
        "publish_date": "TEXT",
        "description": "TEXT",
        "physical_format": "TEXT",
        "subtitle": "TEXT",
        "subjects_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for column, definition in migrations.items():
        if column not in columns:
            db.execute(f"ALTER TABLE books ADD COLUMN {column} {definition}")
    db.execute(
        """
        UPDATE books
        SET provider = 'open_library'
        WHERE provider_book_id IS NOT NULL
          AND provider_book_id != ''
          AND (provider IS NULL OR provider = '' OR provider = 'manual')
        """
    )
    db.execute("UPDATE books SET provider = 'manual' WHERE provider IS NULL OR provider = ''")

    # Frühere Versionen behandelten die App als eine einzige globale Sammlung.
    # Ab jetzt gelten Duplikate pro Benutzer. Noch nicht zugeordnete Altbestände
    # bleiben bis zur Anlage des ersten Kontos erhalten und sind nicht sichtbar.
    db.execute("DROP INDEX IF EXISTS idx_books_isbn")
    db.execute("DROP INDEX IF EXISTS idx_books_provider_book_id")
    db.execute("DROP INDEX IF EXISTS idx_books_user_provider_book")
    db.execute("DROP INDEX IF EXISTS idx_books_identity_key")
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_books_user_isbn
        ON books(user_id, isbn)
        WHERE user_id IS NOT NULL AND isbn IS NOT NULL
        """
    )
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_books_user_provider_book
        ON books(user_id, provider, provider_book_id)
        WHERE user_id IS NOT NULL AND provider_book_id IS NOT NULL
        """
    )
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_books_user_identity
        ON books(user_id, identity_key)
        WHERE user_id IS NOT NULL
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_books_user_updated ON books(user_id, updated_at DESC)"
    )

    series_member_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(series_members)").fetchall()
    }
    if "page_count" not in series_member_columns:
        db.execute("ALTER TABLE series_members ADD COLUMN page_count INTEGER")
    if "provider_edition_id" not in series_member_columns:
        db.execute("ALTER TABLE series_members ADD COLUMN provider_edition_id TEXT")
    if "publish_date" not in series_member_columns:
        db.execute("ALTER TABLE series_members ADD COLUMN publish_date TEXT")

    # Ältere Versionen konnten Cover noch mit einer unverschlüsselten Open-
    # Library-Adresse speichern. Unter HTTPS blockiert der Browser diese Bilder.
    # Open Library stellt dieselben Pfade über HTTPS bereit.
    db.execute(
        """
        UPDATE books
        SET cover_url = 'https://' || substr(cover_url, 8)
        WHERE cover_url LIKE 'http://covers.openlibrary.org/%'
        """
    )
    db.execute(
        """
        UPDATE series_members
        SET cover_url = 'https://' || substr(cover_url, 8)
        WHERE cover_url LIKE 'http://covers.openlibrary.org/%'
        """
    )

    series_columns = {row["name"] for row in db.execute("PRAGMA table_info(series)").fetchall()}
    if "metadata_version" not in series_columns:
        db.execute("ALTER TABLE series ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 1")
    # Vorhandene Reihen bleiben über series_id lesbar, werden aber im Hintergrund
    # neu geladen. Version 3 hält Seitenzahl und Erscheinungsdatum gemeinsam mit
    # der konkreten Ausgabe-ID fest, damit die Karten und Buchinfos dieselbe
    # Open-Library-Ausgabe beschreiben.
    db.execute(
        """
        UPDATE series_lookups
        SET status = 'pending', next_attempt_at = 0, locked_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'ready'
          AND series_id IN (SELECT id FROM series WHERE metadata_version < 3)
        """
    )

    # Alte Datensätze können aus Versionen stammen, die spätere Meilensteine
    # beim Zurückstufen behalten haben. Die aktuelle Statushierarchie wird
    # deshalb auch für bereits gespeicherte Bücher einmalig/invariant repariert.
    db.execute(
        """
        UPDATE books
        SET reading_at = NULL, read_at = NULL
        WHERE status = 'want_to_read'
          AND (reading_at IS NOT NULL OR read_at IS NOT NULL)
        """
    )
    # Bücher, die bereits gelesen werden oder wurden, gelten als im Besitz.
    # Bestehende Wunschlisten-Einträge bleiben bewusst auf der Wunschliste.
    db.execute(
        """
        UPDATE books
        SET is_owned = 1
        WHERE status IN ('reading', 'read') AND is_owned = 0
        """
    )
    db.execute(
        """
        UPDATE books
        SET read_at = NULL
        WHERE status = 'reading' AND read_at IS NOT NULL
        """
    )

    # Frühere Versionen entfernten nicht-lateinische Zeichen aus identity_key.
    # Bestehende Schlüssel werden deshalb bestmöglich Unicode-sicher erneuert.
    rows = db.execute("SELECT id, title, authors, identity_key FROM books").fetchall()
    for row in rows:
        normalized_identity = identity_key(row["title"], row["authors"])
        if normalized_identity == row["identity_key"]:
            continue
        try:
            db.execute(
                "UPDATE books SET identity_key = ? WHERE id = ?",
                (normalized_identity, row["id"]),
            )
        except sqlite3.IntegrityError:
            # Ein bereits vorhandener, gleichwertiger Datensatz bleibt maßgeblich.
            pass

    # Ein unterbrochenes Upgrade kann bereits ein erstes Konto, aber noch nicht
    # zugeordnete Altbestände hinterlassen. Nur bei exakt einem Konto ist die
    # Besitzzuordnung eindeutig und darf automatisch abgeschlossen werden.
    owners = db.execute("SELECT id FROM users ORDER BY id LIMIT 2").fetchall()
    if len(owners) == 1:
        db.execute("UPDATE books SET user_id = ? WHERE user_id IS NULL", (owners[0]["id"],))
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

