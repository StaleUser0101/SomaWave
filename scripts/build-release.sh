#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="${PYTHON:-python3}"
version="$("$python" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$repo/pyproject.toml")"
output_parent="${1:-$repo/dist}"
output="$output_parent/v$version"
if [[ -e "$output" || -L "$output" ]]; then
    printf 'Release output already exists: %s\n' "$output" >&2
    exit 1
fi

scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
"$python" -m build --outdir "$scratch/packages" "$repo"

# Normalize archive ownership so package headers carry no local account names.
source_dir="somawave-$version"
linux_dir="SomaWave-$version"
mkdir "$scratch/source"
tar -xzf "$scratch/packages/$source_dir.tar.gz" -C "$scratch/source"
tar --owner=0 --group=0 --numeric-owner -C "$scratch/source" \
    -czf "$scratch/packages/$source_dir.tar.gz" "$source_dir"
mv -- "$scratch/source/$source_dir" "$scratch/source/$linux_dir"
tar --owner=0 --group=0 --numeric-owner --exclude='*.egg-info' --exclude='PKG-INFO' \
    -C "$scratch/source" -czf "$scratch/packages/$linux_dir-linux.tar.gz" "$linux_dir"

(
    cd "$scratch/packages"
    sha256sum "$linux_dir-linux.tar.gz" "somawave-$version-py3-none-any.whl" "$source_dir.tar.gz" > SHA256SUMS
)
mkdir -p -- "$output_parent"
mkdir -- "$output"
mv -- "$scratch/packages/"* "$output/"
printf 'Built SomaWave %s release artifacts in %s\n' "$version" "$output"
