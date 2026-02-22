"""Shared fixtures for blackbox-agent tests."""

import json
import pytest


@pytest.fixture
def sample_config():
    """A valid, fully-populated config dict."""
    return {
        "blackbox_url": "https://api.ghostlogic.tech",
        "tenant_key": "glk_test_key_abc123",
        "agent_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "collect_interval_secs": 5,
        "seal_interval_secs": 60,
        "demo_mode": True,
        "log_dir": "",
        "log_max_hours": 24,
    }


@pytest.fixture
def sample_raw_telemetry():
    """Realistic output from collector.collect_all() with all 5 event types."""
    return {
        "hostname": "test-host",
        "os": {
            "system": "Windows",
            "release": "10",
            "version": "10.0.19045",
            "machine": "AMD64",
        },
        "username": "testuser",
        "uptime_secs": 86400.0,
        "cpu_percent": 12.5,
        "memory": {
            "total_bytes": 17179869184,
            "used_bytes": 8589934592,
            "percent": 50.0,
        },
        "ram_percent": 50.0,
        "processes": [
            {"pid": 1234, "name": "python.exe", "mem_kb": 102400},
            {"pid": 5678, "name": "chrome.exe", "mem_kb": 512000},
        ],
        "network": [{"listening": 15, "established": 42}],
        "disks": [
            {
                "mount": "C:\\",
                "total_bytes": 500000000000,
                "used_bytes": 250000000000,
                "free_bytes": 250000000000,
                "percent": 50.0,
            }
        ],
        "open_ports": [
            {
                "proto": "TCP",
                "address": "0.0.0.0",
                "port": 8080,
                "pid": 1234,
                "state": "LISTENING",
            }
        ],
    }


@pytest.fixture
def config_file(tmp_path, sample_config):
    """Write sample config to a temp file and return the path."""
    path = tmp_path / "agent-config.json"
    path.write_text(json.dumps(sample_config, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def mock_register_response():
    """Typical successful /api/v1/register response."""
    return {
        "api_key": "glk_test_new_key_xyz789",
        "tenant_id": "tenant-001",
        "key_id": "key-001",
        "name": "auto:test-host",
    }
