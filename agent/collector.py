"""System telemetry collector. No kernel hooks, no scary stuff."""

import getpass
import os
import platform
import socket
import subprocess
import time

_SYSTEM = platform.system()

# On Windows, subprocess.run() creates a visible console window by default.
# CREATE_NO_WINDOW (0x08000000) suppresses this — no more phantom cmd flashes.
_SUBPROCESS_FLAGS = 0x08000000 if _SYSTEM == "Windows" else 0


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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode != 0 or not result.stdout.strip().isdigit():
                return None
            total = int(result.stdout.strip())
            result2 = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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
                creationflags=_SUBPROCESS_FLAGS,
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


# ============================================================
# NEW COLLECTORS — 11 additional (total: 21 with originals)
# ============================================================


def _get_event_log(max_events: int = 25) -> list[dict]:
    """#11: Windows Event Log — recent critical/error/warning entries."""
    events: list[dict] = []
    if _SYSTEM != "Windows":
        return events
    try:
        for log_name in ("System", "Application"):
            result = subprocess.run(
                ["wevtutil", "qe", log_name, f"/c:{max_events}", "/f:text",
                 "/rd:true", "/q:*[System[(Level=1 or Level=2 or Level=3)]]"],
                capture_output=True, text=True, timeout=15,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode != 0:
                continue
            current: dict = {}
            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    if current:
                        current["log_name"] = log_name
                        events.append(current)
                        current = {}
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip().lower().replace(" ", "_")
                    val = val.strip()
                    if key in ("date", "time_created"):
                        current["event_time"] = val
                    elif key == "source":
                        current["source"] = val
                    elif key == "event_id":
                        try:
                            current["event_id"] = int(val)
                        except ValueError:
                            current["event_id"] = val
                    elif key == "level":
                        current["level"] = val
                    elif key in ("description", "message"):
                        current["message"] = val[:500]
            if current:
                current["log_name"] = log_name
                events.append(current)
    except Exception:
        pass
    return events[:max_events]


def _get_services() -> list[dict]:
    """#12: Auto-start Windows services that are NOT running."""
    services: list[dict] = []
    if _SYSTEM != "Windows":
        return services
    try:
        result = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "inactive"],
            capture_output=True, text=True, timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return services
        current: dict = {}
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("SERVICE_NAME:"):
                if current:
                    services.append(current)
                current = {"service_name": line.split(":", 1)[1].strip()}
            elif line.startswith("DISPLAY_NAME:"):
                current["display_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("STATE"):
                for p in line.split():
                    if p in ("STOPPED", "PAUSED", "START_PENDING", "STOP_PENDING"):
                        current["status"] = p
                        break
        if current:
            services.append(current)
    except Exception:
        pass
    return services


def _get_network_bytes() -> list[dict]:
    """#13: Per-adapter bytes sent/received."""
    adapters: list[dict] = []
    try:
        if _SYSTEM == "Windows":
            result = subprocess.run(
                ["netstat", "-e"],
                capture_output=True, text=True, timeout=10,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Bytes" in line:
                        nums = [x.replace(",", "") for x in line.split()
                                if x.replace(",", "").isdigit()]
                        if len(nums) >= 2:
                            adapters.append({
                                "adapter_name": "Total",
                                "bytes_received": int(nums[0]),
                                "bytes_sent": int(nums[1]),
                            })
        elif _SYSTEM == "Linux":
            with open("/proc/net/dev", "r") as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    if len(parts) >= 10:
                        iface = parts[0].rstrip(":")
                        if iface != "lo":
                            adapters.append({
                                "adapter_name": iface,
                                "bytes_received": int(parts[1]),
                                "bytes_sent": int(parts[9]),
                            })
    except Exception:
        pass
    return adapters


def _get_logged_in_users() -> list[dict]:
    """#14: Currently logged-in user sessions."""
    users: list[dict] = []
    try:
        if _SYSTEM == "Windows":
            result = subprocess.run(
                ["query", "user"],
                capture_output=True, text=True, timeout=10,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        users.append({
                            "username": parts[0].lstrip(">"),
                            "session": parts[1],
                            "state": parts[3] if len(parts) > 3 else "unknown",
                        })
        elif _SYSTEM == "Linux":
            result = subprocess.run(
                ["who"], capture_output=True, text=True, timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 3:
                        users.append({
                            "username": parts[0],
                            "terminal": parts[1],
                            "login_time": " ".join(parts[2:4]),
                        })
    except Exception:
        pass
    return users


def _get_firewall_status() -> dict:
    """#15: Windows firewall profile status."""
    status: dict = {}
    if _SYSTEM != "Windows":
        return status
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles", "state"],
            capture_output=True, text=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode == 0:
            current_profile = ""
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "Profile" in line and "Settings" in line:
                    current_profile = line.split()[0].lower()
                elif "State" in line and current_profile:
                    status[current_profile] = line.split()[-1]
    except Exception:
        pass
    return status


def _get_installed_hotfixes() -> list[dict]:
    """#16: Recently installed Windows hotfixes/updates."""
    fixes: list[dict] = []
    if _SYSTEM != "Windows":
        return fixes
    try:
        result = subprocess.run(
            ["wmic", "qfe", "get", "HotFixID,InstalledOn,Description", "/format:csv"],
            capture_output=True, text=True, timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 4:
                    fixes.append({
                        "description": parts[1],
                        "hotfix_id": parts[2],
                        "installed_on": parts[3],
                    })
    except Exception:
        pass
    return fixes[:20]


def _get_scheduled_tasks() -> list[dict]:
    """#17: Running/Ready scheduled tasks."""
    tasks: list[dict] = []
    if _SYSTEM != "Windows":
        return tasks
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.strip('"').split('","')
                if len(parts) >= 3:
                    status_val = parts[2].strip('"') if len(parts) > 2 else ""
                    if status_val in ("Running", "Ready"):
                        tasks.append({
                            "task_name": parts[0].strip('"')[:100],
                            "next_run": parts[1].strip('"')[:30] if len(parts) > 1 else "",
                            "status": status_val,
                        })
    except Exception:
        pass
    return tasks[:30]


def _get_environment_vars() -> dict:
    """#18: Security-relevant environment variables (no secrets)."""
    safe_keys = [
        "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
        "SYSTEMROOT", "TEMP", "TMP", "USERDOMAIN", "LOGONSERVER",
        "PATHEXT", "COMSPEC", "PUBLIC", "PROGRAMDATA",
    ]
    result = {}
    for key in safe_keys:
        val = os.environ.get(key)
        if val:
            result[key] = val
    return result


def _get_dns_cache() -> list[dict]:
    """#19: Windows DNS resolver cache entries."""
    entries: list[dict] = []
    if _SYSTEM != "Windows":
        return entries
    try:
        result = subprocess.run(
            ["ipconfig", "/displaydns"],
            capture_output=True, text=True, timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return entries
        current: dict = {}
        for line in result.stdout.split("\n"):
            line = line.strip()
            if "Record Name" in line:
                if current:
                    entries.append(current)
                current = {"name": line.split(":", 1)[1].strip()}
            elif "Record Type" in line and current:
                current["type"] = line.split(":", 1)[1].strip()
            elif "A (Host)" in line or "AAAA" in line:
                if "Section" not in line and current:
                    current["address"] = line.split(":", 1)[1].strip()
        if current:
            entries.append(current)
    except Exception:
        pass
    return entries[:50]


def _get_startup_programs() -> list[dict]:
    """#20: Programs that run at system startup (registry-based)."""
    programs: list[dict] = []
    if _SYSTEM != "Windows":
        return programs
    try:
        for hive_key in [
            r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
        ]:
            result = subprocess.run(
                ["reg", "query", hive_key],
                capture_output=True, text=True, timeout=10,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "REG_SZ" in line or "REG_EXPAND_SZ" in line:
                    parts = line.split(None, 2)
                    if len(parts) >= 3:
                        programs.append({
                            "name": parts[0],
                            "value": parts[2][:200],
                            "hive": hive_key.split("\\")[0],
                        })
    except Exception:
        pass
    return programs


def _get_battery_status() -> dict | None:
    """#21: Battery status (laptops only)."""
    if _SYSTEM != "Windows":
        return None
    try:
        result = subprocess.run(
            ["wmic", "path", "Win32_Battery", "get",
             "EstimatedChargeRemaining,BatteryStatus", "/format:csv"],
            capture_output=True, text=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return None
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) >= 2:
            parts = lines[1].split(",")
            if len(parts) >= 3:
                status_code = int(parts[1]) if parts[1].isdigit() else 0
                status_map = {1: "discharging", 2: "ac_power", 3: "fully_charged",
                              4: "low", 5: "critical", 6: "charging"}
                return {
                    "charge_percent": int(parts[2]) if parts[2].isdigit() else None,
                    "status": status_map.get(status_code, f"unknown({status_code})"),
                }
    except Exception:
        pass
    return None


# ============================================================
# MASTER COLLECTOR — safe wrappers, never crashes the loop
# ============================================================


def collect_all() -> dict:
    """Collect ALL 21 telemetry sources. Each collector is individually
    wrapped — if one fails, the rest still produce data.
    Failures are recorded in collector_failures for diagnostics.
    """
    failures: list[str] = []

    def _safe(name: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            failures.append(f"{name}: {type(e).__name__}: {e}")
            return None

    mem = _safe("memory", _get_memory_usage)

    result = {
        # --- Original 10 ---
        "hostname": _safe("hostname", _get_hostname) or "unknown",
        "os": _safe("os_info", _get_os_info) or {},
        "username": _safe("username", _get_username) or "unknown",
        "uptime_secs": _safe("uptime", _get_uptime),
        "cpu_percent": _safe("cpu", _get_cpu_usage),
        "memory": mem,
        "ram_percent": mem.get("percent") if mem else None,
        "processes": _safe("processes", _get_processes, 20) or [],
        "network": _safe("network", _get_network_summary) or [],
        "disks": _safe("disks", _get_disk_usage) or [],
        "open_ports": _safe("open_ports", _get_open_ports) or [],
        # --- New 11 ---
        "event_log": _safe("event_log", _get_event_log) or [],
        "services": _safe("services", _get_services) or [],
        "network_bytes": _safe("network_bytes", _get_network_bytes) or [],
        "logged_in_users": _safe("users", _get_logged_in_users) or [],
        "firewall": _safe("firewall", _get_firewall_status) or {},
        "hotfixes": _safe("hotfixes", _get_installed_hotfixes) or [],
        "scheduled_tasks": _safe("schtasks", _get_scheduled_tasks) or [],
        "environment": _safe("env_vars", _get_environment_vars) or {},
        "dns_cache": _safe("dns_cache", _get_dns_cache) or [],
        "startup_programs": _safe("startup", _get_startup_programs) or [],
        "battery": _safe("battery", _get_battery_status),
        # --- Meta ---
        "collector_failures": failures,
    }

    return result
