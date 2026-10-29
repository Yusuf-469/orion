"""Start the ORION interface: `python -m orion.ui` (or ORION.exe --ui)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

WEB = Path(__file__).parent / "web"


class Api:
    """Methods the page may call (pywebview exposes public methods of this object as window.pywebview.api)."""

    def __init__(self, backend):
        self._b = backend

    def get_state(self):
        return self._b.get_state()

    def run(self, goal):
        return self._b.run(goal)

    def stop(self):
        return self._b.stop()

    def answer(self, wid, value):
        return self._b.answer(wid, value)

    def save_profile(self, name, facts):
        return self._b.save_profile(name, facts)

    def set_setting(self, key, value):
        return self._b.set_setting(key, value)

    def mic_start(self):
        return self._b.mic_start()

    def mic_stop(self):
        return self._b.mic_stop()

    def open_workspace(self):
        import os
        os.startfile(self._b.cfg.workspace_dir)   # noqa: S606 - ORION's own workspace folder
        return True


DEMO_PORT = 8765


def _serve_demo_site() -> str | None:
    """ORION's own test site (fictional shop, forms) on http://127.0.0.1:8765, for demos. Loopback only."""
    import functools
    import http.server
    import threading

    from orion import resources
    site = resources.path("demo/site")
    if not site.is_dir():
        return None
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", DEMO_PORT), handler)
    except OSError:
        return None   # already running (e.g. a second ORION) or the port is taken
    threading.Thread(target=srv.serve_forever, name="orion-demo-site", daemon=True).start()
    return f"http://127.0.0.1:{DEMO_PORT}"


def main(argv: list[str] | None = None) -> int:
    import webview

    from orion.config import load_config
    from orion.observability import setup_logging
    from orion.ui.backend import Backend, HotkeyThread

    ap = argparse.ArgumentParser(prog="orion-ui")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--model", default="qwen2.5:7b")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    setup_logging(cfg.log_dir, cfg.log_level)
    backend = Backend(cfg, a.model)
    _serve_demo_site()
    hk = HotkeyThread(cfg.kill_hotkey, backend.stop)
    hk.start()
    hk.ready.wait(3)
    logging.getLogger("orion.ui").info(hk.message)
    window = webview.create_window("ORION", str(WEB / "index.html"), js_api=Api(backend), width=1320, height=800,
                                   min_size=(980, 640), background_color="#03040b")
    backend.window = window
    window.events.loaded += lambda: backend.emit({"kind": "hotkey", "ok": hk.ok, "message": hk.message})
    webview.start(debug=False)
    backend.stop()
    if backend._session is not None:
        backend._session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
