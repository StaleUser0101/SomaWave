#!/usr/bin/env bash
# Keep the entry point last so an incomplete curl stream cannot start an install.
set -euo pipefail

fail() {
    printf 'SomaWave: %s\n' "$*" >&2
    exit 1
}

require_commands() {
    local name
    for name in "$@"; do
        command -v "$name" >/dev/null || fail "Missing required command: $name"
    done
}

download() {
    local url=$1 output=$2 status
    shift 2
    # Ignore curlrc, including options that could disable certificate verification.
    if ! status=$(curl --disable --proto '=https' --proto-redir '=https' --location \
        --fail --show-error --connect-timeout 15 --max-time 180 --retry 2 \
        --output "$output" --write-out '%{http_code}' "$@" "$url"); then
        case "$status" in
            403|429) fail 'GitHub denied or rate-limited the download. Try again later.' ;;
            *) fail "Download failed (HTTP ${status:-unknown}). Check your connection and try again." ;;
        esac
    fi
}

select_assets() {
    python3 -I - "$@" <<'PY'
import json
import re
import sys

metadata, release_base, arch, method = sys.argv[1:]
try:
    with open(metadata, encoding="utf-8") as stream:
        release = json.load(stream)
    tag = release["tag_name"]
    if (release["draft"] is not False or release["prerelease"] is not False
            or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)):
        raise ValueError("expected a stable vMAJOR.MINOR.PATCH release")
    version = tag[1:]
    if not isinstance(release["assets"], list):
        raise ValueError("invalid release assets")
    names = {}
    for asset in release["assets"]:
        name = asset["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name) or name in names:
            raise ValueError("invalid or duplicate release asset name")
        names[name] = asset
    archive = f"SomaWave-{version}-linux.tar.gz"
    groups = [(archive, "SHA256SUMS")] if method != "native" else []
    if method != "standalone":
        prefix = rf"somawave-{re.escape(version)}-[0-9]+(?:\.[0-9]+)?"
        pattern = lambda suffix: rf"{prefix}-{re.escape(suffix)}\.pkg\.tar\.zst"
        matches = [name for name in names if re.fullmatch(pattern(arch), name)]
        if not matches and arch != "any":
            matches = [name for name in names if re.fullmatch(pattern("any"), name)]
        if len(matches) != 1:
            raise ValueError("expected one native package for this architecture")
        groups.insert(0, (matches[0], "SHA256SUMS-arch"))
    for name in (name for group in groups for name in group):
        asset = names.get(name)
        if (not asset or asset["state"] != "uploaded"
                or asset["browser_download_url"] != f"{release_base}/{tag}/{name}"):
            raise ValueError(f"missing or invalid release asset: {name}")
    print(tag, *(name for group in groups for name in group))
except (OSError, KeyError, TypeError, ValueError) as error:
    sys.exit(f"Invalid GitHub release metadata: {error}")
PY
}

fetch_verified() {
    local asset=$1 manifest=$2 digest
    printf 'Downloading %s and %s\n' "$asset" "$manifest"
    download "$release_base/$tag/$manifest" "$scratch/$manifest" --silent
    download "$release_base/$tag/$asset" "$scratch/$asset" --progress-bar
    digest=$(python3 -I - "$scratch/$manifest" "$asset" <<'PY'
import re
import sys

manifest, asset = sys.argv[1:]
with open(manifest, encoding="ascii") as stream:
    entries = [match[1] for line in stream
               if (match := re.fullmatch(r"([a-fA-F0-9]{64}) [ *]" + re.escape(asset),
                                        line.rstrip("\r\n")))]
if len(entries) != 1:
    sys.exit("Expected one SHA-256 entry for the selected asset")
print(entries[0])
PY
    ) || fail "Invalid checksum manifest: $manifest"
    (cd -- "$scratch" && printf '%s  %s\n' "$digest" "$asset" | sha256sum --check) ||
        fail "Checksum verification failed for $asset"
}

prepare_standalone() {
    fetch_verified "$archive" "$archive_manifest"
    source_dir="$scratch/SomaWave-${tag#v}"
    # Validate the entire archive before extracting regular files and directories.
    python3 -I - "$scratch/$archive" "$scratch" "${source_dir##*/}" <<'PY'
import pathlib
import sys
import tarfile

archive, destination, root = sys.argv[1:]
with tarfile.open(archive, "r:gz") as source:
    members = source.getmembers()
    paths = set()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if (not path.parts or path.parts[0] != root or ".." in path.parts
                or path in paths or not (member.isfile() or member.isdir())):
            sys.exit("Unexpected path or file type in standalone archive")
        paths.add(path)
    for script in ("install.sh", "uninstall.sh"):
        if not source.getmember(f"{root}/scripts/{script}").isfile():
            sys.exit(f"Missing standalone script: {script}")
    source.extractall(destination, members, filter="data")
PY
}

