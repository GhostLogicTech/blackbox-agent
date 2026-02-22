"""GhostLogic Black Box Agent — entry point.

Usage:
    ghostlogic-agent                            # pip-installed CLI (register + background)
    ghostlogic-agent --foreground               # stay attached (for services/debugging)
    ghostlogic-agent --stop                     # stop background agent
    python -m agent                             # from repo
    python -m agent --config /path/to/config.json
    python -m agent --demo
"""

import argparse
import os
import platform
import subprocess
import sys
import webbrowser

from .config import load_config, validate_config, save_config, _default_config_path
from .client import register
from .log import setup_logging
from .loop import run

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("ghostlogic-agent")
except Exception:
    VERSION = "1.1.0"  # fallback when running from source

BANNER = r"""
   ____  _                 _   _                 _
  / ___|| |__   ___   ___| |_| |    ___   __ _ (_) ___
 | |  _ | '_ \ / _ \ / __| __| |   / _ \ / _` || |/ __|
 | |_| || | | | (_) |\__ \ |_| |__| (_) | (_| || | (__
  \____||_| |_|\___/ |___/\__|_____\___/ \__, ||_|\___|
                                         |___/
        Black Box Agent v{version}
"""

KEY_BANNER = """
================================================================
|                                                              |
|   YOUR API KEY (paste this into the Black Box Console):      |
|                                                              |
|   {key}
|                                                              |
================================================================
"""

RUNNING_MSG = """
Agent is now running in the background.
  Config:  {config_path}
  Logs:    {log_dir}
  PID:     {pid}

Paste your API key at https://blackbox.ghostlogic.tech
To stop:  ghostlogic-agent --stop
"""

_SYSTEM = platform.system()


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _pid_file_path(config: dict) -> str:
    """Return path to the PID file."""
    log_dir = config.get("log_dir", "")
    if log_dir:
        return os.path.join(log_dir, "ghostlogic-agent.pid")
    if _SYSTEM == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "GhostLogic", "ghostlogic-agent.pid")
    return "/tmp/ghostlogic-agent.pid"


def _write_pid(pid_path: str, pid: int) -> None:
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w") as f:
        f.write(str(pid))


def _remove_pid(pid_path: str) -> None:
    try:
        os.remove(pid_path)
    except OSError:
        pass


def _is_our_agent(pid: int) -> bool:
    """Check whether *pid* is actually a GhostLogic agent process.

    Avoids killing a random process that recycled the same PID.
    Uses only stdlib — no psutil dependency.
    """
    try:
        if _SYSTEM == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            line = result.stdout.lower()
            return "python" in line or "ghostlogic" in line
        else:
            # Unix: read /proc/{pid}/cmdline
            cmdline_path = f"/proc/{pid}/cmdline"
            if os.path.exists(cmdline_path):
                with open(cmdline_path, "rb") as f:
                    cmdline = f.read().decode("utf-8", errors="replace")
                return "agent" in cmdline
            # macOS or no /proc — try kill(0) to check existence
            os.kill(pid, 0)
            return True  # process exists; can't verify identity without /proc
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

def _stop_agent(config: dict) -> None:
    """Stop a running background agent with PID validation."""
    pid_path = _pid_file_path(config)
    if not os.path.isfile(pid_path):
        print("No running agent found (no PID file).")
        return

    with open(pid_path, "r") as f:
        raw = f.read().strip()

    try:
        pid = int(raw)
    except ValueError:
        print("Corrupt PID file. Removing.")
        _remove_pid(pid_path)
        return

    if not _is_our_agent(pid):
        print(f"PID {pid} is not a GhostLogic agent (stale PID file). Cleaning up.")
        _remove_pid(pid_path)
        return

    try:
        if _SYSTEM == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, check=True,
                           creationflags=0x08000000)  # CREATE_NO_WINDOW
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        print(f"Agent (PID {pid}) stopped.")
    except (ProcessLookupError, subprocess.CalledProcessError):
        print(f"Agent (PID {pid}) was already stopped.")

    _remove_pid(pid_path)


# ---------------------------------------------------------------------------
# Background spawn
# ---------------------------------------------------------------------------

def _spawn_background(config_path: str, demo: bool) -> int:
    """Re-launch this agent as a fully detached background process.

    Always passes the absolute config path so cwd doesn't matter.
    Returns child PID.
    """
    config_path = os.path.abspath(config_path)
    cmd = [sys.executable, "-m", "agent", "--foreground", "--config", config_path]
    if demo:
        cmd.append("--demo")

    if _SYSTEM == "Windows":
        # DETACHED_PROCESS (0x08) | CREATE_NEW_PROCESS_GROUP (0x200) | CREATE_NO_WINDOW (0x08000000)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=0x00000008 | 0x00000200 | 0x08000000,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    return proc.pid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="GhostLogic Black Box Agent")
    parser.add_argument("--config", "-c", help="Path to config JSON file")
    parser.add_argument("--demo", action="store_true", help="Force demo mode")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground (don't daemonize)")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running background agent")
    args = parser.parse_args()

    print(BANNER.format(version=VERSION))

    config = load_config(args.config)
    config_path = args.config or os.environ.get("GHOSTLOGIC_CONFIG",
                                                 _default_config_path())
    config_path = os.path.abspath(config_path)

    if args.demo:
        config["demo_mode"] = True

    # --stop: kill background agent and exit
    if args.stop:
        _stop_agent(config)
        return

    # Auto-register if no tenant key
    registered_now = False
    if not config.get("tenant_key"):
        print("\n" + "=" * 60)
        print("  NO API KEY FOUND — Registering with Blackbox server...")
        print("=" * 60 + "\n")

        result = register(config)

        if result:
            config["tenant_key"] = result["api_key"]
            save_config(config_path, config)
            registered_now = True

            print(KEY_BANNER.format(key=result["api_key"]))
            print(f"  Tenant ID: {result['tenant_id']}")
            print("  Paste this key into blackbox.ghostlogic.tech")
            print()
        else:
            # Registration failed — exit, don't spawn a broken background agent
            print("\n  Registration failed. Check your network and try again.")
            print("  You can also set tenant_key manually in the config file.\n")
            sys.exit(1)

    # --- Foreground mode: run the loop directly (used by services + background spawn) ---
    if args.foreground:
        logger = setup_logging(config["log_dir"], config.get("log_max_hours", 24))

        pid_path = _pid_file_path(config)
        _write_pid(pid_path, os.getpid())

        problems = validate_config(config)
        for p in problems:
            logger.warning("Config: %s", p)

        try:
            run(config)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user")
        finally:
            _remove_pid(pid_path)
            sys.exit(0)

    # --- Default mode: spawn background and return shell to user ---

    # Open browser ONLY in interactive (non-foreground) mode
    if registered_now:
        try:
            webbrowser.open("https://blackbox.ghostlogic.tech")
        except Exception:
            pass  # headless / no browser is fine

    pid = _spawn_background(config_path, args.demo)

    pid_path = _pid_file_path(config)
    _write_pid(pid_path, pid)

    print(RUNNING_MSG.format(
        config_path=config_path,
        log_dir=config.get("log_dir", "?"),
        pid=pid,
    ))


if __name__ == "__main__":
    main()
