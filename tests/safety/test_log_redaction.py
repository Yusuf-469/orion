import json
import logging

import pytest

from orion.observability.logging import REDACTED, JsonFormatter, redact, setup_logging

pytestmark = pytest.mark.safety

SECRETS = [
    ("password=hunter2", "hunter2"),
    ("api_key: abcd1234efgh", "abcd1234efgh"),
    ('{"token": "tok_9f8e7d6c"}', "tok_9f8e7d6c"),
    ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ("using key sk-ant-REDACTME1234567890abcd", "sk-ant-REDACTME1234567890abcd"),
    ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"),
    ("aws AKIAABCDEFGHIJKLMNOP here", "AKIAABCDEFGHIJKLMNOP"),
    ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.sigsigsig", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.sigsigsig"),
]


@pytest.mark.parametrize("text,secret", SECRETS)
def test_string_secrets_removed(text, secret):
    out = redact(text)
    assert secret not in out
    assert REDACTED in out


def test_ordinary_text_untouched():
    s = "Opened Notepad, typed 12 characters, saved report.csv"
    assert redact(s) == s


def test_nested_dict_keys_redacted():
    data = {"user": "demo", "author": "me", "Password": "x", "nested": {"api_key": "y", "list": ["token=z"]}}
    out = redact(data)
    assert out["user"] == "demo"
    assert out["author"] == "me"
    assert out["Password"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert "z" not in out["nested"]["list"][0]


def test_formatter_redacts_msg_event_and_exception():
    rec = logging.LogRecord("orion.t", logging.INFO, __file__, 1, "login password=%s", ("p@ss",), None)
    rec.event = {"secret": "s3", "step": 2}
    try:
        raise RuntimeError("failed with token=abc123")
    except RuntimeError:
        import sys
        rec.exc_info = sys.exc_info()
    line = JsonFormatter().format(rec)
    entry = json.loads(line)
    assert "p@ss" not in line and "s3" not in line and "abc123" not in line
    assert entry["event"]["step"] == 2


def test_file_handler_writes_redacted_jsonl(tmp_path):
    path = setup_logging(tmp_path)
    log = logging.getLogger("orion.test")
    log.info("connecting with api_key=SUPERSECRET", extra={"event": {"kind": "test"}})
    for h in logging.getLogger("orion").handlers:
        h.flush()
    content = path.read_text(encoding="utf-8")
    assert "SUPERSECRET" not in content
    assert json.loads(content.strip().splitlines()[-1])["event"]["kind"] == "test"
