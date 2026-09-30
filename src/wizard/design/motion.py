"""Animations, and the setting that says not to play them.

Windows has a system-wide "Show animations in Windows" switch, read through
`SPI_GETCLIENTAREAANIMATION`. People turn it off because motion makes them ill
or because it makes a slow machine feel slower. Honouring it is not decoration:
an app that keeps animating after being told not to is the reason the setting
exists.

Every animation in the app goes through `animate()`, so there is exactly one
place that can get this wrong.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPropertyAnimation,
)

from ..winapi import IS_WINDOWS
from .tokens import MOTION

_SPI_GETCLIENTAREAANIMATION = 0x1042

_user32 = ctypes.WinDLL("user32", use_last_error=True) if IS_WINDOWS else None


def animations_enabled() -> bool:
    """Whether Windows wants us to animate. True when we cannot tell."""
    if _user32 is None:
        return True
    enabled = ctypes.c_int(1)
    try:
        ok = _user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
    except OSError:  # pragma: no cover - the call is ancient and stable
        return True
    if not ok:
        return True
    return bool(enabled.value)


def curve(points: tuple[float, float, float, float] | None = None) -> QEasingCurve:
    """A cubic-bezier easing curve from the motion tokens."""
    control = points or MOTION.ease_out
    easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
    easing.addCubicBezierSegment(
        _point(control[0], control[1]), _point(control[2], control[3]), _point(1.0, 1.0)
    )
    return easing


def _point(x: float, y: float):
    from PySide6.QtCore import QPointF

    return QPointF(x, y)


def animate(
    target: QObject,
    prop: bytes,
    start,
    end,
    duration: int | None = None,
    easing: QEasingCurve | None = None,
    on_finished=None,
) -> QPropertyAnimation | None:
    """Animate a property, or jump straight to the end when motion is off.

    Returns the animation, or None when it was skipped — callers must not rely
    on being called back, which is why `on_finished` is invoked either way.
    """
    if not animations_enabled():
        target.setProperty(prop.decode() if isinstance(prop, bytes) else prop, end)
        if on_finished is not None:
            on_finished()
        return None

    animation = QPropertyAnimation(target, prop, target)
    animation.setDuration(duration if duration is not None else MOTION.normal)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(easing or curve())
    if on_finished is not None:
        animation.finished.connect(on_finished)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def fade_in(widget, duration: int | None = None) -> QPropertyAnimation | None:
    """Show a widget, fading its opacity up from nothing."""
    widget.setWindowOpacity(0.0)
    widget.show()
    return animate(
        widget,
        b"windowOpacity",
        0.0,
        1.0,
        duration if duration is not None else MOTION.quick,
    )


def fade_out(widget, duration: int | None = None, then=None):
    """Fade a widget away, then hide it (and call `then`, always)."""

    def done():
        widget.hide()
        widget.setWindowOpacity(1.0)
        if then is not None:
            then()

    return animate(
        widget,
        b"windowOpacity",
        widget.windowOpacity(),
        0.0,
        duration if duration is not None else MOTION.quick,
        on_finished=done,
    )
