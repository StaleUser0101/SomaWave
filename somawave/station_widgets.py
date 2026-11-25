"""Responsive station view buttons and an independently clickable favorite column."""

from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, OptionList

STATION_VIEWS = (
    ("all", ("All Stations", "All", "A")),
    ("favorites", ("Favorites", "Fav", "F")),
    ("recent", ("Recent", "Rec", "R")),
)


class StationViews(Horizontal):
    def compose(self):
        for key, labels in STATION_VIEWS:
            button = Button(labels[0], id=f"view-{key}", compact=True, tooltip=labels[0])
            button.set_class(key == "all", "active-view")
            yield button

    def on_resize(self, event):
        width = max(1, (event.size.width - 2) // len(STATION_VIEWS))
        for button, (_, labels) in zip(self.query(Button), STATION_VIEWS):
            button.styles.width = width
            button.label = next(label for label in labels if len(label) <= width)


@dataclass(frozen=True)
class StationPrompt:
    name: str
    name_style: str
    star: str
    star_color: str

    def __rich_console__(self, console, options):
        width = options.max_width
        right_padding = " " if width > 1 else ""
        name_width = width - len(right_padding) - 2  # Gap and star.
        text = Text(no_wrap=True)
        if name_width > 0:
            text.append(self.name, self.name_style)
            text.truncate(name_width, overflow="ellipsis", pad=True)
        if width > 2:
            text.append(" ")
        text.append(self.star, Style(color=self.star_color, meta={"favorite_star": True}))
        text.append(right_padding)
        yield text


class StationList(OptionList):
    class FavoritePressed(Message):
        def __init__(self, station_id):
            self.station_id = station_id
            super().__init__()

    def on_click(self, event):
        metadata = event.style.meta
        index = metadata.get("option")
        if metadata.get("favorite_star") and index is not None and index < self.option_count:
            event.prevent_default()
            event.stop()
            self.post_message(self.FavoritePressed(self.get_option_at_index(index).id))
