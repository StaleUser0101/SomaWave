import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from textual.widgets import Input, OptionList, Static

from somawave.app import SomaWave
from somawave.config import Preferences
from somawave.player import Playback, Player
from somawave.spectrum import BAND_COUNT
from somawave.stations import Station


class PreviewPlayer(Player):
    async def play(self, station):
        self.paused = False
        self.update(Playback("Playing", "Test artist", "Test track", 128))


STATIONS = [
    Station("groove", "Groove Salad", "Downtempo", ()),
    Station("drone", "Drone Zone", "Ambient", ()),
]


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = Path(directory) / "settings.json"
        self.cache = Path(directory) / "channels.json"
        self.enterContext(patch("somawave.app.refresh_directory", AsyncMock(
            return_value=(STATIONS, ""),
        )))
        self.app = SomaWave(self.settings, self.cache, PreviewPlayer)

    async def test_search_navigation_and_transport(self):
        async with self.app.run_test(size=(100, 32)) as pilot:
            await self.app.workers.wait_for_complete()
            await pilot.press("enter")
            self.assertEqual(self.app.playing.id, "drone")
            await pilot.press("space", "equals", "m")
            self.assertTrue(self.app.player.paused)
            self.assertEqual(self.app.player.volume, 75)
            self.assertTrue(self.app.player.muted)
            await pilot.press("/", "s", "p", "n", "q", "m", "-", "=")
            self.assertEqual(self.app.query_one(Input).value, "spnqm-=")
            self.assertEqual(self.app.player.state.phase, "Playing")
            self.assertEqual(self.app.query_one(OptionList).option_count, 0)
            await pilot.press("escape", "p")
            self.assertEqual(self.app.playing.id, "drone")
            await pilot.press("/", "g", "r", "o", "o", "v", "e", "escape", "p")
            self.assertEqual(self.app.playing.id, "groove")
            await pilot.press("s")
            self.assertIsNone(self.app.playing)
            self.assertEqual(Preferences.load(self.settings),
                             Preferences("groove", 75, True, recent=["groove", "drone"]))
            await pilot.press("q")

    async def test_mouse_and_resizing(self):
        async with self.app.run_test(size=(110, 35)) as pilot:
            await self.app.workers.wait_for_complete()
            options = self.app.query_one(OptionList)
            self.assertTrue(await pilot.click(options, offset=(4, 0)))
            self.assertEqual(self.app.playing.id, "drone")
            self.assertTrue(await pilot.click("#louder"))
            self.assertEqual(self.app.player.volume, 75)
            for width, height in [(100, 30), (55, 24), (30, 18)]:
                await pilot.resize_terminal(width, height)
                for selector in ("#directory", "#player"):
                    region = self.app.query_one(selector).region
                    self.assertGreater(region.width, 0)
                    self.assertGreater(region.height, 0)
                    self.assertLessEqual(region.right, width)
                    self.assertLessEqual(region.bottom, height)
                mute = self.app.query_one("#mute")
                mute.scroll_visible(immediate=True, animate=False)
                await pilot.pause()
                self.assertTrue(await pilot.click(mute))
            self.assertTrue(self.app.player.muted)
        self.assertEqual(self.app.player.state.phase, "Stopped")

    async def test_remembers_selected_station(self):
        Preferences("groove", 35, True).save(self.settings)
        app = SomaWave(self.settings, self.cache, PreviewPlayer)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app.query_one(OptionList).highlighted_option.id, "groove")
            self.assertEqual(app.player.volume, 35)
            self.assertTrue(app.player.muted)
            self.assertIsNone(app.playing)

    async def test_failed_directory_refresh_preserves_loaded_stations(self):
        async with self.app.run_test() as pilot:
            await self.app.workers.wait_for_complete()
            with patch("somawave.app.refresh_directory", AsyncMock(return_value=([], "offline"))):
                await self.app.load_stations().wait()
            await pilot.pause()
            self.assertEqual(self.app.stations, STATIONS)
            self.assertIn("Using current stations", self.app.query_one("#directory-status").content)

    async def test_metadata_layout(self):
        async with self.app.run_test(size=(100, 35)) as pilot:
            await self.app.workers.wait_for_complete()
            await pilot.press("enter")

            def value(field):
                return self.app.query_one(f"#{field}", Static).content

            self.assertEqual(value("artist"), "Test artist")
            self.assertEqual(value("track"), "Test track")
            self.assertEqual(value("bitrate"), "128 kbps")
            self.app.player.update(Playback("Playing", stream_title="Live from the studio"))
            await pilot.pause()
            self.assertEqual([value(field) for field in ("artist", "track", "bitrate")], ["Unknown"] * 3)
            self.assertEqual(value("stream-title"), "Live from the studio")
            long_value = "A long title with enough words to wrap onto multiple terminal rows " * 3
            long_artist = ("New artist with a long name " * 4).strip()
            self.app.playing = replace(self.app.playing, description=long_value.strip())
            self.app.player.update(Playback("Playing", long_artist, long_value.strip(), 192))
            for width, height in ((100, 35), (55, 24), (30, 18)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                player = self.app.query_one("#player")
                brand = self.app.query_one("#brand")
                banner = self.app.query_one("#banner")
                network = self.app.query_one("#network")
                self.assertEqual([widget.id for widget in banner.children],
                                 ["brand", "network", "open-settings"])
                self.assertEqual(banner.region.height, 1)
                self.assertEqual(brand.region.y, network.region.y)
                self.assertEqual(brand.region.right + 1, network.region.x)
                for field in ("description", "artist", "track"):
                    value_widget = self.app.query_one(f"#{field}")
                    self.assertGreater(value_widget.region.height, 1)
                    self.assertLessEqual(value_widget.region.right, player.region.right)
                    self.assertEqual(value_widget.region.x, self.app.query_one("#station").region.x)
            self.assertEqual(value("artist"), long_artist)
            self.assertFalse(self.app.query_one("#stream-title-row").display)
            await pilot.resize_terminal(14, 18)
            self.assertFalse(network.display)
            self.assertGreaterEqual(brand.region.width, len("SomaWave"))

    async def test_station_change_resets_spectrum(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self.app.workers.wait_for_complete()
            await pilot.press("enter")
            spectrum = self.app.query_one("#spectrum")
            spectrum.motion.advance((0.9,) * BAND_COUNT, 1.0)
            spectrum.show_frame()
            self.assertTrue(spectrum.content)
            await pilot.press("n")
            self.assertEqual(spectrum.content, "")
            self.assertFalse(any(spectrum.motion.bars))
            self.assertFalse(any(spectrum.motion.peaks))

    async def test_favorites_mouse_keyboard_filter_and_persistence(self):
        async with self.app.run_test(size=(110, 35)) as pilot:
            await self.app.workers.wait_for_complete()
            options = self.app.query_one(OptionList)
            self.assertEqual([option.id for option in options.options], ["drone", "groove"])
            self.assertTrue(await pilot.click("#view-favorites"))
            self.assertEqual(self.app.query_one("#station-empty").content,
                             "No favorite stations yet.\nSelect a star to add a station.")
            await pilot.press("[", "[")
            self.assertEqual(self.app.query_one("#station-empty").content,
                             "No recently played stations.")
            await pilot.press("]")
            self.assertEqual(self.app.station_view, "all")
            width = options.scrollable_content_region.width
            self.assertTrue(await pilot.click(options, offset=(width - 2, 1)))
            self.assertEqual(self.app.prefs.favorites, ["groove"])
            self.assertEqual(options.highlighted_option.id, "drone")
            self.assertIsNone(self.app.playing)
            await pilot.press("f", "enter", "]")
            self.assertEqual(self.app.playing.id, "drone")
            self.assertEqual([option.id for option in options.options], ["drone", "groove"])
            self.assertEqual(options.highlighted_option.id, "drone")
            await pilot.press("/", "g", "r", "o", "o", "v", "e")
            self.assertEqual([option.id for option in options.options], ["groove"])
            await pilot.press("escape")
            self.assertTrue(await pilot.click("#view-recent"))
            self.assertEqual(self.app.query_one(Input).value, "")
            self.assertEqual(options.highlighted_option.id, "drone")
            await pilot.press("/", "f", "[", "]")
            self.assertEqual(self.app.query_one(Input).value, "f[]")
            self.assertEqual(self.app.station_view, "recent")
            self.assertEqual(self.app.prefs.favorites, ["groove", "drone"])
            self.assertTrue(await pilot.click("#view-favorites"))
            await pilot.press("f")
            self.assertEqual([option.id for option in options.options], ["groove"])
            self.assertEqual(self.app.playing.id, "drone")
            self.assertEqual(self.app.player.state.phase, "Playing")

        app = SomaWave(self.settings, self.cache, PreviewPlayer)
        async with app.run_test(size=(80, 30)) as pilot:
            await app.workers.wait_for_complete()
            self.assertEqual(app.station_view, "all")
            self.assertEqual(app.prefs.favorites, ["groove"])
            self.assertEqual(app.prefs.recent, ["drone"])
            await pilot.press("]")
            self.assertEqual(app.query_one(OptionList).highlighted_option.id, "groove")

    async def test_recent_records_success_only_and_reorders(self):
        class DeferredPlayer(Player):
            async def play(self, station):
                self.update(Playback("Connecting"))

        app = SomaWave(self.settings, self.cache, DeferredPlayer)
        async with app.run_test(size=(110, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("down")
            self.assertEqual(app.prefs.recent, [])
            await pilot.press("enter")
            app.player.update(Playback("Error"))
            self.assertEqual(app.prefs.recent, [])
            await pilot.press("n")
            app.player.update(Playback("Playing"))
            self.assertEqual(app.prefs.recent, ["drone"])
            await pilot.press("n")
            app.player.update(Playback("Playing"))
            await pilot.press("n")
            app.player.update(Playback("Playing"))
            self.assertEqual(app.prefs.recent, ["drone", "groove"])
            await pilot.press("[")
            options = app.query_one(OptionList)
            self.assertEqual([option.id for option in options.options], ["drone", "groove"])
            await pilot.press("/", "a", "m", "b")
            self.assertEqual([option.id for option in options.options], ["drone"])
            await pilot.press("escape", "f")
            self.assertEqual(app.prefs.favorites, ["drone"])
            self.assertEqual(app.playing.id, "drone")

    async def test_view_buttons_resize_and_keyboard_focus(self):
        async with self.app.run_test(size=(120, 36)) as pilot:
            await self.app.workers.wait_for_complete()
            for size in ((120, 36), (80, 28), (55, 24), (30, 18)):
                await pilot.resize_terminal(*size)
                await pilot.pause()
                buttons = list(self.app.query("#station-views Button"))
                self.assertEqual(len({button.region.width for button in buttons}), 1)
                for button in buttons:
                    self.assertLessEqual(len(button.label.plain), button.region.width)
                    self.assertLessEqual(button.region.right, size[0])
            self.app.query_one("#view-recent").focus()
            await pilot.press("enter")
            self.assertEqual(self.app.station_view, "recent")
            self.assertIsNone(self.app.playing)

    async def test_favorite_star_inset_in_every_view(self):
        async with self.app.run_test(size=(110, 35)) as pilot:
            await self.app.workers.wait_for_complete()
            self.app.stations = [replace(STATIONS[1], name="Drone Zone " * 12), STATIONS[0]]
            self.app.prefs.favorites = ["drone", "groove"]
            self.app.prefs.recent = ["drone", "groove"]
            self.app.populate_stations()
            options = self.app.query_one(OptionList)
            for size in ((110, 35), (30, 24)):
                await pilot.resize_terminal(*size)
                for _ in range(3):
                    await pilot.pause()
                    region = options.scrollable_content_region
                    self.assertTrue(options.render_line(0).text.endswith("… ★ "))
                    for y in (region.y, region.y + 1):
                        star = self.app.screen.get_style_at(region.right - 2, y)
                        padding = self.app.screen.get_style_at(region.right - 1, y)
                        self.assertTrue(star.meta.get("favorite_star"))
                        self.assertFalse(padding.meta.get("favorite_star"))
                    await pilot.press("]")
