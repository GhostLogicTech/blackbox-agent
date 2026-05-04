"""Main agent loop. Collect, normalize, send, seal — with offline queue + crash resilience."""

import logging
import os
import random
import socket
import time
import traceback

from . import collector
from . import normalize
from . import client
from .log import scrub_sensitive

log = logging.getLogger("ghostlogic.loop")


def run(config: dict) -> None:
    """Run the agent loop forever. Never exits unless killed."""
    agent_id = config["agent_id"]
    tenant_key = config.get("tenant_key", "")
    base_url = config["blackbox_url"]
    demo_mode = config.get("demo_mode", True)
    collect_interval = config.get("collect_interval_secs", 5)
    seal_interval = config.get("seal_interval_secs", 60)
    queue_dir = config.get("queue_dir", "")
    max_retries = config.get("max_retries", 3)

    # Default queue dir next to the script
    if not queue_dir:
        queue_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "queue")
    os.makedirs(queue_dir, exist_ok=True)

    hostname = socket.gethostname()
    log.info("=" * 60)
    log.info("Agent started  id=%s  host=%s", agent_id, hostname)
    log.info("Blackbox URL:  %s", base_url)
    log.info("Collect every: %ds   Seal every: %ds", collect_interval, seal_interval)
    log.info("Queue dir:     %s", os.path.abspath(queue_dir))
    log.info("Max retries:   %d", max_retries)
    log.info("Demo mode:     %s", demo_mode)
    log.info("PID:           %d", os.getpid())
    log.info("Collectors:    21")
    log.info("=" * 60)

    if not tenant_key:
        log.warning("No tenant_key configured. Requests will not authenticate.")

    last_seal = time.monotonic()
    cycle = 0
    consecutive_failures = 0

    while True:
        cycle += 1
        cycle_start = time.monotonic()

        # Refresh hostname each cycle (handles VM migration, DHCP changes)
        hostname = socket.gethostname()
        source_id = f"{agent_id}:{hostname}"

        try:
            # Flush offline queue first (if server came back)
            if cycle % 5 == 1:  # every 5th cycle
                try:
                    client.flush_queue(queue_dir, config)
                except Exception as e:
                    log.error("Queue flush error: %s", e)

            # Collect + send
            success = _collect_and_send(
                base_url, tenant_key, agent_id, source_id,
                demo_mode, cycle, queue_dir, max_retries,
            )

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures % 10 == 0:
                    log.warning(
                        "⚠ %d consecutive send failures — data is being queued offline",
                        consecutive_failures,
                    )

        except Exception as e:
            consecutive_failures += 1
            log.error("Cycle %d CRASHED: %s", cycle, e)
            log.error(traceback.format_exc())
            # Never exit the loop — just keep going

        # Seal check — monotonic clock immune to NTP jumps
        now = time.monotonic()
        if now - last_seal >= seal_interval:
            try:
                _seal(base_url, tenant_key, demo_mode)
                last_seal = now
            except Exception as e:
                log.error("Seal failed: %s", e)

        # Sleep with jitter
        elapsed = time.monotonic() - cycle_start
        sleep_time = max(1, collect_interval - elapsed)
        jitter = random.uniform(0, sleep_time * 0.1)
        time.sleep(sleep_time + jitter)


def _collect_and_send(
    base_url: str,
    tenant_key: str,
    agent_id: str,
    source_id: str,
    demo_mode: bool,
    cycle: int,
    queue_dir: str,
    max_retries: int,
) -> bool:
    """Collect, normalize, send. Returns True if sent successfully.
    On failure, queues the payload to disk.
    """
    raw = collector.collect_all()

    # Log collector failures
    failures = raw.get("collector_failures", [])
    if failures:
        log.warning("Cycle %d: %d collector(s) failed: %s", cycle, len(failures), "; ".join(failures))

    payload = normalize.normalize_telemetry(raw, agent_id, source_id)

    event_count = len(payload.get("events", []))
    log.debug("Cycle %d: collected %d events", cycle, event_count)

    resp = client.post_ingest(base_url, tenant_key, payload, demo_mode, max_retries=max_retries)
    status = resp.get("status", "unknown")

    if status == "ingested":
        accepted = resp.get("accepted", 0)
        buffered = resp.get("buffer_size", 0)
        log.info(
            "Cycle %d: sent %d events, accepted=%d buffered=%d",
            cycle, event_count, accepted, buffered,
        )
        return True
    else:
        detail = resp.get("detail", "")
        detail = scrub_sensitive(str(detail), tenant_key)
        log.warning("Cycle %d: status=%s detail=%s", cycle, status, detail[:200])

        # Queue to disk for later retry
        client.queue_to_disk(payload, queue_dir)
        return False


def run_once(config: dict) -> int:
    """Run exactly one collect+send cycle, then return.

    Used by --once smoke mode for safe re-enable validation. Does NOT call
    flush_queue (no historical drain). Does NOT call _seal. Returns 0 on
    successful ingest, 1 on send failure. The single cycle is queued to disk
    on failure so behavior matches the normal loop's first cycle, but no
    further cycles run.
    """
    agent_id = config["agent_id"]
    tenant_key = config.get("tenant_key", "")
    base_url = config["blackbox_url"]
    demo_mode = config.get("demo_mode", True)
    queue_dir = config.get("queue_dir", "")
    max_retries = config.get("max_retries", 3)

    if not queue_dir:
        queue_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "queue")
    os.makedirs(queue_dir, exist_ok=True)

    hostname = socket.gethostname()
    source_id = f"{agent_id}:{hostname}"

    log.info("=" * 60)
    log.info("Agent --once smoke: one collect+send cycle, no queue flush, no seal")
    log.info("Blackbox URL:  %s", base_url)
    log.info("Agent ID:      %s", agent_id)
    log.info("Source ID:     %s", source_id)
    log.info("=" * 60)

    if not tenant_key:
        log.warning("No tenant_key configured. The fresh post will not authenticate.")

    success = _collect_and_send(
        base_url, tenant_key, agent_id, source_id,
        demo_mode, 1, queue_dir, max_retries,
    )
    return 0 if success else 1


def _seal(base_url: str, tenant_key: str, demo_mode: bool) -> None:
    log.info("Sealing capsule...")
    resp = client.post_seal(base_url, tenant_key, demo_mode)
    status = resp.get("status", "unknown")
    if status == "error":
        detail = scrub_sensitive(str(resp.get("detail", "")), tenant_key)
        log.warning("Seal response: %s — %s", status, detail[:200])
    else:
        capsule_id = resp.get("capsule_id", resp.get("id", ""))
        log.info("Seal complete: status=%s capsule=%s", status, capsule_id)
