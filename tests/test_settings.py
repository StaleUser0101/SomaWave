import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from textual.widgets import Button, Checkbox, Select

from somawave.app import SomaWave, Spectrum
from somawave.config import Preferences
from somawave.player import Playback, Player
from somawave.settings import SettingsScreen
from somawave.spectrum import BAND_COUNT
from somawave.stations import Station, parse_directory


class SettingsStorageTests(unittest.TestCase):
    def test_migration_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            old = {"station": "a", "volume": 25, "muted": True, "favorites": ["a"], "recent": ["a"]}
            settings.write_text(json.dumps(old))
            expected = Preferences("a", 25, True, ["a"], ["a"])
            self.assertEqual(Preferences.load(settings), expected)
            settings.write_text(json.dumps({
                **old, "autoplay": 1, "reconnect": "false", "show_spectrum": None,
                "show_peaks": [], "stream_quality": ["bogus"], "default_view": "bogus",
            }))
            self.assertEqual(Preferences.load(settings), expected)

    def test_quality_order_and_missing_tiers(self):
        base = "https://api.somafm.com"
        station = parse_directory({"channels": [{"id": "wave2", "title": "Wave", "playlists": [
            {"url": f"{base}/wave2.pls", "format": "mp3", "quality": "highest"},
            {"url": f"{base}/wave2320.pls", "format": "mp3", "quality": "highest"},
            {"url": f"{base}/wave2130.pls", "format": "aac", "quality": "highest"},
            {"url": f"{base}/wave232.pls", "format": "aacp", "quality": "low"},
        ]}]})[0]
        self.assertEqual(station.playlists_for("highest")[0], f"{base}/wave2320.pls")
        self.assertEqual(station.playlists_for("standard")[0], f"{base}/wave2.pls")
        self.assertEqual(station.playlists_for("low")[0], f"{base}/wave232.pls")
        self.assertEqual(set(station.playlists_for("low")), set(station.playlists))
        single = Station("x", "Single", "", (f"{base}/known.pls",))
        for preference in ("highest", "standard", "low"):
            self.assertEqual(single.playlists_for(preference), single.playlists)


