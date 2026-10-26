"""OllamaBackend error handling against a local fake server (no model needed)."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from orion.models.ollama import LLMBackendError, OllamaBackend


def serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Ok(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        Ok.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        body = json.dumps({"response": '{"a": 1}', "prompt_eval_count": 5, "eval_count": 3}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Aborts(Ok):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = b'{"error":"prediction aborted, token repeat limit reached"}'
        self.send_response(500)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Hangs(Ok):
    def do_POST(self):
        time.sleep(2)


def test_request_is_deterministic_and_capped():
    srv, url = serve(Ok)
    try:
        b = OllamaBackend(url=url, schema={"type": "object"}, num_ctx=4096)
        assert b("hi") == '{"a": 1}'
        opts = Ok.seen[-1]["options"]
        assert opts["temperature"] == 0 and opts["seed"] == 0 and opts["num_predict"] == 1024
        assert Ok.seen[-1]["format"] == {"type": "object"} and b.calls[-1]["output_tokens"] == 3
    finally:
        srv.shutdown()


def test_server_abort_becomes_backend_error():
    srv, url = serve(Aborts)
    try:
        with pytest.raises(LLMBackendError, match="repeat limit"):
            OllamaBackend(url=url)("hi")
    finally:
        srv.shutdown()


def test_health_fails_when_server_is_down():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()   # nothing listens on this port now
    with pytest.raises(LLMBackendError, match="not reachable"):
        OllamaBackend(url=f"http://127.0.0.1:{port}").health()


def test_timeout_becomes_backend_error():
    srv, url = serve(Hangs)
    try:
        b = OllamaBackend(url=url, timeout_s=0.3)
        with pytest.raises(LLMBackendError):
            b("hi")
        assert "error" in b.calls[-1]
    finally:
        srv.shutdown()
