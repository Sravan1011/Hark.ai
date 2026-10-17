import datetime as dt
import json

import pytest

from hark import desktop, history, notes, stats
from hark.llm import notes_ai
from hark.llm.ollama import LLMError


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


def test_stats():
    today = dt.date(2026, 10, 17)
    entries = [
        {"ts": "2026-10-17T09:00:00", "text": "one two three four", "audio_s": 2.0},
        {"ts": "2026-10-16T09:00:00", "text": "five six", "audio_s": 0.5},  # too short for WPM
        {"ts": "2026-10-15T09:00:00", "text": "seven eight nine ten", "audio_s": 2.0},
        {"ts": "2026-10-01T09:00:00", "text": "old words here", "audio_s": 3.0},
        {"ts": "garbage", "text": "x"},
    ]
    s = stats.compute(entries, today=today)
    assert s.total_dictations == 5
    assert s.words_this_week == 10
    assert s.avg_wpm == round(11 / 7 * 60)
    assert s.streak_days == 3
    assert stats.compute(entries[1:3], today=today).streak_days == 2  # streak ending yesterday
    assert stats.compute([], today=today).avg_wpm == 0


def test_history_delete():
    history.append({"text": "keep"})
    history.append({"text": "drop"})
    drop_id = history.read()[-1]["id"]
    assert history.delete(drop_id)
    assert [e["text"] for e in history.read()] == ["keep"]
    assert not history.delete("missing")


def test_notes_round_trip_and_titles():
    a = notes.Note(body="first line\nsecond", updated=1)
    b = notes.Note(title="Named", updated=2)
    notes.save_all([a, b])
    loaded = notes.load()
    assert [n.id for n in loaded] == [b.id, a.id]  # newest first
    assert loaded[1].display_title == "first line"
    assert notes.Note().display_title == "New note"
    assert notes.Note(body="x" * 80).display_title.endswith("…")


def test_desktop_entries():
    path = desktop.install_launcher()
    assert "Exec=" in path.read_text() and "--hidden" not in path.read_text()
    desktop.set_autostart(True)
    assert desktop.autostart_enabled()
    assert "app --hidden" in desktop.autostart_file().read_text()
    desktop.set_autostart(False)
    assert not desktop.autostart_enabled()


class FakeClient:
    def __init__(self, reply):
        self.reply, self.kwargs = reply, None

    def chat(self, model, system, user, **kwargs):
        self.kwargs = kwargs
        return self.reply


def test_note_title_and_summary():
    client = FakeClient(json.dumps({"title": "\"Groceries\"", "summary": "Buy milk."}))
    assert notes_ai.title_and_summary("milk", client, model="m", keep_alive="5m") == \
        ("Groceries", "Buy milk.")
    assert client.kwargs["json_format"] is True
    for bad in ("not json", json.dumps({"title": ""}), json.dumps({"title": "x", "summary": ""})):
        with pytest.raises(LLMError):
            notes_ai.title_and_summary("milk", FakeClient(bad), model="m", keep_alive="5m")
    with pytest.raises(LLMError):
        notes_ai.title_and_summary("  ", client, model="m", keep_alive="5m")
