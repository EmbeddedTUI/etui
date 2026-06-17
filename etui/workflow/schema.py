# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Workflow data model, validation, and variable resolution."""

from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from typing import Any, Literal

MODES = ("auto", "manual")
ON_FAILURE = ("stop", "continue", "prompt")
TITLE_MAX = 20


class WorkflowValidationError(Exception):
    """Raised when a workflow definition is invalid.

    Carries the field path that failed so the UI can show a useful message.
    """

    def __init__(self, message: str, *, field_path: str = "") -> None:
        self.field_path = field_path
        if field_path:
            message = f"{field_path}: {message}"
        super().__init__(message)


@dataclass
class WorkflowStep:
    id: str
    title: str
    description: str = ""               # Markdown
    commands: list[str] = field(default_factory=list)
    mode: Literal["auto", "manual"] = "manual"
    cwd: str = ""                       # relative to repo root; "" = repo root
    confirm: bool = False
    allow_skip: bool = False
    on_failure: Literal["stop", "continue", "prompt"] = "stop"
    timeout: int = 0                   # 0 = inherit global default

    @property
    def label(self) -> str:
        """Title truncated to TITLE_MAX characters for tab/list display."""
        if len(self.title) <= TITLE_MAX:
            return self.title
        return self.title[: TITLE_MAX - 1] + "…"


@dataclass
class Workflow:
    name: str
    description: str = ""
    version: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    steps: list[WorkflowStep] = field(default_factory=list)


_TOP_LEVEL_KEYS = {"name", "description", "version", "variables", "steps"}
_STEP_KEYS = {
    "id",
    "title",
    "description",
    "commands",
    "mode",
    "cwd",
    "confirm",
    "allow_skip",
    "on_failure",
    "timeout",
}


def build_workflow(data: Any) -> Workflow:
    """Validate a parsed YAML mapping and build a :class:`Workflow`.

    Raises :class:`WorkflowValidationError` on any problem.
    """
    if not isinstance(data, dict):
        raise WorkflowValidationError("workflow must be a mapping")

    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise WorkflowValidationError(
            f"unknown keys: {', '.join(sorted(unknown))}"
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowValidationError("required non-empty string", field_path="name")

    variables = data.get("variables", {}) or {}
    if not isinstance(variables, dict):
        raise WorkflowValidationError("must be a mapping", field_path="variables")
    variables = {str(k): str(v) for k, v in variables.items()}

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowValidationError("at least one step is required", field_path="steps")

    steps: list[WorkflowStep] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_steps):
        steps.append(_build_step(raw, index, seen_ids))

    return Workflow(
        name=name.strip(),
        description=str(data.get("description", "")),
        version=str(data.get("version", "")),
        variables=variables,
        steps=steps,
    )


def _build_step(raw: Any, index: int, seen_ids: set[str]) -> WorkflowStep:
    where = f"steps[{index}]"
    if not isinstance(raw, dict):
        raise WorkflowValidationError("must be a mapping", field_path=where)

    unknown = set(raw) - _STEP_KEYS
    if unknown:
        raise WorkflowValidationError(
            f"unknown keys: {', '.join(sorted(unknown))}", field_path=where
        )

    step_id = raw.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise WorkflowValidationError("required non-empty string", field_path=f"{where}.id")
    step_id = step_id.strip()
    if step_id in seen_ids:
        raise WorkflowValidationError(f"duplicate id '{step_id}'", field_path=f"{where}.id")
    seen_ids.add(step_id)

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise WorkflowValidationError(
            "required non-empty string", field_path=f"{where}.title"
        )

    raw_commands = raw.get("commands", []) or []
    if not isinstance(raw_commands, list) or not all(isinstance(c, str) for c in raw_commands):
        raise WorkflowValidationError(
            "must be a list of strings", field_path=f"{where}.commands"
        )

    mode = raw.get("mode", "manual")
    if mode not in MODES:
        raise WorkflowValidationError(
            f"must be one of {MODES}", field_path=f"{where}.mode"
        )

    on_failure = raw.get("on_failure", "stop")
    if on_failure not in ON_FAILURE:
        raise WorkflowValidationError(
            f"must be one of {ON_FAILURE}", field_path=f"{where}.on_failure"
        )

    timeout = raw.get("timeout", 0)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
        raise WorkflowValidationError(
            "must be a non-negative integer", field_path=f"{where}.timeout"
        )

    return WorkflowStep(
        id=step_id,
        title=title.strip(),
        description=str(raw.get("description", "")),
        commands=list(raw_commands),
        mode=mode,
        cwd=str(raw.get("cwd", "")),
        confirm=bool(raw.get("confirm", False)),
        allow_skip=bool(raw.get("allow_skip", False)),
        on_failure=on_failure,
        timeout=timeout,
    )


def resolve(cmd: str, variables: dict[str, str]) -> str:
    """Substitute ``$VAR`` / ``${VAR}`` in *cmd*.

    Workflow *variables* override the OS environment. Unknown variables are
    left intact (``safe_substitute``), never raising.
    """
    env = {**os.environ, **variables}
    return string.Template(cmd).safe_substitute(env)
