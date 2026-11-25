"""Own one headless MPV session and supervise its JSON IPC connection."""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .spectrum import read_spectrum, spectrum_filter

SPECTRUM_FILTER = "@somawave-spectrum"


@dataclass(frozen=True)
class Playback:
    phase: str = "Stopped"
    artist: str = ""
    title: str = ""
    bitrate: int | None = None
    detail: str = ""
    stream_title: str = ""


def track_metadata(metadata):
    """Return structured tags and any ICY text that cannot be classified."""
    if not isinstance(metadata, dict):
        return "", "", ""
    tags = {key.casefold(): value.strip() for key, value in metadata.items()
            if isinstance(key, str) and isinstance(value, str)}
    artist, title = tags.get("artist", ""), tags.get("title", "")
    stream = tags.get("icy-title", "")
    if not stream:
        return artist, title, ""

    # Split ICY's conventional "Artist - Track" pair once, so a track may contain a dash.
    stream_artist, separator, track = (part.strip() for part in stream.partition(" - "))
    if separator and stream_artist and track and (
        not artist or artist.casefold() == stream_artist.casefold()
    ):
        return artist or stream_artist, track, ""
    return artist, title, stream if stream != title else ""


class IPC:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.request_id = 0

    async def command(self, *args):
        self.request_id += 1
        self.writer.write(json.dumps(
            {"command": args, "request_id": self.request_id}
        ).encode() + b"\n")
        async with asyncio.timeout(3):
            await self.writer.drain()
            while line := await self.reader.readline():
                response = json.loads(line)
                if isinstance(response, dict) and response.get("request_id") == self.request_id:
                    if response.get("error") == "success":
                        return response.get("data")
                    if args[0] == "get_property":
                        return None
                    raise OSError(f"MPV rejected {args[0]}: {response.get('error')}")
        raise OSError("MPV disconnected")


