# Bookypedia.

![](/home/led/.config/marktext/images/2026-10-23-16-36-33-image.png)

Eine deutschsprachige Leseverwaltung mit Flask, SQLite und der Open-Library-Suche. Die App läuft lokal per Docker; jedes manuell freigeschaltete Konto besitzt eine eigene Bibliothek im persistenten Docker-Volume.

Bücher und bereits ermittelte Reihen werden gemeinsam in SQLite gespeichert. Neue Bücher sind sofort verfügbar; die zugehörige Reihe lädt ein Hintergrund-Worker unabhängig von der Bedienoberfläche nach. Vorhandene Bücher ohne Reiheninformationen werden beim nächsten App-Start automatisch ergänzt. Vorübergehende Fehler bei Open Library werden mit wachsendem Zeitabstand erneut versucht.

## Entwicklung und Deployment – Kurzablauf

Die Umgebung wird durch den jeweiligen Befehl ausgewählt. Es gibt keine
automatische Umschaltung zwischen lokalem Entwicklungsserver und VPS.

### Web-App lokal entwickeln

Wenn der Docker-Autostart deaktiviert ist, zuerst Docker und anschließend den
Entwicklungscontainer starten:

```bash
sudo systemctl start docker
cd ~/readmore
docker compose up --build -d
```

Danach **http://localhost:5000** öffnen. Der Quellcode ist eingebunden und der
Flask-Entwicklungsserver lädt Python-Änderungen automatisch neu. Für Änderungen
an HTML, CSS oder JavaScript genügt normalerweise ein Neuladen der Seite.

### Android lokal entwickeln

Den lokalen Docker-Server laufen lassen, das Handy mit aktiviertem
USB-Debugging anschließen und dann ausführen:

```bash
cd mobile
npm run run
```

Das Skript synchronisiert die lokale Adresse `http://localhost:8000`, richtet
`adb reverse` zum Flask-Port 5000 ein, installiert die Entwicklungs-App und
startet sie. `npm install` ist nur beim ersten Einrichten sowie nach Änderungen
an `package.json` oder `package-lock.json` erforderlich.

Browser und Android laden dieselbe Weboberfläche. Deshalb benötigen Änderungen
am Backend, an HTML, CSS oder JavaScript – einschließlich der über den
Android-User-Agent aktivierten mobilen Darstellung – keinen neuen APK-Build.
Die App muss zum Aktualisieren gegebenenfalls geschlossen und neu geöffnet
werden. Ein neuer Android-Build ist nur bei Änderungen am nativen Wrapper,
Capacitor, App-Icon, App-Namen, Berechtigungen oder Android-Konfigurationen
erforderlich.

Für die kompakte Touch-Oberfläche der installierten Android-App und mobiler
Webbrowser stehen in CSS die Selektoren unter `.platform-mobile` und in
JavaScript die Konstante `IS_MOBILE_UI` zur Verfügung. Eine normale Media Query
nach Bildschirmbreite betrifft dagegen auch schmale Desktop-Browser.

| Art der Änderung                                     | VPS neu deployen | APK neu bauen |
| ---------------------------------------------------- | ---------------- | ------------- |
| Backend, Templates, API oder Datenbanklogik          | ja               | nein          |
| Allgemeines CSS oder JavaScript                      | ja               | nein          |
| `.platform-mobile`-CSS oder `IS_MOBILE_UI`-Logik     | ja               | nein          |
| App-Icon, Splashscreen, App-Name oder Berechtigungen | nein             | ja            |
| Capacitor-Plugin, native Android-Datei oder App-ID   | nein             | ja            |
| Produktionsdomain in der Android-App                 | nein             | ja            |

Bei Änderungen an statischen Dateien müssen außerdem die verwendeten
Asset-/Service-Worker-Versionen erhöht werden, damit Browser und Android keine
veralteten Dateien aus dem Cache verwenden.

### Änderungen testen und versionieren

Im Projektverzeichnis:

