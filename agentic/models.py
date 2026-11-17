"""Shared data model for the agentic engineering system."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"      # blocked because an upstream task failed or was rejected
    REJECTED = "REJECTED"    # a human declined at an approval gate
    RECOVERED = "RECOVERED"  # failed, but the orchestrator spawned a repair + retry cycle


class TransientError(Exception):
    """A failure worth retrying with backoff (timeout, flaky tool)."""


class ValidationFailed(Exception):
    """Validation found problems. `details` feeds the repair agent."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class Unrecoverable(Exception):
    """No automatic recovery is possible: escalate to a human."""


class UnsupportedRequirement(Unrecoverable):
    """The offline engine has no template for this requirement."""


class Rejected(Exception):
    """A human rejected a gate."""


@dataclass
class Outcome:
    """What an agent returns. `spawn` lets an agent extend the task graph at run time."""
    summary: str = ""
    data: dict = field(default_factory=dict)
    spawn: list = field(default_factory=list)


@dataclass
class Task:
    id: str
    agent: str
    deps: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    title: str = ""
    rationale: str = ""
    max_attempts: int = 3
    status: Status = Status.PENDING
    attempts: int = 0
    summary: str = ""
    error: str = ""
    started: float = 0.0
    ended: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "agent": self.agent, "deps": list(self.deps), "params": self.params,
            "title": self.title, "rationale": self.rationale, "max_attempts": self.max_attempts,
            "status": self.status.value, "attempts": self.attempts, "summary": self.summary,
            "error": self.error, "started": self.started, "ended": self.ended,
        }

    @staticmethod
    def from_dict(d: dict) -> "Task":
        d = dict(d)
        d["status"] = Status(d["status"])
        return Task(**d)
