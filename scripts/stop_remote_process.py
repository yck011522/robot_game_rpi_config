#!/usr/bin/env python3
"""Stop the directly-launched player-panel processes over SSH (no systemd).

Counterpart to ``start_remote_process.py``: kills the panels by the PID files it
wrote, then sweeps any stragglers by command-line pattern. Devices are taken
from ``devices.csv`` by index and serviced concurrently, the same way
``deploy_app.py`` works: with no ``--devices`` the whole fleet is stopped.
"""

from __future__ import annotations

import argparse
import shlex

from rpi_remote_common import (
    resolve_credentials,
    run_on_devices,
    run_remote,
    select_targets,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop directly-launched player-panel processes on Raspberry Pis.")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to stop, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    return parser.parse_args()


def stop_one(ssh, remote_dir: str, role: str) -> None:
    """Stop the panel for ``role`` via its PID file, then by name as a fallback."""

    pid_file = f"{remote_dir}/run/canvas_{role}.pid"
    # The leading [p] character class keeps this pattern from matching the SSH
    # shell that is running pkill (whose own argv contains the pattern text).
    pattern = shlex.quote(f"[p]layer_panel.py --role {role}")

    script = (
        "set +e; "
        f"if [ -f {shlex.quote(pid_file)} ]; then "
        f"  pid=$(cat {shlex.quote(pid_file)}); "
        "  if ps -p $pid >/dev/null 2>&1; then "
        "    kill $pid; "
        "    sleep 0.4; "
        "    if ps -p $pid >/dev/null 2>&1; then kill -9 $pid; fi; "
        "  fi; "
        f"  rm -f {shlex.quote(pid_file)}; "
        "fi; "
        f"pkill -f {pattern} >/dev/null 2>&1 || true"
    )

    run_remote(ssh, "bash -lc " + shlex.quote(script), check=False)


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    targets = select_targets(args.devices)

    print(f"Stopping player-panel processes on {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets))

    def worker(ssh, log) -> None:
        log("Stopping player-panel processes...")
        stop_one(ssh, remote_dir=args.remote_dir, role="left")
        stop_one(ssh, remote_dir=args.remote_dir, role="right")
        log("Stopped (left, right).")

    run_on_devices(
        targets,
        worker,
        username=username,
        password=password,
        port=args.port,
        summary_label="Stop complete",
    )


if __name__ == "__main__":
    main()
