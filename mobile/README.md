# Bookypedia für Android

Die Android-App ist ein Capacitor-Wrapper für die bestehende Flask-Oberfläche.
Dadurch verwenden Browser und Android dieselbe UI, dieselben Benutzerkonten und
dasselbe Backend. Die verwendete Serveradresse wird beim Capacitor-Sync
festgelegt; die App schaltet nicht selbstständig zwischen lokal und Produktion
um.

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
npm run run
```

`npm install` ist nur beim ersten Einrichten sowie nach Änderungen an
`package.json` oder `package-lock.json` notwendig.

Das Startskript richtet mit `adb reverse` eine ausschließlich über die lokale
ADB-Verbindung erreichbare Weiterleitung ein. Innerhalb des Handys zeigt
`http://localhost:8000` dadurch auf Port 5000 der Bookypedia-App des
Entwicklungs-PCs. Anschließend synchronisiert es Capacitor, baut die App,
installiert sie und startet sie auf dem verbundenen Gerät.

`npm run run` wird verwendet, wenn die Anwendung lokal auf einem Handy getestet
werden soll, insbesondere nach dem erneuten Verbinden des Geräts, nach Verlust
der ADB-Weiterleitung oder nach Änderungen am nativen Wrapper. Bei reinen
Änderungen an HTML, CSS, JavaScript oder dem Flask-Backend genügt während einer
bestehenden Verbindung normalerweise das Schließen und erneute Öffnen der App.

## Android-spezifische Weboberfläche

Die Templates erkennen den Android-Wrapper über den ergänzten User-Agent und
setzen auf dem HTML-Element die Klasse `.platform-android`. In JavaScript steht
zusätzlich `IS_ANDROID_APP` zur Verfügung. Damit lassen sich Änderungen nur in
der installierten App aktivieren, ohne die Browseransicht zu verändern.

Solche Änderungen gehören weiterhin zur serverseitigen Weboberfläche. Nach
Commit, Push und VPS-Deployment lädt eine bereits installierte Produktions-App
sie von `https://epiloguehouse.de`; eine neue APK ist dafür nicht erforderlich.
Eine Media Query nach Bildschirmbreite betrifft dagegen sowohl die App als auch
einen normalen Browser auf einem Smartphone.

Eine neue APK ist notwendig bei Änderungen an:

- App-Icon, Splashscreen, App-Name oder App-ID,
- Android-Berechtigungen oder dem Manifest,
- `capacitor.config.ts`, Capacitor-Plugins oder nativen Android-Dateien,
- der in die App eingebauten Produktionsdomain.

## Produktions-App bauen

Die in `capacitor.config.ts` erlaubte unverschlüsselte HTTP-Verbindung gilt nur
für `localhost`. Für einen Build gegen den öffentlich abgesicherten VPS wird
die HTTPS-Adresse explizit beim Synchronisieren gesetzt:

```bash
cd mobile
BOOKYPEDIA_APP_URL=https://epiloguehouse.de npm run sync
cd android
ANDROID_HOME=/home/led/Android/Sdk ./gradlew assembleDebug
```

Die APK liegt anschließend unter
`mobile/android/app/build/outputs/apk/debug/app-debug.apk` und kann auf dem
verbundenen Gerät aktualisiert werden mit:

```bash
/home/led/Android/Sdk/platform-tools/adb install -r \
  app/build/outputs/apk/debug/app-debug.apk
```

Web und Android verwenden danach dieselbe Anmeldung und benutzerspezifische
Bibliothek; ein SSH-Tunnel, Termux oder VPN ist nicht nötig. Reine
Webänderungen werden auf dem VPS veröffentlicht und benötigen keinen erneuten
Android-Build.

Der lokale Entwicklungsbuild und der Produktionsbuild besitzen derzeit
dieselbe App-ID. Sie können daher nicht gleichzeitig installiert sein, sondern
ersetzen sich auf dem Handy gegenseitig. Vor der Weitergabe an andere Personen
wird ein signierter Release-Build mit dauerhaft gesichertem Keystore benötigt;
der Keystore darf nicht in Git eingecheckt werden.
