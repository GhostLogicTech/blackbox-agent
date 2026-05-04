"""GhostLogic Black Box Agent — entry point.

Usage:
    ghostlogic-agent                            # register + background (default)
    ghostlogic-agent --foreground               # stay attached (for services/debugging)
    ghostlogic-agent --stop                     # stop background agent
    ghostlogic-agent --once                     # run ONE collect+send cycle and exit (smoke)
    ghostlogic-agent --dry-run                  # report what queue drain would do, don't contact server
    ghostlogic-agent --foreground --skip-backlog
                                                 # park existing queue, ship only fresh events
    python -m agent --config /path/to/config.json
    python -m agent --demo

Safe re-enable workflow (with preserved historical queue):
    1. python -m agent --dry-run                # confirm queue size + estimated drain time
    2. python -m agent --once --skip-backlog    # one fresh cycle, queue parked
    3. confirm Blackbox endpoint health view shows the agent as healthy
    4. (optional) python -m agent --foreground --skip-backlog  # resume live, no backlog flush
"""

import argparse
import datetime as _dt
import json as _json
import os
import platform
import shutil as _shutil
import subprocess
import sys
import time as _time
import webbrowser

from .config import load_config, validate_config, save_config, _default_config_path
from .client import register
from .log import setup_logging
from .loop import run, run_once

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

def _resolve_queue_dir(config: dict) -> str:
    """Same resolution rule as loop.py — keep these in sync."""
    queue_dir = config.get("queue_dir", "")
    if not queue_dir:
        # Module path: <repo>/agent/__main__.py → queue at <repo>/queue
        queue_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "queue"
        )
    return os.path.abspath(queue_dir)


def _park_queue(queue_dir: str) -> str | None:
    """Rename queue/ to queue.parked-<utc-ts>/ and recreate empty queue/.

    Returns the parked path on success, None if queue/ didn't exist or was
    empty (nothing to park). Never deletes anything (Blackbeard).
    """
    if not os.path.isdir(queue_dir):
        return None
    has_files = any(
        f.endswith(".json") and os.path.isfile(os.path.join(queue_dir, f))
        for f in os.listdir(queue_dir)
    )
    if not has_files:
        return None
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent = os.path.dirname(queue_dir.rstrip(os.sep))
    base = os.path.basename(queue_dir.rstrip(os.sep))
    parked = os.path.join(parent, f"{base}.parked-{ts}")
    os.replace(queue_dir, parked)
    os.makedirs(queue_dir, exist_ok=True)
    return parked


def _scan_queue(queue_dir: str) -> dict:
    """Walk queue_dir and return summary stats."""
    if not os.path.isdir(queue_dir):
        return {"exists": False, "queue_dir": queue_dir}
    count = 0
    total_bytes = 0
    oldest_mtime: float | None = None
    newest_mtime: float | None = None
    oldest_filename: str | None = None
    newest_filename: str | None = None
    for entry in os.scandir(queue_dir):
        if not entry.is_file() or not entry.name.endswith(".json"):
            continue
        st = entry.stat()
        count += 1
        total_bytes += st.st_size
        if oldest_mtime is None or st.st_mtime < oldest_mtime:
            oldest_mtime = st.st_mtime
            oldest_filename = entry.name
        if newest_mtime is None or st.st_mtime > newest_mtime:
            newest_mtime = st.st_mtime
            newest_filename = entry.name
    return {
        "exists": True,
        "queue_dir": queue_dir,
        "count": count,
        "total_bytes": total_bytes,
        "oldest_mtime": oldest_mtime,
        "newest_mtime": newest_mtime,
        "oldest_filename": oldest_filename,
        "newest_filename": newest_filename,
    }


