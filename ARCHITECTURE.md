# Moviepedia – Architektur

## Überblick

```mermaid
flowchart LR
    Browser[Browser oder Android-Wrapper] --> Caddy[Caddy / HTTPS]
    Caddy --> Flask[Gunicorn + Flask]
    Flask --> SQLite[(SQLite)]
    Flask --> TMDB[TMDB]
    Flask --> Worker[Hintergrund-Worker]
    Worker --> OpenLibrary[Open Library]
    Flask --> OpenLibrary
```

Die Browser- und Android-Version verwenden dieselbe Flask-Weboberfläche und
dasselbe Backend. Capacitor stellt lediglich den nativen Android-Wrapper bereit.

## Komponenten

| Bereich       | Technik        | Aufgabe                                                  |
| ------------- | -------------- | -------------------------------------------------------- |
| Backend       | Flask          | Seiten, Authentifizierung und JSON-API                   |
| Produktion    | Gunicorn       | WSGI-Server für Flask                                    |
| Reverse Proxy | Caddy          | Domain, HTTPS und Zertifikate                            |
| Datenbank     | SQLite         | Konten, Bibliotheken, Metadaten und Caches               |
| Medienkatalog | TMDB           | Film- und Seriensuche, Poster und lokalisierte Metadaten |
| Katalog       | Open Library   | Suche, Ausgaben, Cover und Reihen                        |
| Android       | Capacitor      | Native Hülle um die Web-App                              |
| Betrieb       | Docker Compose | Entwicklung und Produktion                               |

## Umgebungen

### Entwicklung

`compose.yaml` startet den Flask-Entwicklungsserver auf `127.0.0.1:5000`. Das
Repository wird nach `/app` eingebunden, damit Codeänderungen ohne Image-Neubau
verfügbar sind. Die Entwicklungsdaten liegen im Volume `readmore_data`.

### Produktion

`compose.prod.yaml` startet Gunicorn hinter einem konfigurierbaren lokalen
Host-Port. Auf dem VPS verwendet Bookypedia `127.0.0.1:8000` und Moviepedia
`127.0.0.1:8001`. Ein zentraler Caddy auf dem Host übernimmt Port 80/443 und
leitet beide Domains weiter. Produktionsdaten liegen pro Compose-Projekt in
einem eigenen Volume `readmore_prod_data`.

## Authentifizierung und Benutzertrennung

- Es gibt keine öffentliche Registrierung.
- Konten werden über `flask user ...` verwaltet.
- Benutzernamen sind unabhängig von Groß-/Kleinschreibung eindeutig.
- Passwörter werden mit Werkzeug/scrypt gehasht.
- Beim ersten Login kann ein Passwortwechsel erzwungen werden.
- `auth_version` macht bestehende Sitzungen nach Passwort-Reset oder
  Deaktivierung ungültig.
- Formulare verwenden CSRF-Tokens.
- Jede Bibliotheksabfrage wird über die angemeldete `user_id` gefiltert.
- Katalog- und Reihendaten dürfen gemeinsam gecacht werden; Lesestatus,
  Bewertungen und Notizen bleiben benutzerspezifisch.

## Datenmodell

Wichtige Tabellen:

| Tabelle                  | Inhalt                                                                       |
| ------------------------ | ---------------------------------------------------------------------------- |
| `users`                  | Konten, Passwort-Hash, Aktivstatus und Sitzungs-Version                      |
| `media_items`            | Filme und Serien pro Konto, TMDB-ID, Status, Bewertung, Review und Metadaten |
| `episode_ratings`        | Persönliche Episodenbewertungen pro Konto, Serie, Staffel und Episode        |
| `saved_seasons`          | Separat gespeicherte Staffeln mit Status und TMDB-Metadaten pro Konto        |
| `books`                  | Bücher einer Person, Status, Bewertung und Metadaten                         |
| `series`                 | gemeinsam gecachte Reihen                                                    |
| `series_members`         | Bücher und Positionen innerhalb einer Reihe                                  |
| `book_series`            | Zuordnung gespeicherter Bücher zu Reihen                                     |
| `series_lookups`         | Status und Wiederholungen der Reihenabfragen                                 |
| `metadata_lookups`       | Status und Wiederholungen der Metadatenabfragen                              |
| `book_metadata_cache`    | gecachte Ausgabedetails der Buchanbieter                                     |
| `catalogue_search_cache` | persistente, anbieterbezogene Suchergebnisse                                 |
| `tmdb_cache`             | persistente TMDB-Suchen, Filmreihen, Staffellisten und Episodendetails       |
| `cover_cache`            | externe Cover-Quellen und lokale Dateipfade                                  |

