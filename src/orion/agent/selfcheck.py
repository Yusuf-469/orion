"""Self-check before sending a form: an independent answer key, compared with the page by code.

1. From the latest page view, list the form's questions (and their options).
2. One focused model call answers them from the user's facts only (no browsing context, nothing else).
3. Code compares that answer key with what the page actually shows. Disagreements are sent back to
   the agent to fix before web.submit is allowed. The user's confirmation still follows after that.
Two independent passes rarely make the same mistake, so disagreement is a strong error signal.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Callable

CHOICE = ("radio", "checkbox", "option")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(s).lower()).split())


def _same(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and (a == b or (len(a) > 2 and (a in b or b in a)) or SequenceMatcher(None, a, b).ratio() > 0.85)


def questions(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Questions on the page with their current answers."""
    out: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for e in elements:
        if e.get("consequential") or e["role"] in ("link", "button") or e.get("type") == "password":
            continue
        if e.get("group") and e["role"] in CHOICE:
            g = groups.get(e["group"])
            if g is None:
                g = {"question": e["group"], "kind": "one" if e["role"] == "radio" else "many",
                     "options": [], "current": []}
                groups[e["group"]] = g
                out.append(g)
            g["options"].append(e["name"])
            if e.get("checked"):
                g["current"].append(e["name"])
        elif e["role"] in ("checkbox", "switch"):
            out.append({"question": e["name"], "kind": "yes/no", "options": ["yes", "no"],
                        "current": ["yes" if e.get("checked") else "no"]})
        elif e["role"] == "select":
            cur = e.get("value", "")
            out.append({"question": e["name"], "kind": "one", "options": e.get("options", []),
                        "current": [cur] if cur and not cur.lower().startswith(("choose", "select")) else []})
        elif "value" in e:
            out.append({"question": e["name"], "kind": "text", "options": [],
                        "current": [e["value"]] if e.get("value") else []})
    return out


KEY_SCHEMA = {"type": "object", "required": ["answers"], "properties": {"answers": {"type": "array", "items": {
    "type": "object", "required": ["question", "answer"],
    "properties": {"question": {"type": "string"}, "answer": {"type": "array", "items": {"type": "string"}}}}}}}


def answer_key(llm: Callable[[str], str], facts: str, qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for q in qs:
        opts = f" options: {q['options']}" if q["options"] else ""
        lines.append(f"- {q['question']} ({'choose ' + q['kind'] if q['kind'] in ('one', 'many') else q['kind']}){opts}")
    prompt = ("Answer this form using ONLY the facts the user gave. For each question give the answer as a list "
              "(several items only for 'choose many'; for yes/no give ['yes'] or ['no']). If the facts do not say, "
              "give an empty list.\n"
              f"FACTS\n{facts}\nQUESTIONS\n" + "\n".join(lines) + "\nJSON: {\"answers\": [{\"question\", \"answer\"}]}")
    old = getattr(llm, "schema", None)
    try:
        if hasattr(llm, "schema"):
            llm.schema = KEY_SCHEMA
        raw = llm(prompt)
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("answers", [])
    finally:
        if hasattr(llm, "schema"):
            llm.schema = old


def compare(qs: list[dict[str, Any]], key: list[dict[str, Any]]) -> list[str]:
    """Problems where the page disagrees with the answer key (questions the facts don't cover are skipped)."""
    problems = []
    for k in key:
        want = [a for a in (k.get("answer") or []) if str(a).strip()]
        if not want:
            continue
        q = max(qs, key=lambda x: SequenceMatcher(None, _norm(x["question"]), _norm(k.get("question", ""))).ratio(),
                default=None)
        if q is None or SequenceMatcher(None, _norm(q["question"]), _norm(k.get("question", ""))).ratio() < 0.6:
            continue
        cur = q["current"]
        if q["kind"] == "text":
            ok = bool(cur) and any(_same(w, cur[0]) for w in want)
        elif q["kind"] == "yes/no":
            ok = _norm(want[0]).startswith(_norm(cur[0])[:1]) if cur else False
        else:
            # The key's answers mapped onto real options; compare as sets.
            mapped = {o for w in want for o in q["options"] if _same(w, o)}
            ok = bool(mapped) and mapped == set(cur) if q["kind"] == "many" else (bool(mapped) and set(cur) <= mapped
                                                                                  and len(cur) == 1)
            if not mapped:
                continue   # the key named no real option; cannot judge
        if not ok:
            problems.append(f"'{q['question'][:70]}' shows {cur or 'nothing'}, but the user's facts say {want}")
    return problems
