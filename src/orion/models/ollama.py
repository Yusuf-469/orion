"""Local LLM backend via Ollama's HTTP API (standard library only).

Local-first rule: only loopback hosts are accepted, so a misconfiguration
cannot send prompts (which contain the user's request) to a remote server.
Decoding is deterministic (temperature 0, fixed seed). With `schema`, Ollama
constrains generation to that JSON schema (structured outputs).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

_LOCAL = {"127.0.0.1", "localhost", "::1"}


class LLMBackendError(RuntimeError):
    """The model server refused or aborted a generation (e.g. a repetition loop)."""


class OllamaBackend:
    def __init__(self, model: str = "phi3.5", url: str = "http://127.0.0.1:11434",
                 schema: dict[str, Any] | None = None, timeout_s: float = 180, num_ctx: int = 8192, seed: int = 0,
                 num_predict: int = 1024):
        host = urlparse(url).hostname
        if host not in _LOCAL:
            raise ValueError(f"refusing non-local LLM endpoint {url!r} (local-first rule)")
        self.model, self.url, self.schema = model, url.rstrip("/"), schema
        # num_predict caps output length: a plan needs ~300 tokens; the cap stops runaway generations.
        self.timeout_s, self.num_ctx, self.seed, self.num_predict = timeout_s, num_ctx, seed, num_predict
        self.calls: list[dict[str, Any]] = []   # per-call latency and token counts

    def __call__(self, prompt: str) -> str:
        body: dict[str, Any] = {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict},
        }
        if self.schema is not None:
            body["format"] = self.schema
        req = urllib.request.Request(f"{self.url}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            self.calls.append({"seconds": round(time.monotonic() - t0, 2), "error": f"HTTP {e.code}: {detail}"})
            raise LLMBackendError(f"HTTP {e.code}: {detail}") from None
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            self.calls.append({"seconds": round(time.monotonic() - t0, 2), "error": f"{type(e).__name__}: {e}"})
            raise LLMBackendError(f"{type(e).__name__}: {e}") from None
        self.calls.append({"seconds": round(time.monotonic() - t0, 2),
                           "prompt_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")})
        return data.get("response", "")
