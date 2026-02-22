"""Tests for agent.__main__ — CLI entry point, PID management, stop/spawn."""

import os
import subprocess
from unittest.mock import patch, MagicMock, mock_open

import pytest

from agent.__main__ import (
    _pid_file_path,
    _write_pid,
    _remove_pid,
    _is_our_agent,
    _stop_agent,
    _spawn_background,
    main,
)


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

class TestPidFilePath:

    def test_uses_log_dir_from_config(self):
        config = {"log_dir": "/var/log/ghostlogic"}
        path = _pid_file_path(config)
        assert path == os.path.join("/var/log/ghostlogic", "ghostlogic-agent.pid")

    @patch("agent.__main__._SYSTEM", "Windows")
    def test_default_windows(self):
        config = {"log_dir": ""}
        path = _pid_file_path(config)
        assert "GhostLogic" in path
        assert path.endswith("ghostlogic-agent.pid")

    @patch("agent.__main__._SYSTEM", "Linux")
    def test_default_linux(self):
        config = {"log_dir": ""}
        path = _pid_file_path(config)
        assert path == "/tmp/ghostlogic-agent.pid"


class TestWritePid:

    def test_writes_pid_to_file(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        _write_pid(pid_file, 12345)
        content = open(pid_file).read()
        assert content == "12345"

    def test_creates_parent_dirs(self, tmp_path):
        pid_file = str(tmp_path / "deep" / "nested" / "test.pid")
        _write_pid(pid_file, 99)
        assert os.path.isfile(pid_file)


class TestRemovePid:

    def test_removes_file(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("123")
        _remove_pid(str(pid_file))
        assert not pid_file.exists()

    def test_no_error_if_missing(self, tmp_path):
        _remove_pid(str(tmp_path / "nonexistent.pid"))  # should not raise


# ---------------------------------------------------------------------------
# _is_our_agent
# ---------------------------------------------------------------------------

class TestIsOurAgent:

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.run")
    def test_windows_python_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='"python.exe","1234","Console","1","50000 K"\n',
        )
        assert _is_our_agent(1234) is True

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.run")
    def test_windows_not_our_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='"notepad.exe","1234","Console","1","10000 K"\n',
        )
        assert _is_our_agent(1234) is False

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.run")
    def test_windows_ghostlogic_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='"ghostlogic-agent.exe","1234","Console","1","50000 K"\n',
        )
        assert _is_our_agent(1234) is True

    @patch("agent.__main__._SYSTEM", "Linux")
    @patch("agent.__main__.os.path.exists", return_value=True)
    def test_linux_reads_cmdline(self, mock_exists):
        cmdline_data = b"/usr/bin/python3\x00-m\x00agent\x00--foreground"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert _is_our_agent(1234) is True

    @patch("agent.__main__._SYSTEM", "Linux")
    @patch("agent.__main__.os.path.exists", return_value=True)
    def test_linux_not_agent(self, mock_exists):
        cmdline_data = b"/usr/bin/vim\x00somefile.txt"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert _is_our_agent(1234) is False

    @patch("agent.__main__._SYSTEM", "Linux")
    @patch("agent.__main__.os.path.exists", return_value=False)
    @patch("agent.__main__.os.kill", side_effect=ProcessLookupError)
    def test_process_not_found(self, mock_kill, mock_exists):
        assert _is_our_agent(99999) is False


# ---------------------------------------------------------------------------
# _stop_agent
# ---------------------------------------------------------------------------

class TestStopAgent:

    def test_no_pid_file(self, tmp_path, sample_config, capsys):
        sample_config["log_dir"] = str(tmp_path)
        _stop_agent(sample_config)
        output = capsys.readouterr().out
        assert "No running agent" in output

    def test_corrupt_pid_file(self, tmp_path, sample_config, capsys):
        sample_config["log_dir"] = str(tmp_path)
        pid_path = _pid_file_path(sample_config)
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write("not_a_number")
        _stop_agent(sample_config)
        output = capsys.readouterr().out
        assert "Corrupt" in output
        assert not os.path.isfile(pid_path)

    @patch("agent.__main__._is_our_agent", return_value=False)
    def test_stale_pid(self, mock_check, tmp_path, sample_config, capsys):
        sample_config["log_dir"] = str(tmp_path)
        pid_file = tmp_path / "ghostlogic-agent.pid"
        pid_file.write_text("12345")
        _stop_agent(sample_config)
        output = capsys.readouterr().out
        assert "not a GhostLogic agent" in output
        assert not pid_file.exists()

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.run")
    @patch("agent.__main__._is_our_agent", return_value=True)
    def test_kills_agent_windows(self, mock_check, mock_run, tmp_path, sample_config, capsys):
        sample_config["log_dir"] = str(tmp_path)
        pid_file = tmp_path / "ghostlogic-agent.pid"
        pid_file.write_text("12345")
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _stop_agent(sample_config)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "taskkill" in args
        assert "12345" in args
        output = capsys.readouterr().out
        assert "stopped" in output


# ---------------------------------------------------------------------------
# _spawn_background
# ---------------------------------------------------------------------------

