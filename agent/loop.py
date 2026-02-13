"""Main agent loop. Collect, normalize, send, seal."""

import logging
import random
import socket
import time

from . import collector
from . import normalize
from . import client
from .log import scrub_sensitive

log = logging.getLogger("ghostlogic.loop")


def run(config: dict) -> None:
    """Run the agent loop forever."""
    agent_id = config["agent_id"]
    tenant_key = config.get("tenant_key", "")
    base_url = config["blackbox_url"]
    demo_mode = config.get("demo_mode", True)
    collect_interval = config.get("collect_interval_secs", 5)
    seal_interval = config.get("seal_interval_secs", 60)

    hostname = socket.gethostname()
    log.info("Agent started  id=%s  host=%s", agent_id, hostname)
    log.info("Blackbox URL:  %s", base_url)
    log.info("Collect every: %ds   Seal every: %ds", collect_interval, seal_interval)
    log.info("Demo mode:     %s", demo_mode)

    if not tenant_key:
        log.warning("No tenant_key configured. Requests will not authenticate.")

    last_seal = time.monotonic()
    cycle = 0

    while True:
        cycle += 1

        # Refresh hostname each cycle (handles VM migration, DHCP changes)
        hostname = socket.gethostname()
        source_id = f"{agent_id}:{hostname}"

        try:
            _collect_and_send(base_url, tenant_key, agent_id, source_id, demo_mode, cycle)
        except Exception as e:
            log.error("Collection cycle %d failed: %s", cycle, e)

        # Seal check — monotonic clock immune to NTP jumps
        now = time.monotonic()
        if now - last_seal >= seal_interval:
            try:
                _seal(base_url, tenant_key, demo_mode)
                last_seal = now
            except Exception as e:
                log.error("Seal failed: %s", e)

        # Small jitter (0-10%) to avoid thundering herd
        jitter = random.uniform(0, collect_interval * 0.1)
        time.sleep(collect_interval + jitter)


def _collect_and_send(
    base_url: str,
    tenant_key: str,
    agent_id: str,
    source_id: str,
    demo_mode: bool,
    cycle: int,
) -> None:
    raw = collector.collect_all()
    payload = normalize.normalize_telemetry(raw, agent_id, source_id)

    event_count = len(payload.get("events", []))
    log.debug("Cycle %d: collected %d events", cycle, event_count)

    resp = client.post_ingest(base_url, tenant_key, payload, demo_mode)
    status = resp.get("status", "unknown")

    if status == "ingested":
        accepted = resp.get("accepted", 0)
        buffered = resp.get("buffer_size", 0)
        log.info(
            "Cycle %d: sent %d events, accepted=%d buffered=%d",
            cycle, event_count, accepted, buffered,
        )
    else:
        detail = resp.get("detail", "")
        detail = scrub_sensitive(str(detail), tenant_key)
        log.warning("Cycle %d: status=%s detail=%s", cycle, status, detail[:200])


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
