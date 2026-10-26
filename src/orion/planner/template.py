"""Deterministic template planner (always available, no model).

Understands a small, documented phrase set and chains clauses joined by
"then" / "and then" / ";". Anything it does not understand is reported as
unsupported instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from orion.planner.schemas import (
    AppWindowOpen, Constraints, FileAbsent, FileContains, FileExists, FilesIdentical, Goal, Plan, PlanStep,
)
from orion.planner.service import Proposal

_P = r'(?:"([^"]+)"|\'([^\']+)\'|(\S+))'
_SPLIT = re.compile(r"\s*(?:;|,?\s+and then\s+|,?\s+then\s+)\s*", re.IGNORECASE)
_APPS = {"notepad": "notepad", "calculator": "calculator", "calc": "calculator", "paint": "paint",
         "mspaint": "paint"}

SUPPORTED_PHRASES = [
    'create a file NAME containing TEXT',
    'copy SRC to DST',
    'back up SRC [to DST]',
    'move SRC to DST',
    'put the contents of SRC into DST',
    'read NAME',
    'list files [in DIR]',
    'delete NAME',
    'open notepad | calculator | paint',
]


def _path(m: re.Match, group_base: int) -> str:
    return next(g for g in m.groups()[group_base:group_base + 3] if g)


@dataclass
class _Draft:
    steps: list[PlanStep] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    deletes: bool = False
    launches: bool = False
    last_path: str | None = None

    def add(self, tool: str, args: dict, desc: str, post=(), *, writes=(), checkpoint=False) -> str:
        sid = f"s{len(self.steps) + 1}"
        deps = [self.steps[-1].id] if self.steps else []
        self.steps.append(PlanStep(id=sid, description=desc, tool_id=tool, args=args, depends_on=deps,
                                   postconditions=list(post), checkpoint_before=checkpoint))
        self.outputs.extend(w for w in writes if w not in self.outputs)
        return sid


def _resolve(word: str, d: _Draft) -> str | None:
    if word.lower() in ("it", "the original", "the file", "original"):
        return d.last_path
    return word


class TemplatePlanner:
    name = "template"

    def __init__(self) -> None:
        self._rules: list[tuple[re.Pattern, Callable[[re.Match, _Draft], None]]] = [
            (re.compile(rf"^(?:create|make|write)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?(?:file|note)"
                        rf"(?:\s+(?:named|called))?\s+{_P}\s+(?:containing|with(?:\s+the)?\s+text|saying|with)"
                        rf"\s+(.+)$", re.I | re.S), self._create),
            (re.compile(rf"^(?:create|make|write)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?(?:file|note)"
                        rf"(?:\s+(?:named|called))?\s+{_P}$", re.I), self._create_no_text),
            (re.compile(r"^(?:create|make|write)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?(?:file|note)\b.*$", re.I),
             self._create_no_name),
            (re.compile(rf"^(?:put|copy|write)\s+(?:the\s+)?(?:contents?|text)\s+of\s+{_P}\s+(?:into|to)\s+"
                        rf"(?:a\s+)?(?:new\s+)?(?:file\s+)?{_P}$", re.I), self._contents),
            (re.compile(rf"^(?:copy|duplicate)\s+{_P}\s+(?:to|as|into)\s+{_P}$", re.I), self._copy),
            (re.compile(rf"^(?:copy|duplicate)\s+{_P}$", re.I), self._copy_no_dst),
            (re.compile(rf"^back\s*up\s+{_P}(?:\s+(?:to|as)\s+{_P})?$", re.I), self._backup),
            (re.compile(rf"^move\s+{_P}\s+(?:to|into)\s+{_P}$", re.I), self._move),
            (re.compile(r"^(?:open|launch|start|run)\s+(?:the\s+)?(notepad|calculator|calc|paint|mspaint)"
                        r"(?:\s+app)?$", re.I), self._launch),
            (re.compile(r"^(?:list|show)\s+(?:the\s+|all\s+)?(?:files|workspace|folder)"
                        rf"(?:\s+in\s+{_P})?$", re.I), self._list),
            (re.compile(rf"^(?:read|show)\s+(?:the\s+)?(?:file\s+)?{_P}$", re.I), self._read),
            (re.compile(r"^(?:delete|remove)\s+(?:the\s+)?(?:file\s+)?"
                        r"(the original|original|it|\"[^\"]+\"|'[^']+'|\S+)$", re.I), self._delete),
        ]

    # --- rules -----------------------------------------------------------------

    def _create(self, m, d):
        path, text = _path(m, 0), m.group(4).strip().strip('"\'')
        d.add("files.write_new", {"path": path, "content": text}, f"create {path}",
              [FileContains(path=path, text=text)], writes=[path])
        d.last_path = path

    def _create_no_text(self, m, d):
        d.missing.append(f"What should '{_path(m, 0)}' contain?")

    def _create_no_name(self, m, d):
        d.missing.append("What should the new file be called (a name inside the workspace)?")

    def _contents(self, m, d):
        src, dst = _path(m, 0), _path(m, 3)
        rid = d.add("files.read", {"path": src}, f"read {src}")
        d.add("files.write_new", {"path": dst, "content": f"${{{rid}.text}}"}, f"write contents of {src} to {dst}",
              [FilesIdentical(a=src, b=dst)], writes=[dst])
        d.last_path = src

    def _copy(self, m, d):
        src, dst = _resolve(_path(m, 0), d), _path(m, 3)
        d.add("files.copy", {"src": src, "dst": dst}, f"copy {src} to {dst}",
              [FilesIdentical(a=src, b=dst)], writes=[dst])
        d.last_path = src

    def _copy_no_dst(self, m, d):
        d.missing.append(f"Where should the copy of '{_path(m, 0)}' go?")

    def _backup(self, m, d):
        src = _resolve(_path(m, 0), d)
        dst = _path(m, 3) if any(m.groups()[3:6]) else f"{src}.bak"
        d.add("files.copy", {"src": src, "dst": dst}, f"back up {src} to {dst}",
              [FilesIdentical(a=src, b=dst)], writes=[dst])
        d.last_path = src

    def _move(self, m, d):
        src, dst = _path(m, 0), _path(m, 3)
        d.add("files.copy", {"src": src, "dst": dst}, f"copy {src} to {dst}",
              [FilesIdentical(a=src, b=dst)], writes=[dst])
        d.add("files.delete", {"path": src}, f"delete original {src}", [FileAbsent(path=src)],
              writes=[src], checkpoint=True)
        d.deletes = True
        d.last_path = dst

    def _launch(self, m, d):
        app = _APPS[m.group(1).lower()]
        d.add("app.launch", {"app": app}, f"open {app}", [AppWindowOpen(app=app)])
        d.launches = True

    def _list(self, m, d):
        path = _path(m, 0) if any(m.groups()[0:3]) else "."
        d.add("files.list", {"path": path}, f"list {path}")

    def _read(self, m, d):
        path = _resolve(_path(m, 0), d)
        d.add("files.read", {"path": path}, f"read {path}")
        d.last_path = path

    def _delete(self, m, d):
        word = m.group(1).strip('"\'')
        path = _resolve(word, d)
        if path is None:
            d.missing.append(f"Which file does '{word}' refer to?")
            return
        d.add("files.delete", {"path": path}, f"delete {path}", [FileAbsent(path=path)],
              writes=[path], checkpoint=True)
        d.deletes = True

    # --- entry -------------------------------------------------------------------

    def propose(self, request: str) -> Proposal:
        text = request.strip().rstrip(".")
        clauses = [c for c in _SPLIT.split(text) if c]
        if not clauses:
            return Proposal(None, None, "empty request")
        d = _Draft()
        for clause in clauses:
            for pattern, handler in self._rules:
                m = pattern.match(clause)
                if m:
                    handler(m, d)
                    break
            else:
                return Proposal(None, None,
                                f"The template planner does not understand {clause!r}. "
                                f"Supported: {'; '.join(SUPPORTED_PHRASES)}.")

        goal = Goal(
            request=request,
            objective=text,
            constraints=Constraints(preserve_source_files=not d.deletes, allow_delete=d.deletes,
                                    allow_app_launch=True),
            authorized_outputs=d.outputs,
            completion_checks=_final_checks(d.steps),
            risk="medium" if d.deletes else "low",
            missing_info=d.missing,
        )
        if d.missing or not d.steps:
            return Proposal(goal, None, "more information needed")
        return Proposal(goal, Plan(goal_id=goal.goal_id, steps=d.steps))


def _final_checks(steps: list[PlanStep]):
    """Goal checks = step postconditions that later steps do not undo (e.g. a moved source)."""
    checks = []
    for i, s in enumerate(steps):
        later_deleted = {t.args.get("path") for t in steps[i + 1:] if t.tool_id == "files.delete"}
        for c in s.postconditions:
            paths = {getattr(c, a) for a in ("path", "a", "b") if hasattr(c, a)}
            if isinstance(c, FileAbsent) or not (paths & later_deleted):
                checks.append(c)
            elif isinstance(c, FilesIdentical):
                checks.append(FileExists(path=c.b))  # the copy must still exist
    return checks
