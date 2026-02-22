"""Tests for agent.collector — subprocess-based telemetry collection."""

import subprocess
from unittest.mock import patch, MagicMock, mock_open

import pytest

import agent.collector as collector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(stdout="", returncode=0):
    """Create a CompletedProcess with given stdout."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# Basic info functions
# ---------------------------------------------------------------------------

class TestHostnameOsUsername:

    def test_get_hostname_returns_string(self):
        result = collector._get_hostname()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_os_info_keys(self):
        info = collector._get_os_info()
        assert "system" in info
        assert "release" in info
        assert "version" in info
        assert "machine" in info

    def test_get_username_returns_string(self):
        result = collector._get_username()
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("agent.collector.getpass.getuser", side_effect=Exception("no tty"))
    @patch.dict("os.environ", {"USERNAME": "fallback_user"})
    def test_get_username_fallback(self, _):
        result = collector._get_username()
        assert result == "fallback_user"


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------

class TestUptime:

    @patch("agent.collector._SYSTEM", "Linux")
    def test_uptime_linux(self):
        data = "12345.67 23456.78\n"
        with patch("builtins.open", mock_open(read_data=data)):
            result = collector._get_uptime()
        assert result == pytest.approx(12345.67)

    @patch("agent.collector._SYSTEM", "Darwin")
    @patch("agent.collector.subprocess.run")
    def test_uptime_darwin(self, mock_run):
        mock_run.return_value = _completed("{ sec = 1700000000, usec = 0 }\n")
        with patch("agent.collector.time.time", return_value=1700086400.0):
            result = collector._get_uptime()
        assert result == pytest.approx(86400.0)

    @patch("agent.collector._SYSTEM", "Windows")
    def test_uptime_windows(self):
        mock_kernel32 = MagicMock()
        mock_kernel32.GetTickCount64.return_value = 86400000  # 86400 seconds
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            result = collector._get_uptime()
        assert result == pytest.approx(86400.0)


# ---------------------------------------------------------------------------
# CPU Usage
# ---------------------------------------------------------------------------

class TestCpuUsage:

    @patch("agent.collector._SYSTEM", "Linux")
    def test_cpu_linux_first_call(self):
        """First call returns 0.0 (no previous sample)."""
        collector._prev_cpu_sample = None
        stat_line = "cpu  100 50 200 1000 10 5 2 0 0 0\n"
        with patch("builtins.open", mock_open(read_data=stat_line)):
            result = collector._get_cpu_usage()
        assert result == 0.0

    @patch("agent.collector._SYSTEM", "Linux")
    def test_cpu_linux_delta(self):
        """Second call computes delta."""
        # Set previous sample
        collector._prev_cpu_sample = (1000, 2000)
        # New sample: idle=1100, total=2200 → (1 - 100/200) = 50%
        stat_line = "cpu  100 50 200 1100 10 5 2 33 0 0\n"
        with patch("builtins.open", mock_open(read_data=stat_line)):
            result = collector._get_cpu_usage()
        assert result is not None
        assert 0 <= result <= 100

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_cpu_windows(self, mock_run):
        mock_run.return_value = _completed("\r\nLoadPercentage=25\r\n\r\n")
        result = collector._get_cpu_usage()
        assert result == 25.0

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_cpu_windows_empty_output(self, mock_run):
        mock_run.return_value = _completed("")
        result = collector._get_cpu_usage()
        assert result is None

    def teardown_method(self):
        collector._prev_cpu_sample = None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class TestMemory:

    @patch("agent.collector._SYSTEM", "Linux")
    def test_memory_linux(self):
        meminfo = (
            "MemTotal:       16384000 kB\n"
            "MemFree:         4096000 kB\n"
            "MemAvailable:    8192000 kB\n"
            "Buffers:          512000 kB\n"
        )
        with patch("builtins.open", mock_open(read_data=meminfo)):
            result = collector._get_memory_usage()
        assert result is not None
        assert result["total_bytes"] == 16384000 * 1024
        assert result["used_bytes"] == (16384000 - 8192000) * 1024
        assert 0 <= result["percent"] <= 100

    @patch("agent.collector._SYSTEM", "Darwin")
    @patch("agent.collector.subprocess.run")
    def test_memory_darwin(self, mock_run):
        # Two subprocess calls: sysctl and vm_stat
        sysctl_resp = _completed("17179869184\n")
        vmstat_resp = _completed(
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages free:                        500000.\n"
            "Pages inactive:                    200000.\n"
            "Pages active:                      300000.\n"
        )
        mock_run.side_effect = [sysctl_resp, vmstat_resp]
        result = collector._get_memory_usage()
        assert result is not None
        assert result["total_bytes"] == 17179869184
        free_pages = (500000 + 200000) * 4096
        expected_used = 17179869184 - free_pages
        assert result["used_bytes"] == expected_used


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

class TestProcesses:

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_processes_windows(self, mock_run):
        csv_output = (
            '"python.exe","1234","Console","1","102,400 K"\n'
            '"chrome.exe","5678","Console","1","512,000 K"\n'
        )
        mock_run.return_value = _completed(csv_output)
        procs = collector._get_processes(20)
        assert len(procs) == 2
        assert procs[0]["name"] == "python.exe"
        assert procs[0]["pid"] == 1234

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_processes_linux(self, mock_run):
        ps_output = (
            " 1234  25.0   5.0 python3\n"
            " 5678  10.0   3.0 chrome\n"
        )
        mock_run.return_value = _completed(ps_output)
        procs = collector._get_processes(20)
        assert len(procs) == 2
        assert procs[0]["pid"] == 1234
        assert procs[0]["cpu_percent"] == 25.0
        assert procs[0]["name"] == "python3"

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_processes_top_n_limit(self, mock_run):
        lines = "\n".join(f" {i}  1.0  0.5 proc{i}" for i in range(100))
        mock_run.return_value = _completed(lines)
        procs = collector._get_processes(5)
        assert len(procs) == 5

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_processes_empty_output(self, mock_run):
        mock_run.return_value = _completed("")
        procs = collector._get_processes(20)
        assert procs == []


# ---------------------------------------------------------------------------
# Network Summary
# ---------------------------------------------------------------------------

class TestNetworkSummary:

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_network_windows(self, mock_run):
        netstat_output = (
            "  TCP    0.0.0.0:80       0.0.0.0:0    LISTENING\n"
            "  TCP    0.0.0.0:443      0.0.0.0:0    LISTENING\n"
            "  TCP    10.0.0.1:52345   1.2.3.4:443  ESTABLISHED\n"
            "  TCP    10.0.0.1:52346   1.2.3.4:443  ESTABLISHED\n"
            "  TCP    10.0.0.1:52347   1.2.3.4:443  ESTABLISHED\n"
        )
        mock_run.return_value = _completed(netstat_output)
        result = collector._get_network_summary()
        assert len(result) == 1
        assert result[0]["listening"] == 2
        assert result[0]["established"] == 3

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_network_linux(self, mock_run):
        ss_output = (
            "State  Recv-Q  Send-Q  Local:Port  Peer:Port\n"
            "LISTEN 0       128     0.0.0.0:22  0.0.0.0:*\n"
            "ESTAB  0       0       10.0.0.1:22 10.0.0.2:55555\n"
        )
        mock_run.return_value = _completed(ss_output)
        result = collector._get_network_summary()
        assert len(result) == 1
        assert result[0]["listening"] == 1
        assert result[0]["established"] == 1


# ---------------------------------------------------------------------------
# Disk Usage
# ---------------------------------------------------------------------------

class TestDiskUsage:

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_disk_linux(self, mock_run):
        df_output = (
            "Mounted on     Size         Used        Avail\n"
            "/dev/sda1      500000000000 250000000000 250000000000\n"
        )
        mock_run.return_value = _completed(df_output)
        result = collector._get_disk_usage()
        # The parsing checks parts[1].isdigit() so the header is skipped
        assert len(result) >= 1
        assert result[0]["total_bytes"] == 500000000000
        assert result[0]["percent"] == 50.0

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_disk_linux_empty(self, mock_run):
        mock_run.return_value = _completed(returncode=1)
        result = collector._get_disk_usage()
        assert result == []


# ---------------------------------------------------------------------------
# Open Ports
# ---------------------------------------------------------------------------

class TestOpenPorts:

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_ports_windows(self, mock_run):
        netstat_output = (
            "  TCP    0.0.0.0:8080     0.0.0.0:0    LISTENING       1234\n"
            "  TCP    0.0.0.0:443      0.0.0.0:0    LISTENING       5678\n"
            "  TCP    10.0.0.1:52345   1.2.3.4:443  ESTABLISHED     9999\n"
        )
        mock_run.return_value = _completed(netstat_output)
        ports = collector._get_open_ports()
        assert len(ports) == 2  # only LISTENING
        assert ports[0]["port"] == 8080
        assert ports[0]["pid"] == 1234

    @patch("agent.collector._SYSTEM", "Linux")
    @patch("agent.collector.subprocess.run")
    def test_ports_linux(self, mock_run):
        ss_output = (
            "State  Recv-Q  Send-Q  Local:Port  Peer:Port  Process\n"
            "LISTEN 0       128     0.0.0.0:22  0.0.0.0:*  users:((\"sshd\",pid=1))\n"
            "LISTEN 0       128     0.0.0.0:80  0.0.0.0:*  users:((\"nginx\",pid=2))\n"
        )
        mock_run.return_value = _completed(ss_output)
        ports = collector._get_open_ports()
        assert len(ports) == 2
        assert ports[0]["port"] == 22
        assert ports[1]["port"] == 80

    @patch("agent.collector._SYSTEM", "Windows")
    @patch("agent.collector.subprocess.run")
    def test_ports_no_listening(self, mock_run):
        netstat_output = "  TCP    10.0.0.1:52345   1.2.3.4:443  ESTABLISHED     9999\n"
        mock_run.return_value = _completed(netstat_output)
        ports = collector._get_open_ports()
        assert ports == []


# ---------------------------------------------------------------------------
# collect_all
# ---------------------------------------------------------------------------

class TestCollectAll:

    def test_collect_all_returns_expected_keys(self):
        """Run actual collection — verifies all keys present."""
        result = collector.collect_all()
        expected_keys = {
            "hostname", "os", "username", "uptime_secs",
            "cpu_percent", "memory", "ram_percent",
            "processes", "network", "disks", "open_ports",
        }
        assert set(result.keys()) == expected_keys

    def test_collect_all_hostname_is_string(self):
        result = collector.collect_all()
        assert isinstance(result["hostname"], str)

    def test_collect_all_os_is_dict(self):
        result = collector.collect_all()
        assert isinstance(result["os"], dict)
        assert "system" in result["os"]
