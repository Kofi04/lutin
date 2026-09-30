"""The bridge between Claude Code's hooks and Little Wizard."""

from .protocol import PIPE_NAME
from .server import HookEvent, HookServer

__all__ = ["PIPE_NAME", "HookEvent", "HookServer"]
