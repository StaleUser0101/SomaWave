# SomaWave development
- Treat `assets/somawave.svg` as the authoritative reference for the application icon. Keep the terminal header text-only.
- Treat the v1.0.0 stable release as the visual and functional baseline, including the approved v0.4.0 interface and spectrum tuning.

- SomaWave is a terminal-only SomaFM player for Linux. Use the official station API and MPV JSON IPC.
- Keep SomaWave compatible with any terminal emulator supported by Textual. Never require or install a specific emulator.
- Use Omarchy's native TUI launcher when available so the desktop entry follows the configured default terminal. Fall back to the system's terminal dispatch on other desktops.
- Integrate with existing Omarchy components. Do not change its default applications, terminal settings, themes, keybindings, or system configuration.
- Use Python 3, Textual, and asynchronous network and playback operations. Keep UI, playback, stations, preferences, and theme separate.
- Install Python dependencies in a virtual environment only. Check for existing dependencies first. Ask before running the installer, using sudo, or modifying system configuration.
- Use XDG locations for configuration, cache, and per-user installation. Preserve preferences on uninstall by default.
- Keep the interface responsive, usable with keyboard and mouse, and clear about selection, focus, playback state, and failures. Follow the active Omarchy palette without writing theme files or changing terminal opacity. Use the original charcoal and teal palette as the fallback and avoid emoji.
- Render spectrum bars only from SomaWave's decoded audio. Keep analysis off the UI path, let bars decay on pause and stop, and keep playback usable if analysis is unavailable. Never capture microphone or system-wide audio.
- Keep dependencies minimal and scope limited to SomaFM. Maintain version metadata, changelog, and setup instructions.
- Run automated tests, including Textual pilot tests for UI behavior where practical. Record verification gaps.
- Commit locally when requested. Do not publish or push without a new explicit request.
