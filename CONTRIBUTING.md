# Contributing to SomaWave

Open an issue for a reproducible bug or to discuss a substantial change. Keep pull requests focused and describe the problem, how you tested the change, and any visible effects. See [SECURITY.md](SECURITY.md) for vulnerability reports.

Use the virtual environment and test commands in the [README](README.md). Prefer local fixtures or mocks for new tests. Preserve the approved playback controls, settings, appearance, and Omarchy behavior unless the change addresses an agreed issue.

If you attach logs, screenshots, or configuration examples, remove personal paths, account details, and listening history. Submit original work or material you have permission to contribute, and identify any third-party material and its license.

## Local release packages

Install the Python `build` package in your development virtual environment, then run `PYTHON="$PWD/.venv/bin/python" ./scripts/build-release.sh` from the repository root. The command creates a wheel, source distribution, standalone Linux archive, and checksum manifest in `dist/v<version>/`. An optional argument sets the parent output directory.
