# Changelog

## 1.0.2

- Fix a regression introduced in v1.0.0 that left Artist and Track at Unknown during playback. Retain a small MPV demuxer back buffer so timed ICY metadata reaches the player.
- Prefer separate artist and title tags when the stream also supplies a combined ICY title.

## 1.0.1

- License SomaWave under MIT and include the license and third-party notices in distribution packages.
- Add authentic application screenshots and prepare the GitHub documentation, contribution templates, and local test workflow.
- Build a standalone Linux archive, Python wheel, source distribution, and SHA-256 checksums.
- Preserve the v1.0.0 interface, playback behavior, and settings format.

## 1.0.0

First stable release of SomaWave, an independent SomaFM player for Linux terminals.

### Stabilization
- Require a Textual version verified to support the compact Settings controls. The previous minimum allowed versions that failed at startup.

- Keep loaded stations usable if a directory refresh fails. Fall back to the cached directory when an HTTP response ends prematurely.
- Treat malformed metadata and bitrate values as unavailable. Report an unsupported spectrum filter without interrupting playback.
- Keep MPV cleanup owned by the player when a station switch is cancelled.
- Disable MPV’s unused rewind cache while keeping forward buffering for live streams.
- Flush preference and cache JSON to disk before replacing the previous file. Preserve the last valid file if a write fails before replacement.
- Build the installation wheel and validate the desktop entry before publishing launcher files. Reuse existing dependencies on upgrades and clean up a newly created environment after a failed package installation.
- Document installation, upgrades, troubleshooting, development and release limitations.

### Features carried forward

- Textual station browser with the live SomaFM directory, an offline directory cache, filtering, favorites and recent history.
- MPV playback with live metadata, volume and mute, ordered stream quality fallback, optional reconnection and startup autoplay.
- Live spectrum display with configurable peak markers, persistent settings and a default station view.
- Native Omarchy launcher integration and live light and dark theme matching, with SomaWave fallback colors.
- Original SVG icon and per-user installation and uninstallation scripts.

### Known limitations

- Live directory and stream availability depend on SomaFM and the network. Cached stations can be browsed offline. Playback still needs a reachable stream.
- Metadata and advertised bitrates vary by station. Missing values show as Unknown, and quality ranking uses playlist labels and known naming conventions when numeric bitrates are absent.
- The spectrum depends on MPV filter support and uses a mono mix. Buffering and stereo phase cancellation can affect the display.
- Favorites and history remain saved by station ID while unavailable stations are absent from the corresponding views.
- The desktop and terminal control transparency and terminal selection. Installation and removal use the current XDG data location.

## 0.4.0

- Added an autosaving Settings dialog for playback and appearance preferences.
- Added stream quality selection, startup autoplay, and optional reconnection.
- Added independent analyzer and peak marker controls plus a default station view.

## 0.3.1

- Inset favorite stars by one cell and reserve room for them when station names are truncated.

## 0.3.0

- Added All Stations, Favorites, and Recent views with filtering, keyboard navigation, and clickable favorite stars.
- Store favorites and the last 10 successfully played stations in the existing preferences file.

## 0.2.4

- Use equal-width spectrum bars and one-cell gaps, with balanced padding when needed.

## 0.2.3

- Simplified the terminal header to SomaWave and SomaFM text.
- Distribute spectrum bar widths across all available columns while preserving one-cell gaps.

## 0.2.2

- Reduced the header waveform to two rows, with a title-only layout at very narrow widths.
- Expanded the spectrum to up to eight rows and 40 log-spaced bands, with responsive sizing, time-based smoothing, and peak markers.

## 0.2.1

- Matched the terminal header waveform to the seven centered bars of the application icon.
- Added aligned Now Playing labels, wrapping values, and explicit fallbacks for missing metadata.

## 0.2.0

- Follow the active light or dark Omarchy palette and reload it during playback.
- Display a live, width-adaptive spectrum measured from MPV's decoded stream.
- Use Omarchy's configured default terminal through its native launcher, with system terminal dispatch on other desktops.

## 0.1.0

- Added a responsive Textual station browser and now-playing panel with keyboard and mouse controls.
- Added official SomaFM directory retrieval, quality-ordered playlists, and a local station cache.
- Added headless MPV playback with JSON IPC, stream metadata, volume and mute, and automatic reconnect.
- Added XDG preferences, an original waveform icon, and per-user install and uninstall scripts.
