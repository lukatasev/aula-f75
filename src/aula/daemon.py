"""Background daemon support: --daemon fork, PID file, --stop."""

from __future__ import annotations

import json
import os
import signal
import time

from .state import config_dir

PID_FILE = os.path.join(os.path.expanduser("~/.config/aula-f75"), "anim.pid")
LOG_FILE = os.path.join(os.path.expanduser("~/.config/aula-f75"), "anim.log")


def read_pid():
    try:
        with open(PID_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_pid(info: dict):
    config_dir()
    with open(PID_FILE, "w") as f:
        json.dump(info, f)


def remove_pid():
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def spawn_daemon(argv: list) -> int:
    """Double-fork and exec argv detached. Returns the child pid."""
    config_dir()
    pid = os.fork()
    if pid != 0:
        _, status = os.waitpid(pid, 0)
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError("daemon fork failed")
        info = read_pid()
        return (info or {}).get("pid", -1)
    # first child
    os.setsid()
    pid2 = os.fork()
    if pid2 != 0:
        os._exit(0)
    # second child: detached
    try:
        log = open(LOG_FILE, "a")
        os.dup2(log.fileno(), 0)
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        os.execvp(argv[0], argv)
    except Exception:
        os._exit(1)


def stop_daemon(timeout: float = 5.0) -> bool:
    info = read_pid()
    if not info:
        return False
    pid = info.get("pid")
    if not pid or not alive(pid):
        remove_pid()
        return False
    os.kill(pid, signal.SIGTERM)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not alive(pid):
            remove_pid()
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    remove_pid()
    return True
