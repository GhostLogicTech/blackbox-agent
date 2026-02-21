"""System telemetry collector. No kernel hooks, no scary stuff."""

import getpass
import os
import platform
import socket
import subprocess
import time

_SYSTEM = platform.system()


def _get_hostname() -> str:
    return socket.gethostname()


def _get_os_info() -> dict:
    return {
        "system": _SYSTEM,
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    }


def _get_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


def _get_uptime() -> float | None:
    """Return system uptime in seconds, or None if unavailable."""
    try:
        if _SYSTEM == "Linux":
            with open("/proc/uptime", "r") as f:
                return float(f.read().split()[0])
        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            # Output: { sec = 1234567890, usec = 0 }
            parts = result.stdout.split("sec = ")
            if len(parts) < 2:
                return None
            sec_str = parts[1].split(",")[0].strip()
            boot_time = int(sec_str)
            return time.time() - boot_time
        elif _SYSTEM == "Windows":
            import ctypes
            lib = ctypes.windll.kernel32
            tick = lib.GetTickCount64()
            return tick / 1000.0
    except Exception:
        pass
    return None


# CPU usage on Linux uses a delta between two /proc/stat reads.
# We cache the previous sample so we don't need to sleep(0.1) inside
# the collection path — the delta is between successive collect cycles instead.
_prev_cpu_sample: tuple[int, int] | None = None