```bash
docker compose run --rm app pytest -q
git status
git add .
git commit -m "Beschreibung der Änderung"
git push
```

### Web-App auf dem VPS veröffentlichen

Nach dem Push:

```bash
ssh bookypedia-vps
cd /opt/bookypedia
git pull --ff-only
docker compose -f compose.prod.yaml -f compose.public.yaml up --build -d
docker compose -f compose.prod.yaml -f compose.public.yaml ps
```

Die Web-App ist anschließend unter **https://epiloguehouse.de** erreichbar.
Browser und installierte Produktions-App laden die aktualisierte Oberfläche
direkt vom VPS. Datenbank, Konten, `.env` und Caddy-Zertifikate bleiben beim
Neubau der Container erhalten. Niemals `docker compose down -v` verwenden,
wenn die Produktionsdaten erhalten bleiben sollen.

### Benutzerkonten anlegen Lokal

Die lokale Entwicklungsdatenbank und die Produktionsdatenbank auf dem VPS sind
getrennt. Deshalb hängt der richtige Befehl von der gewünschten Umgebung ab.

Lokal ein Testkonto anlegen:

```bash
docker compose exec app flask --app run.py user create led
```

Ein **echtes** Konto auf dem öffentlichen VPS anlegen:

```bash
ssh bookypedia-vps
cd /opt/bookypedia
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user create freund
```

Für Freunde wird immer der zweite Befehl auf dem VPS verwendet. Das Konto
erhält eine eigene Bibliothek und muss das vorläufige Passwort beim ersten
Login ändern.

### Android-Produktions-App neu bauen

Dieser Schritt ist nur bei nativen Android-Änderungen oder einer Änderung der
Serveradresse notwendig:

```bash
cd mobile
BOOKYPEDIA_APP_URL=https://epiloguehouse.de npm run sync
cd android
ANDROID_HOME=/home/led/Android/Sdk ./gradlew assembleDebug
```

Die APK liegt danach unter
`mobile/android/app/build/outputs/apk/debug/app-debug.apk`. Auf einem per USB
verbundenen Gerät wird sie aktualisiert mit:

```bash
/home/led/Android/Sdk/platform-tools/adb install -r \
  app/build/outputs/apk/debug/app-debug.apk
```

Der lokale Entwicklungsbuild und der Produktionsbuild besitzen derzeit
dieselbe App-ID und ersetzen sich daher gegenseitig auf dem Handy. Für die
Weitergabe an andere Personen ist später ein signierter Release-Build mit
dauerhaft gesichertem, nicht versioniertem Keystore vorgesehen.

## Starten

Voraussetzung: Docker Desktop bzw. Docker Engine mit Docker Compose.

```bash
docker compose up --build
```

Danach im Browser **http://localhost:5000** öffnen. Der Quellcode ist als Bind-Mount eingebunden; Änderungen laden den Flask-Entwicklungsserver automatisch neu.

Vor der ersten Anmeldung einmalig ein Konto anlegen:

```bash
docker compose exec app flask --app run.py user create led
```

Das vorläufige Passwort wird verdeckt abgefragt und muss beim ersten Login
geändert werden. Beim Upgrade von einer früheren Einbenutzer-Version werden
alle bereits vorhandenen Bücher automatisch dem zuerst angelegten Konto
zugeordnet.

## Android-App lokal testen

Die Capacitor-Version liegt getrennt unter `mobile/`. Sie verwendet in der
aktuellen Entwicklungsphase dieselbe Flask-Oberfläche und Datenbank wie der
Browser. Mit einem per USB verbundenen Android-Handy oder einem Emulator:

```bash
docker compose up --build -d
cd mobile
npm run run
```

