import asyncio
import json
import math
from array import array
from http.client import IncompleteRead
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from somawave.config import Preferences, xdg_path
from somawave.player import IPC, Player
from somawave.stations import Station, refresh_directory


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_and_cache_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channels.json"
            base = "https://api.somafm.com"
            payload = {"channels": [{"id": "example", "title": "Example", "playlists": [
                {"url": f"{base}/low.pls", "quality": "low"},
                {"url": "https://example.net/unofficial.pls", "quality": "highest"},
                {"url": f"{base}/best.pls", "quality": "highest"},
            ]}]}
            with patch("somawave.stations.fetch_directory", return_value=payload):
                stations, message = await refresh_directory(path)
            self.assertEqual(message, "")
            self.assertEqual(stations[0].playlists, (f"{base}/best.pls", f"{base}/low.pls"))
            with patch("somawave.stations.fetch_directory", side_effect=IncompleteRead(b"partial")):
                cached, message = await refresh_directory(path)
                self.assertEqual(cached, stations)
                self.assertIn("cached", message)
                path.write_text("broken", encoding="utf-8")
                self.assertEqual((await refresh_directory(path))[0], [])

    def test_preferences_and_xdg(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}):
                path = xdg_path("XDG_CONFIG_HOME", ".config") / "settings.json"
            self.assertEqual(path, Path(directory) / "somawave/settings.json")
            Preferences("groove", 20, True).save(path)
            self.assertEqual(Preferences.load(path), Preferences("groove", 20, True))
            path.write_text('{"volume": 101}', encoding="utf-8")
            self.assertEqual(Preferences.load(path).volume, 100)

    def test_atomic_write_failure_preserves_previous_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(Preferences.load(path), Preferences())
            path.write_text('{"volume":')
            self.assertEqual(Preferences.load(path), Preferences())
            Preferences("groove", 20, True).save(path)
            before = path.read_bytes()
            with patch("somawave.config.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    Preferences("drone").save(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_station_preferences_migrate_deduplicate_and_limit_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            old = {"station": "groove", "volume": 35, "muted": True}
            path.write_text(json.dumps(old), encoding="utf-8")
            self.assertEqual(Preferences.load(path), Preferences("groove", 35, True))

            path.write_text(json.dumps({
                **old, "favorites": ["groove", None, "", "groove", "unknown"],
                "recent": "malformed",
            }), encoding="utf-8")
            prefs = Preferences.load(path)
            self.assertEqual(prefs.favorites, ["groove", "unknown"])
            self.assertEqual(prefs.recent, [])
            for i in range(12):
                prefs.record_played(str(i))
            prefs.record_played("5")
            self.assertFalse(prefs.record_played("5"))
            self.assertEqual(prefs.recent, ["5", "11", "10", "9", "8", "7", "6", "4", "3", "2"])
            prefs.save(path)
            self.assertEqual(Preferences.load(path), prefs)
            path.write_text(json.dumps({
                "favorites": 123, "recent": ["5", "5", *map(str, range(20))],
            }), encoding="utf-8")
            loaded = Preferences.load(path)
            self.assertEqual(loaded.favorites, [])
            self.assertEqual(len(loaded.recent), 10)
            self.assertEqual(loaded.recent.count("5"), 1)


class PlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_disable_and_startup_fallback(self):
        player = Player(lambda state: None)
        station = Station("test", "Test", "", ("preferred", "fallback"))
        player.set_reconnect(False)
        player._play_url = AsyncMock(side_effect=OSError("offline"))
        await player.play(station)
        await asyncio.wait_for(player._session, 1)
        self.assertEqual(player._play_url.await_count, 2)
        self.assertEqual(player.state.phase, "Error")

        async def disconnected(url):
            player._attempt_played = True
            raise OSError("stream ended")

        player._play_url = AsyncMock(side_effect=disconnected)
        await player.play(station)
        await asyncio.wait_for(player._session, 1)
        self.assertEqual(player._play_url.await_count, 1)
        self.assertIn("Stream disconnected", player.state.detail)

        player.set_reconnect(True)
        await player.play(station)
        await asyncio.sleep(0)
        self.assertEqual(player.state.phase, "Reconnecting")
        player.set_reconnect(False)
        await asyncio.wait_for(player._session, 0.5)
        self.assertEqual(player.state.phase, "Error")
        self.assertEqual(player._play_url.await_count, 2)
        await player.stop()

    async def test_station_change_cancels_pending_retry(self):
        player = Player(lambda state: None)
        player._play_url = AsyncMock(side_effect=OSError("offline"))
        await player.play(Station("a", "Alpha", "", ("alpha",)))
        await asyncio.sleep(0)
        pending = player._session
        self.assertEqual(player.state.phase, "Reconnecting")
        await player.play(Station("b", "Beta", "", ("beta",)))
        await asyncio.sleep(0)
        self.assertTrue(pending.cancelled())
        self.assertEqual([call.args[0] for call in player._play_url.await_args_list], ["alpha", "beta"])
        pending = player._session
        await player.stop()
        self.assertTrue(pending.cancelled())
        self.assertEqual(player.state.phase, "Stopped")

    async def test_retry_rotates_playlists_and_stops(self):
        player = Player(lambda state: None)
        player._play_url = AsyncMock(side_effect=OSError("offline"))
        await player.play(Station("test", "Test", "", ("best", "fallback")))
        try:
            async with asyncio.timeout(3):
                while player._play_url.await_count < 2:
                    await asyncio.sleep(0.02)
            self.assertEqual(player.state.phase, "Reconnecting")
            self.assertEqual([call.args[0] for call in player._play_url.await_args_list],
                             ["best", "fallback"])
        finally:
            await player.stop()
        self.assertEqual(player.state.phase, "Stopped")

    async def test_cancelled_station_change_leaves_cleanup_owned_by_player(self):
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_allowed = asyncio.Event()

        async def playback(url):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cleanup_started.set()
                await cleanup_allowed.wait()

        player = Player(lambda state: None)
        player._play_url = AsyncMock(side_effect=playback)
        station = Station("test", "Test", "", ("test",))
        await player.play(station)
        await asyncio.wait_for(entered.wait(), 1)
        switch = asyncio.create_task(player.play(station))
        try:
            await asyncio.wait_for(cleanup_started.wait(), 1)
            switch.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await switch
            self.assertFalse(player._session.done())
            self.assertEqual(player._play_url.await_count, 1)
        finally:
            cleanup_allowed.set()
            await player.stop()
        self.assertIsNone(player._session)

    async def test_missing_mpv_reports_error_without_retry(self):
        player = Player(lambda state: None)
        with patch("somawave.player.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            await player.play(Station("test", "Test", "", ("test",)))
            await asyncio.wait_for(player._session, 1)
        self.assertEqual(player.state.phase, "Error")
        self.assertIn("MPV was not found", player.state.detail)
        await player.stop()

    async def test_malformed_ipc_values_do_not_interrupt_playback(self):
        updated = asyncio.Event()
        player = Player(lambda state: updated.set())
        ipc = AsyncMock()
        properties = {"audio-params": {"samplerate": 44100},
                      "metadata": ["unexpected"], "audio-bitrate": "invalid"}
        ipc.command.side_effect = lambda operation, name, *args: properties.get(name)
        player.show_spectrum = False
        task = asyncio.create_task(player._monitor(ipc))
        try:
            await asyncio.wait_for(updated.wait(), 1)
            self.assertEqual(player.state.phase, "Playing")
            self.assertIsNone(player.state.bitrate)
            self.assertEqual(player.state.artist, "")
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    @unittest.skipUnless(shutil.which("mpv"), "MPV is required for IPC integration")
    async def test_real_spectrum_station_switch_and_socket_cleanup(self):
        player = Player(lambda state: None)
        process, socket = None, None
        original = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            nonlocal process, socket
            socket = Path(next(arg.split("=", 1)[1] for arg in args
                               if arg.startswith("--input-ipc-server=")))
            process = await original(args[0], "--ao=null", *args[1:], **kwargs)
            return process

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "tone.wav"
            with wave.open(str(audio), "wb") as stream:
                rate = 24000
                stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                tone = array("h", (round(6000 * math.sin(math.tau * 440 * i / rate))
                                   for i in range(rate)))
                quiet = array("h", (sample // 12 for sample in tone))
                stream.writeframes(tone.tobytes() * 2 + quiet.tobytes() * 8)
            playlist = Path(directory) / "test.m3u"
            playlist.write_text(f"#EXTM3U\n{audio}\n", encoding="utf-8")
            with patch("somawave.player.asyncio.create_subprocess_exec", side_effect=spawn):
                await player.play(Station("test", "Test", "", (str(playlist),)))
                try:
                    async with asyncio.timeout(3):
                        while player.state.phase != "Playing":
                            await asyncio.sleep(0.02)
                        self.assertTrue(socket.is_socket())
                        while not player.spectrum_levels:
                            await asyncio.sleep(0.02)
                        # The 440 Hz tone should peak near the 17th log-spaced band.
                        levels = player.spectrum_levels
                        peak = max(range(len(levels)), key=levels.__getitem__)
                        self.assertIn(peak, (16, 17))
                        self.assertGreater(levels[peak], levels[-1] + 0.2)
                        player.paused = True
                        while player.state.phase != "Paused":
                            await asyncio.sleep(0.02)
                        player.paused = False
                    async with asyncio.timeout(4):
                        while not (player.state.phase == "Playing" and
                                   0.05 < player.spectrum_levels[peak] < levels[peak] - 0.2):
                            await asyncio.sleep(0.02)
                    reader, writer = await asyncio.open_unix_connection(socket)
                    try:
                        ipc = IPC(reader, writer)
                        session = player._session
                        self.assertTrue(await ipc.command("get_property", "af"))
                        self.assertEqual(await ipc.command(
                            "get_property", "options/demuxer-max-back-bytes"), 1024 * 1024)
                        player.volume = 35
                        player.muted = True
                        async with asyncio.timeout(2):
                            while (await ipc.command("get_property", "volume") != 35 or
                                   not await ipc.command("get_property", "mute")):
                                await asyncio.sleep(0.05)
                        player.show_spectrum = False
                        async with asyncio.timeout(2):
                            while await ipc.command("get_property", "af") or player.spectrum_levels:
                                await asyncio.sleep(0.05)
                        player.show_spectrum = True
                        async with asyncio.timeout(2):
                            while not player.spectrum_levels:
                                await asyncio.sleep(0.05)
                        self.assertIs(player._session, session)
                        self.assertEqual(player.state.phase, "Playing")
                    finally:
                        writer.close()
                        await writer.wait_closed()
                    previous_process, previous_socket = process, socket
                    with patch("somawave.player.spectrum_filter",
                               return_value="lavfi=[unavailable-filter]"):
                        await player.play(Station("second", "Second", "", (str(playlist),)))
                        async with asyncio.timeout(3):
                            while player.state.phase != "Playing":
                                await asyncio.sleep(0.02)
                            await asyncio.sleep(0.4)
                        self.assertEqual(player.state.phase, "Playing")
                        self.assertEqual(player.spectrum_levels, ())
                    self.assertNotEqual(previous_process.pid, process.pid)
                    self.assertIsNotNone(previous_process.returncode)
                    self.assertFalse(previous_socket.parent.exists())
                finally:
                    await player.stop()
        self.assertIsNotNone(process.returncode)
        self.assertFalse(socket.parent.exists())
