from pathlib import Path

import pytest
from pydantic import ValidationError

from orion.config import OrionConfig, load_config


def test_defaults_are_safe():
    cfg = OrionConfig()
    assert cfg.dry_run_default is True
    assert cfg.db_path == Path("data") / "orion.db"


def test_load_from_file(tmp_path):
    p = tmp_path / "orion.toml"
    p.write_text('[orion]\nlog_level = "DEBUG"\nkill_hotkey = "Ctrl + Alt + F12"\n')
    cfg = load_config(p)
    assert cfg.log_level == "DEBUG"
    assert cfg.kill_hotkey == "ctrl+alt+f12"


def test_utf8_bom_accepted(tmp_path):
    p = tmp_path / "orion.toml"
    p.write_bytes(b"\xef\xbb\xbf[orion]\nlog_level = \"ERROR\"\n")
    assert load_config(p).log_level == "ERROR"


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "orion.toml"
    p.write_text("[orion]\ndry_run_defualt = false\n")
    with pytest.raises(ValidationError):
        load_config(p)


def test_default_permissions_exclude_delete():
    from orion.tools import Permission
    assert Permission.FILES_DELETE not in OrionConfig().granted_permissions


def test_permissions_from_file_and_typos_rejected(tmp_path):
    from orion.tools import Permission
    p = tmp_path / "orion.toml"
    p.write_text('[orion]\ngranted_permissions = ["files.read", "files.delete"]\n')
    assert set(load_config(p).granted_permissions) == {Permission.FILES_READ, Permission.FILES_DELETE}
    p.write_text('[orion]\ngranted_permissions = ["files.everything"]\n')
    with pytest.raises(ValidationError):
        load_config(p)


def test_wrong_type_rejected(tmp_path):
    p = tmp_path / "orion.toml"
    p.write_text('[orion]\nsimulated_steps = "many"\n')
    with pytest.raises(ValidationError):
        load_config(p)


def test_missing_explicit_path_is_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_no_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_config() == OrionConfig()


def test_example_config_loads_and_keeps_default_abilities():
    """Regression: the example once listed only 3 permissions, silently dropping Notepad/Calculator/browser."""
    from orion.config import OrionConfig, load_config
    root = Path(__file__).resolve().parents[2]
    cfg = load_config(root / "config" / "orion.example.toml")
    assert set(cfg.granted_permissions) == set(OrionConfig().granted_permissions)
    assert cfg.dry_run_default is True
