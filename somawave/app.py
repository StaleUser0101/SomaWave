"""Textual interface for SomaWave."""

import asyncio
from functools import partial
from time import monotonic

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .config import DEFAULT_VIEWS, STREAM_QUALITIES, Preferences, xdg_path
from .player import Player
from .settings import SettingsScreen
from .spectrum import FPS, SpectrumMotion, spectrum_rows
from .station_widgets import STATION_VIEWS, StationList, StationPrompt, StationViews
from .stations import read_cache, refresh_directory
from .theme import load_theme


METADATA_FIELDS = (
    ("station", "Station", "Choose a station"),
    ("description", "Description", "—"),
    ("artist", "Artist", "Unknown"),
    ("track", "Track", "Unknown"),
    ("stream-title", "Stream", ""),
    ("status", "Status", "Stopped"),
    ("bitrate", "Bitrate", "Unknown"),
)


class Spectrum(Static):
    def __init__(self):
        super().__init__("", id="spectrum", markup=False)
        self.motion = SpectrumMotion()
        self.show_peaks = True
        self.display = False

    def show_frame(self, unavailable=False):
        width, height = self.content_size
        image = ""
        if unavailable:
            image = "Spectrum unavailable"
        elif self.motion.active:
            peaks = self.motion.peaks if self.show_peaks else ()
            image = spectrum_rows(self.motion.bars, width, height, peaks)
        if image != self.content:
            self.update(image, layout=False)


class PlayerPanel(VerticalScroll):
    def on_resize(self):
        self.app.call_after_refresh(self.app.fit_spectrum)


