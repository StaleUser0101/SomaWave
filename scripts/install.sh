#!/usr/bin/env bash
set -euo pipefail

for dependency in python3 mpv; do
    if ! command -v "$dependency" >/dev/null; then
        printf 'Missing required command: %s. Install it with your Linux distribution package manager, then rerun this script.\n' "$dependency" >&2
        exit 1
    fi
done
python3 -c 'import ensurepip, sys, venv; sys.exit(sys.version_info < (3, 11))' || {
    printf 'Python 3.11 or newer with venv and ensurepip is required.\n' >&2
    exit 1
}

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
[[ "$data_home" = /* ]] || data_home="$HOME/.local/share"
bin_home="$HOME/.local/bin"
venv="$data_home/somawave/venv"
launcher="$data_home/applications/somawave.desktop"
icon="$data_home/icons/hicolor/scalable/apps/somawave.svg"

scratch="$(mktemp -d)"
new_venv=false
installed=false
wrapper_tmp=
launcher_tmp=
icon_tmp=
cleanup() {
    local status=$?
    rm -rf -- "$scratch"
    for file in "$wrapper_tmp" "$launcher_tmp" "$icon_tmp"; do
        [[ -z "$file" ]] || rm -f -- "$file"
    done
    if (( status != 0 )); then
        if "$new_venv" && ! "$installed"; then
            rm -rf -- "$venv"
        fi
        printf 'SomaWave installation failed. See the error above.\n' >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for target in "$bin_home/somawave" "$launcher" "$icon"; do
    if [[ -d "$target" ]]; then
        printf 'Installation path is a directory: %s\n' "$target" >&2
        exit 1
    fi
done
install -d -- "$bin_home" "$(dirname -- "$launcher")" "$(dirname -- "$icon")"
wrapper_tmp="$(mktemp -- "$bin_home/.somawave.XXXXXX")"
launcher_tmp="$(mktemp -- "${launcher%.desktop}.XXXXXX.desktop")"
icon_tmp="$(mktemp -- "${icon%.svg}.XXXXXX.svg")"
install -m 644 -- "$repo/assets/somawave.svg" "$icon_tmp"

printf '#!/usr/bin/env bash\nexec %q -m somawave "$@"\n' "$venv/bin/python" > "$wrapper_tmp"
chmod 755 -- "$wrapper_tmp"
chmod 644 -- "$launcher_tmp"
python3 - "$launcher_tmp" "$bin_home/somawave" <<'PYTHON'
import shutil
import sys
from pathlib import Path


def desktop_argument(value):
    for character in '\\"$`':
        value = value.replace(character, "\\" + character)
    return '"' + value.replace("%", "%%").replace("\\", "\\\\") + '"'


launcher, executable = sys.argv[1:]
omarchy = shutil.which("omarchy")
omarchy_tui = shutil.which("omarchy-launch-tui")
omarchy_terminal = shutil.which("omarchy-launch-terminal")
xdg_terminal = shutil.which("xdg-terminal-exec")

if omarchy and omarchy_tui:
    command = [omarchy, "launch", "tui", "--app-id=somawave"]
elif omarchy_tui:
    command = [omarchy_tui, "--app-id=somawave"]
elif omarchy_terminal:
    command = [omarchy_terminal]
elif xdg_terminal:
    command = [xdg_terminal]
else:
    command = []

terminal = "false" if command else "true"
exec_line = " ".join(desktop_argument(arg) for arg in [*command, executable])
Path(launcher).write_text(
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=SomaWave\n"
    "Comment=Independent radio. Terminal style.\n"
    f"Exec={exec_line}\n"
    "Icon=somawave\n"
    f"Terminal={terminal}\n"
    "Categories=AudioVideo;Audio;Player;\n",
    encoding="utf-8",
)
PYTHON
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$launcher_tmp"
fi

if [[ ! -e "$venv" && ! -L "$venv" ]]; then
    new_venv=true
    python3 -m venv "$venv"
fi
if [[ ! -x "$venv/bin/python" ]] || ! "$venv/bin/python" -m pip --version >/dev/null; then
    printf 'The SomaWave virtual environment is unusable. Run scripts/uninstall.sh, then reinstall. User settings and cache are preserved.\n' >&2
    exit 1
fi
"$venv/bin/python" -m pip wheel --no-deps --wheel-dir "$scratch" "$repo"
"$venv/bin/python" -m pip install "$scratch"/somawave-*.whl
installed=true

mv -fT -- "$icon_tmp" "$icon"
mv -fT -- "$wrapper_tmp" "$bin_home/somawave"
mv -fT -- "$launcher_tmp" "$launcher"
printf 'Installed SomaWave. Launch it from your app menu or run %s/somawave.\n' "$bin_home"
