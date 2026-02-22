"""Tests for agent.log — logging setup and sensitive scrubbing."""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

from agent.log import setup_logging, scrub_sensitive


class TestSetupLogging:
    """Tests for setup_logging()."""

    def test_creates_log_dir(self, tmp_path):
        log_dir = str(tmp_path / "new_logs")
        setup_logging(log_dir)
        assert os.path.isdir(log_dir)

    def test_returns_logger(self, tmp_path):
        logger = setup_logging(str(tmp_path))
        assert isinstance(logger, logging.Logger)
        assert logger.name == "ghostlogic"

    def test_has_file_handler(self, tmp_path):
        logger = setup_logging(str(tmp_path))
        handler_types = [type(h) for h in logger.handlers]
        assert TimedRotatingFileHandler in handler_types

    def test_has_stream_handler(self, tmp_path):
        logger = setup_logging(str(tmp_path))
        handler_types = [type(h) for h in logger.handlers]
        assert logging.StreamHandler in handler_types

    def test_log_file_created(self, tmp_path):
        setup_logging(str(tmp_path))
        log_file = tmp_path / "ghostlogic-agent.log"
        assert log_file.exists()

    def test_logger_level_debug(self, tmp_path):
        logger = setup_logging(str(tmp_path))
        assert logger.level == logging.DEBUG

    def setup_method(self):
        """Clean up logger handlers before each test to avoid accumulation."""
        logger = logging.getLogger("ghostlogic")
        logger.handlers.clear()


class TestScrubSensitive:
    """Tests for scrub_sensitive()."""

    def test_replaces_key(self):
        msg = "Connected with key glk_secret_abc123"
        result = scrub_sensitive(msg, "glk_secret_abc123")
        assert "glk_secret_abc123" not in result
        assert "[REDACTED]" in result

    def test_no_key_in_message(self):
        msg = "Agent started successfully"
        result = scrub_sensitive(msg, "glk_secret_abc123")
        assert result == msg

    def test_empty_key(self):
        msg = "Some log message"
        result = scrub_sensitive(msg, "")
        assert result == msg

    def test_multiple_occurrences(self):
        msg = "key=glk_x, again key=glk_x"
        result = scrub_sensitive(msg, "glk_x")
        assert result.count("[REDACTED]") == 2
        assert "glk_x" not in result
