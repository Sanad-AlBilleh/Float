"""Inline SVG for the cash projection: two lines and a marked lowest point, no charting library (SRS §8.1)."""

from dataclasses import dataclass

WIDTH, HEIGHT, PAD = 640, 220, 24


@dataclass(frozen=True)
class ProjectionChart:
    width: int
    height: int
    conservative: str  # SVG polyline points
    expected: str
    zero_y: float | None  # where €0 sits, if it is inside the chart
    lowest_x: float
    lowest_y: float


def projection_chart(timeline, lowest) -> ProjectionChart:
    values = [p.conservative_cents for p in timeline] + [p.expected_cents for p in timeline] + [0]
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = (WIDTH - 2 * PAD) / max(1, len(timeline) - 1)

    def y(cents: int) -> float:
        return round(PAD + (high - cents) * (HEIGHT - 2 * PAD) / span, 1)

    def line(attribute: str) -> str:
        return " ".join(f"{round(PAD + i * step, 1)},{y(getattr(p, attribute))}" for i, p in enumerate(timeline))

    index = timeline.index(lowest)
    return ProjectionChart(WIDTH, HEIGHT, line("conservative_cents"), line("expected_cents"),
                           y(0) if low <= 0 <= high else None, round(PAD + index * step, 1), y(lowest.expected_cents))


@dataclass(frozen=True)
class DonutSlice:
    label: str
    cents: int
    percent: int  # whole percent of the total, for the label
    colour: str
    dash: str  # stroke-dasharray on a circle whose circumference is 100
    offset: float  # stroke-dashoffset so slices follow each other clockwise from 12 o'clock


def donut(items: list[tuple[str, int, str]]) -> tuple[list[DonutSlice], int]:
    """Slices for an SVG ring chart from (label, cents, colour); returns the slices and the total."""
    total = sum(cents for _, cents, _ in items if cents > 0)
    slices, start = [], 0.0
    for label, cents, colour in sorted(items, key=lambda item: -item[1]):
        if cents <= 0 or total == 0:
            continue
        share = cents * 100 / total
        slices.append(DonutSlice(label, cents, round(share), colour, f"{max(share - 0.6, 0.1):.2f} {100 - max(share - 0.6, 0.1):.2f}",
                                 round(25 - start, 2)))
        start += share
    return slices, total
