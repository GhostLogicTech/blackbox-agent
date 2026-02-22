"""Tests for agent.loop — main agent loop (collect → normalize → send)."""

import logging
from unittest.mock import patch, MagicMock, call

import pytest

from agent.loop import run, _collect_and_send, _seal


SAMPLE_CONFIG = {
    "agent_id": "test-agent-id",
    "tenant_key": "glk_test_key",
    "blackbox_url": "https://api.ghostlogic.tech",
    "demo_mode": True,
    "collect_interval_secs": 5,
    "seal_interval_secs": 60,
}


class TestCollectAndSend:
    """Tests for _collect_and_send() helper."""

    @patch("agent.loop.client.post_ingest")
    @patch("agent.loop.normalize.normalize_telemetry")
    @patch("agent.loop.collector.collect_all")
    def test_collect_normalize_ingest_called(self, mock_collect, mock_normalize, mock_ingest):
        mock_collect.return_value = {"hostname": "h", "os": {}}
        mock_normalize.return_value = {"events": [1, 2, 3]}
        mock_ingest.return_value = {"status": "ingested", "accepted": 3, "buffer_size": 3}

        _collect_and_send("https://api.test", "glk_key", "agent-1", "src-1", True, 1)

        mock_collect.assert_called_once()
        mock_normalize.assert_called_once_with(mock_collect.return_value, "agent-1", "src-1")
        mock_ingest.assert_called_once()

    @patch("agent.loop.client.post_ingest")
    @patch("agent.loop.normalize.normalize_telemetry")
    @patch("agent.loop.collector.collect_all")
    def test_non_ingested_status_logged(self, mock_collect, mock_normalize, mock_ingest, caplog):
        mock_collect.return_value = {}
        mock_normalize.return_value = {"events": []}
        mock_ingest.return_value = {"status": "error", "detail": "bad request"}

        with caplog.at_level(logging.WARNING, logger="ghostlogic.loop"):
            _collect_and_send("https://api.test", "glk_key", "a", "s", True, 1)

        assert any("error" in r.message.lower() or "status=error" in r.message for r in caplog.records)


class TestSeal:
    """Tests for _seal() helper."""

    @patch("agent.loop.client.post_seal")
    def test_seal_success(self, mock_seal, caplog):
        mock_seal.return_value = {"status": "sealed", "capsule_id": "cap-001"}
        with caplog.at_level(logging.INFO, logger="ghostlogic.loop"):
            _seal("https://api.test", "glk_key", True)
        mock_seal.assert_called_once_with("https://api.test", "glk_key", True)
        assert any("cap-001" in r.message for r in caplog.records)

    @patch("agent.loop.client.post_seal")
    def test_seal_error_logged(self, mock_seal, caplog):
        mock_seal.return_value = {"status": "error", "detail": "server down"}
        with caplog.at_level(logging.WARNING, logger="ghostlogic.loop"):
            _seal("https://api.test", "glk_key", True)
        assert any("server down" in r.message for r in caplog.records)