main() {
    local repository=StaleUser0101/SomaWave
    local release_base="https://github.com/$repository/releases/download"
    local distro='' like='' os_name='' os_release key value word
    local native=false standalone=false mode=standalone description action
    local native_version='' standalone_version='' installed_info package_name extra
    local data_home wrapper venv launcher icon target expected resolved
    local scratch tag asset manifest archive archive_manifest selection source_dir
    local arch package_version package_release pkg_python system_python paths answer comparison
    local -a standalone_metadata selection_fields

    printf 'SomaWave\n'
    (( EUID != 0 )) || fail 'Run this installer as your regular user.'
    require_commands uname cat
    [[ $(uname -s) == Linux ]] || fail 'This installer requires Linux.'
    os_release=$(cat /etc/os-release) || fail 'Cannot read /etc/os-release.'
    while IFS='=' read -r key value; do
        value=${value#\"}
        value=${value%\"}
        value=${value#\'}
        value=${value%\'}
        case "$key" in
            ID) distro=$value ;;
            ID_LIKE) like=$value ;;
            PRETTY_NAME) os_name=$value ;;
        esac
    done <<< "$os_release"
    [[ $distro =~ ^[a-z0-9._-]+$ ]] || fail 'Invalid or missing operating system ID.'
    printf 'Operating system: %s\n' "${os_name:-$distro}"
    local -a distro_ids
    read -r -a distro_ids <<< "$distro $like"
    for word in "${distro_ids[@]}"; do
        case "$word" in
            arch|archlinux|omarchy|cachyos|endeavouros|manjaro|garuda|artix)
                mode=native
                break
                ;;
        esac
    done
    if [[ $mode == native ]]; then
        require_commands pacman
    elif command -v pacman >/dev/null && pacman -Q somawave >/dev/null 2>&1; then
        fail 'An existing Pacman installation was found on a non-Arch distribution.'
    fi

    require_commands curl python3 sha256sum mktemp rm
    python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
        fail 'Python 3.11 or newer is required.'
    data_home=${XDG_DATA_HOME:-$HOME/.local/share}
    [[ $data_home == /* ]] || data_home="$HOME/.local/share"
    venv="$data_home/somawave/venv"
    wrapper="$HOME/.local/bin/somawave"
    launcher="$data_home/applications/somawave.desktop"
    icon="$data_home/icons/hicolor/scalable/apps/somawave.svg"

    if [[ $mode == native ]] && installed_info=$(pacman -Q somawave 2>/dev/null); then
        read -r package_name native_version extra <<< "$installed_info"
        [[ $package_name == somawave && -n $native_version && -z $extra ]] ||
            fail 'Unexpected installed package metadata.'
        native=true
        printf 'Installed (native): %s\n' "$native_version"
    fi

    for target in "$wrapper" "$venv" "$launcher" "$icon"; do
        if [[ -e $target || -L $target ]]; then
            standalone=true
        fi
    done
    if "$standalone"; then
        expected=$(printf '#!/usr/bin/env bash\nexec %q -m somawave "$@"\n' "$venv/bin/python")
        [[ -f $wrapper && ! -L $wrapper && $(<"$wrapper") == "$expected" &&
            -d $venv && ! -L $venv && -x $venv/bin/python ]] ||
            fail 'Unrecognized user-local SomaWave files. Check XDG_DATA_HOME and the manual migration instructions.'
        shopt -s nullglob
        standalone_metadata=("$venv"/lib/python*/site-packages/somawave-*.dist-info)
        shopt -u nullglob
        (( ${#standalone_metadata[@]} == 1 )) || fail 'Cannot identify the standalone version.'
        standalone_version=${standalone_metadata[0]##*/somawave-}
        standalone_version=${standalone_version%.dist-info}
        printf 'Installed (standalone): %s\n' "$standalone_version"
        [[ ! -d $launcher && ! -d $icon ]] || fail 'A standalone launcher or icon path is a directory.'
        [[ $mode != native ]] || mode=migrate
    fi
    resolved=$(type -P somawave || true)
    if [[ -n $resolved &&
          ! ( $standalone == true && $resolved == "$wrapper" ) &&
          ! ( $native == true && $resolved -ef /usr/bin/somawave ) ]]; then
        fail "An independently managed SomaWave command is on PATH: $resolved. Resolve it before continuing."
    fi

    arch=$(uname -m) || fail 'Cannot determine CPU architecture.'
    scratch=$(mktemp -d) || fail 'Cannot create a temporary directory.'
    # Capture the path because main's local variables are out of scope at EXIT.
    local cleanup
    printf -v cleanup 'rm -rf -- %q' "$scratch"
    # shellcheck disable=SC2064
    trap "$cleanup" EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    download "https://api.github.com/repos/$repository/releases/latest" "$scratch/release.json" \
        --silent --header 'Accept: application/vnd.github+json'
    selection=$(select_assets "$scratch/release.json" "$release_base" "$arch" "$mode") ||
        fail 'Could not select a stable release with the required assets.'
    read -r -a selection_fields <<< "$selection"
    tag=${selection_fields[0]}
    printf 'Latest available: %s\n' "$tag"
    case "$mode" in
        standalone)
            description='standalone (per user)'
            archive=${selection_fields[1]}
            archive_manifest=${selection_fields[2]}
            if "$standalone"; then
                comparison=$(python3 -I - "$standalone_version" "${tag#v}" <<'PY'
import re
import sys

installed, latest = sys.argv[1:]
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", installed):
    sys.exit("Cannot compare an independently versioned standalone build")
current, available = (tuple(map(int, version.split("."))) for version in (installed, latest))
print((current > available) - (current < available))
PY
                ) || fail 'Cannot safely compare standalone versions.'
            fi
            ;;
        native|migrate)
            description='native Arch package (Pacman)'
            asset=${selection_fields[1]}
            manifest=${selection_fields[2]}
            package_release=${asset#somawave-}
            package_version=${package_release%-*.pkg.tar.zst}
            if "$native"; then
                require_commands vercmp
                comparison=$(vercmp "$native_version" "$package_version") ||
                    fail 'Cannot compare native package versions.'
            fi
            if [[ $mode == migrate ]]; then
                description+=' with standalone removal'
                archive=${selection_fields[3]}
                archive_manifest=${selection_fields[4]}
            fi
            ;;
    esac
    printf 'Installation method: %s\n' "$description"
    if [[ ${comparison:-} == 1 ]]; then
        printf 'A newer package is already installed.\n'
        exit 0
    fi
    if [[ ${comparison:-} == 0 && $mode != migrate ]]; then
        printf 'The latest version is already installed.\n'
        exit 0
    fi

    if [[ $mode == standalone ]]; then
        require_commands mpv install dirname chmod mv rmdir
        python3 -I -c 'import ensurepip, venv' ||
            fail 'Standalone installation requires Python venv and ensurepip.'
    else
        require_commands bsdtar
        [[ ${comparison:-} == 0 ]] || require_commands sudo
    fi
    # Open the controlling terminal before downloading packages and pass it to Pacman.
    { exec 3<>/dev/tty; } 2>/dev/null || fail 'An interactive terminal is required to confirm installation.'
    if [[ $mode != standalone ]]; then
        fetch_verified "$asset" "$manifest"
        installed_info=$(pacman -Qp "$scratch/$asset") || fail 'Cannot inspect the native package.'
        [[ $installed_info == "somawave $package_version" ]] || fail 'Unexpected native package identity.'
        paths=$(bsdtar -tf "$scratch/$asset") || fail 'Cannot list native package files.'
        pkg_python=
        while IFS= read -r target; do
            if [[ $target =~ ^(\./)?usr/lib/python([0-9]+\.[0-9]+)/site-packages/somawave/__init__\.py$ ]]; then
                [[ -z $pkg_python ]] || fail 'Ambiguous Python version in the native package.'
                pkg_python=${BASH_REMATCH[2]}
            fi
        done <<< "$paths"
        [[ -n $pkg_python ]] || fail 'Cannot determine the native package Python version.'
        system_python=$(/usr/bin/python3 -I -c 'import sys; print("%d.%d" % sys.version_info[:2])') ||
            fail 'Cannot determine the system Python version.'
        [[ $pkg_python == "$system_python" ]] ||
            fail "Native package requires Python $pkg_python, but the system has Python $system_python. Use a matching build."
    fi
    if [[ $mode != native ]]; then
        prepare_standalone || fail 'Cannot prepare the verified standalone archive.'
    fi

    action="Install SomaWave $tag"
    if [[ $mode == migrate ]]; then
        action+=" via Pacman and remove the standalone installation"
    elif "$native" || "$standalone"; then
        action="Upgrade SomaWave to $tag"
    fi
    printf 'Quit any running SomaWave session. %s? [y/N] ' "$action" >&3
    if ! IFS= read -r answer <&3 || [[ $answer != [yY] && ${answer,,} != yes ]]; then
        printf 'Installation cancelled.\n'
        exit 0
    fi

    if [[ $mode == standalone ]]; then
        bash "$source_dir/scripts/install.sh" <&3 || fail 'Standalone installation failed.'
        printf 'SomaWave %s is ready. Launch %s or open SomaWave from the app menu.\n' "$tag" "$wrapper"
    else
        if [[ ${comparison:-} != 0 ]]; then
            sudo pacman -U -- "$scratch/$asset" <&3 || fail 'Pacman installation failed.'
            installed_info=$(pacman -Q somawave) || fail 'Pacman did not install SomaWave.'
            [[ $installed_info == "somawave $package_version" ]] ||
                fail 'Pacman did not install the selected version.'
        fi
        if [[ $mode == migrate ]]; then
            bash "$source_dir/scripts/uninstall.sh" <&3 ||
                fail 'Native package installed, but standalone cleanup failed. Follow the manual migration instructions.'
            for target in "$wrapper" "$venv" "$launcher" "$icon"; do
                [[ ! -e $target && ! -L $target ]] ||
                    fail "Standalone cleanup left $target. Follow the manual migration instructions."
            done
        fi
        printf 'SomaWave %s is ready. Launch /usr/bin/somawave or open SomaWave from the app menu.\n' "$tag"
    fi
}

main "$@"
