"""Reliability diagram as a standalone SVG.

No plotting library. The chart is ten numbers and a diagonal, and an
SVG keeps the report readable in git without a matplotlib install.
"""

from __future__ import annotations

from app.backtest.metrics import CalibrationBin


def reliability_svg(bins: list[CalibrationBin]) -> str:
    """Plot mean predicted probability against the realized over rate.

    Point radius grows with the bin count, capped so one huge bin does
    not cover the frame. Empty bins are omitted.
    """
    width = 480
    height = 360
    left = 56
    right = 24
    top = 36
    bottom = 48
    plot_w = width - left - right
    plot_h = height - top - bottom

    def x_of(probability: float) -> float:
        return left + probability * plot_w

    def y_of(probability: float) -> float:
        return top + (1.0 - probability) * plot_h

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
        ),
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        (
            f'<text x="{width / 2:.0f}" y="20" text-anchor="middle" '
            'font-family="sans-serif" font-size="13" fill="#111827">'
            "Predicted probability vs realized over rate</text>"
        ),
        (
            f'<line x1="{x_of(0):.1f}" y1="{y_of(0):.1f}" x2="{x_of(1):.1f}" '
            f'y2="{y_of(1):.1f}" stroke="#6b7280" stroke-dasharray="4 4"/>'
        ),
        (
            f'<line x1="{x_of(0):.1f}" y1="{y_of(0):.1f}" x2="{x_of(1):.1f}" '
            f'y2="{y_of(0):.1f}" stroke="#111827"/>'
        ),
        (
            f'<line x1="{x_of(0):.1f}" y1="{y_of(0):.1f}" x2="{x_of(0):.1f}" '
            f'y2="{y_of(1):.1f}" stroke="#111827"/>'
        ),
    ]
    for tick in (0.0, 0.5, 1.0):
        label = f"{tick:.1f}"
        parts.append(
            f'<text x="{x_of(tick):.1f}" y="{height - 16}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="12" fill="#111827">{label}</text>'
        )
        parts.append(
            f'<text x="8" y="{y_of(tick) + 4:.1f}" font-family="sans-serif" '
            f'font-size="12" fill="#111827">{label}</text>'
        )
    for item in bins:
        if item.count == 0 or item.mean_predicted is None or item.realized_rate is None:
            continue
        radius = 4 + min(item.count, 16)
        parts.append(
            f'<circle cx="{x_of(item.mean_predicted):.2f}" '
            f'cy="{y_of(item.realized_rate):.2f}" r="{radius}" '
            'fill="#1d4ed8" fill-opacity="0.8"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
