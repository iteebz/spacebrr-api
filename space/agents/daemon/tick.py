
import logging
import sys
import time
import traceback

from space import stats
from space.agents import daemon, spawn
from space.ledger import decisions, insights

TICK_INTERVAL = 2
HOUSEKEEP_INTERVAL = 60
logger = logging.getLogger(__name__)

_last_housekeep: float = 0


def tick() -> None:
    try:
        killed, reaped = spawn.reconcile()
        if killed or reaped:
            logger.warning("spawn_reconcile killed=%d reaped=%d", killed, reaped)
        _housekeep()
        if not daemon.is_on():
            return
        since = daemon.enabled_at()
        if since:
            launched_count = spawn.count(since=since)
            if daemon.limit_reached(launched_count):
                daemon.off()
                return
        daemon.check_email_sync()
        _spawn_tick()
    except Exception:
        logger.exception("tick")
        traceback.print_exc(file=sys.stderr)


def _housekeep() -> None:
    global _last_housekeep
    now = time.monotonic()
    if now - _last_housekeep < HOUSEKEEP_INTERVAL:
        return
    _last_housekeep = now
    try:
        insights.prune_stale_status()
        spawn.clear_inertia_summaries()
        stats.write_public_stats()
        decayed = decisions.decay_human_blocked(hours=48)
        if decayed:
            logger.warning("decision_decay count=%d decisions=%s", len(decayed), decayed)
    except Exception:
        logger.exception("housekeep")


def _spawn_tick() -> None:
    active = daemon.active_sovereign()
    slots = daemon.available_slots(active)

    resumed = daemon.resume_crashed(slots, active)
    if resumed:
        logger.warning("spawn_tick resumed=%d crashed spawns", resumed)
        active = daemon.active_sovereign()
        slots = daemon.available_slots(active)

    if slots <= 0:
        return

    picked = daemon.pick_idle_agents(slots, active)
    if picked:
        logger.warning("spawn_tick slots=%d picking=%s", slots, [a.handle for a in picked])
    for agent in picked:
        try:
            daemon.spawn_agent(agent)
        except Exception:
            logger.exception("spawn_agent %s", agent.handle)
            break
        active = daemon.active_sovereign()
        if daemon.available_slots(active) <= 0:
            break
