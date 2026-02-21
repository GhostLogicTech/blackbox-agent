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

    hostname = raw.get("hostname", "unknown")

    return {
        "events": events,
        "source_id": source_id,
        "agent_id": agent_id,
        "endpoint_name": hostname,
        "batch_id": str(uuid.uuid4()),
        "timestamp": ts,
    }


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
