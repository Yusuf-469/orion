"""One long-lived browser for ORION's web tools (Playwright, Chromium, ORION's own profile).

Playwright's sync API must be used from the thread that started it, while ORION runs each tool call in
its own thread. So the browser lives on one worker thread and tools hand it jobs. The profile is ORION's
own folder (never the user's everyday browser profile): the user may sign in there themselves; ORION
never types passwords.

Page snapshots give every visible interactive element a number (`ref`). The AI acts on refs, never on
CSS or coordinates it invents. Elements whose job is to send something (submit, apply, pay, ...) are
marked `consequential`; only the confirm-gated `web.submit` tool may press them.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from orion.tools.errors import ErrorCode, ToolError

# Words on a control that mean pressing it sends, buys, applies, publishes or deletes something.
CONSEQUENTIAL_WORDS = (r"submit|send|apply|buy|pay|purchase|place order|order now|checkout|check out|post|publish|"
                       r"donate|subscribe|sign up|register|confirm|delete|remove|transfer|book now|reserve")

SNAPSHOT_JS = r"""
(args) => {
  const [maxItems, words] = args;
  const re = new RegExp("\\b(" + words + ")\\b", "i");
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], ' +
              '[role=checkbox], [role=radio], [role=option], [role=combobox], [role=textbox], [role=tab], ' +
              '[role=menuitem], [role=switch], [contenteditable=true]';
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const byId = id => { const e = document.getElementById(id); return e ? clean(e.innerText || e.textContent) : ''; };
  const visible = e => {
    const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const label = e => {
    if (e.getAttribute('aria-label')) return clean(e.getAttribute('aria-label'));
    if (e.getAttribute('aria-labelledby'))
      return clean(e.getAttribute('aria-labelledby').split(/\s+/).map(byId).join(' '));
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) return clean(l.innerText); }
    const wrap = e.closest('label'); if (wrap) return clean(wrap.innerText);
    if (e.placeholder) return clean(e.placeholder);
    const t = clean(e.innerText || e.value || ''); if (t) return t.slice(0, 100);
    return clean(e.title || e.name || e.getAttribute('alt') || '');
  };
  const group = e => {
    const fs = e.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return clean(lg.innerText); }
    const rg = e.closest('[role=radiogroup],[role=group],[role=listitem]');
    if (rg) { if (rg.getAttribute('aria-label')) return clean(rg.getAttribute('aria-label'));
              if (rg.getAttribute('aria-labelledby')) return clean(rg.getAttribute('aria-labelledby').split(/\s+/).map(byId).join(' '));
              const h = rg.querySelector('[role=heading], h1, h2, h3, h4, legend'); if (h) return clean(h.innerText); }
    return '';
  };
  document.querySelectorAll('[data-orion-ref]').forEach(e => e.removeAttribute('data-orion-ref'));
  const out = []; let n = 0;
  for (const e of document.querySelectorAll(sel)) {
    if (!visible(e) || e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
    n += 1; e.setAttribute('data-orion-ref', String(n));
    const tag = e.tagName.toLowerCase(); const type = (e.getAttribute('type') || '').toLowerCase();
    const role = e.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'select' ? 'select' :
                 tag === 'textarea' ? 'textbox' : tag === 'button' ? 'button' :
                 ['checkbox', 'radio'].includes(type) ? type : ['submit', 'button', 'reset'].includes(type) ? 'button' :
                 tag === 'input' ? 'textbox' : tag);
    const item = {ref: n, role, name: label(e).slice(0, 120)};
    const g = group(e); if (g && g !== item.name) item.group = g.slice(0, 120);
    if (tag === 'input' && !['checkbox', 'radio', 'submit', 'button'].includes(type)) { item.value = e.value; if (type) item.type = type; }
    if (tag === 'textarea' || e.isContentEditable) item.value = tag === 'textarea' ? e.value : clean(e.innerText);
    if (tag === 'select') { item.value = e.options[e.selectedIndex] ? clean(e.options[e.selectedIndex].text) : '';
                            item.options = [...e.options].map(o => clean(o.text)).slice(0, 30); }
    if (['checkbox', 'radio'].includes(type)) item.checked = e.checked;
    if (['checkbox', 'radio', 'switch'].includes(role) && e.getAttribute('aria-checked') !== null)
      item.checked = e.getAttribute('aria-checked') === 'true';
    if (e.required || e.getAttribute('aria-required') === 'true') item.required = true;
    if (tag === 'a') item.href = e.href.slice(0, 200);
    // Links only navigate (an "Apply" link opens the application form); buttons are what send.
    const sends = tag !== 'a' && (type === 'submit' || (tag === 'button' && e.form && !type) ||
                  (['button', 'link'].includes(role) && re.test(item.name)));
    if (sends && !['textbox', 'select', 'checkbox', 'radio', 'option'].includes(role)) item.consequential = true;
    out.push(item);
    if (out.length >= maxItems) break;
  }
  return out;
}
"""

TEXT_JS = r"""
() => {
  // Text a person cannot see (tiny, transparent, or the same colour as its background) is a classic way to
  // hide instructions for AI agents. Hide it while reading, then restore the page exactly.
  const rgb = s => { const m = (s || '').match(/[\d.]+/g); return m ? m.map(Number) : null; };
  const bgOf = e => {
    for (let x = e; x; x = x.parentElement) {
      const c = rgb(getComputedStyle(x).backgroundColor);
      if (c && (c.length < 4 || c[3] > 0.1)) return c;
    }
    return [255, 255, 255];
  };
  const hidden = [];
  for (const e of document.body.querySelectorAll('*')) {
    if (!e.childNodes.length || ![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const st = getComputedStyle(e); const c = rgb(st.color); const bg = bgOf(e);
    const tiny = parseFloat(st.fontSize) < 4;
    const clear = parseFloat(st.opacity) < 0.1 || (c && c.length > 3 && c[3] < 0.1);
    const same = c && Math.abs(c[0] - bg[0]) + Math.abs(c[1] - bg[1]) + Math.abs(c[2] - bg[2]) < 30;
    if (tiny || clear || same) hidden.push([e, e.style.display]);
  }
  hidden.forEach(([e]) => { e.style.display = 'none'; });
  const main = document.querySelector('main, [role=main], article') || document.body;
  const text = (main.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
  hidden.forEach(([e, d]) => { e.style.display = d; });
  return text;
}
"""


class WebSession:
    """Owns the Playwright browser on a dedicated thread; `call(fn)` runs fn(page) there."""

    def __init__(self, profile_dir: Path | str, headless: bool = False):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.page = None
        self.last_snapshot: list[dict[str, Any]] = []

    # --- thread plumbing -------------------------------------------------------------------
    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                ready: Future = Future()
                self._thread = threading.Thread(target=self._loop, args=(ready,), name="orion-browser", daemon=True)
                self._thread.start()
                ready.result(timeout=60)

    def _loop(self, ready: Future) -> None:
        from playwright.sync_api import sync_playwright
        try:
            pw = sync_playwright().start()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            ctx = pw.chromium.launch_persistent_context(str(self.profile_dir), headless=self.headless,
                                                        viewport={"width": 1280, "height": 860})
            self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ready.set_result(True)
        except BaseException as e:  # noqa: BLE001
            ready.set_exception(e)
            return
        while True:
            fn, fut = self._jobs.get()
            if fn is None:
                break
            if fut.set_running_or_notify_cancel():
                try:
                    if self.page.is_closed():   # the user closed the window: open a fresh tab
                        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    fut.set_result(fn(self.page))
                except BaseException as e:  # noqa: BLE001
                    fut.set_exception(e)
        try:
            ctx.close()
            pw.stop()
        except Exception:  # noqa: BLE001
            pass

    def call(self, fn: Callable[[Any], Any], timeout: float = 30.0) -> Any:
        from playwright.sync_api import Error as PwError
        try:
            self._ensure_started()
        except Exception as e:  # noqa: BLE001
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE,
                            f"could not start ORION's browser: {str(e).splitlines()[0]} "
                            f"(run ORION --install-browser once)") from None
        fut: Future = Future()
        self._jobs.put((fn, fut))
        try:
            return fut.result(timeout=timeout)
        except ToolError:
            raise
        except PwError as e:
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, f"browser error: {str(e).splitlines()[0]}") from None
        except TimeoutError:
            raise ToolError(ErrorCode.TIMEOUT, "the browser did not respond in time") from None

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._jobs.put((None, None))
            self._thread.join(timeout=10)

    # --- helpers used by the tools (run on the browser thread) -----------------------------
    def snapshot(self, page, max_items: int = 150) -> list[dict[str, Any]]:
        items = page.evaluate(SNAPSHOT_JS, [max_items, CONSEQUENTIAL_WORDS])
        self.last_snapshot = items
        return items

    def element(self, page, ref: int):
        loc = page.locator(f'[data-orion-ref="{ref}"]')
        if loc.count() != 1:
            raise ToolError(ErrorCode.STALE_STATE,
                            f"element {ref} is no longer on the page; take a new snapshot (web.look)")
        return loc

    def item(self, ref: int) -> dict[str, Any] | None:
        return next((i for i in self.last_snapshot if i["ref"] == ref), None)

    @staticmethod
    def text(page, limit: int) -> str:
        return page.evaluate(TEXT_JS)[:limit]

    def form_summary(self, ref: int) -> str:
        """What a submit would send: the filled fields of the form around `ref` (for the confirmation)."""
        def read(page):
            return page.evaluate(r"""(ref) => {
              const b = document.querySelector('[data-orion-ref="' + ref + '"]');
              const scope = (b && (b.form || b.closest('form,[role=form],[role=list],main'))) || document.body;
              const clean = s => (s || '').replace(/\s+/g, ' ').trim();
              const lines = [];
              for (const e of scope.querySelectorAll('input, select, textarea, [role=radio], [role=checkbox]')) {
                const t = (e.getAttribute('type') || '').toLowerCase();
                if (['hidden', 'submit', 'button', 'password'].includes(t)) continue;
                let name = clean(e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].innerText)
                                 || e.placeholder || e.name);
                if (['checkbox', 'radio'].includes(t) || e.getAttribute('role')) {   // "Question: answer"
                  const fs = e.closest('fieldset'); const g = e.closest('[role=radiogroup],[role=group]');
                  let q = fs && fs.querySelector('legend') ? fs.querySelector('legend').innerText : '';
                  if (!q && g) q = g.getAttribute('aria-label') || (g.getAttribute('aria-labelledby') || '')
                      .split(/\s+/).map(id => { const x = document.getElementById(id); return x ? x.innerText : ''; }).join(' ');
                  if (clean(q)) name = clean(q) + ' -> ' + name;
                }
                let v = null;
                if (['checkbox', 'radio'].includes(t)) { if (e.checked) v = 'selected'; }
                else if (e.getAttribute('role')) { if (e.getAttribute('aria-checked') === 'true') v = 'selected'; }
                else if (e.tagName === 'SELECT') v = e.options[e.selectedIndex] ? clean(e.options[e.selectedIndex].text) : '';
                else v = clean(e.value);
                if (v) lines.push(name + ': ' + v);
              }
              return lines.slice(0, 40).join('\n');
            }""", ref)
        try:
            return self.call(read, timeout=15)
        except ToolError:
            return "(could not read the form)"
