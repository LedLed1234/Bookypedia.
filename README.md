# Moviepedia

Persönliche Film- und Serienverwaltung mit Flask, SQLite, TMDB und einer
optionalen Android-App. Filme und Serien lassen sich mit Detailvorschau suchen,
zur Watchlist hinzufügen, mit 1–5 Sternen plus persönlicher Review bewerten und
unter **Watching**, **Completed** oder **Dropped** verwalten. Die Sammlung kann
nach Filmen oder Serien gefiltert werden; bei Filmen zeigt die Infoansicht
zugehörige TMDB-Filmreihen und deren einzelne Teile. Bei Serien erscheinen
Staffel-Tabs und eine scrollbar bleibende Episodenliste. Episoden können
persönlich bewertet, aber nicht zur Sammlung hinzugefügt werden. Einzelne
Staffeln lassen sich dagegen als eigene Watchlist-Einträge speichern. Der
„Staffeln“-Schalter in der Sammlungsleiste blendet diese Karten ein oder aus,
ohne sie zu löschen.
Historische Buchdaten bleiben während der Umstellung unangetastet, werden in
der Moviepedia-Oberfläche aber nicht mehr angezeigt. Architekturdetails stehen
in [ARCHITECTURE.md](ARCHITECTURE.md).

## Lokal starten

```bash
sudo systemctl start docker
cd /home/led/moviepedia/Bookypedia.
docker compose up --build -d
```

Danach: **http://localhost:5001**

Beim ersten Start ein Konto anlegen:

```bash
docker compose exec app flask --app run.py user create led
```

## TMDB für Filme und Serien konfigurieren

Den **API Read Access Token** ausschließlich in `.env` speichern:

```bash
TMDB_READ_ACCESS_TOKEN=dein-read-access-token
```

Der Token bleibt im Flask-Backend und wird nicht an den Browser ausgeliefert.
Die Suche verwendet deutsche Metadaten und die Region Deutschland. Ein separater
TMDB-v3-API-Key ist dafür nicht erforderlich.

### Cache und gespeicherte Metadaten

Moviepedia verwendet zwei Cache-Ebenen: Der Browser hält häufig benötigte
Antworten kurz im Arbeitsspeicher; Flask speichert TMDB-Suchen, Filmreihen,
Staffellisten und Episodendetails zusätzlich dauerhaft in SQLite. Die regulären
TTL-Werte liegen je nach Datentyp zwischen 12 Stunden und 7 Tagen. Ist TMDB
vorübergehend nicht erreichbar, dürfen bis zu 30 Tage alte Cache-Daten als
Fallback angezeigt werden.

Gespeicherte Filme und Serien liegen unabhängig davon vollständig in
`media_items`, gespeicherte Staffeln in `saved_seasons`. Ein abgelaufener oder
geleerter TMDB-Cache entfernt deshalb keine Titel, Beschreibungen, Poster-URLs,
Statuswerte oder persönlichen Bewertungen aus der Sammlung.

Die Anzahl der Staffel-Tabs pro Zeile steht in
`readmore/static/config.json`. Standardmäßig beginnt nach sechs Tabs eine neue
Zeile:

```json
"seasonTabsPerRow": 6
```

## Häufige Befehle

```bash
# Starten
docker compose up --build -d

# Status
docker compose ps

# Logs
docker compose logs -f app

# Tests
docker compose run --rm app pytest -q

# Stoppen, Daten behalten
docker compose down
```

Nicht ohne Absicht `docker compose down -v` verwenden: `-v` löscht auch die
gespeicherte Bibliothek.

## Alter Buchkatalog (nur Kompatibilität)

Die folgenden Einstellungen gehören zum erhaltenen Bookypedia-Backend und
werden von der neuen Moviepedia-Oberfläche nicht mehr verwendet. Sie bleiben
vorerst bestehen, damit vorhandene Buchdaten und alte Installationen nicht
beschädigt werden.

In `readmore/static/config.json`:

```json
"catalogue": {
  "mode": "primary_fallback",
  "primaryProvider": "open_library",
  "fallbackProvider": "google_books"
}
```

