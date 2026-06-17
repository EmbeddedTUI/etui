# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Workflow state machine.

The engine is UI-agnostic: it tracks per-step state and advances the wizard.
The owning tab drives subprocess execution and renders the state. Textual
``Message`` subclasses are provided for tabs that prefer a message-based flow.
"""

from __future__ import annotations

from enum import Enum

from textual.message import Message

from .schema import Workflow, WorkflowStep


class StepState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


ICONS: dict[StepState, str] = {
    StepState.PENDING: "○",
    StepState.ACTIVE: "►",
    StepState.RUNNING: "●",
    StepState.DONE: "✓",
    StepState.FAILED: "✗",
    StepState.SKIPPED: "⊘",
}


# --- Textual messages -------------------------------------------------------

class StepStarted(Message):
    def __init__(self, step_id: str) -> None:
        super().__init__()
        self.step_id = step_id


class StepCompleted(Message):
    def __init__(self, step_id: str, exit_code: int) -> None:
        super().__init__()
        self.step_id = step_id
        self.exit_code = exit_code


class StepFailed(Message):
    def __init__(self, step_id: str, exit_code: int) -> None:
        super().__init__()
        self.step_id = step_id
        self.exit_code = exit_code


class StepSkipped(Message):
    def __init__(self, step_id: str) -> None:
        super().__init__()
        self.step_id = step_id


class StepFailedPrompt(Message):
    def __init__(self, step_id: str, exit_code: int) -> None:
        super().__init__()
        self.step_id = step_id
        self.exit_code = exit_code


class WorkflowCompleted(Message):
    def __init__(self, total: int, done: int, failed: int, skipped: int) -> None:
        super().__init__()
        self.total = total
        self.done = done
        self.failed = failed
        self.skipped = skipped


class WorkflowAborted(Message):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


# --- Engine -----------------------------------------------------------------

class WorkflowEngine:
    """Tracks step state and enforces forward-only navigation."""

    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.states: list[StepState] = [StepState.PENDING for _ in workflow.steps]
        self.exit_codes: list[int | None] = [None for _ in workflow.steps]
        # index of the step currently being viewed/run
        self.current_index = 0
        # index of the active (next-to-run) step in the forward sequence
        self._active_index = 0
        if self.states:
            self.states[0] = StepState.ACTIVE

    # -- queries -----------------------------------------------------------
    @property
    def complete(self) -> bool:
        return all(
            s in (StepState.DONE, StepState.FAILED, StepState.SKIPPED)
            for s in self.states
        )

    def step_at(self, index: int) -> WorkflowStep:
        return self.workflow.steps[index]

    def state_at(self, index: int) -> StepState:
        return self.states[index]

    def current_step(self) -> WorkflowStep:
        return self.workflow.steps[self.current_index]

    def active_step(self) -> WorkflowStep | None:
        if self._active_index < len(self.workflow.steps):
            return self.workflow.steps[self._active_index]
        return None

    def is_viewing_active(self) -> bool:
        return self.current_index == self._active_index

    # -- transitions -------------------------------------------------------
    def mark_running(self) -> None:
        self.states[self._active_index] = StepState.RUNNING

    def mark_active(self) -> None:
        """Return the active step to ACTIVE (e.g. after a cancelled confirm)."""
        if self.states[self._active_index] == StepState.RUNNING:
            self.states[self._active_index] = StepState.ACTIVE

    def step_completed(self, exit_code: int = 0) -> None:
        idx = self._active_index
        self.states[idx] = StepState.DONE
        self.exit_codes[idx] = exit_code
        self._advance()

    def step_failed(self, exit_code: int) -> str:
        """Apply the active step's ``on_failure`` policy.

        Returns the policy that was applied: ``"stop"``, ``"continue"`` or
        ``"prompt"``. For ``prompt`` the caller must subsequently call
        :meth:`resolve_prompt`.
        """
        idx = self._active_index
        self.exit_codes[idx] = exit_code
        policy = self.workflow.steps[idx].on_failure
        if policy == "continue":
            self.states[idx] = StepState.FAILED
            self._advance()
        elif policy == "prompt":
            self.states[idx] = StepState.FAILED
        else:  # stop
            self.states[idx] = StepState.FAILED
        return policy

    def resolve_prompt(self, cont: bool) -> None:
        """Resolve a ``prompt`` failure: continue to next step or stop."""
        if cont:
            self._advance()
        # stop: leave FAILED in place; workflow is effectively aborted

    def skip_current(self) -> bool:
        """Skip the active step if it allows skipping. Returns success."""
        idx = self._active_index
        if not self.workflow.steps[idx].allow_skip:
            return False
        if self.states[idx] not in (StepState.ACTIVE, StepState.RUNNING):
            return False
        self.states[idx] = StepState.SKIPPED
        self._advance()
        return True

    def _advance(self) -> None:
        nxt = self._active_index + 1
        self._active_index = nxt
        if nxt < len(self.workflow.steps):
            self.states[nxt] = StepState.ACTIVE
            self.current_index = nxt
        else:
            self.current_index = min(self._active_index, len(self.workflow.steps) - 1)

    # -- navigation (review only) -----------------------------------------
    def can_select(self, index: int) -> bool:
        """Completed/skipped/active steps are selectable; pending are not."""
        if index == self._active_index:
            return True
        return self.states[index] in (
            StepState.DONE,
            StepState.FAILED,
            StepState.SKIPPED,
        )

    def select(self, index: int) -> bool:
        if 0 <= index < len(self.workflow.steps) and self.can_select(index):
            self.current_index = index
            return True
        return False

    def review_previous(self) -> bool:
        for i in range(self.current_index - 1, -1, -1):
            if self.can_select(i):
                self.current_index = i
                return True
        return False

    # -- summary -----------------------------------------------------------
    def summary(self) -> tuple[int, int, int, int]:
        total = len(self.states)
        done = sum(1 for s in self.states if s == StepState.DONE)
        failed = sum(1 for s in self.states if s == StepState.FAILED)
        skipped = sum(1 for s in self.states if s == StepState.SKIPPED)
        return total, done, failed, skipped