Auf einem physischen Handy muss zuvor in den Entwickleroptionen USB-Debugging
aktiviert und die Verbindung zu diesem PC bestätigt werden. Das Startskript
richtet über ADB eine lokale Portweiterleitung ein, synchronisiert Capacitor und
installiert die App. Vor dem ersten Start beziehungsweise nach Änderungen an
den Node-Abhängigkeiten einmal `npm install` im Verzeichnis `mobile` ausführen.
Weitere Hinweise stehen in `mobile/README.md`.

Die Android-Konfiguration erlaubt unverschlüsseltes HTTP ausschließlich zu
`localhost:8000`. Für den VPS wird beim Build die HTTPS-Domain gesetzt; Login
und Bibliothekstrennung funktionieren anschließend identisch zum Browser.

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

## Konten auf dem VPS verwalten

Es gibt bewusst keine öffentliche Registrierung. Konten werden ausschließlich
auf dem Produktionsserver verwaltet. Alle folgenden Befehle werden unter
`/opt/bookypedia` auf dem VPS ausgeführt:

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

Passwörter werden nicht als Kommandozeilenargument übergeben und mit scrypt
gehasht gespeichert. Ein Reset oder das Deaktivieren eines Kontos macht
vorhandene Sitzungen ungültig. Reihen- und Katalogmetadaten werden gemeinsam
gecached; Lesestatus, Bewertungen und Notizen sind pro Konto getrennt.

## Produktion über den bisherigen SSH-Zugang

Zuerst eine lokale `.env` auf dem VPS anlegen:

```bash
cp .env.example .env
openssl rand -hex 32
```

Den ausgegebenen Wert in `.env` als `SECRET_KEY` eintragen. Die Datei wird durch
`.gitignore` nicht versioniert. Danach startet die getrennte Compose-Datei die
App ohne Debug-Modus mit Gunicorn und bindet sie lokal an Port 8000:

```bash
docker compose -f compose.prod.yaml up --build -d
```

Die Anwendung besitzt jetzt einen Zugangsschutz; Gunicorn bleibt trotzdem
bewusst nur an `127.0.0.1` gebunden. Ohne die öffentliche Caddy-Konfiguration
ist Bookypedia weiterhin ausschließlich über den bisherigen SSH-Tunnel erreichbar.

## Öffentlich mit Domain und HTTPS betreiben

Voraussetzungen:

- eine Domain oder Subdomain mit A/AAAA-Eintrag auf den VPS,
- von außen erreichbare TCP-Ports 80 und 443 sowie UDP-Port 443,
- `BOOKYPEDIA_DOMAIN` und ein zufälliger `SECRET_KEY` in `.env`.

Dann Gunicorn und den Caddy-Reverse-Proxy gemeinsam starten:

```bash
docker compose -f compose.prod.yaml -f compose.public.yaml up --build -d
```

Caddy beantragt und erneuert das TLS-Zertifikat automatisch. Buchsuche und
sämtliche privaten Bibliotheks-APIs erfordern ein aktives Konto; öffentlich
bleiben nur Anmeldung, statische App-Dateien und der technische Healthcheck.
Danach das erste Konto anlegen:

```bash
docker compose -f compose.prod.yaml -f compose.public.yaml exec app \
  flask --app run.py user create led
```

Weitere Personen erhalten auf dieselbe Weise eigene Konten. Eine öffentliche
Registrierung und E-Mail-Funktionen sind nicht vorhanden.

## Bookypedia auf dem VPS aktualisieren

Der Produktionscode liegt auf dem VPS unter `/opt/bookypedia`. Nach einem Push auf den `main`-Branch wird die laufende Installation als administrativer Benutzer aktualisiert mit:

```bash
cd /opt/bookypedia
git pull --ff-only
docker compose -f compose.prod.yaml -f compose.public.yaml up --build -d
```

Anschließend Status und aktuelle Logs kontrollieren:

```bash
docker compose -f compose.prod.yaml -f compose.public.yaml ps
docker compose -f compose.prod.yaml -f compose.public.yaml logs --tail=100 app caddy
```

