# Epiloguehouse

Persönliche Leseverwaltung mit Flask, SQLite, Open Library und einer optionalen
Android-App. Architekturdetails stehen in [ARCHITECTURE.md](ARCHITECTURE.md).

## Lokal starten

```bash
sudo systemctl start docker
cd ~/readmore
docker compose up --build -d
```

Danach: **http://localhost:5000**

Beim ersten Start ein Konto anlegen:

```bash
docker compose exec app flask --app run.py user create led
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

## Buchkataloge konfigurieren

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
nötig. Der VPS prüft `main` und `movies` alle fünf Minuten und baut nur die App
mit einem neuen Commit.

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
BOOKYPEDIA_APP_URL=https://epiloguehouse.de npm run sync
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

Der bestehende Bookypedia-Checkout bleibt erhalten. Moviepedia wird aus
demselben Remote direkt nach `/opt/moviepedia` geklont:

```bash
repo_url="$(sudo git -C /opt/bookypedia remote get-url origin)"
sudo git clone --branch movies --single-branch \
  "${repo_url}" /opt/moviepedia
```

Bookypedia verwendet in `/opt/bookypedia/.env` mindestens:

```dotenv
SECRET_KEY=eigener-zufaelliger-wert
APP_PORT=8000
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
```

Moviepedia verwendet in `/opt/moviepedia/.env` einen eigenen `SECRET_KEY`,
Port `8001` und den TMDB-Token:

```dotenv
SECRET_KEY=anderer-eigener-zufaelliger-wert
APP_PORT=8001
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
TMDB_READ_ACCESS_TOKEN=dein-tmdb-read-access-token
```

Zufällige Schlüssel lassen sich jeweils mit `openssl rand -hex 32` erzeugen.
Die echten `.env`-Dateien und Tokens niemals committen. Beide Apps werden als
getrennte Compose-Projekte gestartet, sodass auch ihre SQLite-Volumes getrennt
bleiben:

```bash
sudo docker compose --env-file /opt/bookypedia/.env -p bookypedia \
  -f /opt/bookypedia/compose.prod.yaml up --build -d
sudo docker compose --env-file /opt/moviepedia/.env -p moviepedia \
  -f /opt/moviepedia/compose.prod.yaml up --build -d

curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8001/health
```

Nur der zentrale Caddy-Dienst des VPS belegt Ports 80 und 443. Seine
Konfiguration liegt in `deploy/Caddyfile.vps`. `compose.public.yaml` wird beim
gemeinsamen Betrieb beider Apps nicht verwendet.

- `https://epiloguehouse.de` stellt Bookypedia bereit.
- `https://books.epiloguehouse.de` leitet dauerhaft auf Bookypedia weiter.
- `https://movies.epiloguehouse.de` stellt Moviepedia bereit.

### Gemeinsamer Reverse Proxy

Vor der Umstellung müssen `epiloguehouse.de`, `books.epiloguehouse.de` und
`movies.epiloguehouse.de` per DNS auf den VPS zeigen. Die Auflösung lässt sich
so prüfen:

```bash
dig +short epiloguehouse.de A
dig +short books.epiloguehouse.de A
dig +short movies.epiloguehouse.de A
```

Bei einer bestehenden Installation zunächst Caddy herunterladen, ohne den noch
laufenden Docker-Caddy zu verändern:

```bash
sudo apt update
sudo apt install --download-only caddy
```

Für die eigentliche Umstellung den Deploy-Timer vorübergehend stoppen, den alten
Docker-Caddy anhalten und den Host-Caddy aktivieren:

```bash
sudo systemctl stop epiloguehouse-deploy.timer
sudo docker stop bookypedia-caddy-1

sudo apt install -y caddy
sudo install -m 0644 /opt/bookypedia/deploy/Caddyfile.vps \
  /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy

curl -fsS https://epiloguehouse.de/health
curl -fsSI https://books.epiloguehouse.de
curl -fsS https://movies.epiloguehouse.de/health
```

Erst wenn beide HTTPS-Tests erfolgreich sind, den alten Container entfernen:

```bash
sudo docker rm bookypedia-caddy-1
sudo systemctl enable --now caddy
```

Falls der Host-Caddy nicht startet, kann auf den vorherigen Zustand
zurückgewechselt werden:

```bash
sudo systemctl stop caddy
sudo docker start bookypedia-caddy-1
```

## VPS manuell aktualisieren

```bash
ssh bookypedia-vps
sudo git -C /opt/bookypedia pull --ff-only origin main
sudo docker compose --env-file /opt/bookypedia/.env -p bookypedia \
  -f /opt/bookypedia/compose.prod.yaml up --build -d

sudo git -C /opt/moviepedia pull --ff-only origin movies
sudo docker compose --env-file /opt/moviepedia/.env -p moviepedia \
  -f /opt/moviepedia/compose.prod.yaml up --build -d
```

