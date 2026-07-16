"""Perceived-performance helpers: value smoothing + micro-animations so numbers
and bars glide instead of jumping.

The download engine reports raw, spiky numbers (speed flicks to 0 between
chunks, progress arrives in bursts). The UI should never show that jitter.
These widgets interpolate toward their target every frame, and the speed
smoother runs an EMA so "125.4 MB/s" drifts smoothly rather than strobing to 0
and back. A single shared 60fps ticker drives every animated widget, so this
stays cheap even with hundreds of rows.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from app.ui import theme
from app.ui.format import human_bytes

_FPS = 60
_FRAME_MS = 1000 // _FPS
_SPARK_HISTORY = 48


class _Ticker(QObject):
    """One 60fps heartbeat shared by every animated widget. Widgets subscribe
    while they have work to do and unsubscribe when settled, so an idle app
    burns no frames."""

    tick = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._fire)
        self._subs = 0

    def subscribe(self) -> None:
        self._subs += 1
        if not self._timer.isActive():
            self._timer.start()

    def unsubscribe(self) -> None:
        self._subs = max(0, self._subs - 1)
        if self._subs == 0:
            self._timer.stop()

    def _fire(self) -> None:
        self.tick.emit()


_ticker: _Ticker | None = None


def ticker() -> _Ticker:
    global _ticker
    if _ticker is None:
        _ticker = _Ticker()
    return _ticker


class Animated:
    """A single float that eases toward a target with exponential approach
    (framerate-independent). Call :meth:`set` with a new target; read
    :attr:`value` each frame. ``on_change`` fires while it's still moving."""

    def __init__(self, value: float = 0.0, speed: float = 14.0, *, epsilon: float = 0.4) -> None:
        self.value = value
        self._target = value
        self._speed = speed  # higher = snappier
        # How close counts as "arrived". Must match the value's scale: pixels
        # want ~0.4, but a 0..1 progress fraction needs something tiny, or every
        # small per-poll step snaps instantly and the bar looks like it stalls.
        self._epsilon = epsilon
        self._running = False
        self._on_change: Callable[[], None] | None = None

    def bind(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change

    def set(self, target: float, *, immediate: bool = False) -> None:
        self._target = target
        if immediate or abs(target - self.value) < self._epsilon:
            self.value = target
            self._stop()
            if self._on_change:
                self._on_change()
            return
        if not self._running:
            self._running = True
            ticker().tick.connect(self._step)
            ticker().subscribe()

    def _step(self) -> None:
        # Exponential smoothing toward the target; ~1/60s per frame.
        alpha = 1.0 - pow(2.718281828, -self._speed / _FPS)
        self.value += (self._target - self.value) * alpha
        if abs(self._target - self.value) < self._epsilon:
            self.value = self._target
            self._stop()
        if self._on_change:
            self._on_change()

    def _stop(self) -> None:
        if self._running:
            self._running = False
            ticker().tick.disconnect(self._step)
            ticker().unsubscribe()


class SpeedSmoother:
    """A steady bytes/sec readout taken from a *cumulative* byte count.

    Measuring between two consecutive polls doesn't work: the engine flushes
    progress on its own interval, which doesn't line up with ours, so one poll
    catches two flushes, the next catches none, and the readout strobes between
    zero and double. Measuring across a whole window instead averages that
    quantisation out - it only reads zero when genuinely nothing arrived for
    the entire window. A light EMA on top settles the last wobble.

    Feed it ``push_total(now, total_bytes)`` exactly once per poll.
    """

    def __init__(self, window: float = 3.0, weight: float = 0.35) -> None:
        self._window = window
        self._weight = weight
        self._samples: deque[tuple[float, float]] = deque()
        self._ema: float | None = None

    def push_total(self, now: float, total: float) -> float:
        self._samples.append((now, total))
        # Keep one sample just outside the window so the span covers it fully.
        cutoff = now - self._window
        while len(self._samples) > 2 and self._samples[1][0] < cutoff:
            self._samples.popleft()
        oldest_at, oldest_total = self._samples[0]
        span = now - oldest_at
        if span <= 0:
            return self._ema or 0.0
        rate = max(0.0, total - oldest_total) / span
        self._ema = (
            rate if self._ema is None else self._ema * (1 - self._weight) + rate * self._weight
        )
        return self._ema

    def reset(self) -> None:
        self._samples.clear()
        self._ema = None


def fmt_speed(bps: float) -> str:
    """A stable speed readout with a fixed decimal, so digits don't jitter."""
    if bps < 1:
        return "—"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def fmt_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


class SmoothProgressBar(QWidget):
    """A thin, rounded progress bar whose fill glides to each new value and can
    run an indeterminate shimmer (for a magnet resolving its metadata)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(5)
        self.setMinimumWidth(60)
        # speed ~7 makes the glide take a hair longer than the 500ms poll, so a
        # steadily-advancing download keeps the fill in continuous motion rather
        # than jumping and pausing; epsilon is tiny because value is a 0..1
        # fraction (see Animated).
        self._fill = Animated(0.0, speed=7.0, epsilon=0.0008)
        self._fill.bind(self.update)
        self._indeterminate = False
        self._marquee = 0.0
        self._color: QColor | None = None

    def set_value(self, fraction: float, *, immediate: bool = False) -> None:
        """fraction in 0..1."""
        if self._indeterminate:
            self._indeterminate = False
            ticker().tick.disconnect(self._advance_marquee)
            ticker().unsubscribe()
        self._fill.set(max(0.0, min(1.0, fraction)), immediate=immediate)

    def set_indeterminate(self, on: bool) -> None:
        if on == self._indeterminate:
            return
        self._indeterminate = on
        if on:
            ticker().tick.connect(self._advance_marquee)
            ticker().subscribe()
        else:
            ticker().tick.disconnect(self._advance_marquee)
            ticker().unsubscribe()
        self.update()

    def set_color(self, color: str | None) -> None:
        self._color = QColor(color) if color else None
        self.update()

    def _advance_marquee(self) -> None:
        self._marquee = (self._marquee + 0.012) % 1.0
        self.update()

    def paintEvent(self, _event: object) -> None:
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        if w <= 0 or h <= 0:  # pragma: no cover - not laid out yet
            painter.end()
            return
        r = h / 2
        track = QPainterPath()
        track.addRoundedRect(0, 0, w, h, r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(track, QColor(p.border))
        # Clip to the track, then draw at true coordinates: the fill can never
        # escape the rounded ends, and the marquee slides in and out smoothly
        # instead of being clamped to the edges (which made it jump).
        painter.setClipPath(track)
        color = self._color or QColor(p.accent)
        if self._indeterminate:
            seg = w * 0.3
            x = self._marquee * (w + seg) - seg
            painter.fillRect(QRectF(x, 0.0, seg, h), color)
        elif self._fill.value > 0:
            painter.fillRect(QRectF(0.0, 0.0, w * self._fill.value, h), color)
        painter.end()


class Sparkline(QWidget):
    """A recent-speed sparkline. Between data pushes the line scrolls smoothly
    (driven by the shared ticker while visible) instead of stepping."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from collections import deque

        self._samples: deque[float] = deque(maxlen=_SPARK_HISTORY)
        self._last_push = 0.0
        self._push_interval = 0.5
        self._animating = False
        self.setMinimumSize(72, 24)
        self.setToolTip("Recent total speed")

    def push(self, bytes_per_second: float) -> None:
        import time

        now = time.monotonic()
        if self._last_push:
            gap = min(2.0, max(0.05, now - self._last_push))
            self._push_interval = self._push_interval * 0.7 + gap * 0.3
        self._last_push = now
        self._samples.append(max(0.0, bytes_per_second))
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self._last_push = 0.0
        self.update()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._animating:
            ticker().tick.connect(self.update)
            ticker().subscribe()
            self._animating = True

    def hideEvent(self, event: object) -> None:
        super().hideEvent(event)  # type: ignore[arg-type]
        if self._animating:
            self._animating = False
            import contextlib

            with contextlib.suppress(RuntimeError, TypeError):  # app teardown
                ticker().tick.disconnect(self.update)
                ticker().unsubscribe()

    def paintEvent(self, _event: object) -> None:
        import time

        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen, QPolygonF

        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 2, -1, -2)
        peak = max(self._samples, default=0.0)
        if peak > 0 and len(self._samples) > 1:
            accent = QColor(p.accent)
            step = rect.width() / (_SPARK_HISTORY - 1)
            base = rect.bottom()
            frac = 1.0
            if self._last_push:
                frac = min(1.0, (time.monotonic() - self._last_push) / self._push_interval)
            shift = (1.0 - frac) * step
            painter.setClipRect(rect)
            pts = [
                QPointF(rect.left() + i * step + shift, base - (v / peak) * rect.height())
                for i, v in enumerate(self._samples)
            ]
            fill = QColor(accent)
            fill.setAlpha(38)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(
                QPolygonF([QPointF(pts[0].x(), base), *pts, QPointF(pts[-1].x(), base)])
            )
            painter.setPen(QPen(accent, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF(pts))
        painter.end()

    def human(self, bps: float) -> str:  # pragma: no cover - convenience
        return f"{human_bytes(bps)}/s"
