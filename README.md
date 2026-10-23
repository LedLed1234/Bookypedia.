# Bookypedia.

Eine persönliche, deutschsprachige Leseverwaltung mit Flask, SQLite und der Open-Library-Suche. Die App läuft lokal per Docker; deine Sammlung liegt dauerhaft in einem Docker-Volume.

Bücher und bereits ermittelte Reihen werden gemeinsam in SQLite gespeichert. Neue Bücher sind sofort verfügbar; die zugehörige Reihe lädt ein Hintergrund-Worker unabhängig von der Bedienoberfläche nach. Vorhandene Bücher ohne Reiheninformationen werden beim nächsten App-Start automatisch ergänzt. Vorübergehende Fehler bei Open Library werden mit wachsendem Zeitabstand erneut versucht.

## Starten

Voraussetzung: Docker Desktop bzw. Docker Engine mit Docker Compose.

```bash
docker compose up --build
```

Danach im Browser **http://localhost:5000** öffnen. Der Quellcode ist als Bind-Mount eingebunden; Änderungen laden den Flask-Entwicklungsserver automatisch neu.

Im Hintergrund starten:

```bash
docker compose up --build -d
```

## Stoppen

```bash
docker compose down
```

Das benannte Volume `readmore_data` bleibt dabei erhalten. `docker compose down -v` würde dagegen auch die gespeicherte Sammlung löschen und sollte nur bewusst verwendet werden.

## Datenbank sichern und wiederherstellen

Für eine konsistente Sicherung die App zuerst stoppen:

```bash
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
  python -c "import sqlite3; source=sqlite3.connect('/data/readmore.db'); target=sqlite3.connect('/backup/readmore-backup.db'); source.backup(target); target.close(); source.close()"
docker compose start app
```

Die Sicherung liegt anschließend unter `backups/readmore-backup.db`. Wiederherstellen lässt sie sich nach dem Stoppen der App mit:

```bash
docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app \
  python -c "import sqlite3; source=sqlite3.connect('/backup/readmore-backup.db'); target=sqlite3.connect('/data/readmore.db'); source.backup(target); target.close(); source.close()"
```

## Tests

```bash
docker compose run --rm app pytest -q
```

Die Tests prüfen unter anderem, dass Reihenabfragen nicht das Hinzufügen oder Öffnen eines Buches blockieren, dass fehlgeschlagene Abfragen erneut eingeplant werden und dass der Reihencache einen Neustart überlebt.

## Logs ansehen

Die App schreibt strukturierte Logs nach stdout. Docker übernimmt die Speicherung und begrenzt sie auf drei Dateien mit jeweils maximal 10 MB:

```bash
docker compose logs -f app
```

Standardmäßig gilt `LOG_LEVEL=INFO`. Für die Fehlersuche lassen sich zusätzlich erfolgreiche Lese- und Polling-Anfragen einblenden:

```bash
LOG_LEVEL=DEBUG docker compose up
```

Mit `LOG_FORMAT=text` kann lokal statt JSON ein kompakteres Textformat verwendet werden. Logs enthalten technische IDs, Statuswerte und Laufzeiten, aber keine Suchbegriffe, Buchtitel, ISBNs oder Bewertungstexte. Jede HTTP-Antwort enthält außerdem eine `X-Request-ID`, über die sich ein Fehler im Log wiederfinden lässt.

## Produktionsvorbereitung

Eine getrennte Compose-Datei startet die App ohne Debug-Modus mit Gunicorn und bindet sie lokal an Port 8000:

```bash
docker compose -f compose.prod.yaml up --build -d
```

Für einen öffentlich erreichbaren VPS müssen davor ein HTTPS-Reverse-Proxy und ein Zugangsschutz ergänzt werden. Die Produktionskonfiguration veröffentlicht Gunicorn bewusst nur auf `127.0.0.1`; sie ist für einen vorgeschalteten Proxy gedacht.

## Suchanbieter austauschen

Open Library ist hinter der kleinen Provider-Schnittstelle in `readmore/providers/` gekapselt. Ein anderer Katalog kann dort dieselben normalisierten Felder (`title`, `authors`, `isbn`, `cover_url`, `provider_book_id`) liefern und anschließend über `BOOK_PROVIDER` ausgewählt werden. Die bereits gespeicherten Bücher bleiben unabhängig vom Suchanbieter erhalten.

Die Open-Library-Suche unterscheidet zwischen dem sprachunabhängigen Werk und der passendsten konkreten Ausgabe. Angezeigt und gespeichert werden bevorzugt Titel, ISBN, Sprache und Cover der passenden Ausgabe; die Work-ID bleibt für Duplikaterkennung und Reihen erhalten. Originaltitel und Originalautor können zusätzlich in der Buchdetailansicht erscheinen. Vergleiche und manuelle Duplikaterkennung unterstützen Unicode-Schriften wie Japanisch, Kyrillisch und Arabisch.

