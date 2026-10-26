"""Test-only tools for crash/resume tests. Never registered by the app."""

import os

from pydantic import BaseModel, ConfigDict

from orion.tools.base import Idempotency, SideEffect, Tool, ToolSpec
from orion.tools.files.workspace import resolve_in_workspace


class PathArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class Out(BaseModel):
    evidence: str


class _Base(Tool):
    crash = False          # the crashing subprocess sets this to True
    calls = 0


class CrashWriteTool(_Base):
    """Writes a file, then (if crash) kills the whole process before reporting back."""
    spec = ToolSpec(id="test.crash_write", version="1", description="test", input_model=PathArgs, output_model=Out,
                    permissions=frozenset(), side_effect=SideEffect.REVERSIBLE, timeout_s=10,
                    idempotency=Idempotency.NON_IDEMPOTENT, verification="test")

    def run(self, args, ctx):
        type(self).calls += 1
        p = resolve_in_workspace(ctx.workspace, args.path)
        with open(p, "xb") as f:
            f.write(b"written before crash")
            f.flush()
            os.fsync(f.fileno())
        if self.crash:
            os._exit(3)
        return Out(evidence=f"wrote {args.path}")


class CrashReadTool(_Base):
    """Read-only; crashes the process mid-call if crash is set."""
    spec = ToolSpec(id="test.crash_read", version="1", description="test", input_model=PathArgs, output_model=Out,
                    permissions=frozenset(), side_effect=SideEffect.READ_ONLY, timeout_s=10,
                    idempotency=Idempotency.IDEMPOTENT, verification="test")

    def run(self, args, ctx):
        type(self).calls += 1
        if self.crash:
            os._exit(3)
        return Out(evidence=f"read {args.path}")
