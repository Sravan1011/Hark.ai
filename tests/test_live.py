import threading

import numpy as np
import pytest
from evdev import ecodes as e

from hark import audio, dictation
from hark import config as c
from hark.hotkey import HotkeyError, HotkeyListener, parse_combo, pretty
from hark.stt import SAMPLE_RATE

# -- hotkey ---------------------------------------------------------------------------


def test_parse_combo_and_pretty():
    assert parse_combo("KEY_RIGHTCTRL") == (e.KEY_RIGHTCTRL,)
    assert parse_combo("leftmeta + space") == (e.KEY_LEFTMETA, e.KEY_SPACE)
    assert parse_combo("BTN_SIDE") == (e.BTN_SIDE,)
    assert pretty(parse_combo("leftmeta+space")) == "Super + Space"
    with pytest.raises(HotkeyError):
        parse_combo("KEY_NOPE")


def _listener(combo="leftmeta+space"):
    events = []
    return HotkeyListener(parse_combo(combo), events.append), events


def test_combo_press_release_and_autorepeat():
    lst, events = _listener()
    lst._handle(e.KEY_LEFTMETA, 1)
    assert events == []
    lst._handle(e.KEY_SPACE, 1)
    lst._handle(e.KEY_SPACE, 2)  # autorepeat is ignored
    assert events == ["press"]
    lst._handle(e.KEY_SPACE, 0)
    assert events == ["press", "release"]
    lst._handle(e.KEY_LEFTMETA, 0)
    assert events == ["press", "release"]


def test_other_key_while_held_is_an_interrupt():
    lst, events = _listener("rightctrl")
    lst._handle(e.KEY_RIGHTCTRL, 1)
    lst._handle(e.KEY_C, 1)  # Right Ctrl+C is a shortcut, not dictation
    lst._handle(e.KEY_C, 0)
    lst._handle(e.KEY_RIGHTCTRL, 0)
    assert events == ["press", "interrupt", "release"]


def test_escape_and_wait_released():
    lst, events = _listener("rightctrl")
    lst._handle(e.KEY_ESC, 1)
    assert events == ["escape"]
    lst._handle(e.KEY_RIGHTCTRL, 1)
    assert not lst.wait_released(timeout=0.05)
    threading.Timer(0.05, lst._handle, args=(e.KEY_RIGHTCTRL, 0)).start()
    assert lst.wait_released(timeout=1)


# -- audio ----------------------------------------------------------------------------


def test_resample_and_silence():
    one_second_48k = np.sin(np.linspace(0, 440 * 2 * np.pi, 48_000)).astype(np.float32)
    assert audio.resample(one_second_48k, 48_000).size == SAMPLE_RATE
    assert audio.resample(one_second_48k[:44_100], 44_100).size == SAMPLE_RATE
    assert audio.is_silent(np.zeros(SAMPLE_RATE, np.float32))
    assert not audio.is_silent(audio.resample(one_second_48k, 48_000) * 0.1)


# -- dictation loop -------------------------------------------------------------------


class FakeRecorder:
    def __init__(self, **_):
        self.recording, self.elapsed = False, 1.0

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
        return (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def cancel(self):
        self.recording = False


class FakeInjector:
    def __init__(self, *_):
        self.inserted, self.method, self.uinput_error = [], "fake", ""
        self.done = threading.Event()

    def insert(self, text):
        self.inserted.append(text)
        self.done.set()
        return "pasted (fake)"

    def close(self):
        pass


class FakeEngine:
    model_id = c.Config().stt.model

    def transcribe(self, audio, *, language="auto", hints=()):
        return "um hello comma world"


@pytest.fixture
def loop(monkeypatch):
    monkeypatch.setattr(dictation, "Injector", FakeInjector)
    monkeypatch.setattr(dictation.audio, "Recorder", FakeRecorder)
    cfg = c.Config()
    cfg.hotkey.evdev_enabled = False
    cfg.ui.sounds = False
    cfg.llm.enabled = False
    logs = []
    d = dictation.Dictation(cfg, log=logs.append)
    d.engine = FakeEngine()
    d.start()
    yield d, logs
    d.close()


def test_hold_to_talk_inserts_cleaned_text(loop):
    d, _ = loop
    d.handle_hotkey("press")
    assert d.recording
    d.handle_hotkey("release")
    assert d.injector.done.wait(2)
    assert d.injector.inserted == ["hello, world "]


def test_interrupt_cancels_silently(loop):
    d, logs = loop
    d.handle_hotkey("press")
    d.handle_hotkey("interrupt")
    d.handle_hotkey("release")
    assert not d.recording and not d.injector.done.wait(0.2)
    assert "Cancelled." not in " ".join(logs)


def test_toggle_mode(loop):
    d, _ = loop
    d.cfg.hotkey.mode = "toggle"
    d.handle_hotkey("press")
    d.handle_hotkey("release")
    assert d.recording  # release doesn't stop in toggle mode
    d.handle_hotkey("press")
    assert d.injector.done.wait(2)


def test_short_tap_is_ignored(loop):
    d, logs = loop
    d.handle_hotkey("press")
    d.recorder.elapsed = 0.1
    d.handle_hotkey("release")
    assert not d.injector.done.wait(0.2)
    assert any("too short" in line for line in logs)
