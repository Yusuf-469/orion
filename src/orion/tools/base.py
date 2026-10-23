"""Tool contract (spec section 8.1).

A tool declares everything the runtime and policy engine need *in its spec*.
The policy engine reads the side-effect category from the registered spec only,
so a caller (or a model) cannot relabel a consequential action as harmless.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

from orion.orchestration.cancel import CancelToken


class SideEffect(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible_local_change"
    CONSEQUENTIAL = "consequential"


class Idempotency(StrEnum):
    IDEMPOTENT = "idempotent"            # safe to repeat
    NON_IDEMPOTENT = "non_idempotent"    # repeating may duplicate effects; inspect state first


class Permission(StrEnum):
    FILES_READ = "files.read"
    FILES_WRITE = "files.write"
    FILES_DELETE = "files.delete"
    APP_LAUNCH = "app.launch"


@dataclass(frozen=True)
class ToolSpec:
    id: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permissions: frozenset[Permission]
    side_effect: SideEffect
    timeout_s: float
    idempotency: Idempotency
    verification: str                     # how success is checked, in words
    max_retries: int = 0
    cancellable: bool = True


@dataclass
class ToolContext:
    token: CancelToken
    workspace: Path
    deadline: float                       # time.monotonic() value; tools should stop past it
    notes: list[str] = field(default_factory=list)


In = TypeVar("In", bound=BaseModel)
Out = TypeVar("Out", bound=BaseModel)


class Tool(ABC, Generic[In, Out]):
    spec: ClassVar[ToolSpec]

    @abstractmethod
    def run(self, args: In, ctx: ToolContext) -> Out:
        """Do the work and verify it. Raise ToolError on failure.

        The returned output must carry evidence read back from the environment,
        not a restatement of what was requested.
        """