class TestSpawnBackground:

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.Popen")
    def test_spawn_returns_pid(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc
        pid = _spawn_background("/path/to/config.json", demo=False)
        assert pid == 9999
        mock_popen.assert_called_once()

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.Popen")
    def test_spawn_passes_absolute_config(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        _spawn_background("relative/config.json", demo=False)
        cmd = mock_popen.call_args[0][0]
        config_path = cmd[cmd.index("--config") + 1]
        assert os.path.isabs(config_path)

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.Popen")
    def test_spawn_demo_flag(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        _spawn_background("/path/config.json", demo=True)
        cmd = mock_popen.call_args[0][0]
        assert "--demo" in cmd

    @patch("agent.__main__._SYSTEM", "Windows")
    @patch("agent.__main__.subprocess.Popen")
    def test_spawn_no_demo_flag(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        _spawn_background("/path/config.json", demo=False)
        cmd = mock_popen.call_args[0][0]
        assert "--demo" not in cmd

    @patch("agent.__main__._SYSTEM", "Linux")
    @patch("agent.__main__.subprocess.Popen")
    def test_spawn_unix_new_session(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        _spawn_background("/path/config.json", demo=False)
        kwargs = mock_popen.call_args[1]
        assert kwargs["start_new_session"] is True


# ---------------------------------------------------------------------------
# main() flow
# ---------------------------------------------------------------------------

class TestMainFlow:

    @patch("agent.__main__._stop_agent")
    @patch("agent.__main__.load_config", return_value={"log_dir": "/tmp", "demo_mode": True})
    @patch("sys.argv", ["ghostlogic-agent", "--stop"])
    def test_stop_flag(self, mock_load, mock_stop):
        main()
        mock_stop.assert_called_once()

    @patch("agent.__main__.run")
    @patch("agent.__main__.setup_logging", return_value=MagicMock())
    @patch("agent.__main__._write_pid")
    @patch("agent.__main__._remove_pid")
    @patch("agent.__main__.validate_config", return_value=[])
    @patch("agent.__main__.load_config")
    @patch("sys.argv", ["ghostlogic-agent", "--foreground", "--config", "/tmp/test.json"])
    def test_foreground_mode(self, mock_load, mock_validate, mock_remove, mock_write,
                             mock_logging, mock_run):
        mock_load.return_value = {
            "tenant_key": "glk_existing",
            "log_dir": "/tmp/logs",
            "log_max_hours": 24,
            "demo_mode": True,
        }
        # run() will be called — make it raise to break the loop
        mock_run.side_effect = KeyboardInterrupt
        with pytest.raises(SystemExit):
            main()
        mock_run.assert_called_once()

    @patch("agent.__main__._spawn_background", return_value=8888)
    @patch("agent.__main__._write_pid")
    @patch("agent.__main__.register")
    @patch("agent.__main__.save_config")
    @patch("agent.__main__.load_config")
    @patch("agent.__main__.webbrowser.open")
    @patch("sys.argv", ["ghostlogic-agent"])
    def test_auto_register(self, mock_browser, mock_load, mock_save, mock_register,
                           mock_write, mock_spawn):
        mock_load.return_value = {
            "tenant_key": "",
            "blackbox_url": "https://api.ghostlogic.tech",
            "agent_id": "test-id",
            "log_dir": "/tmp/logs",
            "demo_mode": True,
        }
        mock_register.return_value = {
            "api_key": "glk_new_key",
            "tenant_id": "t-1",
        }
        main()
        mock_register.assert_called_once()
        mock_save.assert_called_once()

    @patch("agent.__main__.register", return_value=None)
    @patch("agent.__main__.load_config")
    @patch("sys.argv", ["ghostlogic-agent"])
    def test_register_failure_exits(self, mock_load, mock_register):
        mock_load.return_value = {
            "tenant_key": "",
            "blackbox_url": "https://api.ghostlogic.tech",
            "agent_id": "test-id",
            "log_dir": "/tmp",
            "demo_mode": True,
        }
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("agent.__main__._spawn_background", return_value=7777)
    @patch("agent.__main__._write_pid")
    @patch("agent.__main__.load_config")
    @patch("sys.argv", ["ghostlogic-agent"])
    def test_spawns_background_when_has_key(self, mock_load, mock_write, mock_spawn):
        mock_load.return_value = {
            "tenant_key": "glk_existing_key",
            "log_dir": "/tmp/logs",
            "demo_mode": True,
        }
        main()
        mock_spawn.assert_called_once()

    @patch("agent.__main__._spawn_background", return_value=6666)
    @patch("agent.__main__._write_pid")
    @patch("agent.__main__.register")
    @patch("agent.__main__.save_config")
    @patch("agent.__main__.load_config")
    @patch("agent.__main__.webbrowser.open")
    @patch("sys.argv", ["ghostlogic-agent"])
    def test_opens_browser_on_register(self, mock_browser, mock_load, mock_save,
                                       mock_register, mock_write, mock_spawn):
        mock_load.return_value = {
            "tenant_key": "",
            "blackbox_url": "https://api.ghostlogic.tech",
            "agent_id": "test-id",
            "log_dir": "/tmp/logs",
            "demo_mode": True,
        }
        mock_register.return_value = {"api_key": "glk_new", "tenant_id": "t-1"}
        main()
        mock_browser.assert_called_once_with("https://blackbox.ghostlogic.tech")
