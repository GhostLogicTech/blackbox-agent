"""Tests for agent.normalize — telemetry → event schema transformation."""

import uuid
from unittest.mock import patch

from agent.normalize import normalize_telemetry


AGENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SOURCE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee:test-host"


class TestFullPayload:
    """Tests for the complete payload structure."""

    def test_top_level_keys(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert "events" in result
        assert "source_id" in result
        assert "agent_id" in result
        assert "endpoint_name" in result
        assert "batch_id" in result
        assert "timestamp" in result

    def test_five_events_produced(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert len(result["events"]) == 5

    def test_event_types(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        types = [e["event_type"] for e in result["events"]]
        assert types == ["system", "processes", "network", "disk_usage", "open_ports"]

    def test_agent_id_passthrough(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert result["agent_id"] == AGENT_ID

    def test_source_id_passthrough(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert result["source_id"] == SOURCE_ID

    def test_endpoint_name_is_hostname(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert result["endpoint_name"] == "test-host"

    def test_batch_id_is_uuid(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        parsed = uuid.UUID(result["batch_id"])
        assert str(parsed) == result["batch_id"]

    def test_timestamp_iso_format(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        ts = result["timestamp"]
        # ISO 8601 UTC ends with +00:00
        assert "T" in ts
        assert "+" in ts or "Z" in ts


class TestSystemEvent:
    """Tests for the system event specifically."""

    def test_system_event_fields(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        system = result["events"][0]
        assert system["event_type"] == "system"
        data = system["data"]
        assert data["hostname"] == "test-host"
        assert data["os"] == "Windows"
        assert data["cpu_percent"] == 12.5
        assert data["ram_percent"] == 50.0
        assert data["uptime_secs"] == 86400.0
        assert data["memory"]["total_bytes"] == 17179869184

    def test_system_event_has_timestamp(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert "timestamp" in result["events"][0]


class TestProcessesEvent:
    """Tests for the processes event."""

    def test_processes_count(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        proc_event = [e for e in result["events"] if e["event_type"] == "processes"][0]
        assert proc_event["data"]["count"] == 2

    def test_processes_top_list(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        proc_event = [e for e in result["events"] if e["event_type"] == "processes"][0]
        assert proc_event["data"]["top"] == sample_raw_telemetry["processes"]


class TestNetworkEvent:

    def test_network_summary(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        net_event = [e for e in result["events"] if e["event_type"] == "network"][0]
        assert net_event["data"]["summary"] == sample_raw_telemetry["network"]


class TestDiskEvent:

    def test_disk_count_and_volumes(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        disk_event = [e for e in result["events"] if e["event_type"] == "disk_usage"][0]
        assert disk_event["data"]["count"] == 1
        assert disk_event["data"]["volumes"] == sample_raw_telemetry["disks"]


class TestPortsEvent:

    def test_ports_count_and_list(self, sample_raw_telemetry):
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        port_event = [e for e in result["events"] if e["event_type"] == "open_ports"][0]
        assert port_event["data"]["count"] == 1
        assert port_event["data"]["ports"] == sample_raw_telemetry["open_ports"]


class TestEmptyListsSkipped:
    """When a list is empty, its event should be omitted."""

    def test_empty_processes_skipped(self, sample_raw_telemetry):
        sample_raw_telemetry["processes"] = []
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        types = [e["event_type"] for e in result["events"]]
        assert "processes" not in types
        assert len(result["events"]) == 4

    def test_empty_network_skipped(self, sample_raw_telemetry):
        sample_raw_telemetry["network"] = []
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        types = [e["event_type"] for e in result["events"]]
        assert "network" not in types

    def test_empty_disks_skipped(self, sample_raw_telemetry):
        sample_raw_telemetry["disks"] = []
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        types = [e["event_type"] for e in result["events"]]
        assert "disk_usage" not in types

    def test_empty_ports_skipped(self, sample_raw_telemetry):
        sample_raw_telemetry["open_ports"] = []
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        types = [e["event_type"] for e in result["events"]]
        assert "open_ports" not in types

    def test_all_lists_empty_only_system(self, sample_raw_telemetry):
        sample_raw_telemetry["processes"] = []
        sample_raw_telemetry["network"] = []
        sample_raw_telemetry["disks"] = []
        sample_raw_telemetry["open_ports"] = []
        result = normalize_telemetry(sample_raw_telemetry, AGENT_ID, SOURCE_ID)
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "system"
