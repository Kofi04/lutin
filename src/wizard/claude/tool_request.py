"""One action Claude wants to take, as the approval card shows it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRequest:
    """One action Claude wants to take, described for a human."""

    tool: str  # "Bash", "Edit", ...
    detail: str  # the command, the file being edited...
    project: str = ""  # working directory name, when known

    def title(self) -> str:
        where = f" dans {self.project}" if self.project else ""
        return f"Claude veut utiliser {self.tool}{where}"