class SettingsPlayer(Player):
    async def play(self, station):
        self.started = (station.id, self.volume, self.muted, self.stream_quality)
        self.update(Playback("Playing", "Artist", "Title", 128))
        self.spectrum_levels = (0.5,) * BAND_COUNT


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = self.root / "prefs"
        self.stations = [Station("a", "Alpha", "", ()), Station("b", "Beta", "", ())]
        self.enterContext(patch("somawave.app.refresh_directory", AsyncMock(return_value=(self.stations, ""))))

    def make_app(self, prefs):
        prefs.save(self.settings)
        return SomaWave(self.settings, self.root / "cache", SettingsPlayer)

    async def test_settings_persist_during_playback_and_restore_focus(self):
        app = self.make_app(Preferences(favorites=["a"], recent=["b"]))
        async with app.run_test(size=(100, 36)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            with patch.object(app.prefs, "save", wraps=app.prefs.save) as save:
                await pilot.press("o")
                save.assert_not_called()
            self.assertIsInstance(app.screen, SettingsScreen)
            self.assertEqual(app.screen.query_one("#settings-version").content, "SomaWave 1.0.2")
            started = app.player.started
            await pilot.press("n", "s", "p", "f", "q", "m", "=")
            self.assertEqual(app.player.started, started)
            self.assertEqual(app.player.state.phase, "Playing")
            self.assertEqual(app.prefs.volume, 70)
            self.assertFalse(app.player.muted)
            spectrum = app.main_screen.query_one(Spectrum)
            spectrum.motion.bars[:] = [0.3] * BAND_COUNT
            spectrum.motion.peaks[:] = [0.8] * BAND_COUNT
            spectrum.motion.active = True
            spectrum.show_frame()
            self.assertIn("─", spectrum.content)
            await pilot.click("#show_peaks")
            self.assertNotIn("─", spectrum.content)
            await pilot.click("#show_spectrum")
            modal = app.screen
            self.assertTrue(modal.query_one("#show_peaks", Checkbox).disabled)
            self.assertFalse(app.main_screen.query_one(Spectrum).display)
            for field in ("stream_quality", "default_view"):
                modal.query_one(f"#{field}", Select).focus()
                await pilot.press("enter", "down", "down", "enter")
            await pilot.click("#autoplay")
            await pilot.click("#reconnect")
            await pilot.pause()
            self.assertEqual(app.station_view, "all")
            self.assertEqual(app.player.started, started)
            self.assertEqual(Preferences.load(self.settings), Preferences(
                "a", favorites=["a"], recent=["a", "b"], stream_quality="low",
                autoplay=True, reconnect=False, show_spectrum=False, show_peaks=False,
                default_view="recent",
            ))
            app.player.update(Playback("Playing", "Changed", "New title", 64))
            await pilot.press("escape")
            self.assertIs(app.screen, app.main_screen)
            self.assertEqual(app.focused.id, "stations")
            self.assertEqual(app.main_screen.query_one("#track").content, "New title")
            self.assertTrue(await pilot.click("#open-settings"))
            await pilot.click("#show_spectrum")
            self.assertFalse(app.screen.query_one("#show_peaks", Checkbox).disabled)
            self.assertFalse(app.screen.query_one("#show_peaks", Checkbox).value)
            await pilot.click("#close-settings")
            self.assertIs(app.screen, app.main_screen)
            self.assertTrue(app.main_screen.query_one(Spectrum).display)
            self.assertFalse(app.main_screen.query_one(Spectrum).show_peaks)
            await pilot.press("n")
            self.assertEqual(app.player.started[-1], "low")

    async def test_autoplay_uses_successful_history_and_default_view(self):
        prefs = Preferences("b", 21, True, favorites=["b"], recent=["a"], autoplay=True,
                            stream_quality="standard", default_view="favorites")
        app = self.make_app(prefs)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            self.assertEqual(app.player.started, ("a", 21, True, "standard"))
            self.assertEqual(app.station_view, "favorites")
            self.assertEqual(app.main_screen.query_one("#stations").highlighted_option.id, "b")
        prefs.recent = ["unavailable"]
        missing = self.make_app(prefs)
        async with missing.run_test():
            await missing.workers.wait_for_complete()
            self.assertIsNone(missing.playing)
            self.assertEqual(missing.prefs.recent, ["unavailable"])

    async def test_settings_resize_and_live_theme_reload(self):
        path = self.root / "colors.toml"
        path.write_text('background="#151B23"\nforeground="#E6EDF3"\n')
        self.enterContext(patch("somawave.theme.theme_paths", return_value=(path,)))
        app = self.make_app(Preferences())
        async with app.run_test(size=(95, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("o")
            path.write_text('background="#FEFEFE"\nforeground="#222222"\nmode="light"\n')
            async with asyncio.timeout(3):
                while app.current_theme.dark:
                    await asyncio.sleep(0.05)
            await pilot.pause()
            dialog = app.screen.query_one("#settings-dialog")
            self.assertEqual(dialog.styles.background.hex, app.current_theme.panel)
            for width, height in ((40, 18), (28, 13), (16, 12)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                self.assertLessEqual(dialog.region.right, width)
                self.assertLessEqual(dialog.region.bottom, height)
                close = app.screen.query_one("#close-settings", Button)
                self.assertGreater(app.screen.query_one("#settings-body").max_scroll_y, 0)
                close.focus()
                await pilot.pause()
                self.assertLessEqual(close.region.bottom, height)
                if width == 28:
                    app.screen.query_one("#stream_quality", Select).focus()
                    await pilot.press("enter", "down", "enter")
                    self.assertEqual(app.prefs.stream_quality, "standard")
            await pilot.press("escape")
            self.assertEqual(app.main_screen.query_one("#open-settings", Button).label.plain, "O")
            self.assertTrue(await pilot.click("#open-settings"))
