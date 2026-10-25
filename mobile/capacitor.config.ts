import type { CapacitorConfig } from "@capacitor/cli";

const nodeProcess = (globalThis as typeof globalThis & {
  process?: { env?: Record<string, string | undefined> };
}).process;
const appUrl = nodeProcess?.env?.BOOKYPEDIA_APP_URL?.trim() || "http://localhost:8000";

const config: CapacitorConfig = {
  appId: "de.bookypedia.app",
  appName: "Bookypedia",
  webDir: "www",
  server: {
    // Lokal leitet `adb reverse` diesen Port an den Entwicklungs-PC weiter.
    // Produktions-Builds erhalten BOOKYPEDIA_APP_URL=https://... beim Sync.
    url: appUrl,
    cleartext: appUrl.startsWith("http://localhost"),
  },
  android: {
    // Eindeutige Kennung fuer Android-spezifische, serverseitig geladene UI-Regeln.
    appendUserAgent: " BookypediaAndroid",
  },
};

export default config;
