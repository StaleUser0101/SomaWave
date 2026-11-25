"""Fetch the official station directory and fall back to the last usable copy."""

import asyncio
import json
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import write_json

API_URL = "https://somafm.com/channels.json"
QUALITY_ORDER = {"highest": 0, "high": 1, "medium": 2, "low": 3}
NOMINAL_RATES = {24: 24, 32: 32, 48: 48, 56: 56, 64: 64, 80: 80, 96: 96,
                 128: 128, 130: 128, 160: 160, 192: 192, 256: 256, 320: 320}


@dataclass(frozen=True)
class Playlist:
    url: str
    bitrate: int | None
    quality: int

    def rank(self, preference):
        rate = self.bitrate
        if rate is None:
            priority = -self.quality if preference == "low" and self.quality < 4 else self.quality
        elif preference == "standard":
            priority = abs(rate - 128)
        else:
            priority = rate if preference == "low" else -rate
        return rate is None, priority, self.quality, not self.url.startswith("https:"), self.url


def advertised_bitrate(playlist, station_id, path):
    rate = playlist.get("bitrate")
    if type(rate) is int and 0 < rate <= 10**9:
        return round(rate / 1000) if rate >= 1000 else rate
    name = PurePosixPath(path).stem
    suffix = name.removeprefix(station_id)
    if not suffix and playlist.get("format") == "mp3":
        return 128
    if name != suffix and suffix.isascii() and suffix.isdecimal() and len(suffix) <= 3:
        return NOMINAL_RATES.get(int(suffix))
    return None


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    description: str
    playlists: tuple[str, ...]
    playlist_info: tuple[Playlist, ...] = ()

    def playlists_for(self, preference):
        if not self.playlist_info:
            return self.playlists
        return tuple(item.url for item in sorted(self.playlist_info, key=lambda item: item.rank(preference)))


def parse_directory(data):
    if not isinstance(data, dict) or not isinstance(data.get("channels"), list):
        raise ValueError("Invalid station directory")

    stations = {}
    for channel in data["channels"]:
        if not isinstance(channel, dict):
            continue
        station_id, name = channel.get("id"), channel.get("title")
        if not all(isinstance(value, str) and value.strip() for value in (station_id, name)):
            continue
        playlists = channel.get("playlists")
        if not isinstance(playlists, list):
            continue
        candidates = {}
        for playlist in playlists:
            if not isinstance(playlist, dict):
                continue
            url, quality = playlist.get("url"), playlist.get("quality")
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme in {"http", "https"} and parsed.hostname in {"somafm.com", "api.somafm.com"}:
                rank = QUALITY_ORDER.get(quality, 4) if isinstance(quality, str) else 4
                candidate = Playlist(url, advertised_bitrate(playlist, station_id, parsed.path), rank)
                if url not in candidates or candidate.rank("highest") < candidates[url].rank("highest"):
                    candidates[url] = candidate
        if candidates:
            description = channel.get("description")
            ordered = sorted(candidates.values(), key=lambda item: item.rank("highest"))
            stations[station_id] = Station(
                station_id, name, description if isinstance(description, str) else "",
                tuple(item.url for item in ordered), tuple(ordered),
            )
    if not stations:
        raise ValueError("Station directory has no playable channels")
    return sorted(stations.values(), key=lambda station: station.name.casefold())


def read_cache(path):
    try:
        return parse_directory(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, RecursionError):
        return []


def fetch_directory():
    request = Request(API_URL, headers={"User-Agent": "SomaWave"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read(2_000_000))


async def refresh_directory(path):
    try:
        data = await asyncio.to_thread(fetch_directory)
        stations = parse_directory(data)
    except (OSError, ValueError, HTTPException, RecursionError):
        cached = await asyncio.to_thread(read_cache, path)
        if cached:
            return cached, "Using cached stations · SomaFM API unavailable"
        return [], "SomaFM API unavailable · Select Retry to try again"

    try:
        await asyncio.to_thread(write_json, path, data)
    except OSError:
        return stations, "Station cache could not be saved"
    return stations, ""
