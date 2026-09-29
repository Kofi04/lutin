"""Capturing what the user wants to show Claude: a region, a window, a file."""

from .prepare import Capture, CaptureKind, estimate_tokens, fit_within, prepare

__all__ = [
    "Capture",
    "CaptureKind",
    "estimate_tokens",
    "fit_within",
    "prepare",
]
