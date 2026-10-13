import pytest

from hark import cli
from hark import config as c
from hark.stt import catalog


@pytest.fixture(autouse=True)
def isolated_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


def _fake_download(model_id):
    d = catalog.model_dir(model_id)
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x" * 1000)
    (d / catalog._MARKER).write_text("{}")


def test_ids_unique_and_default_selectable():
    ids = [m.id for m in catalog.CATALOG]
    assert len(ids) == len(set(ids))
    assert c.Config().stt.model in catalog.selectable_ids()
    assert "silero-vad" not in catalog.selectable_ids()


def test_unknown_model():
    with pytest.raises(catalog.ModelError, match="Available"):
        catalog.get("whisper-gigantic")


def test_parakeet_needs_vad_too():
    _fake_download("parakeet-v3")
    assert not catalog.is_downloaded("parakeet-v3")
    _fake_download("silero-vad")
    assert catalog.is_downloaded("parakeet-v3")


def test_partial_download_not_counted():
    d = catalog.model_dir("whisper-small")
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"partial")
    assert not catalog.is_downloaded("whisper-small")


def test_remove():
    _fake_download("whisper-base.en")
    assert catalog.remove("whisper-base.en") >= 1000
    assert not catalog.model_dir("whisper-base.en").exists()


def test_config_rejects_unknown_model():
    with pytest.raises(c.ConfigError):
        c.set_value(c.Config(), "stt.model", "nope")


def test_cli_use_and_list(capsys):
    assert cli.main(["models", "use", "whisper-small"]) == 0
    assert c.load().stt.model == "whisper-small"
    capsys.readouterr()
    assert cli.main(["models", "list"]) == 0
    line = next(l for l in capsys.readouterr().out.splitlines() if "whisper-small" in l)
    assert line.startswith("*")


def test_transcribe_without_model_gives_hint(tmp_path, capsys):
    wav = tmp_path / "silence.wav"
    import wave

    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)
    assert cli.main(["transcribe", str(wav), "--model", "whisper-small"]) == 1
    assert "hark models download whisper-small" in capsys.readouterr().err