def _get_cpu_usage() -> float | None:
    """Return CPU usage percent (0-100)."""
    global _prev_cpu_sample
    try:
        if _SYSTEM == "Linux":
            with open("/proc/stat", "r") as f:
                line = f.readline()
            fields = line.strip().split()[1:]
            idle = int(fields[3])
            total = sum(int(x) for x in fields)

            if _prev_cpu_sample is None:
                _prev_cpu_sample = (idle, total)
                return 0.0

            prev_idle, prev_total = _prev_cpu_sample
            _prev_cpu_sample = (idle, total)

            idle_delta = idle - prev_idle
            total_delta = total - prev_total
            if total_delta <= 0:
                return 0.0
            return round((1.0 - idle_delta / total_delta) * 100, 1)

        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["ps", "-A", "-o", "%cpu"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            lines = result.stdout.strip().split("\n")[1:]  # skip header
            total = 0.0
            for line in lines:
                stripped = line.strip()
                if stripped:
                    try:
                        total += float(stripped)
                    except ValueError:
                        pass
            cpu_count = os.cpu_count() or 1
            return round(min(total / cpu_count, 100.0), 1)

        elif _SYSTEM == "Windows":
            result = subprocess.run(
                ["wmic", "cpu", "get", "LoadPercentage", "/value"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "LoadPercentage" in line and "=" in line:
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return float(val)
    except Exception:
        pass
    return None


def _get_memory_usage() -> dict | None:
    """Return memory usage stats."""
    try:
        if _SYSTEM == "Linux":
            meminfo: dict[str, int] = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_parts = parts[1].strip().split()
                        if val_parts and val_parts[0].isdigit():
                            meminfo[key] = int(val_parts[0]) * 1024  # kB to bytes
            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", 0)
            used = total - available
            pct = round((used / total) * 100, 1) if total > 0 else 0.0
            return {"total_bytes": total, "used_bytes": used, "percent": pct}

        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip().isdigit():
                return None
            total = int(result.stdout.strip())
            result2 = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5,
            )
            pages_free = 0
            page_size = 4096
            for line in result2.stdout.split("\n"):
                if "page size of" in line:
                    tokens = line.split()
                    for i, t in enumerate(tokens):
                        if t.isdigit() and i > 0:
                            page_size = int(t)
                if "Pages free" in line:
                    val = line.split()[-1].rstrip(".")
                    if val.isdigit():
                        pages_free = int(val)
                if "Pages inactive" in line:
                    val = line.split()[-1].rstrip(".")
                    if val.isdigit():
                        pages_free += int(val)
            available = pages_free * page_size
            used = total - available
            pct = round((used / total) * 100, 1) if total > 0 else 0.0
            return {"total_bytes": total, "used_bytes": used, "percent": pct}

        elif _SYSTEM == "Windows":
            import ctypes
            import ctypes.wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.wintypes.DWORD),
                    ("dwMemoryLoad", ctypes.wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = stat.ullTotalPhys
            used = total - stat.ullAvailPhys
            pct = round((used / total) * 100, 1) if total > 0 else 0.0
            return {"total_bytes": total, "used_bytes": used, "percent": pct}
    except Exception:
        pass
    return None


def _get_processes(top_n: int = 20) -> list[dict]:
    """Return top N processes by CPU. No external deps."""
    procs: list[dict] = []
    try:
        if _SYSTEM == "Linux":
            result = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu", "--no-headers"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return procs
            for line in result.stdout.strip().split("\n")[:top_n]:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    try:
                        procs.append({
                            "pid": int(parts[0]),
                            "cpu_percent": float(parts[1]),
                            "mem_percent": float(parts[2]),
                            "name": parts[3],
                        })
                    except ValueError:
                        pass

        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,comm", "-r"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return procs
            lines = result.stdout.strip().split("\n")[1:]  # skip header
            for line in lines[:top_n]:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    try:
                        procs.append({
                            "pid": int(parts[0]),
                            "cpu_percent": float(parts[1]),
                            "mem_percent": float(parts[2]),
                            "name": parts[3],
                        })
                    except ValueError:
                        pass

        elif _SYSTEM == "Windows":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return procs
            for line in result.stdout.strip().split("\n")[:top_n]:
                line = line.strip().strip('"')
                parts = line.split('","')
                if len(parts) >= 5:
                    name = parts[0].strip('"')
                    pid_str = parts[1].strip('"')
                    mem_str = parts[4].strip('"').replace(",", "").replace(" K", "").replace(" k", "")
                    try:
                        procs.append({
                            "pid": int(pid_str),
                            "name": name,
                            "mem_kb": int(mem_str) if mem_str.isdigit() else 0,
                        })
                    except ValueError:
                        pass
    except Exception:
        pass
    return procs


def _get_network_summary() -> list[dict]:
    """Basic network connections summary. No external deps."""
    connections: list[dict] = []
    try:
        if _SYSTEM in ("Linux", "Darwin"):
            cmd = ["ss", "-tuln"] if _SYSTEM == "Linux" else ["netstat", "-an", "-p", "tcp"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
            )
            listening = 0
            established = 0
            for line in result.stdout.split("\n"):
                lower = line.lower()
                if "listen" in lower:
                    listening += 1
                elif "estab" in lower:
                    established += 1
            connections.append({
                "listening": listening,
                "established": established,
            })
        elif _SYSTEM == "Windows":
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True, text=True, timeout=10,
            )
            listening = 0
            established = 0
            for line in result.stdout.split("\n"):
                if "LISTENING" in line:
                    listening += 1
                elif "ESTABLISHED" in line:
                    established += 1
            connections.append({
                "listening": listening,
                "established": established,
            })
    except Exception:
        pass
    return connections


def _get_disk_usage() -> list[dict]:
    """Return disk usage per mounted volume. No external deps."""
    disks: list[dict] = []
    try:
        if _SYSTEM == "Windows":
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter_idx in range(26):
                if bitmask & (1 << letter_idx):
                    drive = f"{chr(65 + letter_idx)}:\\"
                    try:
                        total, used, free = _win_disk_usage(drive)
                        if total > 0:
                            disks.append({
                                "mount": drive,
                                "total_bytes": total,
                                "used_bytes": used,
                                "free_bytes": free,
                                "percent": round((used / total) * 100, 1),
                            })
                    except Exception:
                        pass
        elif _SYSTEM == "Linux":
            result = subprocess.run(
                ["df", "-B1", "--output=target,size,used,avail"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1].isdigit():
                        mount = parts[0]
                        # Skip pseudo-filesystems
                        if mount.startswith(("/dev", "/run", "/sys", "/proc", "/snap")):
                            if not mount.startswith("/dev"):
                                continue
                        total = int(parts[1])
                        used = int(parts[2])
                        free = int(parts[3])
                        if total > 0:
                            disks.append({
                                "mount": mount,
                                "total_bytes": total,
                                "used_bytes": used,
                                "free_bytes": free,
                                "percent": round((used / total) * 100, 1),
                            })
        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["df", "-b"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        mount = parts[-1]
                        if mount in ("/", "/System/Volumes/Data") or mount.startswith("/Volumes"):
                            try:
                                blocks = int(parts[1])
                                used_blocks = int(parts[2])
                                avail_blocks = int(parts[3])
                                total = blocks * 512
                                used = used_blocks * 512
                                free = avail_blocks * 512
                                if total > 0:
                                    disks.append({
                                        "mount": mount,
                                        "total_bytes": total,
                                        "used_bytes": used,
                                        "free_bytes": free,
                                        "percent": round((used / total) * 100, 1),
                                    })
                            except ValueError:
                                pass
    except Exception:
        pass
    return disks


def _win_disk_usage(path: str) -> tuple[int, int, int]:
    """Windows disk usage via GetDiskFreeSpaceExW."""
    import ctypes
    free_bytes = ctypes.c_uint64(0)
    total_bytes = ctypes.c_uint64(0)
    free_total = ctypes.c_uint64(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        path,
        ctypes.byref(free_bytes),
        ctypes.byref(total_bytes),
        ctypes.byref(free_total),
    )
    total = total_bytes.value
    free = free_bytes.value
    used = total - free
    return total, used, free


def _get_open_ports() -> list[dict]:
    """Return listening ports with process info where available."""
    ports: list[dict] = []
    try:
        if _SYSTEM == "Windows":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return ports
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "LISTENING" not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    local = parts[1]
                    pid_str = parts[4]
                    # Parse address:port
                    if ":" in local:
                        addr, port_str = local.rsplit(":", 1)
                        try:
                            ports.append({
                                "proto": "TCP",
                                "address": addr,
                                "port": int(port_str),
                                "pid": int(pid_str) if pid_str.isdigit() else None,
                                "state": "LISTENING",
                            })
                        except ValueError:
                            pass
        elif _SYSTEM == "Linux":
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return ports
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    local = parts[3]
                    if ":" in local:
                        addr, port_str = local.rsplit(":", 1)
                        try:
                            entry: dict = {
                                "proto": "TCP",
                                "address": addr,
                                "port": int(port_str),
                                "state": "LISTEN",
                            }
                            # Try to extract process info
                            if len(parts) >= 6:
                                entry["process"] = parts[5][:80]
                            ports.append(entry)
                        except ValueError:
                            pass
        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["netstat", "-an", "-p", "tcp"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return ports
            for line in result.stdout.split("\n"):
                if "LISTEN" not in line:
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    local = parts[3]
                    if "." in local:
                        last_dot = local.rfind(".")
                        addr = local[:last_dot]
                        port_str = local[last_dot + 1:]
                        try:
                            ports.append({
                                "proto": "TCP",
                                "address": addr,
                                "port": int(port_str),
                                "state": "LISTEN",
                            })
                        except ValueError:
                            pass
    except Exception:
        pass
    return ports


def collect_all() -> dict:
    """Collect all telemetry and return as a raw dict."""
    mem = _get_memory_usage()
    return {
        "hostname": _get_hostname(),
        "os": _get_os_info(),
        "username": _get_username(),
        "uptime_secs": _get_uptime(),
        "cpu_percent": _get_cpu_usage(),
        "memory": mem,
        "ram_percent": mem.get("percent") if mem else None,
        "processes": _get_processes(20),
        "network": _get_network_summary(),
        "disks": _get_disk_usage(),
        "open_ports": _get_open_ports(),
    }
