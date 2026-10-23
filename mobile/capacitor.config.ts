import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "de.bookypedia.app",
  appName: "Bookypedia",
  webDir: "www",
  server: {
    // Nur fuer die lokale Entwicklung: `adb reverse` leitet diesen Port
    // vom Android-Geraet an die Flask-App auf dem Entwicklungs-PC weiter.
    url: "http://localhost:5000",
    cleartext: true,
  },
  android: {
    // Eindeutige Kennung fuer Android-spezifische, serverseitig geladene UI-Regeln.
    appendUserAgent: " BookypediaAndroid",
  },
};

export default config;
