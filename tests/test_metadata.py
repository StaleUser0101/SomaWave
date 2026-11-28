import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from somawave.player import Player, track_metadata
from somawave.stations import Station


class MetadataTests(unittest.TestCase):
    def test_structured_and_icy_fields(self):
        self.assertEqual(track_metadata({"ARTIST": " Partner ", "TITLE": "Play The Field"}),
                         ("Partner", "Play The Field", ""))
        self.assertEqual(track_metadata({"icy-title": "Partner - Play The Field - Live"}),
                         ("Partner", "Play The Field - Live", ""))
        self.assertEqual(track_metadata({"title": "Track - Live"}), ("", "Track - Live", ""))

    def test_missing_and_unclassified_fields(self):
        self.assertEqual(track_metadata(None), ("", "", ""))
        self.assertEqual(track_metadata({"icy-title": "Live from the studio"}),
                         ("", "", "Live from the studio"))


    def test_structured_fields_take_precedence_over_icy(self):
        self.assertEqual(track_metadata({
            "aRtIsT": "Björk", "TiTlE": "Jóga", "IcY-TiTlE": "Björk - Another Song",
        }), ("Björk", "Jóga", ""))
        self.assertEqual(track_metadata({
            "TITLE": "Jóga", "ICY-TITLE": "Björk - Another Song",
        }), ("Björk", "Jóga", ""))


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg"),
                     "MPV and FFmpeg are required for ICY integration")
class IcyPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_icy_metadata_updates_during_playback(self):
        audio = subprocess.check_output([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "1", "-b:a", "128k", "-write_xing", "0", "-id3v2_version", "0",
            "-f", "mp3", "pipe:1",
        ])
        interval = 8192
        tracks = asyncio.Queue()
        first = ("Björk", "Jóga")
        second = ("Sigur Rós", "Svefn-g-englar - Live")
        track = first

        async def serve_stream(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: audio/mpeg\r\n"
                    b"icy-metaint: 8192\r\nicy-name: Test Station\r\n\r\n"
                )
                offset = 0
                while True:
                    packet = audio[offset:offset + interval]
                    packet += audio[:interval - len(packet)]
                    offset = (offset + interval) % len(audio)
                    metadata = "StreamTitle='%s - %s';" % track
                    encoded = metadata.encode("utf-8")
                    block_count = (len(encoded) + 15) // 16
                    writer.write(packet + bytes([block_count]) + encoded.ljust(block_count * 16, b"\0"))
                    await writer.drain()
                    await asyncio.sleep(0.25)
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()

        def update(state):
            if state.phase == "Playing" and state.title:
                tracks.put_nowait((state.artist, state.title))

        original_spawn = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            return await original_spawn(args[0], "--ao=null", *args[1:], **kwargs)

        player = Player(update)
        player.show_spectrum = False
        player.set_reconnect(False)
        with tempfile.TemporaryDirectory() as directory:
            async with await asyncio.start_server(serve_stream, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                playlist = Path(directory) / "test.m3u"
                playlist.write_text(f"#EXTM3U\nhttp://127.0.0.1:{port}/stream.mp3\n")
                with patch("somawave.player.asyncio.create_subprocess_exec", side_effect=spawn):
                    await player.play(Station("test", "Test", "", (str(playlist),)))
                    try:
                        self.assertEqual(await asyncio.wait_for(tracks.get(), 8), first)
                        track = second
                        async with asyncio.timeout(12):
                            while await tracks.get() != second:
                                pass
                    finally:
                        await player.stop()
