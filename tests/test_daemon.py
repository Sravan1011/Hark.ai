import json
import os
import stat

import pytest

from hark import cli, daemon, history, ipc, paths
from hark import config as c
from hark.errors import HarkError


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "run").mkdir()


# -- ipc ------------------------------------------------------------------------------


def test_ipc_round_trip_and_errors():
    server = ipc.Server(lambda req: {"ok": True, "echo": req["cmd"]})
    server.start()
    try:
        assert ipc.request("hello")["echo"] == "hello"
        assert stat.S_IMODE(os.stat(paths.socket_path()).st_mode) == 0o600
        with pytest.raises(ipc.AlreadyRunning):
            ipc.Server(lambda req: {"ok": True})
    finally:
        server.close()
    assert not paths.socket_path().exists()
    with pytest.raises(ipc.NotRunning):
        ipc.request("hello")


def test_ipc_handler_errors_are_returned():
    def handler(req):
        raise c.ConfigError("bad setting")

    server = ipc.Server(handler)
    server.start()
    try:
        with pytest.raises(HarkError, match="bad setting"):
            ipc.request("reload")
    finally:
        server.close()


def test_stale_socket_is_replaced():
    import socket

    stale = socket.socket(socket.AF_UNIX)
    stale.bind(str(paths.socket_path()))  # bound but never listening: like a crashed daemon
    stale.close()
    server = ipc.Server(lambda req: {"ok": True})
    server.start()
    try:
        assert ipc.is_running()
    finally:
        server.close()


# -- history --------------------------------------------------------------------------


def test_history_append_read_trim_clear(monkeypatch):
    monkeypatch.setattr(history, "MAX_ENTRIES", 5)
    for i in range(7):
        history.append({"text": f"t{i}"})
    assert stat.S_IMODE(os.stat(paths.history_file()).st_mode) == 0o600
    assert [e["text"] for e in history.read()] == [f"t{i}" for i in range(2, 7)]
    with open(paths.history_file(), "a") as fh:
        fh.write("{not json\n")
    assert history.read(2)[-1]["text"] == "t6"
    assert history.clear() == 5
    assert history.read() == []


# -- daemon command handling ------------------------------------------------------------


class FakeDictation:
    def __init__(self, cfg, *, log, on_result, log_text, on_event=None):
        self.cfg, self.on_result = cfg, on_result
        self.state, self.listener, self.engine, self.combo = "idle", None, None, (97,)
        self.calls = []

    def toggle(self):
        self.calls.append("toggle")
        self.state = "recording"

    def begin(self):
        self.calls.append("begin")

    def finish(self):
        self.calls.append("finish")

    def cancel(self):
        self.calls.append("cancel")

    def reconfigure(self, cfg):
        self.calls.append(("reconfigure", cfg.llm.model))
        return ["llm"]


@pytest.fixture
def fake_daemon(monkeypatch):
    monkeypatch.setattr(daemon, "Dictation", FakeDictation)
    return daemon.Daemon(c.Config(), log=lambda _m: None)


def test_daemon_commands(fake_daemon):
    resp = fake_daemon.handle({"cmd": "toggle"})
    assert resp["ok"] and resp["state"] == "recording"
    for cmd, call in (("start", "begin"), ("stop", "finish"), ("cancel", "cancel")):
        fake_daemon.handle({"cmd": cmd})
        assert fake_daemon.dictation.calls[-1] == call
    assert fake_daemon.handle({"cmd": "nope"})["ok"] is False


def test_daemon_reload_reads_config(fake_daemon):
    cfg = c.Config()
    cfg.llm.model = "gemma3:1b"
    c.save(cfg)
    fake_daemon.handle({"cmd": "reload"})
    assert fake_daemon.dictation.calls[-1] == ("reconfigure", "gemma3:1b")
    assert fake_daemon.cfg.llm.model == "gemma3:1b"


def test_daemon_records_history(fake_daemon):
    from hark.dictation import Result

    fake_daemon._on_result(Result(raw="um hi", text="Hi", delivered="pasted (uinput)",
                                  audio_s=1.0, stt_s=0.3, llm_status="off", llm_s=0))
    assert history.read()[-1]["text"] == "Hi"
    assert fake_daemon.status()["last"]["text"] == "Hi"
    fake_daemon.cfg.save_history = False
    fake_daemon._on_result(Result(raw="x", text="Secret", delivered="", audio_s=1, stt_s=0,
                                  llm_status="off", llm_s=0))
    assert history.read()[-1]["text"] == "Hi"


# -- cli ------------------------------------------------------------------------------


def test_cli_when_not_running(capsys):
    assert cli.main(["toggle"]) == 1
    assert "hark daemon --detach" in capsys.readouterr().err
    assert cli.main(["status", "--json"]) == 3
    assert json.loads(capsys.readouterr().out) == {"state": "stopped"}


def test_cli_talks_to_running_daemon(fake_daemon, capsys):
    server = ipc.Server(fake_daemon.handle)
    server.start()
    try:
        assert cli.main(["toggle"]) == 0
        assert "recording" in capsys.readouterr().out
        assert cli.main(["llm", "style", "notes"]) == 0  # saving settings triggers a reload
        assert fake_daemon.dictation.calls[-1][0] == "reconfigure"
        assert cli.main(["status", "--json"]) == 0
        assert json.loads(capsys.readouterr().out.splitlines()[-1])["state"] == "recording"
    finally:
        server.close()
