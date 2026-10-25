#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
adb_bin="${ADB_BIN:-}"

if [[ -z "$adb_bin" ]]; then
  if command -v adb >/dev/null 2>&1; then
    adb_bin="$(command -v adb)"
  elif [[ -x "${ANDROID_HOME:-}/platform-tools/adb" ]]; then
    adb_bin="${ANDROID_HOME}/platform-tools/adb"
  elif [[ -x "$HOME/Android/Sdk/platform-tools/adb" ]]; then
    adb_bin="$HOME/Android/Sdk/platform-tools/adb"
  else
    echo "adb wurde nicht gefunden. Installiere zuerst die Android SDK Platform-Tools." >&2
    exit 1
  fi
fi

android_sdk_dir="$(cd "$(dirname "$adb_bin")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$android_sdk_dir}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export PATH="$(dirname "$adb_bin"):$PATH"

if ! curl --fail --silent --show-error http://127.0.0.1:5000/health >/dev/null; then
  echo "Bookypedia läuft nicht auf http://localhost:5000." >&2
  echo "Starte im Projektverzeichnis zuerst: docker compose up --build -d" >&2
  exit 1
fi

if ! "$adb_bin" get-state >/dev/null 2>&1; then
  echo "Kein freigegebenes Android-Gerät oder kein laufender Emulator gefunden." >&2
  echo "Aktiviere USB-Debugging, verbinde das Handy und bestätige die Geräteabfrage." >&2
  exit 1
fi

# Die App verwendet auf dem Handy immer Port 8000. Lokal wird dieser Port
# per ADB an den Flask-Entwicklungsport 5000 des PCs weitergereicht.
"$adb_bin" reverse tcp:8000 tcp:5000
cd "$project_dir"
npx cap sync android
npx cap run android
