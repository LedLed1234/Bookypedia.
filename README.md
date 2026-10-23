# Bookypedia.

![](/home/led/.config/marktext/images/2026-10-23-16-36-33-image.png)

Eine persönliche, deutschsprachige Leseverwaltung mit Flask, SQLite und der Open-Library-Suche. Die App läuft lokal per Docker; deine Sammlung liegt dauerhaft in einem Docker-Volume.

Bücher und bereits ermittelte Reihen werden gemeinsam in SQLite gespeichert. Neue Bücher sind sofort verfügbar; die zugehörige Reihe lädt ein Hintergrund-Worker unabhängig von der Bedienoberfläche nach. Vorhandene Bücher ohne Reiheninformationen werden beim nächsten App-Start automatisch ergänzt. Vorübergehende Fehler bei Open Library werden mit wachsendem Zeitabstand erneut versucht.

## Starten

Voraussetzung: Docker Desktop bzw. Docker Engine mit Docker Compose.

```bash
docker compose up --build
```

Danach im Browser **http://localhost:5000** öffnen. Der Quellcode ist als Bind-Mount eingebunden; Änderungen laden den Flask-Entwicklungsserver automatisch neu.

## Android-App lokal testen

Die Capacitor-Version liegt getrennt unter `mobile/`. Sie verwendet in der
aktuellen Entwicklungsphase dieselbe Flask-Oberfläche und Datenbank wie der
Browser. Mit einem per USB verbundenen Android-Handy oder einem Emulator:

```bash
docker compose up --build -d
cd mobile
npm install
npm run run
```

Auf einem physischen Handy muss zuvor in den Entwickleroptionen USB-Debugging
aktiviert und die Verbindung zu diesem PC bestätigt werden. Das Startskript
richtet über ADB eine lokale Portweiterleitung ein, synchronisiert Capacitor und
installiert die App. Weitere Hinweise stehen in `mobile/README.md`.

Die Android-Konfiguration erlaubt vorübergehend unverschlüsseltes HTTP zu
`localhost:5000`. Das ist ausschließlich für die lokale Entwicklung vorgesehen
und wird vor der Verbindung mit dem VPS durch HTTPS und Geräteanmeldung ersetzt.

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

## Bookypedia auf dem VPS aktualisieren

Der Produktionscode liegt auf dem VPS unter `/opt/bookypedia`. Nach einem Push auf den `main`-Branch wird die laufende Installation als administrativer Benutzer aktualisiert mit:

```bash
cd /opt/bookypedia
git pull --ff-only
docker compose -f compose.prod.yaml up --build -d
```

Anschließend Status und aktuelle Logs kontrollieren:

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs --tail=100 app
```

`git pull` aktualisiert nur den Anwendungscode. Die SQLite-Datenbank liegt dauerhaft im benannten Docker-Volume `readmore_prod_data` und bleibt bei Neubauten und Container-Neustarts erhalten. Weder `docker compose down -v` noch `docker volume rm` verwenden, wenn die gespeicherte Sammlung erhalten bleiben soll.

## Lokaler Desktop-Starter über SSH

Unter Linux kann Bookypedia ohne öffentlich freigegebenen Web-Port über einen SSH-Tunnel geöffnet werden. Voraussetzung ist der SSH-Konfigurationseintrag `bookypedia-vps`. Den Starter installieren mit:

```bash
./scripts/install-desktop-launcher
```

Danach im Anwendungsmenü nach **Bookypedia** suchen. Der Starter baut bei Bedarf einen SSH-Tunnel auf und öffnet `http://bookypedia.localhost:8000` in Firefox. Das geöffnete Terminal hält die Verbindung aufrecht. Mit `Strg+C` oder durch Schließen des Terminalfensters wird der Tunnel wieder beendet.

Der lokale SSH-Agent übernimmt die Passphrase des Schlüssels. Falls der Schlüssel noch nicht entsperrt ist, fragt der Starter beim ersten Verbindungsaufbau danach.

## Suchanbieter austauschen

Open Library ist hinter der kleinen Provider-Schnittstelle in `readmore/providers/` gekapselt. Ein anderer Katalog kann dort dieselben normalisierten Felder (`title`, `authors`, `isbn`, `cover_url`, `provider_book_id`) liefern und anschließend über `BOOK_PROVIDER` ausgewählt werden. Die bereits gespeicherten Bücher bleiben unabhängig vom Suchanbieter erhalten.

Die Open-Library-Suche unterscheidet zwischen dem sprachunabhängigen Werk und der passendsten konkreten Ausgabe. Angezeigt und gespeichert werden bevorzugt Titel, ISBN, Sprache und Cover der passenden Ausgabe; die Work-ID bleibt für Duplikaterkennung und Reihen erhalten. Originaltitel und Originalautor können zusätzlich in der Buchdetailansicht erscheinen. Vergleiche und manuelle Duplikaterkennung unterstützen Unicode-Schriften wie Japanisch, Kyrillisch und Arabisch.