Erlaubte Werte: `open_library` und `google_books`. Sind beide Werte gleich,
wird kein Fallback aufgerufen. Diese Werte sind die Standardauswahl; Haupt- und
Fallback-Katalog lassen sich pro Gerät zusätzlich unter **Settings** wählen.
Nach einer Änderung an `config.json` Container neu bauen.

Für einen zuverlässigen Google-Books-Zugriff den API-Key ausschließlich in
`.env` speichern (nicht in `config.json`):

```bash
GOOGLE_BOOKS_API_KEY=dein-key
```

## Änderungen veröffentlichen

```bash
docker compose run --rm app pytest -q
git status
git add .
git commit -m "Beschreibung der Änderung"
git push
```

Ist der automatische VPS-Deploy aktiv, sind danach keine weiteren Schritte
nötig. Der VPS prüft die Branches `main` und `movies` alle fünf Minuten und baut
nur die App mit einem neuen Commit.

## Android lokal testen

Einmalig oder nach Änderungen an den Node-Abhängigkeiten:

```bash
cd ~/readmore/mobile
npm install
```

Docker lokal laufen lassen, Handy per USB verbinden und starten:

```bash
cd ~/readmore/mobile
npm run run
```

Webänderungen an Flask, HTML, CSS und JavaScript benötigen keinen neuen
APK-Build. Für native Änderungen oder eine andere Serveradresse:

```bash
cd ~/readmore/mobile
BOOKYPEDIA_APP_URL=https://movies.epiloguehouse.de npm run sync
cd android
ANDROID_HOME=/home/led/Android/Sdk ./gradlew assembleDebug

/home/led/Android/Sdk/platform-tools/adb install -r \
  app/build/outputs/apk/debug/app-debug.apk
```

Weitere Android-Befehle: [mobile/README.md](mobile/README.md)

## VPS erstmalig einrichten

Auf dem VPS laufen zwei getrennte Checkouts desselben Git-Remotes:

- `/opt/bookypedia` auf Branch `main`, intern auf `127.0.0.1:8000`
- `/opt/moviepedia` auf Branch `movies`, intern auf `127.0.0.1:8001`

Der bestehende Bookypedia-Checkout bleibt bestehen. Moviepedia wird zusätzlich
geklont:

```bash
repo_url="$(sudo git -C /opt/bookypedia remote get-url origin)"
sudo git clone --branch movies --single-branch \
  "${repo_url}" /opt/moviepedia
cd /opt/moviepedia
sudo cp .env.example .env
openssl rand -hex 32
```

Den erzeugten Wert als `SECRET_KEY` in `/opt/moviepedia/.env` eintragen. Für
Moviepedia müssen außerdem diese Werte gesetzt sein:

```dotenv
APP_PORT=8001
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
TMDB_READ_ACCESS_TOKEN=dein-tmdb-read-access-token
```

In `/opt/bookypedia/.env` müssen `SESSION_COOKIE_SECURE=1` und `TRUST_PROXY=1`
gesetzt sein; Bookypedia bleibt auf Port 8000. Danach beide Apps zunächst lokal
starten:

```bash
cd /opt/bookypedia
sudo docker compose -p bookypedia -f compose.prod.yaml up --build -d

cd /opt/moviepedia
sudo APP_PORT=8001 docker compose -p moviepedia -f compose.prod.yaml up --build -d

curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8001/health
```

### Gemeinsamer Reverse Proxy

Nur ein zentraler Caddy-Prozess darf Ports 80 und 443 belegen. Der VPS-Caddy
verwendet `deploy/Caddyfile.vps` und leitet wie folgt weiter:

- `https://epiloguehouse.de` → Bookypedia auf Port 8000
- `https://movies.epiloguehouse.de` → Moviepedia auf Port 8001

Für `movies.epiloguehouse.de` zuerst beim DNS-Anbieter einen A- und, falls
verwendet, AAAA-Eintrag auf denselben VPS wie `epiloguehouse.de` setzen. Danach
Caddy auf dem Host installieren und konfigurieren:

```bash
sudo apt update
sudo apt install -y caddy
sudo install -m 0644 /opt/moviepedia/deploy/Caddyfile.vps /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
```

Beim Wechsel vom bisherigen Caddy-Container einmalig dessen Ports freigeben und
den Host-Caddy starten:

