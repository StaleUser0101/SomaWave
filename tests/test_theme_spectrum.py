import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from textual.color import Color

from somawave.app import SomaWave, Spectrum
from somawave.player import Playback
from somawave.spectrum import BAND_COUNT, SpectrumMotion, display_level, spectrum_rows
from somawave.stations import Station
from somawave.theme import SOMAWAVE, contrast, load_theme, parse_theme

DARK = 'background = "#151B23"\nforeground = "#E6EDF3"\naccent = "#64D8BB"\n'
LIGHT = ('mode = "light"\nbackground = "#FAF5E8"\nforeground = "#383025"\n'
         'accent = "#FFEEDD"\nselection = "#EADCBE"\nmuted = "#F5EEDF"\n')


class ThemeTests(unittest.TestCase):
    def test_legacy_light_mode_and_text_contrast(self):
        palette = parse_theme(LIGHT.replace('mode = "light"\n', ""), True)
        self.assertFalse(palette.dark)
        self.assertEqual(palette.background, "#FAF5E8")
        panel = Color.parse(palette.panel)
        for text in (palette.foreground, palette.accent, palette.variables["muted-text"]):
            self.assertGreaterEqual(contrast(Color.parse(text), panel), 4.5)

    def test_invalid_or_missing_theme_uses_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "colors.toml"
            with patch("somawave.theme.theme_paths", return_value=(path,)):
                self.assertEqual(load_theme(), SOMAWAVE)
                path.write_text("malformed", encoding="utf-8")
                self.assertEqual(load_theme(), SOMAWAVE)

    def test_fractional_bars_fit_panel(self):
        self.assertEqual(spectrum_rows((0.5, 0.25), 3, 1), "▄ ▂")
        self.assertEqual(spectrum_rows((0.25,), 1, 2, (0.9,)), "─\n▄")
        levels = (0.8,) * BAND_COUNT
        for width in range(1, 301):
            rows = spectrum_rows(levels, width, 5).splitlines()
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(len(row) == width for row in rows))
            bottom = rows[-1]
            bars = bottom.strip().split(" ")
            self.assertLessEqual(len(bars), BAND_COUNT)
            self.assertTrue(all(bars))
            self.assertEqual(len(set(map(len, bars))), 1)
            left = width - len(bottom.lstrip())
            right = width - len(bottom.rstrip())
            self.assertLessEqual(abs(left - right), 1)
            self.assertLessEqual(left + right, max(2, len(bars[0])))
        self.assertEqual(spectrum_rows(levels, 80, 1)[-1], " ")
        self.assertEqual(len(spectrum_rows(levels, 80, 1).strip().split(" ")), BAND_COUNT)
        self.assertEqual(spectrum_rows((), 40, 5), "")


class SpectrumMotionTests(unittest.TestCase):
    def test_time_constants_and_independent_bands(self):
        results = []
        for fps in (10, 30, 60):
            motion = SpectrumMotion()
            motion.updated_at = 0
            loud = (1.0, 0.4) + (0.0,) * (BAND_COUNT - 2)
            motion.advance(loud, 0.05)
            self.assertAlmostEqual(motion.bars[0], 0.63212, places=4)
            self.assertAlmostEqual(motion.bars[1], motion.bars[0] * 0.4)
            self.assertEqual(motion.bars[2], 0)
            for tick in range(1, fps + 1):
                motion.advance((), 0.05 + 0.35 * tick / fps)
            results.append(motion.bars[0])
        for level in results:
            self.assertAlmostEqual(level, 0.23254, places=4)

    def test_peak_hold_decay_and_reset(self):
        motion = SpectrumMotion()
        motion.updated_at = 0
        loud = (1.0,) * BAND_COUNT
        silent = (0.0,) * BAND_COUNT
        motion.advance(loud, 0.1)
        peak = motion.peaks[0]
        motion.advance(silent, 0.4)
        self.assertAlmostEqual(motion.peaks[0], peak)
        motion.advance(silent, 1.0)
        self.assertAlmostEqual(motion.peaks[0], peak / 2.71828, places=5)
        motion.advance((), 1.034)
        self.assertEqual(motion.peaks[0], 0)
        self.assertGreater(motion.bars[0], 0)
        motion.reset()
        self.assertFalse(motion.active)
        self.assertFalse(any(motion.bars))

    def test_fixed_level_mapping_preserves_quiet_audio(self):
        self.assertEqual(display_level(-70), 0)
        self.assertEqual(display_level(-8), 1)
        self.assertLess(display_level(-45), 0.3)
        self.assertGreater(display_level(-18), 0.7)


class LiveInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_theme_reload_pause_and_resize(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "colors.toml"
        path.write_text(DARK, encoding="utf-8")
        self.enterContext(patch("somawave.theme.theme_paths", return_value=(path,)))
        stations = [Station("drone", "Drone Zone", "Ambient", ())]
        self.enterContext(patch("somawave.app.refresh_directory", AsyncMock(return_value=(stations, ""))))
        app = SomaWave(directory / "settings", directory / "cache")
        async with app.run_test(size=(100, 35)) as pilot:
            await app.workers.wait_for_complete()
            self.assertEqual(app.current_theme.background, "#151B23")
            await pilot.press("f", "]")
            star = app.query_one("#stations").highlighted_option.prompt
            self.assertEqual(star.star, "★")
            self.assertEqual(star.star_color, app.current_theme.variables["station-playing"])
            player = app.player
            player.update(Playback("Playing"))
            player.spectrum_levels = (0.5,) * BAND_COUNT
            await pilot.pause(0.1)
            widget = app.query_one(Spectrum)
            wide = len(widget.content.splitlines()[-1])
            self.assertEqual(wide, widget.content_size.width)
            self.assertIn("█", widget.content)

            path.write_text(LIGHT, encoding="utf-8")
            async with asyncio.timeout(3):
                while app.current_theme.dark:
                    await asyncio.sleep(0.05)
            await pilot.pause()
            self.assertEqual(app.screen.styles.background.hex, "#FAF5E8")
            self.assertEqual(widget.styles.color.hex, app.current_theme.accent)
            self.assertEqual(app.query_one("#brand").styles.color.hex, app.current_theme.accent)
            self.assertEqual(app.query_one("#view-favorites").styles.background.hex,
                             app.current_theme.accent)
            star = app.query_one("#stations").highlighted_option.prompt
            self.assertEqual(star.star_color, app.current_theme.variables["station-playing"])
            self.assertIs(app.player, player)
            self.assertEqual(player.state.phase, "Playing")
            path.write_text(LIGHT.replace("#FAF5E8", "#FFFFFF"), encoding="utf-8")
            await app.refresh_omarchy_theme()
            self.assertEqual(app.screen.styles.background.hex, "#FFFFFF")

            await pilot.resize_terminal(100, 27)
            await pilot.pause(0.1)
            self.assertGreater(widget.region.height, 0)
            self.assertLess(widget.region.height, 8)
            self.assertEqual(app.query_one("#player").max_scroll_y, 0)
            for terminal_width, terminal_height in ((150, 38), (120, 38), (40, 52)):
                await pilot.resize_terminal(terminal_width, terminal_height)
                await pilot.pause(0.1)
                bottom = widget.content.splitlines()[-1]
                self.assertEqual(len(bottom), widget.content_size.width)
                bars = bottom.strip().split(" ")
                self.assertTrue(all(bars))
                self.assertEqual(len(set(map(len, bars))), 1)
            self.assertLess(widget.content_size.width, wide)
            player.paused = True
            await pilot.pause(0.1)
            self.assertTrue(widget.motion.active)
            self.assertFalse(any(widget.motion.peaks))
            async with asyncio.timeout(3):
                while widget.content:
                    await asyncio.sleep(0.05)
            player.paused = False
            await pilot.pause(0.2)
            self.assertIn("█", widget.content)
            player.update(Playback())
            await pilot.pause(0.1)
            self.assertTrue(widget.motion.active)
            async with asyncio.timeout(3):
                while widget.content:
                    await asyncio.sleep(0.05)
