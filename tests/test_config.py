"""Tests for agent.config — load, save, validate."""

import json
import os
from unittest.mock import patch

import pytest

from agent.config import (
    DEFAULT_CONFIG,
    load_config,
    save_config,
    validate_config,
    _default_config_path,
    _default_log_dir,
)


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_reads_existing_file(self, config_file, sample_config):
        cfg = load_config(config_file)
        assert cfg["tenant_key"] == sample_config["tenant_key"]
        assert cfg["blackbox_url"] == sample_config["blackbox_url"]

    def test_load_merges_with_defaults(self, tmp_path):
        """User config only has one key — rest come from defaults."""
        path = tmp_path / "partial.json"
        path.write_text('{"tenant_key": "glk_partial"}', encoding="utf-8")
        cfg = load_config(str(path))
        assert cfg["tenant_key"] == "glk_partial"
        assert cfg["blackbox_url"] == DEFAULT_CONFIG["blackbox_url"]
        assert cfg["collect_interval_secs"] == DEFAULT_CONFIG["collect_interval_secs"]

    def test_load_creates_default_when_missing(self, tmp_path):
        path = tmp_path / "subdir" / "new-config.json"
        cfg = load_config(str(path))
        # File should be created
        assert path.exists()
        # agent_id should be generated
        assert cfg["agent_id"] != ""
        assert len(cfg["agent_id"]) == 36  # UUID format

    def test_load_generates_agent_id_if_empty(self, tmp_path):
        path = tmp_path / "no-id.json"
        path.write_text('{"agent_id": ""}', encoding="utf-8")
        cfg = load_config(str(path))
        assert cfg["agent_id"] != ""
        assert len(cfg["agent_id"]) == 36

    def test_load_sets_default_log_dir(self, tmp_path):
        path = tmp_path / "no-log.json"
        path.write_text('{"log_dir": ""}', encoding="utf-8")
        cfg = load_config(str(path))
        assert cfg["log_dir"] != ""

    def test_load_env_var_override(self, tmp_path, sample_config):
        path = tmp_path / "env-config.json"
        path.write_text(json.dumps(sample_config), encoding="utf-8")
        with patch.dict(os.environ, {"GHOSTLOGIC_CONFIG": str(path)}):
            cfg = load_config(None)
        assert cfg["tenant_key"] == sample_config["tenant_key"]

    def test_load_permission_error(self, tmp_path, capsys):
        """When we can't create the directory, return defaults."""
        fake_path = "/nonexistent/restricted/dir/config.json"
        with patch("agent.config.os.makedirs", side_effect=PermissionError("denied")):
            with patch("agent.config.os.path.isfile", return_value=False):
                with patch("agent.config._default_config_path", return_value=fake_path):
                    cfg = load_config(fake_path)
        # Should return defaults without crashing
        assert cfg["blackbox_url"] == DEFAULT_CONFIG["blackbox_url"]

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json!!!}", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_config(str(path))


class TestSaveConfig:
    """Tests for save_config()."""

    def test_save_creates_file(self, tmp_path, sample_config):
        path = str(tmp_path / "saved.json")
        save_config(path, sample_config)
        assert os.path.isfile(path)

    def test_save_creates_parent_dirs(self, tmp_path, sample_config):
        path = str(tmp_path / "deep" / "nested" / "config.json")
        save_config(path, sample_config)
        assert os.path.isfile(path)

    def test_save_roundtrip(self, tmp_path, sample_config):
        path = str(tmp_path / "roundtrip.json")
        save_config(path, sample_config)
        loaded = load_config(path)
        assert loaded["tenant_key"] == sample_config["tenant_key"]
        assert loaded["agent_id"] == sample_config["agent_id"]
        assert loaded["blackbox_url"] == sample_config["blackbox_url"]

    def test_save_overwrites_existing(self, tmp_path, sample_config):
        path = str(tmp_path / "overwrite.json")
        save_config(path, sample_config)
        sample_config["tenant_key"] = "glk_updated"
        save_config(path, sample_config)
        with open(path, "r") as f:
            data = json.load(f)
        assert data["tenant_key"] == "glk_updated"


class TestValidateConfig:
    """Tests for validate_config()."""

    def test_valid_config_no_problems(self, sample_config):
        problems = validate_config(sample_config)
        assert problems == []

    def test_missing_tenant_key(self, sample_config):
        sample_config["tenant_key"] = ""
        problems = validate_config(sample_config)
        assert any("tenant_key" in p for p in problems)

    def test_missing_blackbox_url(self, sample_config):
        sample_config["blackbox_url"] = ""
        problems = validate_config(sample_config)
        assert any("blackbox_url" in p for p in problems)

    def test_collect_interval_too_low(self, sample_config):
        sample_config["collect_interval_secs"] = 0
        problems = validate_config(sample_config)
        assert any("collect_interval" in p for p in problems)

    def test_seal_interval_too_low(self, sample_config):
        sample_config["seal_interval_secs"] = 2
        problems = validate_config(sample_config)
        assert any("seal_interval" in p for p in problems)

    def test_multiple_problems(self):
        cfg = {
            "tenant_key": "",
            "blackbox_url": "",
            "collect_interval_secs": 0,
            "seal_interval_secs": 0,
        }
        problems = validate_config(cfg)
        assert len(problems) == 4


class TestDefaultPaths:
    """Tests for platform-specific default paths."""

    @patch("agent.config.platform.system", return_value="Windows")
    def test_default_config_path_windows(self, _):
        path = _default_config_path()
        assert "GhostLogic" in path
        assert path.endswith("agent-config.json")

    @patch("agent.config.platform.system", return_value="Linux")
    def test_default_config_path_linux(self, _):
        path = _default_config_path()
        assert path == "/etc/ghostlogic/agent-config.json"

    @patch("agent.config.platform.system", return_value="Darwin")
    def test_default_config_path_darwin(self, _):
        path = _default_config_path()
        assert path == "/usr/local/etc/ghostlogic/agent-config.json"

    @patch("agent.config.platform.system", return_value="Windows")
    def test_default_log_dir_windows(self, _):
        path = _default_log_dir()
        assert "GhostLogic" in path
        assert "logs" in path

    @patch("agent.config.platform.system", return_value="Linux")
    def test_default_log_dir_linux(self, _):
        path = _default_log_dir()
        assert path == "/var/log/ghostlogic"
