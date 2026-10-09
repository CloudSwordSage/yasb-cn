import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

STATISTICS = ("current", "avg", "min", "max", "median", "stddev", "range", "sample_count")
# A single outage longer than this (or any connection change) breaks the line.
GAP_SECONDS = 15.0


def parse_measurement(data: bytes | bytearray) -> int | None:
    """Parse 0x2A37, validating optional energy/RR fields without retaining them.

    Returns:
        Positive UINT8/UINT16 heart rate, or None for malformed/zero measurements.
        Reserved flag bits and trailing bytes without the RR flag are invalid.
    """
    if len(data) < 2 or data[0] & 0xE0:
        return None
    flags = data[0]
    size = 2 if flags & 1 else 1
    end = 1 + size
    required = end + (2 if flags & 8 else 0)
    if len(data) < required:
        return None
    remaining = len(data) - required
    if flags & 16:
        if remaining < 2 or remaining % 2:
            return None
    elif remaining:
        return None
    value = int.from_bytes(data[1:end], "little")
    return value or None


@dataclass(frozen=True, slots=True)
class Sample:
    """Actual measurement with monotonic/wall seconds and connection segment ID."""

    value: int
    monotonic: float
    wall: float
    segment: int


class SampleWindow:
    """Time-bounded, lossless buffer, owned exclusively by the BLE event loop.

    Statistics use per-sample arithmetic mean and population standard deviation.
    The inclusive left boundary is ``now - seconds``. Expiration never fills gaps.
    """

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.samples: deque[Sample] = deque()
        self.revision = 0
        self._cached_revision = -1
        self._cached = {}

    def add(self, value: int, monotonic: float, wall: float, segment: int) -> None:
        """Append one valid sample in monotonic order; prune expired samples."""
        if not 0 < value <= 65535 or (self.samples and monotonic < self.samples[-1].monotonic):
            raise ValueError("Invalid heart rate sample or out-of-order timestamp")
        self.samples.append(Sample(value, monotonic, wall, segment))
        self.revision += 1
        self.prune(monotonic)

    def prune(self, now: float) -> bool:
        """Remove samples older than the time window; report whether it changed."""
        changed = False
        while self.samples and self.samples[0].monotonic < now - self.seconds:
            self.samples.popleft()
            changed = True
        if changed:
            self.revision += 1
        return changed

    def statistics(self, now: float) -> dict[str, float | int | None]:
        """Return cached raw-window metrics, None for missing values, count zero."""
        self.prune(now)
        if self._cached_revision != self.revision:
            values = [sample.value for sample in self.samples]
            self._cached = dict.fromkeys(STATISTICS)
            self._cached["sample_count"] = len(values)
            if values:
                self._cached.update(
                    current=values[-1],
                    avg=statistics.mean(values),
                    min=min(values),
                    max=max(values),
                    median=statistics.median(values),
                    stddev=statistics.pstdev(values),
                    range=max(values) - min(values),
                )
            self._cached_revision = self.revision
        return dict(self._cached)


def y_bounds(values: Sequence[int], minimum_span: float) -> tuple[float, float]:
    """Padded dynamic bounds with a minimum span to avoid exaggerated noise."""
    low, high = (min(values), max(values)) if values else (0, minimum_span)
    span = max(high - low, minimum_span)
    center = (low + high) / 2
    return center - span * 0.55, center + span * 0.55


def graph_segments(
    samples: Sequence[Sample], now: float, seconds: float, width: int, gap_seconds: float, gap_on_disconnect: bool
) -> list[list[Sample]]:
    """Split real gaps, then retain first/min/max/last points per horizontal pixel.

    Returned points retain chronological order. Raw statistical samples are untouched.
    ``gap_on_disconnect=False`` disables segment breaks, but never time-gap breaks.
    """
    segments = []
    current = []
    previous = None
    width = max(1, width)
    for sample in samples:
        if sample.monotonic < now - seconds:
            continue
        if previous and (
            sample.monotonic - previous.monotonic > gap_seconds
            or (gap_on_disconnect and sample.segment != previous.segment)
        ):
            segments.append(current)
            current = []
        current.append(sample)
        previous = sample
    if current:
        segments.append(current)
    result = []
    for segment in segments:
        buckets = {}
        for index, sample in enumerate(segment):
            pixel = min(width - 1, max(0, int((sample.monotonic - now + seconds) / seconds * width)))
            buckets.setdefault(pixel, []).append(index)
        indices = set()
        for bucket in buckets.values():
            indices.update(
                (
                    bucket[0],
                    bucket[-1],
                    min(bucket, key=lambda i: segment[i].value),
                    max(bucket, key=lambda i: segment[i].value),
                )
            )
        result.append([segment[index] for index in sorted(indices)])
    return result
