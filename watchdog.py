"""Watchdog — ensures the GhostLogic agent stays alive.
Run this every 2 minutes via Task Scheduler.
If the agent process is dead, it restarts it.
"""

import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(SCRIPT_DIR, "agent.pid")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, f"watchdog_{time.strftime('%Y-%m-%d')}.log")


def log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [WATCHDOG] {msg}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass
    print(line, end="")


def is_agent_alive() -> bool:
    """Check if the stored PID is a live Python/agent process."""
    if not os.path.isfile(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return False

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        lower = result.stdout.lower()
        return "python" in lower or "ghostlogic" in lower
    except Exception:
        return False


def restart_agent() -> None:
    """Restart the agent as a hidden background process."""
    agent_main = os.path.join(SCRIPT_DIR, "agent")

    cmd = [sys.executable, "-m", "agent", "--foreground"]

    proc = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=0x00000008 | 0x00000200 | 0x08000000,
    )

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    log(f"Restarted agent — PID: {proc.pid}")


def cleanup_old_logs() -> None:
    """Remove watchdog logs older than 7 days."""
    try:
        cutoff = time.time() - (7 * 86400)
        for f in os.listdir(LOG_DIR):
            if f.startswith("watchdog_") and f.endswith(".log"):
                path = os.path.join(LOG_DIR, f)
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
    except Exception:
        pass


if __name__ == "__main__":
    if is_agent_alive():
        log("Agent is alive")
    else:
        log("Agent is DEAD — restarting...")
        restart_agent()
    cleanup_old_logs()
