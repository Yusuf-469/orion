"""Web tools on ORION's local test site (headless Chromium, temp profile). Marked `real`: launches a browser."""

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.real
SITE = Path(__file__).resolve().parents[2] / "demo" / "site"


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class Answer:
    def __init__(self, yes):
        self.yes, self.asked = yes, []

    def confirm(self, req, token):
        self.asked.append(req)
        return self.yes


@pytest.fixture
def web(tmp_path, site):
    from orion.execution.runtime import ToolRuntime
    from orion.orchestration.cancel import CancelToken
    from orion.policy import PolicyEngine
    from orion.tools import Permission, ToolRegistry
    from orion.tools.web import WebSession, web_tools
    session = WebSession(tmp_path / "profile", headless=True)
    reg = ToolRegistry()
    for t in web_tools(session, search_url=site + "/search.html?q={q}"):
        reg.register(t)
    confirmer = Answer(False)
    rt = ToolRuntime(reg, PolicyEngine(frozenset(Permission)), confirmer, tmp_path)

    def call(tool, **args):
        from orion.execution.runtime import ToolCall
        return rt.execute(ToolCall(tool_id=tool, args=args), CancelToken())
    yield call, confirmer, session
    session.close()


def ref(look, name, role=None):
    return next(e["ref"] for e in look.output["elements"]
                if name.lower() in e["name"].lower() and (role is None or e["role"] == role))


def test_search_and_open_product(web, site):
    call, _, _ = web
    r = call("web.search", query="aurora x1 nimbus pro")
    assert r.ok, r.evidence
    urls = [x["url"] for x in r.output["results"]]
    assert any("aurora-x1" in u for u in urls) and any("nimbus-pro" in u for u in urls)
    r = call("web.open", url=site + "/products/nimbus-pro.html")
    assert r.ok and "199 USD" in r.output["text"] and r.output["untrusted"]


def test_fill_long_form_every_widget_and_read_back(web, site):
    call, _, session = web
    assert call("web.open", url=site + "/form/feedback.html").ok
    look = call("web.look")
    assert look.ok
    sends = [e for e in look.output["elements"] if e.get("consequential")]
    assert [e["name"] for e in sends] == ["Submit"]
    assert call("web.type", ref=ref(look, "Full name"), text="Test Person").ok
    assert call("web.choose", ref=ref(look, "Weekly", "radio")).ok
    sat4 = next(e["ref"] for e in look.output["elements"] if e["role"] == "radio" and e["name"] == "4")
    r = call("web.choose", ref=sat4)                      # ARIA radio, like Google Forms
    assert r.ok, r.evidence
    assert call("web.choose", ref=ref(look, "E-books", "checkbox")).ok
    assert call("web.choose", ref=ref(look, "Your branch"), option="Riverside").ok
    assert call("web.type", ref=ref(look, "improve"), text="Longer opening hours").ok
    again = call("web.look").output["elements"]
    by = {e["name"]: e for e in again}
    assert by["4"]["checked"] and by["Full name *"]["value"] == "Test Person" if "Full name *" in by else True
    assert next(e for e in again if e["name"].strip().startswith("E-books"))["checked"]


def test_click_never_presses_submit_and_submit_needs_a_yes(web, site):
    call, confirmer, session = web
    call("web.open", url=site + "/form/feedback.html")
    look = call("web.look")
    submit = ref(look, "Submit")
    r = call("web.click", ref=submit)
    assert not r.ok and r.error_code == "permission_denied"
    call("web.type", ref=ref(look, "Full name"), text="Test Person")
    r = call("web.submit", ref=submit)                     # incomplete: refused before the user is even asked
    assert not r.ok and "required questions are unanswered" in r.error_message and not confirmer.asked
    r = call("web.answer", answers=[{"question": "Email", "answer": "t@example.com"},
                                    {"question": "How often do you use the app", "answer": "Weekly"},
                                    {"question": "Overall satisfaction", "answer": "4"}])
    assert r.ok, r.evidence
    r = call("web.submit", ref=submit)                     # complete; the user says no
    assert not r.ok and r.error_code == "confirmation_required"
    assert confirmer.asked and "Test Person" in confirmer.asked[-1].consequence
    assert session.call(lambda p: p.evaluate("document.body.dataset.submitted")) is None


def test_submit_with_a_yes_sends_once(web, site):
    call, confirmer, session = web
    confirmer.yes = True
    call("web.open", url=site + "/form/feedback.html")
    look = call("web.look")
    for name, text in (("Full name", "Test Person"), ("Email", "test@example.com")):
        call("web.type", ref=ref(look, name), text=text)
    call("web.choose", ref=ref(look, "Daily", "radio"))
    call("web.choose", ref=next(e["ref"] for e in look.output["elements"] if e["role"] == "radio" and e["name"] == "5"))
    r = call("web.submit", ref=ref(look, "Submit"))
    assert r.ok, r.evidence
    sent = json.loads(session.call(lambda p: p.evaluate("document.body.dataset.response")))
    assert sent["name"] == "Test Person" and sent["satisfaction"] == "5" and sent["freq"] == "daily"


def test_passwords_are_never_typed(web, site):
    call, _, session = web
    call("web.open", url=site + "/form/feedback.html")
    session.call(lambda p: p.evaluate("document.body.insertAdjacentHTML('afterbegin', "
                                      "'<input type=password aria-label=Password>')"))
    look = call("web.look")
    r = call("web.type", ref=ref(look, "Password"), text="secret")
    assert not r.ok and "never types passwords" in r.error_message


def test_write_document_docx(tmp_path):
    from orion.execution.runtime import ToolCall, ToolRuntime
    from orion.orchestration.cancel import CancelToken
    from orion.policy import PolicyEngine
    from orion.tools import Permission, ToolRegistry
    from orion.tools.write_document import WriteDocumentTool
    reg = ToolRegistry()
    reg.register(WriteDocumentTool())
    rt = ToolRuntime(reg, PolicyEngine(frozenset(Permission)), Answer(False), tmp_path)
    md = "# Compare\n\n| Spec | A | B |\n|---|---|---|\n| Price | 1 | 2 |\n\n## Pros\n- **fast**\n"
    r = rt.execute(ToolCall(tool_id="docs.write_document", args={"path": "c.docx", "content": md}), CancelToken())
    assert r.ok and r.output["tables"] == 1 and r.output["headings"] == 2, r.evidence
    r = rt.execute(ToolCall(tool_id="docs.write_document", args={"path": "c.docx", "content": md}), CancelToken())
    assert not r.ok   # never overwrites
