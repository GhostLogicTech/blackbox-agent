"""Normalize raw collector output into GhostLogic event JSON schema."""

import time
import uuid


def normalize_telemetry(raw: dict, agent_id: str, source_id: str) -> dict:
    """Convert raw collector dict into a GhostLogic ingest payload.

    Returns the full payload dict ready to POST to /api/v1/ingest.
    """
    ts = _iso_now()

    events = []

    # System info event
    events.append({
        "event_type": "system",
        "timestamp": ts,
        "data": {
            "hostname": raw.get("hostname", "unknown"),
            "os": raw.get("os", {}).get("system", "unknown"),
            "os_version": raw.get("os", {}).get("version", ""),
            "os_release": raw.get("os", {}).get("release", ""),
            "machine": raw.get("os", {}).get("machine", ""),
            "username": raw.get("username", "unknown"),
            "uptime_secs": raw.get("uptime_secs"),
            "cpu_percent": raw.get("cpu_percent"),
            "ram_percent": raw.get("ram_percent"),
            "memory": raw.get("memory"),
        },
    })

    # Process list event
    processes = raw.get("processes", [])
    if processes:
        events.append({
            "event_type": "processes",
            "timestamp": ts,
            "data": {
                "count": len(processes),
                "top": processes,
            },
        })

    # Network summary event
    network = raw.get("network", [])
    if network:
        events.append({
            "event_type": "network",
            "timestamp": ts,
            "data": {
                "summary": network,
            },
        })

    # Disk usage event
    disks = raw.get("disks", [])
    if disks:
        events.append({
            "event_type": "disk_usage",
            "timestamp": ts,
            "data": {
                "count": len(disks),
                "volumes": disks,
            },
        })

    # Open ports event
    open_ports = raw.get("open_ports", [])
    if open_ports:
        events.append({
            "event_type": "open_ports",
            "timestamp": ts,
            "data": {
                "count": len(open_ports),
                "ports": open_ports,
            },
        })

    # --- NEW EVENT TYPES ---

    _append_list_event(events, ts, raw, "event_log", "event_log", "entries")
    _append_list_event(events, ts, raw, "services", "services", "services", count_key="stopped_count")
    _append_list_event(events, ts, raw, "network_bytes", "network_bytes", "adapters", include_count=False)
    _append_list_event(events, ts, raw, "logged_in_users", "user_sessions", "sessions")
    _append_list_event(events, ts, raw, "hotfixes", "hotfixes", "patches")
    _append_list_event(events, ts, raw, "scheduled_tasks", "scheduled_tasks", "tasks")
    _append_list_event(events, ts, raw, "dns_cache", "dns_cache", "entries")
    _append_list_event(events, ts, raw, "startup_programs", "startup_programs", "programs")

    # Dict-type events (firewall, environment, battery)
    for raw_key, evt_type in [("firewall", "firewall"), ("environment", "environment")]:
        val = raw.get(raw_key)
        if val:
            events.append({"event_type": evt_type, "timestamp": ts, "data": val})

    battery = raw.get("battery")
    if battery:
        events.append({"event_type": "battery", "timestamp": ts, "data": battery})

    # Collector failures (meta)
    failures = raw.get("collector_failures", [])
    if failures:
        events.append({
            "event_type": "collector_failures",
            "timestamp": ts,
            "data": {"count": len(failures), "failures": failures},
        })

    hostname = raw.get("hostname", "unknown")

    return {
        "events": events,
        "source_id": source_id,
        "agent_id": agent_id,
        "endpoint_name": hostname,
        "batch_id": str(uuid.uuid4()),
        "timestamp": ts,
    }


def _append_list_event(
    events: list, ts: str, raw: dict,
    raw_key: str, event_type: str, data_key: str,
    count_key: str = "count", include_count: bool = True,
) -> None:
    """Helper: if raw[raw_key] has items, append a normalized event."""
    items = raw.get(raw_key, [])
    if items:
        data: dict = {data_key: items}
        if include_count:
            data[count_key] = len(items)
        events.append({"event_type": event_type, "timestamp": ts, "data": data})


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