class SomaWave(App):
    TITLE = "SomaWave"
    SUB_TITLE = "Independent radio. Terminal style."
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("space", "transport('play')"),
        Binding("s", "transport('stop')"),
        Binding("n", "transport('next')"),
        Binding("p", "transport('previous')"),
        Binding("plus,equals", "adjust_volume(5)"),
        Binding("minus", "adjust_volume(-5)"),
        Binding("m", "mute"),
        Binding("f", "favorite"),
        Binding("left_square_bracket", "station_view(-1)"),
        Binding("right_square_bracket", "station_view(1)"),
        Binding("slash", "search"),
        Binding("escape", "stations"),
        Binding("q", "quit"),
        Binding("o", "settings"),
    ]

    def __init__(self, config_path=None, cache_path=None, player_factory=Player):
        super().__init__()
        palette = load_theme()
        self.register_theme(palette)
        self.theme = palette.name
        self.config_path = config_path or xdg_path("XDG_CONFIG_HOME", ".config") / "settings.json"
        self.cache_path = cache_path or xdg_path("XDG_CACHE_HOME", ".cache") / "channels.json"
        self.prefs = Preferences.load(self.config_path)
        self.player = player_factory(self.render_playback, self.prefs.volume, self.prefs.muted)
        self.player.stream_quality = self.prefs.stream_quality
        self.player.set_reconnect(self.prefs.reconnect)
        self.player.show_spectrum = self.prefs.show_spectrum
        self.stations = []
        self.visible_stations = []
        self.station_view = self.prefs.default_view
        self.playing = None
        self._awaiting_playback = False
        self.selected = self.prefs.station
        self._startup_station = self.prefs.recent[0] if self.prefs.autoplay and self.prefs.recent else ""

    @property
    def main_screen(self):
        return self.screen_stack[0]

    def compose(self) -> ComposeResult:
        with Horizontal(id="banner"):
            yield Static("SomaWave", id="brand")
            yield Static("SomaFM", id="network")
            yield Button("Settings", id="open-settings", compact=True, tooltip="Settings (O)")
        with Container(id="deck"):
            with Vertical(id="directory"):
                yield Label("Stations", classes="section")
                yield StationViews(id="station-views")
                yield Input(placeholder="Filter stations", id="search")
                yield StationList(id="stations")
                empty = Static("", id="station-empty", markup=False)
                empty.display = False
                yield empty
                yield Static("", id="directory-status", markup=False)
                yield Button("Retry", id="retry")
            with PlayerPanel(id="player"):
                yield Label("Now Playing", classes="section")
                for field, label, initial in METADATA_FIELDS:
                    with Horizontal(id=f"{field}-row", classes="metadata-row") as row:
                        row.display = bool(initial)
                        yield Label(f"{label}:", classes="metadata-label")
                        yield Static(initial, id=field, classes="metadata-value", markup=False)
                detail = Static("", id="playback-detail", markup=False)
                detail.display = False
                yield detail
                yield Spectrum()
                with Container(id="transport"):
                    yield Button("‹ Prev", id="previous")
                    yield Button("Play", id="play", variant="primary")
                    yield Button("Stop", id="stop")
                    yield Button("Next ›", id="next")
                with Container(id="volume-controls"):
                    yield Button("−", id="quieter", tooltip="Decrease volume")
                    yield Static("", id="volume")
                    yield Button("+", id="louder", tooltip="Increase volume")
                    yield Button("Mute", id="mute")
        yield Static("↑↓ Browse  ↵ Tune  Space Pause  S Stop  P/N Skip  ± Vol  M Mute  / Find  F Star  [/] Views  O Settings  Q Quit",
                     id="shortcuts", markup=False)

    def on_mount(self):
        self.main_screen.query_one("#stations").focus()
        self.main_screen.query_one("#retry").display = False
        self.render_volume()
        self.update_view_buttons()
        self.load_stations()
        self.set_interval(1, self.refresh_omarchy_theme)
        spectrum = self.main_screen.query_one(Spectrum)
        spectrum.show_peaks = self.prefs.show_peaks
        self.spectrum_timer = spectrum.set_interval(
            1 / FPS, partial(self.draw_spectrum, spectrum), pause=not self.prefs.show_spectrum
        )
        self.call_after_refresh(self.fit_spectrum)

    async def refresh_omarchy_theme(self):
        palette = await asyncio.to_thread(load_theme)
        if self.is_running and palette != self.current_theme:
            self.register_theme(palette)
            if self.theme == palette.name:
                self.refresh_css(animate=False)
            else:
                self.theme = palette.name
            if self.main_screen.query(StationList):
                options = self.main_screen.query_one(StationList)
                for station in self.visible_stations:
                    options.replace_option_prompt(station.id, self.station_label(station))
            self.call_after_refresh(self.fit_spectrum)

    def draw_spectrum(self, spectrum):
        if not spectrum.is_attached or not self.prefs.show_spectrum:
            return
        player = self.player
        playing = player.state.phase == "Playing" and not player.paused
        levels = player.spectrum_levels if playing else ()
        now = monotonic()
        if levels or spectrum.motion.active:
            spectrum.motion.advance(levels, now)
        elif spectrum.motion.updated_at is not None:
            spectrum.motion.updated_at = None
        if spectrum.display:
            deadline = player.spectrum_deadline
            spectrum.show_frame(playing and deadline is not None and now >= deadline and not levels)

    def fit_spectrum(self):
        if not self.is_running or not self.main_screen.query("#spectrum"):
            return
        spectrum = self.main_screen.query_one(Spectrum)
        if not self.prefs.show_spectrum:
            spectrum.display = False
            return
        player = self.main_screen.query_one("#player")
        volume = self.main_screen.query_one("#volume-controls")
        if not volume.region.height:
            return
        # Measure the actual metadata and controls, including any wrapped rows.
        margins = spectrum.styles.margin.height
        occupied = spectrum.region.height + margins if spectrum.display else 0
        controls_end = volume.virtual_region.bottom + volume.styles.margin.bottom
        height = min(8, max(0, player.content_size.height - controls_end + occupied - margins))
        if spectrum.display != bool(height) or (height and spectrum.styles.height.value != height):
            spectrum.styles.height = height
            spectrum.display = bool(height)
            self.call_after_refresh(self.fit_spectrum)

    async def on_unmount(self):
        await self.player.stop()

    def on_resize(self, event):
        self.main_screen.set_class(event.size.width < 68, "narrow")
        self.main_screen.set_class(event.size.height < 25, "short")
        self.main_screen.set_class(event.size.width < 36, "tiny")
        self.main_screen.set_class(event.size.width < 24, "compact")
        self.main_screen.set_class(event.size.width < 18, "icon-settings")
        if self.main_screen.query("#open-settings"):
            self.main_screen.query_one("#open-settings", Button).label = (
                "O" if event.size.width < 18 else "Settings"
            )
        self.call_after_refresh(self.fit_spectrum)

    @work(exclusive=True)
    async def load_stations(self):
        self.directory_message("Loading stations…")
        if not self.stations:
            self.stations = await asyncio.to_thread(read_cache, self.cache_path)
            if self.stations:
                self.populate_stations()
                await self.autoplay_last_station()
        stations, message = await refresh_directory(self.cache_path)
        # A failed refresh should leave the current directory usable even if the cache is gone.
        if not stations and self.stations:
            message = "Using current stations · SomaFM API unavailable"
        else:
            self.stations = stations
        self.populate_stations()
        self.directory_message(message)
        self.main_screen.query_one("#retry").display = bool(message)
        await self.autoplay_last_station(directory_loaded=True)

    async def autoplay_last_station(self, directory_loaded=False):
        if not self._startup_station:
            return
        station = next((item for item in self.stations if item.id == self._startup_station), None)
        if station:
            await self.play(station)
        elif directory_loaded:
            self._startup_station = ""
            self.notify("The last played station is unavailable", severity="warning")

    def directory_message(self, message):
        label = self.main_screen.query_one("#directory-status", Static)
        label.update(message)
        label.display = bool(message)

    def populate_stations(self, preferred=None):
        options = self.main_screen.query_one("#stations", OptionList)
        search = self.main_screen.query_one("#search", Input).value.casefold().strip()
        stations = sorted(self.stations, key=lambda station: station.name.casefold())
        if self.station_view == "favorites":
            stations = [station for station in stations if station.id in self.prefs.favorites]
        elif self.station_view == "recent":
            by_id = {station.id: station for station in stations}
            stations = [by_id[item] for item in self.prefs.recent if item in by_id]
        visible = self.visible_stations = [
            station for station in stations
            if search in f"{station.name} {station.description}".casefold()
        ]
        options.clear_options()
        options.add_options(Option(self.station_label(station), id=station.id) for station in visible)
        index = next((i for i, station in enumerate(visible)
                      if station.id == (preferred or self.selected)), 0)
        options.highlighted = index if visible else None
        if visible:
            options.scroll_to_highlight()

        message = ""
        if not visible:
            if stations and search:
                message = "No matching stations."
            elif self.station_view == "favorites":
                message = ("No favorite stations yet.\nSelect a star to add a station."
                           if not self.prefs.favorites else "Favorite stations are currently unavailable.")
            elif self.station_view == "recent":
                message = ("No recently played stations." if not self.prefs.recent
                           else "Recent stations are currently unavailable.")
        empty = self.main_screen.query_one("#station-empty", Static)
        empty.update(message)
        empty.display = bool(message)

    def station_label(self, station):
        active = self.playing is not None and self.playing.id == station.id
        marker = {"Playing": "▶", "Paused": "Ⅱ"}.get(self.player.state.phase, "◦") if active else " "
        colors = self.current_theme.variables
        accent = colors["station-playing"]
        favorite = station.id in self.prefs.favorites
        return StationPrompt(f"{marker}  {station.name}", f"bold {accent}" if active else "",
                             "★" if favorite else "☆", accent if favorite else colors["station-star"])

    def set_station_view(self, view):
        if view == self.station_view:
            return
        options = self.main_screen.query_one(StationList)
        previous = options.highlighted_option
        self.station_view = view
        self.main_screen.query_one("#search", Input).value = ""
        self.update_view_buttons()
        self.populate_stations(previous.id if previous else None)
        if options.highlighted_option:
            self.remember_station(options.highlighted_option.id)
        options.focus()

    def update_view_buttons(self):
        for button in self.main_screen.query("#station-views Button"):
            button.set_class(button.id == f"view-{self.station_view}", "active-view")

    def action_station_view(self, step):
        views = [key for key, _ in STATION_VIEWS]
        self.set_station_view(views[(views.index(self.station_view) + step) % len(views)])

    def action_favorite(self):
        option = self.main_screen.query_one(StationList).highlighted_option
        if option:
            self.toggle_favorite(option.id)

    @on(StationList.FavoritePressed)
    def favorite_pressed(self, event):
        self.toggle_favorite(event.station_id)

    def toggle_favorite(self, station_id):
        station = next((item for item in self.visible_stations if item.id == station_id), None)
        if station is None:
            return
        if station_id in self.prefs.favorites:
            self.prefs.favorites.remove(station_id)
        else:
            self.prefs.favorites.append(station_id)
        self.persist()
        options = self.main_screen.query_one(StationList)
        if self.station_view == "favorites":
            selected = options.highlighted_option
            self.populate_stations(selected.id if selected else None)
        else:
            options.replace_option_prompt(station_id, self.station_label(station))

    def persist(self):
        try:
            self.prefs.save(self.config_path)
        except OSError:
            self.notify("Preferences could not be saved", severity="warning")

    @on(Input.Changed, "#search")
    def filter_stations(self, event):
        if event.value == event.input.value:
            self.populate_stations()

    @on(Input.Submitted, "#search")
    def focus_results(self):
        self.action_stations()

    @on(OptionList.OptionHighlighted, "#stations")
    def select_station(self, event):
        if (self.screen_stack and self.main_screen.query("#search") and event.option_id is not None
                and event.option_list.highlighted_option is event.option
                and not self.main_screen.query_one("#search", Input).has_focus):
            self.remember_station(event.option_id)

    def remember_station(self, station_id):
        self.selected = station_id
        if self.prefs.station != station_id:
            self.prefs.station = station_id
            self.persist()

    @on(OptionList.OptionSelected, "#stations")
    async def tune(self, event):
        station = next((item for item in self.stations if item.id == event.option_id), None)
        if station:
            await self.play(station)

    async def play(self, station):
        self._startup_station = ""
        self.remember_station(station.id)
        spectrum = self.main_screen.query_one(Spectrum)
        spectrum.motion.reset()
        spectrum.show_frame()
        self.playing = station
        self._awaiting_playback = True
        await self.player.play(station)
        self.render_playback(self.player.state)
        self.populate_stations()

    def render_playback(self, state):
        if not self.is_running or not self.main_screen.query("#status"):
            return
        station = self.playing
        if station and state.phase == "Playing" and self._awaiting_playback:
            self._awaiting_playback = False
            if self.prefs.record_played(station.id):
                self.persist()
                if self.station_view == "recent":
                    self.populate_stations()
        values = {
            "station": station.name if station else "",
            "description": station.description if station else "",
            "artist": state.artist,
            "track": state.title,
            "stream-title": state.stream_title,
            "status": state.phase if state.phase == "Stopped" else f"●  {state.phase}",
            "bitrate": f"{state.bitrate} kbps" if state.bitrate else "",
        }
        layout_changed = False
        for field, _, fallback in METADATA_FIELDS:
            value = values[field] or fallback
            widget = self.main_screen.query_one(f"#{field}", Static)
            if value != widget.content:
                widget.update(value)
                layout_changed = True
            widget.parent.display = bool(value)
        detail = self.main_screen.query_one("#playback-detail", Static)
        if detail.content != state.detail:
            detail.update(state.detail)
            layout_changed = True
        detail.display = bool(state.detail)
        if layout_changed:
            self.call_after_refresh(self.fit_spectrum)
        self.main_screen.query_one("#play", Button).label = (
            "Pause" if station and not self.player.paused and state.phase not in {"Stopped", "Error"} else "Play"
        )
        self.render_station_marker()

    def render_station_marker(self):
        station = self.playing
        if station is None or not self.main_screen.query("#stations"):
            return
        options = self.main_screen.query_one("#stations", OptionList)
        option = next((item for item in options.options if item.id == station.id), None)
        if option is not None:
            prompt = self.station_label(station)
            if option.prompt != prompt:
                options.replace_option_prompt(station.id, prompt)

    def check_action(self, action, parameters):
        if isinstance(self.screen, SettingsScreen):
            return False
        if isinstance(self.focused, Input) and action in {
            "transport", "adjust_volume", "mute", "search", "quit", "favorite", "station_view", "settings",
        }:
            return False
        return super().check_action(action, parameters)

    def action_search(self):
        self.main_screen.query_one("#search").focus()

    def action_stations(self):
        self.main_screen.query_one("#stations").focus()

    def action_settings(self):
        if not isinstance(self.screen, SettingsScreen):
            self.push_screen(SettingsScreen())

    def set_preference(self, name, value):
        if name in {"autoplay", "reconnect", "show_spectrum", "show_peaks"}:
            if type(value) is not bool:
                return
        elif name == "stream_quality":
            if value not in tuple(key for _, key in STREAM_QUALITIES):
                return
        elif name != "default_view" or value not in tuple(key for _, key in DEFAULT_VIEWS):
            return
        if getattr(self.prefs, name) == value:
            return
        setattr(self.prefs, name, value)
        if name == "stream_quality":
            self.player.stream_quality = value
        elif name == "autoplay" and not value:
            self._startup_station = ""
        elif name == "reconnect":
            self.player.set_reconnect(value)
        elif name == "show_spectrum":
            self.player.show_spectrum = value
            spectrum = self.main_screen.query_one(Spectrum)
            if value:
                self.spectrum_timer.resume()
            else:
                self.spectrum_timer.pause()
                self.player.spectrum_levels = ()
            spectrum.motion.reset()
            spectrum.show_frame()
            self.call_after_refresh(self.fit_spectrum)
        elif name == "show_peaks":
            self.main_screen.query_one(Spectrum).show_peaks = value
        self.persist()

    async def action_transport(self, control):
        options = self.main_screen.query_one("#stations", OptionList)
        if control == "stop":
            self._startup_station = ""
            self.playing = None
            self._awaiting_playback = False
            await self.player.stop()
            self.render_playback(self.player.state)
            self.populate_stations()
        elif control == "play":
            if self.playing and self.player.state.phase not in {"Stopped", "Error"}:
                self.player.paused = not self.player.paused
                self.render_playback(self.player.state)
            elif options.highlighted_option is not None:
                station_id = options.highlighted_option.id
                station = next((item for item in self.stations if item.id == station_id), None)
                if station:
                    await self.play(station)
        elif self.visible_stations:
            anchor = self.playing.id if self.playing else self.selected
            step = 1 if control == "next" else -1
            index = next((i for i, item in enumerate(self.visible_stations) if item.id == anchor),
                         -1 if step == 1 else 0)
            await self.play(self.visible_stations[(index + step) % len(self.visible_stations)])

    def action_adjust_volume(self, change):
        self.prefs.volume = max(0, min(100, self.prefs.volume + change))
        self.player.volume = self.prefs.volume
        self.render_volume()
        self.persist()

    def action_mute(self):
        self.prefs.muted = not self.prefs.muted
        self.player.muted = self.prefs.muted
        self.render_volume()
        self.persist()

    def render_volume(self):
        self.main_screen.query_one("#volume", Static).update(f"{self.prefs.volume}%")
        self.main_screen.query_one("#mute", Button).label = "Unmute" if self.prefs.muted else "Mute"

    @on(Button.Pressed)
    async def button_pressed(self, event):
        control = event.button.id
        if control == "retry":
            self.load_stations()
        elif control == "open-settings":
            self.action_settings()
        elif control.startswith("view-"):
            self.set_station_view(control.removeprefix("view-"))
        elif control == "quieter":
            self.action_adjust_volume(-5)
        elif control == "louder":
            self.action_adjust_volume(5)
        elif control == "mute":
            self.action_mute()
        else:
            await self.action_transport(control)