SQLite-Migrationen werden beim Anwendungsstart in `readmore/db.py` ausgeführt.
Historische Zeitpunkte werden dabei nicht erfunden.

## Buchstatus

Die Statushierarchie lautet:

```text
Wunschliste → Ungelesen/Im Besitz → Lese ich → Gelesen
```

Zeitpunkte werden nur bei einem tatsächlichen Statuswechsel aktualisiert.
Beim Zurückstufen werden zeitlich spätere Meilensteine entfernt, ältere bekannte
Zeitpunkte bleiben erhalten.

## Suche, Werke und Ausgaben

Die neue Film- und Seriensuche liegt unter `/api/media/search`. Das Backend
authentifiziert sich mit `TMDB_READ_ACCESS_TOKEN`, fragt TMDB mit `de-DE` und
Region `DE` ab und liefert ausschließlich normalisierte Film- und
Serientreffer an den Browser. Personen aus der TMDB-Multisuche werden verworfen.
Der Token bleibt serverseitig. Gespeicherte Treffer landen getrennt in
`media_items`; dadurch gelangen keine Mediendaten in die bestehende
Büchertabelle. Die sichtbaren Statuswerte sind `watchlist`, `watching`,
`completed` und `dropped`. Die Endpunkte `/api/media` und
`/api/media/<id>` verwalten die benutzerspezifische Sammlung. Suchtreffer
lassen sich vor dem Speichern in einer Detailvorschau öffnen. Persönliche
Bewertungen von 1–5 Sternen und optionale Reviews bleiben strikt dem jeweiligen
Konto zugeordnet und sind von der öffentlichen TMDB-Wertung getrennt.

Für gespeicherte Filme fragt `/api/media/<id>/collection` zunächst die
TMDB-Filmdetails und anschließend – falls `belongs_to_collection` vorhanden ist –
die zugehörige Collection ab. Die normalisierten Teile erscheinen chronologisch
in der Film-Infoansicht. Noch nicht gespeicherte Suchtreffer verwenden dafür
`/api/media/movie/<tmdb_id>/collection`, sodass dieselben Reihendaten bereits in
der Vorschau sichtbar sind. Serien verwenden `/api/media/tv/<tmdb_id>/seasons`
für reguläre Staffeln und `/api/media/tv/<tmdb_id>/seasons/<staffel>` für die
Episoden. Episodebewertungen liegen unabhängig von der Sammlung in
`episode_ratings`; Episoden selbst können nicht gespeichert werden. Einzelne
Staffeln liegen dagegen in `saved_seasons` und können unabhängig von der
übergeordneten Serie den Status wechseln. Ihre Karten werden clientseitig über
den persistenten „Staffeln“-Schalter ein- oder ausgeblendet.

Die bisherige Buchsuche bleibt während der Migration vorerst parallel bestehen:

`readmore/providers/open_library.py` und `readmore/providers/google_books.py`
kapseln die externen Kataloge hinter einer gemeinsamen Provider-Schnittstelle.
Die Reihenfolge steht unter `catalogue` in `readmore/static/config.json`.
Im Modus `primary + fallback` wird der zweite Anbieter nur angefragt, wenn der
erste keinen plausiblen Treffer liefert oder vorübergehend nicht erreichbar
ist. Identische Anbieterwerte deaktivieren den Fallback.

Die Konfigurationsdatei liefert die globalen Standardwerte. Benutzer können
Haupt- und Fallback-Katalog in den Settings pro Browser beziehungsweise Gerät
überschreiben. Die Auswahl liegt in `localStorage` und wird als erlaubte,
serverseitig validierte Anbieterkennung an `/api/search` übergeben.

