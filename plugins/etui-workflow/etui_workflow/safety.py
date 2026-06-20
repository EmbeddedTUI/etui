# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Destructive-command denylist used to gate workflow execution."""

from __future__ import annotations

import re

# Patterns describing commands considered destructive enough to warrant an
# explicit confirmation even when the workflow step sets ``confirm: false``.
DENYLIST_PATTERNS: tuple[str, ...] = (
    r"\brm\b[^\n]*\s-[a-zA-Z]*r[a-zA-Z]*f|\brm\b[^\n]*\s-[a-zA-Z]*f[a-zA-Z]*r",  # rm -rf / -fr
    r"\bmkfs\b",
    r"\bdd\b[^\n]*\bif=",
    r"\btruncate\b",
    r"\bDROP\s+TABLE\b",
    r"\bchmod\b[^\n]*\b[0-7]*[0-7]*7[0-7]{2}\b",   # world-writable/exec masks
    r">\s*/dev/sd[a-z]",                            # raw disk write
    r"\bgit\b[^\n]*\breset\b[^\n]*--hard",          # destructive working-tree reset
)


class DenylistChecker:
    """Checks commands against the destructive-command denylist.

    In ``strict`` mode (default) a match means the command requires explicit
    confirmation. In ``permissive`` mode the denylist is bypassed entirely
    (used by the ``--workflow-unsafe`` automation flag).
    """

    def __init__(self, level: str = "strict") -> None:
        self.level = level
        self._patterns = [re.compile(p, re.IGNORECASE) for p in DENYLIST_PATTERNS]

    @property
    def strict(self) -> bool:
        return self.level == "strict"

    def matches(self, cmd: str) -> bool:
        """Return True if *cmd* matches any denylist pattern (ignores mode)."""
        return any(p.search(cmd) for p in self._patterns)

    def requires_confirm(self, cmd: str) -> bool:
        """Return True if *cmd* must be confirmed under the current mode."""
        if not self.strict:
            return False
        return self.matches(cmd)
