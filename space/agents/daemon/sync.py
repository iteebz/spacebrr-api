
import logging
import time

from space.lib import state

EMAIL_CHECK_INTERVAL = 60
logger = logging.getLogger(__name__)


def _due(key: str, interval: int) -> bool:
    last = state.get(key, 0)
    now = int(time.time())
    if now - last < interval:
        return False
    state.set(key, now)
    return True


def check_email_sync() -> None:
    if not _due("daemon_last_email_check", EMAIL_CHECK_INTERVAL):
        return
    from space.agents import email  # noqa: PLC0415

    try:
        email.sync_inbound()
    except Exception:
        logger.exception("email_check")