`git pull` aktualisiert nur den Anwendungscode. Die SQLite-Datenbank liegt dauerhaft im benannten Docker-Volume `readmore_prod_data` und bleibt bei Neubauten und Container-Neustarts erhalten. Weder `docker compose down -v` noch `docker volume rm` verwenden, wenn die gespeicherte Sammlung erhalten bleiben soll.

### Automatisch nach einem Push deployen

Der VPS kann `origin/main` regelmäßig prüfen und nur bei einem neuen Commit
deployen. Die mitgelieferte Variante prüft alle zwei Minuten. Ohne Änderung
werden weder Docker-Images gebaut noch Container neu gestartet.

Einmalig auf dem VPS unter `/opt/bookypedia` installieren:

```bash
sudo install -m 0755 deploy/epiloguehouse-auto-deploy \
  /usr/local/sbin/epiloguehouse-auto-deploy
sudo install -m 0644 deploy/epiloguehouse-deploy.service \
  /etc/systemd/system/epiloguehouse-deploy.service
sudo install -m 0644 deploy/epiloguehouse-deploy.timer \
  /etc/systemd/system/epiloguehouse-deploy.timer
sudo systemctl daemon-reload
sudo systemctl enable --now epiloguehouse-deploy.timer
```

Timer und letzte Deployment-Logs kontrollieren:

```bash
systemctl list-timers epiloguehouse-deploy.timer
sudo journalctl -u epiloguehouse-deploy.service -n 100 --no-pager
```

Ein Deployment sofort manuell anstoßen:

```bash
sudo systemctl start epiloguehouse-deploy.service
```

Das Skript bricht bei lokalen Änderungen oder einem abweichenden Git-Verlauf
ab, verhindert parallele Deployments und markiert eine Version erst nach einem
erfolgreichen Healthcheck als ausgerollt. Ein fehlgeschlagener Build wird beim
nächsten Timer-Lauf erneut versucht.

## Optionaler Desktop-Starter über SSH

Solange noch keine öffentliche HTTPS-Domain eingerichtet ist, kann Bookypedia
unter Linux weiterhin über einen SSH-Tunnel geöffnet werden. Nach Aktivierung
der HTTPS-Domain wird dieser Starter nicht mehr benötigt. Voraussetzung ist der
SSH-Konfigurationseintrag `bookypedia-vps`. Den Starter installieren mit:

```bash
./scripts/install-desktop-launcher
```

Danach im Anwendungsmenü nach **Bookypedia** suchen. Der Starter baut bei Bedarf einen SSH-Tunnel auf und öffnet `http://bookypedia.localhost:8000` in Firefox. Das geöffnete Terminal hält die Verbindung aufrecht. Mit `Strg+C` oder durch Schließen des Terminalfensters wird der Tunnel wieder beendet.

Der lokale SSH-Agent übernimmt die Passphrase des Schlüssels. Falls der Schlüssel noch nicht entsperrt ist, fragt der Starter beim ersten Verbindungsaufbau danach.

## Suchanbieter austauschen

Open Library ist hinter der kleinen Provider-Schnittstelle in `readmore/providers/` gekapselt. Ein anderer Katalog kann dort dieselben normalisierten Felder (`title`, `authors`, `isbn`, `cover_url`, `provider_book_id`) liefern und anschließend über `BOOK_PROVIDER` ausgewählt werden. Die bereits gespeicherten Bücher bleiben unabhängig vom Suchanbieter erhalten.

Die Open-Library-Suche unterscheidet zwischen dem sprachunabhängigen Werk und der passendsten konkreten Ausgabe. Angezeigt und gespeichert werden bevorzugt Titel, ISBN, Sprache und Cover der passenden Ausgabe; die Work-ID bleibt für Duplikaterkennung und Reihen erhalten. Originaltitel und Originalautor können zusätzlich in der Buchdetailansicht erscheinen. Vergleiche und manuelle Duplikaterkennung unterstützen Unicode-Schriften wie Japanisch, Kyrillisch und Arabisch.