def _do_dry_run(config: dict) -> int:
    queue_dir = _resolve_queue_dir(config)
    summary = _scan_queue(queue_dir)
    print()
    print("=== ghostlogic-agent --dry-run ===")
    print(f"queue_dir: {summary['queue_dir']}")
    if not summary.get("exists"):
        print("queue: does not exist (nothing to drain)")
        return 0
    count = summary["count"]
    total = summary["total_bytes"]
    print(f"queued payloads: {count:,}")
    print(f"total bytes:     {total:,} ({total / 1_048_576:,.1f} MiB)")
    if count == 0:
        print("queue is empty — drain would be a no-op")
        return 0
    def _fmt(ts):
        if not ts:
            return "-"
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"oldest payload:  {_fmt(summary['oldest_mtime'])}  ({summary['oldest_filename']})")
    print(f"newest payload:  {_fmt(summary['newest_mtime'])}  ({summary['newest_filename']})")
    posts_per_min = int(config.get("drain_max_posts_per_minute", 30))
    bytes_per_min = int(config.get("drain_max_bytes_per_minute", 50_000_000))
    avg_size = total / max(count, 1)
    minutes_by_count = count / max(posts_per_min, 1)
    minutes_by_bytes = total / max(bytes_per_min, 1)
    minutes = max(minutes_by_count, minutes_by_bytes)
    print()
    print(f"rate cap:        {posts_per_min} posts/min  {bytes_per_min:,} bytes/min  ({bytes_per_min/1_048_576:.1f} MiB/min)")
    print(f"avg payload:     {avg_size:,.0f} bytes  ({avg_size/1024:,.1f} KiB)")
    print(f"estimated drain: {minutes:.1f} min  ({minutes/60:.1f} h)")
    print(f"  by count cap:  {minutes_by_count:.1f} min")
    print(f"  by byte cap:   {minutes_by_bytes:.1f} min")
    print()
    print("Re-enable hint: `python -m agent --once --skip-backlog` posts ONE fresh")
    print("snapshot without touching this queue. Park it first if you want a clean")
    print("queue: `python -m agent --foreground --skip-backlog`.")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="GhostLogic Black Box Agent")
    parser.add_argument("--config", "-c", help="Path to config JSON file")
    parser.add_argument("--demo", action="store_true", help="Force demo mode")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground (don't daemonize)")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running background agent")
    parser.add_argument("--once", action="store_true",
                        help="Run ONE collect+send cycle and exit. No queue flush, no seal. "
                             "Used for safe re-enable smoke test.")
    parser.add_argument("--skip-backlog", action="store_true",
                        help="On startup, rename queue/ to queue.parked-<ts>/ and start with "
                             "an empty queue. Original queue is preserved (Blackbeard).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan queue, print drain plan + estimated drain time. "
                             "Does NOT contact the server. Exits without starting the agent.")
    args = parser.parse_args()

    print(BANNER.format(version=VERSION))

    config = load_config(args.config)
    config_path = args.config or os.environ.get("GHOSTLOGIC_CONFIG",
                                                 _default_config_path())
    config_path = os.path.abspath(config_path)

    if args.demo:
        config["demo_mode"] = True
    if args.skip_backlog:
        config["skip_backlog"] = True

    # --stop: kill background agent and exit
    if args.stop:
        _stop_agent(config)
        return

    # --dry-run: report on queue + drain plan, don't start anything.
    if args.dry_run:
        sys.exit(_do_dry_run(config))

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
    if args.foreground or args.once:
        logger = setup_logging(config["log_dir"], config.get("log_max_hours", 24))

        # Park the existing queue if requested (no Flush-Queue burst on resume).
        if config.get("skip_backlog"):
            qd = _resolve_queue_dir(config)
            parked = _park_queue(qd)
            if parked:
                logger.warning("skip_backlog: parked existing queue at %s "
                               "(preserved, will not flush)", parked)
            else:
                logger.info("skip_backlog: no queue to park (was empty or missing)")

        pid_path = _pid_file_path(config)
        _write_pid(pid_path, os.getpid())

        problems = validate_config(config)
        for p in problems:
            logger.warning("Config: %s", p)

        try:
            if args.once:
                rc = run_once(config)
                _remove_pid(pid_path)
                sys.exit(rc)
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