class TestRunLoop:
    """Tests for run() — the infinite loop."""

    @patch("agent.loop.time.sleep", side_effect=[None, KeyboardInterrupt])
    @patch("agent.loop.time.monotonic", side_effect=[0, 0, 10, 10])
    @patch("agent.loop.random.uniform", return_value=0.0)
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 5, "buffer_size": 5})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": [1, 2, 3, 4, 5]})
    @patch("agent.loop.collector.collect_all", return_value={"hostname": "h"})
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_loop_runs_collect_cycle(self, mock_host, mock_collect, mock_norm, mock_ingest,
                                     mock_rand, mock_mono, mock_sleep):
        with pytest.raises(KeyboardInterrupt):
            run(SAMPLE_CONFIG)
        assert mock_collect.call_count >= 1
        assert mock_ingest.call_count >= 1

    @patch("agent.loop.time.sleep", side_effect=KeyboardInterrupt)
    @patch("agent.loop.time.monotonic", side_effect=[0, 100])  # 100 > seal_interval(60)
    @patch("agent.loop.random.uniform", return_value=0.0)
    @patch("agent.loop.client.post_seal", return_value={"status": "sealed", "capsule_id": "x"})
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 5, "buffer_size": 5})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": []})
    @patch("agent.loop.collector.collect_all", return_value={"hostname": "h"})
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_seal_fires_after_interval(self, mock_host, mock_collect, mock_norm,
                                       mock_ingest, mock_seal, mock_rand, mock_mono, mock_sleep):
        with pytest.raises(KeyboardInterrupt):
            run(SAMPLE_CONFIG)
        mock_seal.assert_called_once()

    @patch("agent.loop.time.sleep", side_effect=KeyboardInterrupt)
    @patch("agent.loop.time.monotonic", side_effect=[0, 10])  # 10 < seal_interval(60)
    @patch("agent.loop.random.uniform", return_value=0.0)
    @patch("agent.loop.client.post_seal")
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 5, "buffer_size": 5})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": []})
    @patch("agent.loop.collector.collect_all", return_value={"hostname": "h"})
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_seal_not_before_interval(self, mock_host, mock_collect, mock_norm,
                                      mock_ingest, mock_seal, mock_rand, mock_mono, mock_sleep):
        with pytest.raises(KeyboardInterrupt):
            run(SAMPLE_CONFIG)
        mock_seal.assert_not_called()

    @patch("agent.loop.time.sleep", side_effect=KeyboardInterrupt)
    @patch("agent.loop.time.monotonic", return_value=0)
    @patch("agent.loop.random.uniform", return_value=0.0)
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 0, "buffer_size": 0})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": []})
    @patch("agent.loop.collector.collect_all", side_effect=RuntimeError("disk full"))
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_collection_error_continues(self, mock_host, mock_collect, mock_norm,
                                        mock_ingest, mock_rand, mock_mono, mock_sleep):
        """Exception in collect_all doesn't crash the loop."""
        with pytest.raises(KeyboardInterrupt):
            run(SAMPLE_CONFIG)
        # If we got to sleep (which raised KeyboardInterrupt), the loop continued past the error

    @patch("agent.loop.time.sleep", side_effect=KeyboardInterrupt)
    @patch("agent.loop.time.monotonic", return_value=0)
    @patch("agent.loop.random.uniform", return_value=0.3)
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 5, "buffer_size": 5})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": []})
    @patch("agent.loop.collector.collect_all", return_value={"hostname": "h"})
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_jitter_applied(self, mock_host, mock_collect, mock_norm,
                            mock_ingest, mock_rand, mock_mono, mock_sleep):
        with pytest.raises(KeyboardInterrupt):
            run(SAMPLE_CONFIG)
        # sleep should be called with collect_interval + jitter = 5 + 0.3 = 5.3
        mock_sleep.assert_called_with(5.3)

    @patch("agent.loop.time.sleep", side_effect=KeyboardInterrupt)
    @patch("agent.loop.time.monotonic", return_value=0)
    @patch("agent.loop.random.uniform", return_value=0.0)
    @patch("agent.loop.client.post_ingest", return_value={"status": "ingested", "accepted": 5, "buffer_size": 5})
    @patch("agent.loop.normalize.normalize_telemetry", return_value={"events": []})
    @patch("agent.loop.collector.collect_all", return_value={"hostname": "h"})
    @patch("agent.loop.socket.gethostname", return_value="test-host")
    def test_no_tenant_key_warning(self, mock_host, mock_collect, mock_norm,
                                    mock_ingest, mock_rand, mock_mono, mock_sleep, caplog):
        config = dict(SAMPLE_CONFIG)
        config["tenant_key"] = ""
        with caplog.at_level(logging.WARNING, logger="ghostlogic.loop"):
            with pytest.raises(KeyboardInterrupt):
                run(config)
        assert any("tenant_key" in r.message for r in caplog.records)
