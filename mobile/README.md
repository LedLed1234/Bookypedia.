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
`http://localhost:5000` dadurch auf die Bookypedia-App des Entwicklungs-PCs.

Die in `capacitor.config.ts` erlaubte unverschlüsselte HTTP-Verbindung ist nur
für diese lokale Entwicklungsphase bestimmt. Vor einer Veröffentlichung wird
sie entfernt und durch den abgesicherten HTTPS-Endpunkt mit Geräteanmeldung
ersetzt.