Die Buchsuche verwendet zwei Cache-Ebenen. Ein kleiner L1-Cache im Prozess hält
häufige Antworten fünf Minuten. Der gemeinsame L2-Cache in SQLite speichert
Vorschläge 24 Stunden und vollständige Suchen sieben Tage; leere erfolgreiche
Antworten nur 30 Sekunden. Fehler werden nicht gespeichert. Cache-Schlüssel
enthalten einen SHA-256-Hash statt des lesbaren Suchbegriffs und sind nach
Anbieter, Suchart und Ergebnislimit getrennt. Maximal 2.000 L2-Einträge bleiben
erhalten. Abgelaufene Einträge werden nicht angezeigt, sondern durch die
unveränderte Provider-Suche ersetzt.

Open Library unterscheidet zwischen:

- Werk: sprachunabhängige Identität und Reihenbezug (`provider_book_id`)
- Ausgabe: ISBN, Sprache, Cover, Verlag, Datum und Seitenzahl
  (`provider_edition_id`)

Die Oberfläche bevorzugt Ausgabedaten. Werkdaten dienen als Fallback und für
die Duplikat- und Reihenerkennung. Unicode-Titel und nichtlateinische Schriften
werden bei Normalisierung und Suche beibehalten.

Jeder Katalogtreffer und jedes gespeicherte Buch trägt zusätzlich den Namen
seines Anbieters. Dadurch werden Google-Books-IDs bei späteren Metadaten- und
Hintergrundabfragen nicht versehentlich an Open Library geschickt.

Cover von Open Library und Google Books werden beim ersten Abruf unter
`/data/covers` gespeichert. Die Tabelle `cover_cache` ordnet die externe Quelle
dem lokalen Dateipfad zu. Weitere Browser und Geräte laden dasselbe Cover danach
direkt von Moviepedia; das persistente Docker-Volume übersteht Image-Neubauten.
Open-Library-Weiterleitungen auf dessen Archive unter `*.archive.org` sind
zugelassen; andere Redirect-Ziele werden zum Schutz vor SSRF verworfen.

Google Books liefert bei einem Teil der Datensätze `volumeInfo.seriesInfo` mit
`seriesId` und Bandnummer. Der Provider verwendet diese Struktur bevorzugt und
sucht weitere Ausgaben anhand von Reihentitel und Autor. Fehlt `seriesInfo`,
werden nur eindeutige Titelmuster mit Bandnummer vorsichtig als Reihe erkannt.
Da Google keine vollständige Serienauflistung anhand der `seriesId` anbietet,
werden Google-Reihen als potenziell unvollständig gekennzeichnet und wie alle
anderen Reihenergebnisse in SQLite gecacht.

## Asynchrone Metadaten und Reihen

Beim Hinzufügen eines Buches wird zuerst der Bibliothekseintrag gespeichert.
Metadaten- und Reihenabfragen werden anschließend in Warteschlangen eingetragen.
Der Hintergrund-Worker verarbeitet diese Jobs unabhängig von der Anfrage, die
das Buch angelegt oder geöffnet hat.

Fehler führen zu einem erneuten Versuch mit wachsendem Abstand. Bereits
gespeicherte Ergebnisse werden aus SQLite verwendet. Die Oberfläche fragt den
Jobstatus kurzzeitig ab und aktualisiert einen geöffneten Dialog, sobald neue
Daten verfügbar sind.

Beim Start werden vorhandene Bücher ohne abgeschlossene Metadaten- oder
Reihenabfrage erneut eingeplant.

## Frontend und mobile Darstellung

- Templates: `readmore/templates/`
- Styles: `readmore/static/css/app.css`
- Browserlogik: `readmore/static/js/app.js`
- PWA-Cache: `readmore/static/service-worker.js`

Mobile Browser und der Capacitor-Wrapper erhalten `.platform-mobile`.
Android-spezifische Sonderfälle können zusätzlich `.platform-android` nutzen.
Die JavaScript-Konstante `IS_MOBILE_UI` aktiviert Touch-spezifisches Verhalten.

Reine Webänderungen werden vom VPS geladen und benötigen keinen APK-Neubau.
Native Android-Konfiguration, App-ID, Icons, Berechtigungen und Serveradresse
erfordern einen neuen Android-Build.

