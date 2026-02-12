
import contextlib
import logging
import os as _os
import signal
import subprocess
import sys
import time
from pathlib import Path

from space.agents import spawn
from space.lib import store

logger = logging.getLogger(__name__)


def _lock_path() -> Path:
    from space.lib import paths  # noqa: PLC0415

    return paths.dot_space() / "daemon.lock"


def pid() -> int | None:
    lock = _lock_path()
    if not lock.exists():
        return None
    try:
        raw = lock.read_text().strip()
        if not raw.isdigit():
            return None
        p = int(raw)
        _os.kill(p, 0)
        return p
    except (OSError, ValueError):
        return None


def stop() -> bool:
    daemon_pid = pid()

    active = spawn.fetch(status="active")
    for s in active:
        spawn.terminate(s.id)

    if daemon_pid is None:
        return False
    try:
        _os.killpg(daemon_pid, signal.SIGTERM)
    except ProcessLookupError:
        return False

    for _ in range(50):
        time.sleep(0.1)
        if pid() is None:
            return True

    with contextlib.suppress(ProcessLookupError):
        _os.killpg(daemon_pid, signal.SIGKILL)
    return True


def start() -> int | None:
    if existing := pid():
        return existing
    stop()
    log_path = _lock_path().parent / "logs" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fd = log_path.open("a")
    cmd = [sys.executable, "-m", "space.agents.daemon"]
    if sys.platform == "darwin":
        cmd = ["caffeinate", "-i", *cmd]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=log_fd,
        start_new_session=True,
    )
    log_fd.close()
    for _ in range(30):
        time.sleep(0.1)
        if daemon_pid := pid():
            return daemon_pid
    return None


def restart() -> int | None:
    return start()


_running = True


def run(interval: int = 2) -> None:
    import logging  # noqa: PLC0415

    from space.agents.daemon.tick import tick  # noqa: PLC0415

    logging.basicConfig(
        level=logging.WARNING,
        stream=__import__("sys").stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    global _running
    _running = True

    def handle_term(_signum, _frame):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    with store.ensure() as conn:
        repaired = store.repair_fts_if_needed(conn)
        if repaired:
            logger.info("fts_repair tables=%s", repaired)

    while _running:
        tick()
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)
