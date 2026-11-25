"""XDG paths and atomic storage for user preferences and station cache."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

RECENT_LIMIT = 10
STREAM_QUALITIES = (
    ("Highest available", "highest"),
    ("Standard", "standard"),
    ("Low bandwidth", "low"),
)
DEFAULT_VIEWS = (("All Stations", "all"), ("Favorites", "favorites"), ("Recent", "recent"))


def saved_choice(data, key, choices):
    return next((value for _, value in choices if data.get(key) == value), choices[0][1])


def saved_switch(data, key, default):
    value = data.get(key)
    return value if isinstance(value, bool) else default


def station_ids(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item.strip() for item in value
                              if isinstance(item, str) and item.strip()))


def xdg_path(variable, fallback):
    path = Path(os.environ.get(variable) or Path.home() / fallback)
    return (path if path.is_absolute() else Path.home() / fallback) / "somawave"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class Preferences:
    station: str = ""
    volume: int = 70
    muted: bool = False
    favorites: list[str] = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    stream_quality: str = "highest"
    autoplay: bool = False
    reconnect: bool = True
    show_spectrum: bool = True
    show_peaks: bool = True
    default_view: str = "all"

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls()
            station = data.get("station")
            volume = data.get("volume")
            return cls(
                station=station if isinstance(station, str) else "",
                volume=max(0, min(100, volume)) if type(volume) is int else 70,
                muted=data.get("muted") is True,
                favorites=station_ids(data.get("favorites")),
                recent=station_ids(data.get("recent"))[:RECENT_LIMIT],
                stream_quality=saved_choice(data, "stream_quality", STREAM_QUALITIES),
                autoplay=saved_switch(data, "autoplay", False),
                reconnect=saved_switch(data, "reconnect", True),
                show_spectrum=saved_switch(data, "show_spectrum", True),
                show_peaks=saved_switch(data, "show_peaks", True),
                default_view=saved_choice(data, "default_view", DEFAULT_VIEWS),
            )
        except (OSError, ValueError, RecursionError):
            return cls()

    def save(self, path):
        write_json(path, asdict(self))

    def record_played(self, station_id):
        recent = [station_id, *(item for item in self.recent if item != station_id)][:RECENT_LIMIT]
        if recent == self.recent:
            return False
        self.recent = recent
        return True
