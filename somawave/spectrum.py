"""Measure frequency bands from MPV's decoded audio and map them to terminal cells."""

import math

FPS = 30
BAND_COUNT = 40
LOW_HZ, HIGH_HZ = 45, 10500
FLOOR_DB, CEILING_DB = -66, -9
ATTACK, RELEASE = 0.05, 0.35
PEAK_HOLD, PEAK_DECAY = 0.30, 0.60
BLOCKS = " ▁▂▃▄▅▆▇█"
RMS_PREFIX = b"lavfi.astats."


def spectrum_filter():
    """Keep the playback branch intact and measure a resampled copy."""
    inputs = "".join(f"[in{i}]" for i in range(BAND_COUNT))
    bands = "".join(f"[band{i}]" for i in range(BAND_COUNT))
    octave_width = math.log2(HIGH_HZ / LOW_HZ) / BAND_COUNT
    filters = [
        f"[in{i}]bandpass=f={LOW_HZ * 2 ** ((i + 0.5) * octave_width):.2f}"
        f":t=o:w={octave_width:.4f},aformat=sample_fmts=flt:channel_layouts=mono[band{i}]"
        for i in range(BAND_COUNT)
    ]
    graph = ";".join([
        "asplit[playback][tap]",
        f"[tap]aformat=channel_layouts=mono,aresample=24000,asplit={BAND_COUNT}{inputs}",
        *filters,
        f"{bands}amerge=inputs={BAND_COUNT},asetnsamples=n={24000 // FPS},"
        "astats=metadata=1:reset=1:measure_perchannel=RMS_level:measure_overall=none,"
        "ametadata=mode=print:file=/dev/stdout:direct=1,anullsink",
    ])
    return f"lavfi=[{graph}]"


async def read_spectrum(reader, publish):
    levels = {}
    while line := await reader.readline():
        if line.startswith(b"frame:"):
            levels.clear()
        if not line.startswith(RMS_PREFIX):
            continue
        name, _, value = line[len(RMS_PREFIX):].partition(b"=")
        channel, _, metric = name.partition(b".")
        if metric != b"RMS_level" or not channel.isdigit():
            continue
        try:
            db = float(value)
        except ValueError:
            continue
        index = int(channel)
        if 1 <= index <= BAND_COUNT and not math.isnan(db):
            levels[index] = display_level(db)
        if len(levels) == BAND_COUNT:
            publish(tuple(levels[index] for index in range(1, BAND_COUNT + 1)))
            levels.clear()


def display_level(db):
    """Map absolute RMS dBFS to height without per-frame normalization."""
    return max(0.0, min(1.0, (db - FLOOR_DB) / (CEILING_DB - FLOOR_DB))) ** 1.4


class SpectrumMotion:
    def __init__(self):
        self.reset()

    def reset(self):
        self.bars = [0.0] * BAND_COUNT
        self.peaks = [0.0] * BAND_COUNT
        self.hold_until = [0.0] * BAND_COUNT
        self.updated_at = None
        self.active = False

    def advance(self, levels, now):
        previous = now - 1 / FPS if self.updated_at is None else self.updated_at
        elapsed = now - previous
        self.updated_at = now
        attack = -math.expm1(-elapsed / ATTACK)
        release = -math.expm1(-elapsed / RELEASE)
        self.active = False
        for i, bar in enumerate(self.bars):
            target = levels[i] if levels else 0.0
            bar += (target - bar) * (attack if target > bar else release)
            self.bars[i] = bar if bar >= 1 / 128 else 0.0
            if not levels:
                self.peaks[i] = self.hold_until[i] = 0.0
            elif bar >= self.peaks[i]:
                self.peaks[i] = bar
                self.hold_until[i] = now + PEAK_HOLD
            else:
                decay_time = max(0.0, now - max(previous, self.hold_until[i]))
                self.peaks[i] = max(bar, self.peaks[i] * math.exp(-decay_time / PEAK_DECAY))
            self.active |= bool(self.bars[i] or self.peaks[i] >= 1 / 128)


def spectrum_rows(levels, width, height, peaks=()):
    if not levels or width < 1 or not height:
        return ""
    # Keep the higher band count when it leaves at most two spare cells.
    # The pitch includes a one-cell gap, except after the final bar.
    pitch = max(2, (width + len(levels) - 2) // len(levels))
    count = min(len(levels), (width + 1) // pitch)
    bar_width = pitch - 1
    padding = width + 1 - count * pitch
    left = " " * (padding // 2)
    right = " " * (padding - len(left))
    # Combine adjacent frequency bands when the panel is too narrow for all of them.
    groups = [slice(i * len(levels) // count, (i + 1) * len(levels) // count)
              for i in range(count)]
    steps = [round(max(levels[group]) * height * 8) for group in groups]
    peak_rows = [math.ceil(max(peaks[group]) * height) - 1 for group in groups] if peaks else [-1] * count
    return "\n".join(
        left + " ".join((BLOCKS[min(8, step - row * 8)] if step > row * 8
                  else "─" if peak == row else " ") * bar_width
                 for step, peak in zip(steps, peak_rows)) + right
        for row in reversed(range(height))
    )
