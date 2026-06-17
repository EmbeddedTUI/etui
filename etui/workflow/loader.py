# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Loading and discovery of workflow YAML files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .schema import Workflow, WorkflowValidationError, build_workflow


def builtin_dir() -> Path:
    """Directory of workflow YAML files bundled with the etui package."""
    return Path(__file__).resolve().parent.parent / "workflows"


def load(path: Path) -> Workflow:
    """Read, parse, and validate a workflow YAML file.

    Raises :class:`WorkflowValidationError` on parse or validation failure.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowValidationError(f"cannot read file: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowValidationError(f"invalid YAML: {exc}") from exc

    return build_workflow(data)


@dataclass(frozen=True)
class WorkflowMeta:
    path: Path
    name: str
    description: str
    step_count: int
    mtime: float


def list_workflows(directory: Path) -> list[WorkflowMeta]:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` workflow files.

    Files that fail to parse are skipped silently so a single bad file does
    not break discovery. Results are sorted by name.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    metas: list[WorkflowMeta] = []
    seen: set[Path] = set()
    for pattern in ("*.yaml", "*.yml"):
        for path in directory.glob(pattern):
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            try:
                wf = load(path)
            except WorkflowValidationError:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            metas.append(
                WorkflowMeta(
                    path=resolved,
                    name=wf.name,
                    description=wf.description,
                    step_count=len(wf.steps),
                    mtime=mtime,
                )
            )

    metas.sort(key=lambda m: m.name.lower())
    return metas
