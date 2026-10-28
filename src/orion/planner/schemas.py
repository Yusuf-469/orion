"""Goal and plan schemas (spec 5.1, 5.2).

A plan is data, not code: every step names a registered tool and literal
arguments, or a reference "${step_id.field}" to an output field of an earlier
step it depends on. Side effects are never stated in the plan; they come from
the tool registry.
"""

from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

STEP_ID = r"^[a-z][a-z0-9_]{0,39}$"
REF = re.compile(r"^\$\{([a-z][a-z0-9_]{0,39})\.([a-z_][a-z0-9_]*)\}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- checks (pre/postconditions and goal completion) ----------------------------

class FileExists(_Strict):
    kind: Literal["file_exists"] = "file_exists"
    path: str


class FileAbsent(_Strict):
    kind: Literal["file_absent"] = "file_absent"
    path: str


class FileContains(_Strict):
    kind: Literal["file_contains"] = "file_contains"
    path: str
    text: str
    ignore_case: bool = False


class FilesIdentical(_Strict):
    kind: Literal["files_identical"] = "files_identical"
    a: str
    b: str


class AppWindowOpen(_Strict):
    kind: Literal["app_window_open"] = "app_window_open"
    app: Literal["notepad", "calculator", "paint"]


class NotepadShows(_Strict):
    """ORION's Notepad tab for `path` is active and shows exactly the file's text on disk."""
    kind: Literal["notepad_shows"] = "notepad_shows"
    path: str


Check = Annotated[Union[FileExists, FileAbsent, FileContains, FilesIdentical, AppWindowOpen, NotepadShows],
                  Field(discriminator="kind")]


# --- goal --------------------------------------------------------------------------

class Constraints(_Strict):
    preserve_source_files: bool = True     # no delete steps
    allow_app_launch: bool = True
    allow_delete: bool = False


class Goal(_Strict):
    goal_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    request: str                           # the user's words, verbatim
    objective: str
    constraints: Constraints = Constraints()
    deliverables: list[str] = []
    authorized_outputs: list[str] = []     # workspace-relative paths/dirs non-read-only steps may touch
    completion_checks: list[Check] = []
    risk: Literal["low", "medium", "high"] = "low"
    missing_info: list[str] = []           # questions to ask before planning can finish


# --- plan --------------------------------------------------------------------------

class PlanStep(_Strict):
    id: str = Field(pattern=STEP_ID)
    description: str
    tool_id: str
    args: dict[str, Any] = {}
    depends_on: list[str] = []
    postconditions: list[Check] = []
    checkpoint_before: bool = False


class Plan(_Strict):
    goal_id: str
    steps: list[PlanStep] = Field(min_length=1, max_length=50)


class Outcome(StrEnum):
    """Task-level outcome (spec 9)."""
    VERIFIED_COMPLETE = "verified_complete"
    PARTIALLY_COMPLETE = "partially_complete"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNVERIFIED = "unverified"
    WAITING_FOR_USER = "waiting_for_user"
    DRY_RUN = "dry_run"


def parse_ref(value: Any) -> tuple[str, str] | None:
    if isinstance(value, str):
        m = REF.match(value)
        if m:
            return m.group(1), m.group(2)
    return None
