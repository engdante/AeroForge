#!/usr/bin/env bash
# ============================================================
#  AeroForge — стартиране под Linux / macOS
#
#  1) намира python3 (>= 3.10);
#  2) създава локална среда .venv (ако още я няма);
#  3) инсталира зависимостите от app/requirements.txt
#     (само ако eel липсва в средата);
#  4) стартира приложението (Eel + браузър).
#
#  Използване:   ./start.sh [порт]
#  Пример:       ./start.sh 8080
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV_PY="./.venv/bin/python"

# ---------- 1. Python ----------
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ГРЕШКА] python3 не е намерен."
  echo "Инсталирай го:"
  echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip"
  echo "  Fedora:         sudo dnf install python3 python3-pip"
  echo "  Arch:           sudo pacman -S python python-pip"
  echo "  macOS:          brew install python"
  exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)'; then
  echo "[ГРЕШКА] Намереният Python е по-стар от 3.10: $("$PY" --version)"
  exit 1
fi

# ---------- 2. Локална среда .venv ----------
if [ ! -x "$VENV_PY" ]; then
  echo "Създавам локална среда .venv ..."
  if ! "$PY" -m venv .venv; then
    echo "[ГРЕШКА] Не мога да създам .venv."
    echo "На Debian/Ubuntu най-често липсва пакетът: sudo apt install python3-venv"
    exit 1
  fi
fi

# ---------- 3. Зависимости ----------
if ! "$VENV_PY" -c 'import eel' >/dev/null 2>&1; then
  echo "Инсталирам зависимости от app/requirements.txt ..."
  "$VENV_PY" -m pip install --disable-pip-version-check -r app/requirements.txt
fi

# ---------- 4. Стартиране ----------
echo
echo "Стартиране на AeroForge ...  (Ctrl+C за спиране)"
exec "$VENV_PY" app/server.py "$@"