## Automatisches VPS-Deployment

Einmalig auf dem VPS installieren:

```bash
cd /opt/bookypedia

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

### Zuletzt deployed
journalctl -u epiloguehouse-deploy.service \
  --no-pager | grep epiloguehouse-deploy | tail -20

### Wann der Timer zuletzt geprüft hat – auch wenn es keinen neuen Commit gab:
systemctl show epiloguehouse-deploy.service \
  -p ExecMainStartTimestamp \
  -p ExecMainExitTimestamp \
  -p Result \
  -p ExecMainStatus

### Die zuletzt erfolgreich übernommenen Commits:
cat /var/lib/epiloguehouse-deploy/bookypedia-deployed-commit
cat /var/lib/epiloguehouse-deploy/moviepedia-deployed-commit
```

Änderungen an den Deployment-Dateien werden nicht automatisch in
`/usr/local/sbin` beziehungsweise `/etc` installiert. Nach solchen Änderungen
die installierten Kopien aktualisieren:

```bash
cd /opt/bookypedia

sudo install -m 0755 deploy/epiloguehouse-auto-deploy \
  /usr/local/sbin/epiloguehouse-auto-deploy
sudo install -m 0644 deploy/epiloguehouse-deploy.service \
  /etc/systemd/system/epiloguehouse-deploy.service
sudo install -m 0644 deploy/epiloguehouse-deploy.timer \
  /etc/systemd/system/epiloguehouse-deploy.timer
sudo install -m 0644 deploy/Caddyfile.vps /etc/caddy/Caddyfile

sudo systemctl daemon-reload
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl restart epiloguehouse-deploy.timer
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

Auf dem VPS, ausgeführt unter `/opt/bookypedia`:

```bash
docker compose --env-file .env -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user list
docker compose --env-file .env -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user create freund
docker compose --env-file .env -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user reset-password freund
docker compose --env-file .env -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user deactivate freund
docker compose --env-file .env -p bookypedia -f compose.prod.yaml exec app \
  flask --app run.py user activate freund
```

Moviepedia besitzt eine eigene Datenbank und deshalb eigene Benutzerkonten. Auf
dem VPS, ausgeführt unter `/opt/moviepedia`:

```bash
docker compose --env-file .env -p moviepedia -f compose.prod.yaml exec app \
  flask --app run.py user list
docker compose --env-file .env -p moviepedia -f compose.prod.yaml exec app \
  flask --app run.py user create freund
docker compose --env-file .env -p moviepedia -f compose.prod.yaml exec app \
  flask --app run.py user reset-password freund
docker compose --env-file .env -p moviepedia -f compose.prod.yaml exec app \
  flask --app run.py user deactivate freund
docker compose --env-file .env -p moviepedia -f compose.prod.yaml exec app \
  flask --app run.py user activate freund
```

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

Bookypedia und Moviepedia verwenden getrennte Compose-Projekte und damit
getrennte Datenbanken. Lokal wird die Datenbank so gesichert:

```bash
mkdir -p backups
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
  python -c "import sqlite3; s=sqlite3.connect('/data/readmore.db'); t=sqlite3.connect('/backup/readmore-backup.db'); s.backup(t); t.close(); s.close()"
docker compose start app
```

Auf dem VPS Bookypedia unter `/opt/bookypedia` sichern:

```bash
sudo mkdir -p backups
sudo docker compose --env-file .env -p bookypedia -f compose.prod.yaml stop app
sudo docker compose --env-file .env -p bookypedia -f compose.prod.yaml \
  run --rm --no-deps -v "$PWD/backups:/backup" app \
  python -c "import sqlite3; s=sqlite3.connect('/data/readmore.db'); t=sqlite3.connect('/backup/bookypedia-backup.db'); s.backup(t); t.close(); s.close()"
sudo docker compose --env-file .env -p bookypedia -f compose.prod.yaml start app
```

Moviepedia unter `/opt/moviepedia` entsprechend separat sichern:

```bash
sudo mkdir -p backups
sudo docker compose --env-file .env -p moviepedia -f compose.prod.yaml stop app
sudo docker compose --env-file .env -p moviepedia -f compose.prod.yaml \
  run --rm --no-deps -v "$PWD/backups:/backup" app \
  python -c "import sqlite3; s=sqlite3.connect('/data/readmore.db'); t=sqlite3.connect('/backup/moviepedia-backup.db'); s.backup(t); t.close(); s.close()"
sudo docker compose --env-file .env -p moviepedia -f compose.prod.yaml start app
```

Lokal wiederherstellen:

```bash
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app \
  python -c "import sqlite3; s=sqlite3.connect('/backup/readmore-backup.db'); t=sqlite3.connect('/data/readmore.db'); s.backup(t); t.close(); s.close()"
docker compose start app
```

## Weitere Dokumentation

- [Architektur](ARCHITECTURE.md)
- [Android](mobile/README.md)
