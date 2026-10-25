# Bookypedia für Android

Die Android-App ist zunächst ein lokaler Capacitor-Entwicklungswrapper für die
bestehende Flask-Oberfläche. Dadurch verwenden Browser und Android dieselbe UI
und dasselbe Backend.

## Lokal auf einem Android-Gerät starten

Voraussetzungen:

- Android Studio mit Android SDK und Platform-Tools
- auf dem Handy aktiviertes USB-Debugging oder ein laufender Emulator
- die lokale Bookypedia-App auf Port 5000

Im Projektverzeichnis zuerst Flask starten:

```bash
docker compose up --build -d
```

Anschließend:

```bash
cd mobile
npm install
npm run run
```

Das Startskript richtet mit `adb reverse` eine ausschließlich über die lokale
ADB-Verbindung erreichbare Weiterleitung ein. Innerhalb des Handys zeigt
`http://localhost:8000` dadurch auf Port 5000 der Bookypedia-App des
Entwicklungs-PCs. Derselbe Handy-Port kann später vorübergehend über einen
lokalen SSH-Tunnel zum VPS geführt werden.

Die in `capacitor.config.ts` erlaubte unverschlüsselte HTTP-Verbindung gilt nur
für `localhost`. Für einen Build gegen den öffentlich abgesicherten VPS wird
die HTTPS-Adresse beim Synchronisieren gesetzt:

```bash
BOOKYPEDIA_APP_URL=https://books.example.com npm run sync
cd android
./gradlew assembleDebug
```

Ersetze die Beispieladresse durch die konfigurierte Bookypedia-Domain. Web und
Android verwenden anschließend dieselbe Anmeldung und benutzerspezifische
Bibliothek; ein SSH-Tunnel oder Termux ist nicht nötig.
