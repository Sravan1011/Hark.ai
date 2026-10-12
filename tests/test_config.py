import json

import pytest

from hark import config as c


def test_missing_file_gives_defaults(tmp_path):
    assert c.load(tmp_path / "nope.json") == c.Config()


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    cfg = c.Config()
    cfg.llm.model = "qwen2.5:1.5b"
    cfg.vocabulary = [{"from": "hark ai", "to": "Hark.ai"}]
    c.save(cfg, path)
    assert c.load(path) == cfg
    assert not list(path.parent.glob(".config-*"))  # temp file cleaned up


def test_tolerant_load(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "hotkey": {"mode": "sideways", "combo": "KEY_F9"},  # invalid choice is ignored
        "llm": {"enabled": "yes", "timeout_s": 3},           # wrong type ignored, int -> float
        "stt": "not a section",
        "unknown": 1,
        "vocabulary": [{"from": "a", "to": "b"}, {"from": ""}, "junk"],
    }))
    cfg = c.load(path)
    assert cfg.hotkey.mode == "hold"
    assert cfg.hotkey.combo == "KEY_F9"
    assert cfg.llm.enabled is False
    assert cfg.llm.timeout_s == 3.0 and isinstance(cfg.llm.timeout_s, float)
    assert cfg.stt == c.STTConfig()
    assert cfg.vocabulary == [{"from": "a", "to": "b"}]


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{oops")
    with pytest.raises(c.ConfigError):
        c.load(path)


@pytest.mark.parametrize("key,raw,expected", [
    ("llm.enabled", "on", True),
    ("llm.enabled", "False", False),
    ("llm.timeout_s", "2.5", 2.5),
    ("llm.model", "gemma3:1b", "gemma3:1b"),
    ("hotkey.mode", "toggle", "toggle"),
    ("save_history", "no", False),
])
def test_set_value(key, raw, expected):
    cfg = c.Config()
    assert c.set_value(cfg, key, raw) == expected
    assert c.get_value(cfg, key) == expected


@pytest.mark.parametrize("key,raw", [
    ("llm.enabled", "maybe"),
    ("llm.timeout_s", "soon"),
    ("hotkey.mode", "sideways"),
    ("llm", "x"),
    ("vocabulary", "x"),
    ("llm.nope", "x"),
    ("nope.model", "x"),
])
def test_set_value_rejects(key, raw):
    with pytest.raises(c.ConfigError):
        c.set_value(c.Config(), key, raw)