class Player:
    def __init__(self, on_update, volume=70, muted=False):
        self.on_update = on_update
        self.volume = volume
        self.muted = muted
        self.paused = False
        self.stream_quality = "highest"
        self.reconnect = True
        self.show_spectrum = True
        self.state = Playback()
        self.spectrum_levels = ()
        self.spectrum_deadline = None
        self._session = None
        self._transition = asyncio.Lock()
        self._retry_cancelled = asyncio.Event()
        self._attempt_played = False

    def set_reconnect(self, enabled):
        self.reconnect = enabled
        if enabled:
            self._retry_cancelled.clear()
        else:
            self._retry_cancelled.set()

    def update(self, state):
        if state != self.state:
            self.state = state
            self.on_update(state)

    async def play(self, station):
        async with self._transition:
            await self._stop()
            self.paused = False
            self.update(Playback("Connecting"))
            self._session = asyncio.create_task(self._supervise(station.playlists_for(self.stream_quality)))

    async def stop(self):
        async with self._transition:
            await self._stop()

    async def _stop(self):
        session = self._session
        if session is not None:
            if not session.done() and not session.cancelling():
                session.cancel()
            try:
                await asyncio.shield(session)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            finally:
                if session.done():
                    self._session = None
        self.spectrum_levels = ()
        self.spectrum_deadline = None
        self.update(Playback())

    async def _supervise(self, playlists):
        if not playlists:
            self.update(Playback("Error", detail="No official stream is available for this station"))
            return
        attempt = 0
        index = 0
        played = False
        untried = len(playlists)
        while True:
            self._attempt_played = False
            try:
                await self._play_url(playlists[index])
            except FileNotFoundError:
                self.update(Playback("Error", detail="MPV was not found on PATH"))
                return
            except (OSError, ValueError, TimeoutError) as error:
                if self._attempt_played:
                    attempt = 0
                    played = True
                untried -= 1
                if self.paused:
                    self.update(Playback("Paused"))
                    while self.paused:
                        await asyncio.sleep(0.25)
                if not self.reconnect and (played or untried <= 0):
                    self.report_disconnect(error, played)
                    return
                index = (index + 1) % len(playlists)
                if not self.reconnect:
                    self.update(Playback("Connecting", detail="Trying another official stream"))
                    continue
                delay = min(2 ** min(attempt, 5), 30)
                self.update(Playback("Reconnecting", detail=f"{error} · retry in {delay}s"))
                try:
                    async with asyncio.timeout(delay):
                        await self._retry_cancelled.wait()
                except TimeoutError:
                    pass
                if not self.reconnect and (played or untried <= 0):
                    self.report_disconnect(error, played)
                    return
                while self.paused:
                    await asyncio.sleep(0.25)
                attempt += 1

    def report_disconnect(self, error, played):
        description = "Stream disconnected" if played else "Could not start the stream"
        self.update(Playback("Error", detail=f"{description} · {error}"))

    async def _play_url(self, url):
        self.spectrum_levels = ()
        self.spectrum_deadline = None
        with TemporaryDirectory(prefix="sw-") as directory:
            socket = str(Path(directory) / "mpv.sock")
            # Shield process creation so cancellation cannot leave a spawned child unowned.
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                "mpv", "--no-config", "--no-video", "--no-terminal", "--idle=no",
                "--audio-display=no", "--network-timeout=10", "--cache=yes",
                # Live radio has no rewind control. Keep only the forward buffer.
                "--demuxer-max-back-bytes=0",
                "--volume-max=100", f"--volume={self.volume}", f"--mute={'yes' if self.muted else 'no'}",
                f"--pause={'yes' if self.paused else 'no'}", f"--input-ipc-server={socket}",
                f"--playlist={url}", stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            ))
            writer = None
            process = None
            spectrum_reader = None
            try:
                process = await asyncio.shield(spawn)
                spectrum_reader = asyncio.create_task(
                    read_spectrum(process.stdout, self._receive_spectrum)
                )
                async with asyncio.timeout(5):
                    while True:
                        try:
                            reader, writer = await asyncio.open_unix_connection(socket)
                            break
                        except OSError:
                            if process.returncode is not None:
                                raise OSError(f"MPV exited with code {process.returncode}")
                            await asyncio.sleep(0.05)
                await self._monitor(IPC(reader, writer))
            finally:
                if writer is not None:
                    writer.close()
                if process is None and not spawn.cancelled():
                    with suppress(OSError):
                        process = await spawn
                if process is not None:
                    await self._terminate(process)
                if spectrum_reader is not None:
                    spectrum_reader.cancel()
                    with suppress(asyncio.CancelledError):
                        await spectrum_reader
                if writer is not None:
                    with suppress(OSError):
                        await writer.wait_closed()

    def _receive_spectrum(self, levels):
        if self.show_spectrum:
            self.spectrum_levels = levels

    @staticmethod
    async def _terminate(process):
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()

    async def _monitor(self, ipc):
        clock = asyncio.get_running_loop().time
        last_ready = clock()
        applied = {}
        spectrum_requested = False
        while True:
            controls = {"volume": self.volume, "mute": self.muted, "pause": self.paused}
            for name, value in controls.items():
                if applied.get(name) != value:
                    await ipc.command("set_property", name, value)
                    applied[name] = value

            audio = await ipc.command("get_property", "audio-params")
            buffering = await ipc.command("get_property", "paused-for-cache")
            core_idle = await ipc.command("get_property", "core-idle")
            paused = await ipc.command("get_property", "pause")
            if spectrum_requested and not self.show_spectrum:
                with suppress(OSError):
                    await ipc.command("af", "remove", SPECTRUM_FILTER)
                spectrum_requested = False
                self.spectrum_levels = ()
                self.spectrum_deadline = None
            if audio and (paused or not (buffering or core_idle)):
                last_ready = clock()
                phase = "Paused" if paused else "Playing"
                if phase == "Playing":
                    self._attempt_played = True
                if phase == "Playing" and self.show_spectrum and not spectrum_requested:
                    # Attach after playback succeeds. MPV leaves playback intact if
                    # the optional filter is rejected or fails to initialize.
                    self.spectrum_deadline = monotonic() + 4
                    spectrum_requested = True
                    try:
                        await ipc.command("af", "add", f"{SPECTRUM_FILTER}:{spectrum_filter()}")
                    except OSError:
                        # Report the optional filter failure while playback continues.
                        self.spectrum_deadline = monotonic()
            else:
                if paused:
                    last_ready = clock()
                    phase = "Paused"
                elif clock() - last_ready > 20:
                    raise TimeoutError("Stream stalled")
                else:
                    phase = "Buffering" if audio or buffering else "Connecting"

            artist, title, stream_title = track_metadata(await ipc.command("get_property", "metadata"))
            bitrate = await ipc.command("get_property", "audio-bitrate")
            rate = (round(bitrate / 1000) if type(bitrate) in (int, float)
                    and 0 < bitrate <= 10**9 else None)
            self.update(Playback(phase, artist, title, rate,
                                 stream_title=stream_title))
            await asyncio.sleep(0.25)