```bash
cd /opt/bookypedia
sudo docker compose -p bookypedia \
  -f compose.prod.yaml -f compose.public.yaml stop caddy
sudo docker compose -p bookypedia \
  -f compose.prod.yaml -f compose.public.yaml rm -f caddy
sudo systemctl restart caddy
```

## VPS manuell aktualisieren

```bash
cd /opt/bookypedia
sudo git pull --ff-only origin main
sudo docker compose -p bookypedia -f compose.prod.yaml up --build -d

cd /opt/moviepedia
sudo git pull --ff-only origin movies
sudo APP_PORT=8001 docker compose -p moviepedia -f compose.prod.yaml up --build -d
```

## Automatisches VPS-Deployment

Das Skript prüft beide Checkouts unabhängig voneinander. Ein Fehler in einer App
verhindert nicht, dass die andere geprüft und gegebenenfalls aktualisiert wird.
Der Timer startet es alle fünf Minuten. Einmalig auf dem VPS installieren:

```bash
cd /opt/moviepedia

sudo install -m 0755 deploy/epiloguehouse-auto-deploy \
  /usr/local/sbin/epiloguehouse-auto-deploy
sudo install -m 0644 deploy/epiloguehouse-deploy.service \
  /etc/systemd/system/epiloguehouse-deploy.service
sudo install -m 0644 deploy/epiloguehouse-deploy.timer \
  /etc/systemd/system/epiloguehouse-deploy.timer

sudo systemctl daemon-reload
sudo systemctl enable --now epiloguehouse-deploy.timer
```

Kontrollieren und testen:

```bash
systemctl status epiloguehouse-deploy.timer
systemctl list-timers epiloguehouse-deploy.timer --no-pager

sudo systemctl start epiloguehouse-deploy.service
sudo systemctl show epiloguehouse-deploy.service -p Result -p ExecMainStatus
sudo journalctl -u epiloguehouse-deploy.service -n 100 --no-pager
```

Wenn das Deploy-Skript selbst geändert wurde, die installierte Kopie erneut
aktualisieren:

```bash
cd /opt/moviepedia
sudo install -m 0755 deploy/epiloguehouse-auto-deploy \
  /usr/local/sbin/epiloguehouse-auto-deploy
```

## Konten verwalten

Lokal:

```bash
docker compose exec app flask --app run.py user list
docker compose exec app flask --app run.py user create freund
docker compose exec app flask --app run.py user reset-password freund
docker compose exec app flask --app run.py user deactivate freund
docker compose exec app flask --app run.py user activate freund
```

Auf dem VPS für Bookypedia, ausgeführt unter `/opt/bookypedia`:

```bash
docker compose -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user list
docker compose -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user create freund
docker compose -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user reset-password freund
docker compose -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user deactivate freund
docker compose -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user activate freund
```

Für Moviepedia dieselben Befehle unter `/opt/moviepedia` mit `-p moviepedia`.

## Produktionslogs

```bash
sudo docker compose --env-file /opt/bookypedia/.env -p bookypedia \
  -f /opt/bookypedia/compose.prod.yaml logs -f app
sudo docker compose --env-file /opt/moviepedia/.env -p moviepedia \
  -f /opt/moviepedia/compose.prod.yaml logs -f app
sudo journalctl -fu caddy
sudo journalctl -fu epiloguehouse-deploy.service
```

Zusätzliche erfolgreiche GET-Abfragen lokal anzeigen:

```bash
LOG_LEVEL=DEBUG docker compose up
```

## Datenbank sichern

```bash
mkdir -p backups
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
  python -c "import sqlite3; s=sqlite3.connect('/data/readmore.db'); t=sqlite3.connect('/backup/readmore-backup.db'); s.backup(t); t.close(); s.close()"
docker compose start app
```

Wiederherstellen:

```bash
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app \
  python -c "import sqlite3; s=sqlite3.connect('/backup/readmore-backup.db'); t=sqlite3.connect('/data/readmore.db'); s.backup(t); t.close(); s.close()"
docker compose start app
```

## Weitere Dokumentation

- [Architektur](ARCHITECTURE.md)
- [Android](mobile/README.md)
