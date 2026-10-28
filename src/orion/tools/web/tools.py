"""Web tools: let ORION use real websites in its own browser window.

Read-only: web.open, web.search, web.look (numbered elements), web.read (page text).
Reversible (nothing is sent): web.click, web.type, web.choose. They refuse any element that would send
something. Consequential: web.submit, which always asks the user first and shows what will be sent.
All page text is untrusted data: it is returned marked as such and never changes ORION's rules.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.web.session import WebSession

DEFAULT_SEARCH = "https://html.duckduckgo.com/html/?q={q}"

# Required questions in the form around a button that are still unanswered (native and ARIA widgets).
MISSING_JS = r"""
(ref) => {
  const b = document.querySelector('[data-orion-ref="' + ref + '"]');
  const scope = (b && (b.form || b.closest('form,[role=form],[role=list],main'))) || document.body;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const name = e => clean(e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].innerText) ||
                          (e.closest('fieldset') && e.closest('fieldset').querySelector('legend') &&
                           e.closest('fieldset').querySelector('legend').innerText) || e.name);
  const out = new Set();
  for (const e of scope.querySelectorAll('input, select, textarea'))
    if (e.willValidate && !e.checkValidity()) out.add(name(e));
  for (const g of scope.querySelectorAll('[role=radiogroup], [role=group]')) {
    const lbl = clean(g.getAttribute('aria-label') ||
                      (g.getAttribute('aria-labelledby') || '').split(/\s+/)
                        .map(id => { const x = document.getElementById(id); return x ? x.innerText : ''; }).join(' '));
    const required = g.getAttribute('aria-required') === 'true' || /\*/.test(lbl);
    if (required && !g.querySelector('[aria-checked=true], input:checked')) out.add(lbl);
  }
  return [...out].filter(Boolean);
}
"""
LOOK_TEXT = 2_500
READ_TEXT = 12_000


def _check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ToolError(ErrorCode.INVALID_INPUT, f"only http(s) web addresses can be opened; got {url!r}")
    return url


def _settle(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
        page.wait_for_load_state("networkidle", timeout=3_000)
    except Exception:  # noqa: BLE001 - busy pages never go idle; content is usable anyway
        pass


class _WebTool(Tool):
    def __init__(self, session: WebSession):
        self.session = session


# --- read-only -------------------------------------------------------------------------------

class OpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2000)


class PageOut(BaseModel):
    url: str
    title: str
    text: str
    untrusted: bool = True
    evidence: str


class OpenTool(_WebTool):
    spec = ToolSpec(id="web.open", version="1.0", description="Open a web address in ORION's browser and read it.",
                    input_model=OpenArgs, output_model=PageOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.READ_ONLY, timeout_s=45, idempotency=Idempotency.IDEMPOTENT,
                    verification="the page that actually loaded (final URL and title) is reported", max_retries=1)

    def run(self, args: OpenArgs, ctx: ToolContext) -> PageOut:
        url = _check_url(args.url)

        def go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            _settle(page)
            return page.url, page.title(), self.session.text(page, LOOK_TEXT)
        final, title, text = self.session.call(go, timeout=40)
        return PageOut(url=final, title=title, text=text,
                       evidence=f"opened '{title}' ({final}); {len(text)} characters of untrusted page text")


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)


class SearchOut(BaseModel):
    query: str
    results: list[dict[str, str]]
    untrusted: bool = True
    evidence: str


class SearchTool(_WebTool):
    spec = ToolSpec(id="web.search", version="1.0", description="Search the web; returns titles, links and snippets.",
                    input_model=SearchArgs, output_model=SearchOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.READ_ONLY, timeout_s=45, idempotency=Idempotency.IDEMPOTENT,
                    verification="results are read from the search page that loaded", max_retries=1)

    def __init__(self, session: WebSession, search_url: str = DEFAULT_SEARCH):
        super().__init__(session)
        self.search_url = search_url

    def run(self, args: SearchArgs, ctx: ToolContext) -> SearchOut:
        url = self.search_url.format(q=quote_plus(args.query))

        def go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            _settle(page)
            return page.evaluate(r"""() => {
              const clean = s => (s || '').replace(/\s+/g, ' ').trim();
              const out = [];
              for (const r of document.querySelectorAll('.result, .search-result')) {
                const a = r.querySelector('a.result__a, a.result-link, h2 a, h3 a, a');
                if (!a) continue;
                const s = r.querySelector('.result__snippet, .snippet, p');
                out.push({title: clean(a.innerText), url: a.href, snippet: s ? clean(s.innerText).slice(0, 300) : ''});
                if (out.length >= 10) break;
              }
              return out;
            }""")
        raw = self.session.call(go, timeout=40)
        results = []
        for r in raw:
            u = urlparse(r["url"])
            if "uddg" in (q := parse_qs(u.query)):      # DuckDuckGo wraps result links in a redirect
                r["url"] = q["uddg"][0]
            if r["title"] and r["url"].startswith("http"):
                results.append(r)
        if not results:
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"the search page showed no results for {args.query!r}")
        return SearchOut(query=args.query, results=results,
                         evidence=f"{len(results)} results for {args.query!r} (untrusted page text)")


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookOut(BaseModel):
    url: str
    title: str
    elements: list[dict[str, Any]]
    text: str
    untrusted: bool = True
    evidence: str


class LookTool(_WebTool):
    spec = ToolSpec(id="web.look", version="1.0",
                    description="Look at the current page: numbered buttons, links and form fields, plus some text. "
                                "Use the numbers (ref) with web.click / web.type / web.choose / web.submit.",
                    input_model=NoArgs, output_model=LookOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.READ_ONLY, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="elements are read from the live page", max_retries=1)

    def run(self, args: NoArgs, ctx: ToolContext) -> LookOut:
        def go(page):
            _settle(page)
            return page.url, page.title(), self.session.snapshot(page), self.session.text(page, LOOK_TEXT)
        url, title, items, text = self.session.call(go)
        return LookOut(url=url, title=title, elements=items, text=text,
                       evidence=f"'{title}': {len(items)} interactive elements "
                                f"({sum(1 for i in items if i.get('consequential'))} that would send something)")


class ReadOut(BaseModel):
    url: str
    title: str
    text: str
    untrusted: bool = True
    evidence: str


class ReadTool(_WebTool):
    spec = ToolSpec(id="web.read", version="1.0", description="Read the main text of the current page (longer).",
                    input_model=NoArgs, output_model=ReadOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.READ_ONLY, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="text read from the live page", max_retries=1)

    def run(self, args: NoArgs, ctx: ToolContext) -> ReadOut:
        url, title, text = self.session.call(lambda p: (p.url, p.title(), self.session.text(p, READ_TEXT)))
        return ReadOut(url=url, title=title, text=text,
                       evidence=f"read {len(text)} characters from '{title}' (untrusted page text)")


# --- reversible: change the page, send nothing -----------------------------------------------

class RefArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)


class ActOut(BaseModel):
    url: str
    title: str
    detail: str
    evidence: str


def _refuse_if_sends(session: WebSession, ref: int, tool: str) -> None:
    item = session.item(ref)
    if item is None:
        raise ToolError(ErrorCode.STALE_STATE, f"no element {ref} in the last snapshot; use web.look first")
    if item.get("consequential"):
        raise ToolError(ErrorCode.PERMISSION_DENIED,
                        f"element {ref} ('{item['name']}') would send something; {tool} never presses those. "
                        f"Use web.submit, which asks the user first", needs_submit=ref)


class ClickTool(_WebTool):
    spec = ToolSpec(id="web.click", version="1.0",
                    description="Click a link, button, tab or option by its ref (never one that sends something).",
                    input_model=RefArgs, output_model=ActOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.NON_IDEMPOTENT,
                    verification="the page after the click (URL, title) is reported")

    def run(self, args: RefArgs, ctx: ToolContext) -> ActOut:
        _refuse_if_sends(self.session, args.ref, "web.click")

        def go(page):
            before = page.url
            self.session.element(page, args.ref).click(timeout=10_000)
            _settle(page)
            time.sleep(0.3)
            return page.url, page.title(), before
        url, title, before = self.session.call(go)
        moved = "opened a new page" if url != before else "page stayed (content may have changed)"
        name = (self.session.item(args.ref) or {}).get("name", "")
        return ActOut(url=url, title=title, detail=moved, evidence=f"clicked {args.ref} '{name}': {moved}; now '{title}'")


class TypeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)
    text: str = Field(max_length=5_000)


class TypeTool(_WebTool):
    spec = ToolSpec(id="web.type", version="1.0", description="Type text into a field by its ref (replaces its text).",
                    input_model=TypeArgs, output_model=ActOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="the field's value is read back and must equal the text")

    def run(self, args: TypeArgs, ctx: ToolContext) -> ActOut:
        item = self.session.item(args.ref)
        if item is None:
            raise ToolError(ErrorCode.STALE_STATE, f"no element {args.ref} in the last snapshot; use web.look first")
        if item.get("type") == "password":
            raise ToolError(ErrorCode.PERMISSION_DENIED, "ORION never types passwords; please sign in yourself")

        def go(page):
            el = self.session.element(page, args.ref)
            el.fill(args.text, timeout=10_000)
            try:
                got = el.input_value(timeout=3_000)
            except Exception:  # noqa: BLE001 - contenteditable fields
                got = el.inner_text()
            return page.url, page.title(), got
        url, title, got = self.session.call(go)
        if got.strip() != args.text.strip():
            raise ToolError(ErrorCode.VERIFICATION_FAILED, f"field {args.ref} shows {got[:80]!r} after typing")
        return ActOut(url=url, title=title, detail=got[:200],
                      evidence=f"typed {len(args.text)} characters into {args.ref} '{item['name']}'; read back OK")


class ChooseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)
    option: str | None = Field(default=None, max_length=300)   # for drop-down lists
    checked: bool = True                                        # for check boxes


class ChooseTool(_WebTool):
    spec = ToolSpec(id="web.choose", version="1.0",
                    description="Pick an answer: a radio button or check box by ref (checked true/false), "
                                "or a drop-down option by ref + option text.",
                    input_model=ChooseArgs, output_model=ActOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="the selected / checked state is read back")

    def run(self, args: ChooseArgs, ctx: ToolContext) -> ActOut:
        _refuse_if_sends(self.session, args.ref, "web.choose")
        item = self.session.item(args.ref)

        def go(page):
            el = self.session.element(page, args.ref)
            if item["role"] == "select":
                if not args.option:
                    raise ToolError(ErrorCode.INVALID_INPUT, f"{args.ref} is a drop-down; give option text")
                el.select_option(label=args.option, timeout=10_000)
                state = el.evaluate("e => e.options[e.selectedIndex].text").strip()
                ok = state.lower() == args.option.strip().lower()
            elif item["role"] in ("checkbox", "radio", "switch"):
                native = el.evaluate("e => e.tagName === 'INPUT'")
                if native:
                    el.set_checked(args.checked, timeout=10_000)
                    state = el.is_checked()
                else:   # ARIA widgets (e.g. Google Forms): click until the state matches
                    if (el.get_attribute("aria-checked") == "true") != args.checked:
                        el.click(timeout=10_000)
                    state = el.get_attribute("aria-checked") == "true"
                ok = state == args.checked
            elif item["role"] in ("option", "tab", "menuitem"):
                el.click(timeout=10_000)   # list items, tabs and menu entries
                state, ok = "selected", True
            else:
                raise ToolError(ErrorCode.INVALID_INPUT, f"{args.ref} is a {item['role']}, not a choice; "
                                                         f"use web.type for text or web.click for buttons/links")
            return page.url, page.title(), state, ok
        url, title, state, ok = self.session.call(go)
        if not ok:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, f"{args.ref} shows {state!r} after choosing")
        what = args.option if item["role"] == "select" else ("checked" if args.checked else "unchecked")
        return ActOut(url=url, title=title, detail=str(state),
                      evidence=f"{args.ref} '{item.get('group') or ''} {item['name']}'".replace("' ", "'") +
                               f" -> {what}; read back OK")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)
    # Small models write "text" or "option" as often as "value"; all three mean the same here.
    value: str = Field(max_length=5_000, validation_alias=AliasChoices("value", "text", "option"))


class FillArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[Answer] = Field(min_length=1, max_length=60)


_YES = {"yes", "true", "checked", "on", "1", "y", "x", "select", "selected"}


def apply_answer(page, session: WebSession, item: dict[str, Any], value: str) -> str:
    """Set one field the way its kind needs and return what it reads back as (runs on the browser thread)."""
    el = session.element(page, item["ref"])
    role = item["role"]
    if role == "select":
        opts = el.evaluate("e => [...e.options].map(o => o.text.trim())")
        match = next((o for o in opts if o.lower() == value.strip().lower()), None) or \
            next((o for o in opts if value.strip().lower() in o.lower()), None)
        if match is None:
            raise ToolError(ErrorCode.INVALID_INPUT, f"'{item['name']}' has no option {value!r} (options: {opts[:12]})")
        el.select_option(label=match, timeout=10_000)
        return el.evaluate("e => e.options[e.selectedIndex].text").strip()
    if role in ("checkbox", "switch", "radio"):
        # "yes", or the option's own name ("E-books" for the E-books box), means tick it.
        want = role == "radio" or value.strip().lower() in _YES or _norm(value) == _norm(item["name"])
        if el.evaluate("e => e.tagName === 'INPUT'"):
            el.set_checked(want, timeout=10_000)
            return "checked" if el.is_checked() else "unchecked"
        if (el.get_attribute("aria-checked") == "true") != want:
            el.click(timeout=10_000)
        return "checked" if el.get_attribute("aria-checked") == "true" else "unchecked"
    if role in ("option", "tab", "menuitem"):
        el.click(timeout=10_000)
        return "selected"
    if role in ("textbox", "combobox", "searchbox") or item.get("type") or "value" in item:
        el.fill(value, timeout=10_000)
        try:
            return el.input_value(timeout=3_000)
        except Exception:  # noqa: BLE001 - contenteditable fields
            return el.inner_text()
    raise ToolError(ErrorCode.INVALID_INPUT, f"{item['ref']} is a {role}; it cannot hold an answer")


class FillOut(BaseModel):
    filled: list[str]
    problems: list[str]
    evidence: str


class FillTool(_WebTool):
    spec = ToolSpec(id="web.fill", version="1.0",
                    description="Fill several form fields at once: answers=[{ref, value}]. Text fields get the text; "
                                "drop-downs the option text; check boxes 'yes'/'no'; radio buttons any value (it is "
                                "selected). Never presses anything that sends.",
                    input_model=FillArgs, output_model=FillOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=60, idempotency=Idempotency.IDEMPOTENT,
                    verification="every field is read back after setting it")

    def _option_for(self, item: dict[str, Any], value: str) -> dict[str, Any] | str:
        """A choice answered by naming an option: pick THAT option of the same question, never a wrong one.

        Models often give the ref of a question's first option with the wanted answer as the value
        ("ref of Daily, value Weekly"). Selecting the ref would record the wrong answer silently.
        """
        if item["role"] not in ("radio", "checkbox", "option"):
            return item
        v = " ".join(value.lower().split())
        if v in _YES or v in ("no", "false", "off", "0", "unchecked") or v == item["name"].lower().strip():
            return item
        same = [i for i in self.session.last_snapshot if i.get("group") == item.get("group")
                and i["role"] == item["role"]] if item.get("group") else [item]
        exact = [i for i in same if " ".join(i["name"].lower().split()) == v]
        loose = exact or [i for i in same if v in i["name"].lower() or i["name"].lower().strip() in v]
        if len(loose) == 1:
            return loose[0]
        q = item.get("group") or item["name"]
        return f"{item['ref']}: question '{q[:60]}' has no single option {value!r} " \
               f"(options: {[i['name'] for i in same][:10]})"

    def run(self, args: FillArgs, ctx: ToolContext) -> FillOut:
        jobs = []
        problems = []
        for a in args.answers:
            item = self.session.item(a.ref)
            if item is None:
                problems.append(f"{a.ref}: not on the page (look again)")
            elif item.get("consequential"):
                problems.append(f"{a.ref} '{item['name']}': sends something; skipped (use web.submit)")
            elif item.get("type") == "password":
                problems.append(f"{a.ref}: password field; ORION never types passwords")
            else:
                target = self._option_for(item, a.value)
                if isinstance(target, str):
                    problems.append(target)
                else:
                    jobs.append((target, "yes" if target is not item else a.value))

        def go(page):
            done = []
            for item, value in jobs:
                if ctx.token.is_cancelled:
                    problems.append("cancelled before the remaining fields")
                    break
                try:
                    got = apply_answer(page, self.session, item, value)
                    label = f"{item.get('group', '')} {item['name']}".strip()
                    expect_text = item["role"] not in ("checkbox", "switch", "radio", "option", "tab", "menuitem",
                                                       "select")
                    if expect_text and got.strip() != value.strip():
                        problems.append(f"{item['ref']} '{label}': shows {got[:60]!r} after typing")
                    else:
                        done.append(f"{item['ref']} '{label[:80]}' = {got[:80]}")
                except ToolError as e:
                    problems.append(f"{item['ref']}: {e.message}")
            return done
        done = self.session.call(go, timeout=55) if jobs else []
        if not done:
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, "no field could be filled: " + "; ".join(problems))
        return FillOut(filled=done, problems=problems,
                       evidence=f"filled {len(done)} field(s), each read back"
                                + (f"; {len(problems)} problem(s): " + "; ".join(problems) if problems else ""))


class QA(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=400)
    answer: str | list[str] = Field(validation_alias=AliasChoices("answer", "answers", "value"))


class AnswerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[QA] = Field(min_length=1, max_length=60)


def _norm(s: str) -> str:
    import re
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


class AnswerTool(_WebTool):
    spec = ToolSpec(id="web.answer", version="1.0",
                    description="Answer a form by QUESTION TEXT: answers=[{question, answer}]. answer is text, an "
                                "option name, or a list of option names for 'choose all that apply' (ORION ticks "
                                "exactly those). For a single check box like 'contact me' answer yes or no. "
                                "Never presses anything that sends.",
                    input_model=AnswerArgs, output_model=FillOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=60, idempotency=Idempotency.IDEMPOTENT,
                    verification="every field is read back after setting it")

    def _plan(self, qa: QA) -> tuple[list[tuple[dict, str]], str | None]:
        """Map one question->answer to concrete (element, value) settings, or explain why not."""
        items = [i for i in self.session.last_snapshot if not i.get("consequential") and i.get("type") != "password"]
        wanted = qa.answer if isinstance(qa.answer, list) else [qa.answer]
        groups: dict[str, list[dict]] = {}
        for i in items:
            if i.get("group") and i["role"] in ("radio", "checkbox", "option"):
                groups.setdefault(i["group"], []).append(i)
        best_g = max(groups, key=lambda g: _similar(qa.question, g), default=None)
        g_score = _similar(qa.question, best_g) if best_g else 0.0
        fields = [i for i in items if not (i.get("group") and i["role"] in ("radio", "checkbox", "option"))
                  and i["role"] not in ("link", "button")]
        best_f = max(fields, key=lambda i: _similar(qa.question, i["name"]), default=None)
        f_score = _similar(qa.question, best_f["name"]) if best_f else 0.0
        if max(g_score, f_score) < 0.6:
            return [], f"no question like {qa.question[:60]!r} on the page"
        if g_score >= f_score:
            opts = groups[best_g]
            chosen = []
            for w in wanted:
                match = [o for o in opts if _similar(w, o["name"]) >= 0.85]
                exact = [o for o in match if _norm(o["name"]) == _norm(w)]
                pick = exact or match
                if len(pick) != 1:
                    return [], f"'{best_g[:50]}': no single option {w!r} (options: {[o['name'] for o in opts][:10]})"
                chosen.append(pick[0])
            if opts[0]["role"] == "radio" and len(chosen) != 1:
                return [], f"'{best_g[:50]}' takes exactly one answer"
            jobs = [(o, "yes") for o in chosen]
            if opts[0]["role"] == "checkbox":   # "choose all that apply": exactly the listed ones
                jobs += [(o, "no") for o in opts if o not in chosen and o.get("checked")]
            return jobs, None
        value = ", ".join(wanted)
        return [(best_f, value)], None

    def run(self, args: AnswerArgs, ctx: ToolContext) -> FillOut:
        jobs, problems = [], []
        for qa in args.answers:
            j, err = self._plan(qa)
            if err:
                problems.append(err)
            jobs += j

        def go(page):
            done = []
            for item, value in jobs:
                try:
                    got = apply_answer(page, self.session, item, value)
                    done.append(f"{(item.get('group') or '')[:50]} {item['name'][:50]}: {got[:60]}".strip())
                except ToolError as e:
                    problems.append(f"{item['name'][:40]}: {e.message}")
            return done
        done = self.session.call(go, timeout=55) if jobs else []
        if not done:
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, "nothing could be answered: " + "; ".join(problems))
        return FillOut(filled=done, problems=problems,
                       evidence=f"answered {len(done)} field(s), each read back"
                                + (f"; {len(problems)} problem(s): " + "; ".join(problems) if problems else ""))


# --- consequential: always asks the user ----------------------------------------------------

class SubmitOut(BaseModel):
    url: str
    title: str
    text: str
    untrusted: bool = True
    evidence: str


class SubmitTool(_WebTool):
    spec = ToolSpec(id="web.submit", version="1.0",
                    description="Press a button that SENDS something (submit, send, apply, pay, post). "
                                "ORION always shows the user what will be sent and waits for their yes.",
                    input_model=RefArgs, output_model=SubmitOut, permissions=frozenset({Permission.BROWSER_WEB}),
                    side_effect=SideEffect.CONSEQUENTIAL, timeout_s=60, idempotency=Idempotency.NON_IDEMPOTENT,
                    verification="the page after sending is reported; the user approved this one press")

    def describe(self, args: RefArgs) -> tuple[str, str]:
        item = self.session.item(args.ref) or {"name": f"element {args.ref}"}
        summary = self.session.form_summary(args.ref)
        page = self.session.call(lambda p: (p.title(), p.url), timeout=10)
        return (f"Press '{item['name']}' on '{page[0]}'?",
                f"This SENDS it to {urlparse(page[1]).hostname}. It cannot be undone by ORION.\n\n"
                f"What is filled in:\n{summary or '(nothing filled)'}")

    def precheck(self, args: RefArgs) -> None:
        item = self.session.item(args.ref)
        if item is None:
            raise ToolError(ErrorCode.STALE_STATE, f"no element {args.ref} in the last snapshot; use web.look first")
        if not item.get("consequential"):
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.ref} ('{item['name']}') does not send anything; "
                                                     f"use web.click / web.choose / web.type for it")
        missing = self.session.call(lambda p: p.evaluate(MISSING_JS, args.ref), timeout=15)
        if missing:
            raise ToolError(ErrorCode.INVALID_INPUT, "not sending: required questions are unanswered: "
                                                     + "; ".join(missing[:10]), missing=missing)

    def run(self, args: RefArgs, ctx: ToolContext) -> SubmitOut:
        self.precheck(args)
        item = self.session.item(args.ref)

        def go(page):
            self.session.element(page, args.ref).click(timeout=10_000)
            _settle(page)
            time.sleep(0.5)
            return page.url, page.title(), self.session.text(page, LOOK_TEXT)
        url, title, text = self.session.call(go, timeout=50)
        return SubmitOut(url=url, title=title, text=text,
                         evidence=f"pressed '{item['name']}' (approved by the user); now '{title}'")


# The tools offered to the agent. Fewer, higher-level tools work far better with small local models
# (measured: with four overlapping form tools the model mixed them up). The low-level ones stay registered.
AGENT_TOOL_IDS = ["web.search", "web.open", "web.look", "web.read", "web.click", "web.answer", "web.submit"]


def web_tools(session: WebSession, search_url: str = DEFAULT_SEARCH) -> list[Tool]:
    return [OpenTool(session), SearchTool(session, search_url), LookTool(session), ReadTool(session),
            ClickTool(session), TypeTool(session), ChooseTool(session), FillTool(session), AnswerTool(session), SubmitTool(session)]
