"""Control socket between `hark <command>` and the running daemon.

One JSON request line per connection, one JSON response line back:
    -> {"cmd": "toggle"}
    <- {"ok": true, "state": "recording", ...}
The socket lives in $XDG_RUNTIME_DIR (private to the user) and is created mode 0600.
Kept free of heavy imports: `hark toggle` should feel instant from a desktop shortcut.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
from collections.abc import Callable
from typing import Any

from . import paths
from .errors import HarkError

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class NotRunning(HarkError):
    def __init__(self):
        super().__init__("Hark isn't running. Start it with: hark daemon --detach "
                         "(or hark listen in a terminal)")


class AlreadyRunning(HarkError):
    pass


def request(cmd: str, timeout: float = 5.0, **args: Any) -> dict[str, Any]:
    path = paths.socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall((json.dumps({"cmd": cmd, **args}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
    except (FileNotFoundError, ConnectionRefusedError):
        raise NotRunning() from None
    except OSError as e:
        raise HarkError(f"couldn't talk to Hark at {path}: {e}") from None
    try:
        response = json.loads(data)
    except ValueError:
        raise HarkError("Hark sent an invalid response") from None
    if not response.get("ok"):
        raise HarkError(response.get("error", "request failed"))
    return response


def is_running() -> bool:
    try:
        request("ping", timeout=1.0)
    except HarkError:
        return False
    return True


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            req = json.loads(self.rfile.readline())
        except ValueError:
            req = None
        if not isinstance(req, dict):
            resp: dict[str, Any] = {"ok": False, "error": "invalid request"}
        else:
            try:
                resp = self.server.handler(req)
            except HarkError as e:
                resp = {"ok": False, "error": str(e)}
        self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, handler: Handler):
        self.handler = handler
        super().__init__(path, _RequestHandler)


class Server:
    """Owns the socket; refuses to start if another daemon is already answering."""

    def __init__(self, handler: Handler):
        self.path = paths.socket_path()
        if is_running():
            raise AlreadyRunning("Hark is already running (see: hark status)")
        self.path.unlink(missing_ok=True)  # stale socket from a crashed daemon
        old_umask = os.umask(0o177)  # socket created as 0600
        try:
            self._server = _Server(str(self.path), handler)
        finally:
            os.umask(old_umask)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="hark-ipc", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.path.unlink(missing_ok=True)
