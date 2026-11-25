#!/usr/bin/env bash
set -euo pipefail

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
[[ "$data_home" = /* ]] || data_home="$HOME/.local/share"
rm -f -- "$HOME/.local/bin/somawave" \
    "$data_home/applications/somawave.desktop" \
    "$data_home/icons/hicolor/scalable/apps/somawave.svg"
rm -rf -- "$data_home/somawave/venv"
rmdir -- "$data_home/somawave" 2>/dev/null || true
printf 'Removed SomaWave. Preferences, station cache, and source files were preserved.\n'
