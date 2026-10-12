import json

from hark import cli, paths


def test_xdg_env_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert paths.config_file() == tmp_path / "cfg" / "hark" / "config.json"
    assert paths.models_dir() == tmp_path / "data" / "hark" / "models"


def test_relative_xdg_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert paths.config_dir() == tmp_path / ".config" / "hark"


def test_config_set_get_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(["config", "set", "llm.model", "qwen2.5:1.5b"]) == 0
    capsys.readouterr()
    assert cli.main(["config", "get", "llm.model"]) == 0
    assert capsys.readouterr().out.strip() == "qwen2.5:1.5b"
    assert cli.main(["config", "set", "hotkey.mode", "bad"]) == 1


def test_doctor_json_runs(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cli.main(["doctor", "--json"])
    checks = json.loads(capsys.readouterr().out)
    assert {"name", "status", "detail", "fix"} <= set(checks[0])
