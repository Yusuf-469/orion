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
    AppWindowOpen, Constraints, FileAbsent, FileContains, FileExists, FilesIdentical, Goal, NotepadShows, Plan,
    PlanStep,
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
    'save the table from PAGE.html as FILE.csv',
    'summarize FILE.csv into FILE.txt',
    'open FILE in notepad',
    'type "TEXT" into FILE in notepad',
    'close FILE in notepad',
    'fill the form on PAGE.html with name "..." email "..." (stops before submit)',
]

_FIELD = re.compile(r'([A-Za-z][\w ]*?)\s*[:=]?\s*"([^"]*)"')


def split_clauses(text: str) -> list[str]:
    """Split on then / and then / ; but never inside "double" or 'single' quotes."""
    quoted: list[str] = []

    def hide(m: re.Match) -> str:
        quoted.append(m.group(0))
        return f"\x00{len(quoted) - 1}\x00"

    masked = re.sub(r'"[^"]*"|\'[^\']*\'', hide, text)
    parts = [p for p in _SPLIT.split(masked) if p]
    return [re.sub(r"\x00(\d+)\x00", lambda m: quoted[int(m.group(1))], p) for p in parts]


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
    open_in_notepad: set = field(default_factory=set)

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
            (re.compile(rf"^(?:save|extract|export|get)\s+the\s+table\s+(?:from|on|in)\s+{_P}\s+(?:as|into|to)\s+{_P}$",
                        re.I), self._table_to_csv),
            (re.compile(rf"^summari[sz]e\s+{_P}\s+(?:into|to|as)\s+{_P}$", re.I), self._summarize),
            (re.compile(rf"^open\s+{_P}\s+in\s+notepad$", re.I), self._np_open),
            (re.compile(rf"^(?:type|write|put)\s+(?:\"([^\"]*)\"|'([^']*)'|(.+?))\s+into\s+{_P}\s+(?:in|using|with)\s+"
                        rf"notepad$", re.I | re.S), self._np_type),
            (re.compile(rf"^close\s+{_P}\s+in\s+notepad$", re.I), self._np_close),
            (re.compile(rf"^fill\s+(?:in\s+)?the\s+form\s+(?:on|in)\s+{_P}\s+with\s+(.+)$", re.I | re.S),
             self._fill_form),
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

    def _table_to_csv(self, m, d):
        page, csv_path = _path(m, 0), _path(m, 3)
        rid = d.add("browser.read_table", {"page": page}, f"read the table on {page}")
        d.add("docs.write_csv", {"path": csv_path, "headers": f"${{{rid}.headers}}", "rows": f"${{{rid}.rows}}"},
              f"save the table as {csv_path}", [FileExists(path=csv_path)], writes=[csv_path])
        d.last_path = csv_path

    def _summarize(self, m, d):
        src, dst = _resolve(_path(m, 0), d), _path(m, 3)
        d.add("docs.summarize_csv", {"src": src, "dst": dst}, f"summarize {src} into {dst}",
              [FileContains(path=dst, text="Rows:")], writes=[dst])
        d.last_path = dst

    def _np_open(self, m, d):
        path = _resolve(_path(m, 0), d)
        d.add("notepad.open_file", {"path": path}, f"open {path} in Notepad", [NotepadShows(path=path)],
              writes=[path])
        d.last_path = path
        d.open_in_notepad.add(path.lower())

    def _np_type(self, m, d):
        text = next(g for g in m.groups()[0:3] if g is not None)
        path = _resolve(_path(m, 3), d)
        if path.lower() not in d.open_in_notepad:
            d.add("notepad.open_file", {"path": path}, f"open {path} in Notepad", [NotepadShows(path=path)],
                  writes=[path])
            d.open_in_notepad.add(path.lower())
        d.add("notepad.set_text", {"path": path, "text": text}, f"type the text into {path} in Notepad and save",
              [FileContains(path=path, text=text), NotepadShows(path=path)], writes=[path])
        d.last_path = path

    def _np_close(self, m, d):
        path = _resolve(_path(m, 0), d)
        d.add("notepad.close_tab", {"path": path}, f"close {path} in Notepad", writes=[path])
        d.open_in_notepad.discard(path.lower())

    def _fill_form(self, m, d):
        page = _path(m, 0)
        pairs = _FIELD.findall(m.group(4))
        if not pairs:
            d.missing.append('Which fields and values? e.g. name "Asha" email "asha@example.com"')
            return
        fields = {name.strip().removeprefix("and ").strip(): value for name, value in pairs}
        d.add("browser.fill_form", {"page": page, "fields": fields},
              f"fill {len(fields)} field(s) on {page} and stop before submitting")

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
        clauses = split_clauses(text)
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
        later_closed = {t.args.get("path") for t in steps[i + 1:] if t.tool_id == "notepad.close_tab"}
        for c in s.postconditions:
            if isinstance(c, NotepadShows) and c.path in later_closed:
                continue   # a later step closes that tab on purpose
            paths = {getattr(c, a) for a in ("path", "a", "b") if hasattr(c, a)}
            if isinstance(c, FileAbsent) or not (paths & later_deleted):
                checks.append(c)
            elif isinstance(c, FilesIdentical):
                checks.append(FileExists(path=c.b))  # the copy must still exist
    return checks
