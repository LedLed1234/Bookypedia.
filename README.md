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
wird kein Fallback aufgerufen. Nach einer Änderung Container neu bauen.

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
nötig. Der VPS prüft `main` alle zwei Minuten und baut nur bei einem neuen
Commit.

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

Produktionsverzeichnis: `/opt/bookypedia`

```bash
cd /opt/bookypedia
cp .env.example .env
openssl rand -hex 32
```

Den erzeugten Wert als `SECRET_KEY` in `.env` eintragen und außerdem
`BOOKYPEDIA_DOMAIN=epiloguehouse.de` setzen. Danach:

```bash
docker compose -f compose.prod.yaml -f compose.public.yaml up --build -d
docker compose -f compose.prod.yaml -f compose.public.yaml ps
curl -fsS http://127.0.0.1:8000/health
```

## VPS manuell aktualisieren

```bash
ssh bookypedia-vps
cd /opt/bookypedia
git pull --ff-only
docker compose -f compose.prod.yaml -f compose.public.yaml up --build -d
docker compose -f compose.prod.yaml -f compose.public.yaml ps
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
```

Wenn das Deploy-Skript selbst geändert wurde, die installierte Kopie erneut
aktualisieren:

```bash
cd /opt/bookypedia
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

Auf dem VPS, ausgeführt unter `/opt/bookypedia`:

```bash
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user list
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user create freund
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user reset-password freund
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user deactivate freund
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user activate freund
```

## Produktionslogs

```bash
cd /opt/bookypedia
docker compose -f compose.prod.yaml -f compose.public.yaml logs -f app caddy
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
