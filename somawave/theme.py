"""Read the active Omarchy palette without changing terminal settings."""

import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path

from textual.color import Color
from textual.theme import Theme

HEX_COLOR = re.compile(r"#?[0-9a-fA-F]{6}")
BLACK, WHITE = Color(0, 0, 0), Color(255, 255, 255)


def luminance(color):
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sum(weight * linear(channel) for weight, channel in
               zip((0.2126, 0.7152, 0.0722), (color.r, color.g, color.b)))


def contrast(first, second):
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def readable(color, *backgrounds):
    """Keep the supplied color where possible, moving toward black or white as needed."""
    candidates = (color, *(color.blend(endpoint, step / 20)
                           for step in range(1, 21) for endpoint in (BLACK, WHITE)))
    return next(
        (candidate for candidate in candidates
         if all(contrast(candidate, background) >= 4.5 for background in backgrounds)),
        max((BLACK, WHITE), key=lambda endpoint:
            min(contrast(endpoint, background) for background in backgrounds)),
    )


def build_theme(name, background, panel, foreground, muted, accent, border, selected,
                focused, dark):
    foreground = readable(foreground, background, panel)
    muted = readable(muted, background, panel)
    accent = readable(accent, background, panel)
    return Theme(
        name=name, primary=accent.hex, accent=accent.hex, background=background.hex,
        surface=panel.hex, panel=panel.hex, foreground=foreground.hex, dark=dark,
        variables={
            "muted-text": muted.hex,
            "panel-border": border.hex,
            "station-selected": selected.hex,
            "station-focused": focused.hex,
            "station-selected-text": readable(foreground, selected).hex,
            "station-focused-text": readable(foreground, focused).hex,
            "station-playing": readable(accent, panel, selected, focused).hex,
            "station-star": readable(muted, panel, selected, focused).hex,
            "button-foreground": foreground.hex,
            "button-color-foreground": readable(background, accent).hex,
            "input-cursor-background": accent.hex,
            "input-cursor-foreground": readable(background, accent).hex,
        },
    )


SOMAWAVE = build_theme("somawave", *map(Color.parse, (
    "#151B23", "#222C36", "#E6EDF3", "#929BA8", "#64D8BB", "#303640", "#303640", "#25463F",
)), dark=True)


def theme_paths():
    home = Path.home()
    for variable, default in (("XDG_STATE_HOME", ".local/state"), ("XDG_CONFIG_HOME", ".config")):
        standard = home / default
        override = Path(os.environ.get(variable) or standard)
        for root in dict.fromkeys((override, standard)):
            if root.is_absolute():
                yield root / "omarchy/current/theme/colors.toml"


@lru_cache(maxsize=8)
def parse_theme(contents, legacy_light):
    data = tomllib.loads(contents)

    def get(*keys, fallback=None):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and HEX_COLOR.fullmatch(value):
                return Color.parse("#" + value.lstrip("#"))
        return fallback

    background = get("background")
    foreground = get("foreground")
    if background is None or foreground is None:
        raise ValueError("Theme requires a background and foreground")
    mode = data.get("mode", data.get("theme_type"))
    dark = mode == "dark" if mode in ("light", "dark") else (
        not legacy_light and luminance(background) < 0.35
    )
    # Older themes may only supply the ANSI palette and selection colors.
    panel = get("lighter_background" if dark else "dark_background",
                fallback=background.blend(foreground, 0.08))
    if contrast(panel, background) > 1.65:
        panel = background.blend(panel, 0.25)
    accent = get("accent", "color4", "blue", fallback=foreground)
    muted = get("muted", "dark_foreground", fallback=background.blend(foreground, 0.65))
    border = get("border", fallback=panel.blend(foreground, 0.2))
    selected = get("selection", "selection_background",
                   fallback=panel.blend(foreground, 0.15))
    if contrast(selected, panel) > 3:
        selected = panel.blend(selected, 0.24)
    focused = selected.blend(readable(accent, panel), 0.20)
    return build_theme("omarchy-dark" if dark else "omarchy-light",
                       background, panel, foreground, muted, accent, border,
                       selected, focused, dark)


def load_theme():
    for path in theme_paths():
        try:
            return parse_theme(path.read_text(encoding="utf-8"), path.with_name("light.mode").is_file())
        except (OSError, ValueError):
            continue
    return SOMAWAVE