## Einstellungen

`readmore/static/config.json` enthält Standardwerte und verfügbare Optionen.
`defaults.reviewMaxLength` begrenzt Bewertungstexte in Oberfläche und Backend.
`defaults.seasonTabsPerRow` legt fest, nach wie vielen Staffel-Tabs eine neue
Zeile beginnt (Standard: `6`).
Die weiteren Längen- und Suchgrenzen liegen ebenfalls unter `defaults`. Das
Backend begrenzt Suchanfragen zusätzlich pro Konto und Minute; die Zähler
liegen in `search_rate_limits` und überstehen mehrere Gunicorn-Threads.
Gerätespezifische Einstellungen wie Theme, Startansicht und mobile Textgröße
werden im Browser gespeichert.

## Build-Version

Der Docker-Build berechnet einen SHA-256-Hash über den vollständigen
Build-Kontext und kürzt ihn auf zwölf Zeichen. Er wird als
`/app/.build-version` im Image gespeichert.

Flask liest den Wert beim Start und stellt ihn bereit:

- unten im Settings-Dialog,
- im `/health`-Endpunkt,
- im strukturierten Start-Log.

Ein identischer Quellstand erzeugt denselben Hash. Eine Änderung an einer in den
Build einfließenden Datei erzeugt beim nächsten Image-Build einen neuen Hash.
Ohne Build-Datei wird `development` angezeigt; `APP_VERSION` kann den Wert
explizit überschreiben.

## Logging

`readmore/logging_config.py` erzeugt strukturierte JSON-Logs. Jeder Request
erhält eine `X-Request-ID`. Erfolgreiche GET-Anfragen werden nur auf
`LOG_LEVEL=DEBUG` geschrieben; schreibende Anfragen, Warnungen und Fehler sind
mit `INFO` sichtbar.

Logs enthalten technische IDs, Status und Laufzeiten, aber keine Suchbegriffe,
Buchtitel, ISBNs, Passwörter oder Bewertungstexte. Docker begrenzt App-Logs auf
drei Dateien mit jeweils 10 MB.

## Deployment

Der systemd-Timer startet `deploy/epiloguehouse-auto-deploy` alle fünf Minuten.
Das Skript prüft `/opt/bookypedia` auf Branch `main` und `/opt/moviepedia` auf
Branch `movies` unabhängig voneinander und deployt nur neue Commits.
Das Skript:

1. lädt die Git-Referenzen von `origin/main` und `origin/movies`,
2. beendet sich ohne Log, wenn kein neuer Commit vorhanden ist,
3. akzeptiert ausschließlich einen sauberen Fast-Forward-Verlauf,
4. baut und startet die Produktions-Container,
5. markiert den Commit erst nach erfolgreichem Healthcheck als deployt,
6. versucht fehlgeschlagene Deployments beim nächsten Lauf erneut.

Ein Lock verhindert parallele Deployments. Die im Repository liegende Datei
wird bei der Installation nach `/usr/local/sbin` kopiert; Änderungen am
Deploy-Skript selbst müssen daher erneut installiert werden.

## Sicherheitsgrenzen

- Gunicorn ist nur an `127.0.0.1` gebunden.
- Ausschließlich Caddy veröffentlicht HTTP/HTTPS.
- Produktionsgeheimnisse liegen in `.env` und nicht im Repository.
- Session-Cookies sind in Produktion `Secure`, `HttpOnly` und `SameSite=Lax`.
- Sicherheitsheader verbieten unter anderem Frames, unnötige Browserrechte und
  fremde Skriptquellen.
- Das GitHub-Repository erlaubt ohne Schreibberechtigung keine Änderungen an
  `main` oder `movies`; der automatische Deploy vertraut beiden Branches
  dennoch als Produktionsquellen.

## Persistenz und Sicherungen

Container und Images sind austauschbar. Dauerhaft sind ausschließlich die
benannten Docker-Volumes und die VPS-`.env`. `docker compose down` behält die
Volumes; `docker compose down -v` löscht sie.

SQLite-Sicherungen verwenden die Backup-API von SQLite, damit eine konsistente
Kopie entsteht. Die Bedienbefehle stehen in der README.
