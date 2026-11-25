"""Settings dialog with immediate preference updates."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Select

from .config import DEFAULT_VIEWS, STREAM_QUALITIES


def app_version():
    # Read the checkout's version when running `python -m somawave` from source.
    try:
        with (Path(__file__).resolve().parents[1] / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
            if project.get("name") == "somawave":
                return project["version"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        return version("somawave")
    except PackageNotFoundError:
        return "development"


class SettingsScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close settings")]

    def compose(self):
        prefs = self.app.prefs
        with Vertical(id="settings-dialog"):
            with VerticalScroll(id="settings-body"):
                yield Label("Settings", id="settings-heading")
                yield Label("Playback", classes="settings-section")
                yield Label("Preferred stream quality")
                yield Select(STREAM_QUALITIES, value=prefs.stream_quality, allow_blank=False,
                             id="stream_quality")
                yield Checkbox("Auto-play last station at startup", prefs.autoplay, id="autoplay", compact=True)
                yield Checkbox("Automatically reconnect", prefs.reconnect, id="reconnect", compact=True)
                yield Label("Appearance", classes="settings-section")
                yield Checkbox("Show spectrum analyzer", prefs.show_spectrum, id="show_spectrum", compact=True)
                yield Checkbox("Show spectrum peak markers", prefs.show_peaks, id="show_peaks",
                               compact=True, disabled=not prefs.show_spectrum)
                yield Label("Default station view")
                yield Select(DEFAULT_VIEWS, value=prefs.default_view, allow_blank=False, id="default_view")
            with Horizontal(id="settings-footer"):
                yield Label(f"SomaWave {app_version()}", id="settings-version")
                yield Button("Close", id="close-settings", compact=True)

    @on(Select.Changed)
    @on(Checkbox.Changed)
    def setting_changed(self, event):
        event.stop()
        self.app.set_preference(event.control.id, event.value)
        if event.control.id == "show_spectrum":
            self.query_one("#show_peaks", Checkbox).disabled = not event.value

    @on(Button.Pressed, "#close-settings")
    def close_pressed(self, event):
        event.stop()
        self.dismiss()
