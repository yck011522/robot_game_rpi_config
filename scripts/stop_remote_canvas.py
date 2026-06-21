#!/usr/bin/env python3
"""Stop remote pygame canvas processes over SSH."""

from __future__ import annotations

import argparse
import shlex

from rpi_remote_common import connect_ssh, resolve_credentials, resolve_target, run_remote


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop canvas processes on a Raspberry Pi over SSH.")
    parser.add_argument("--device", default="11", help="Device selector. Supports index (1) or hostname suffix (11).")
    parser.add_argument("--host", help="Override SSH host/IP directly.")
    parser.add_argument("--ip", help="Override IP directly.")
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    return parser.parse_args()


def stop_one(ssh, remote_dir: str, role: str) -> None:
    pid_file = f"{remote_dir}/run/canvas_{role}.pid"
    pattern_canvas = shlex.quote(f"simple_canvas.py --role {role}")
    pattern_panel = shlex.quote(f"player_panel.py --role {role}")

    cmd = (
        "bash -lc "
        + shlex.quote(
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
            f"pkill -f {pattern_canvas} >/dev/null 2>&1 || true; "
            f"pkill -f {pattern_panel} >/dev/null 2>&1 || true"
        )
    )

    run_remote(ssh, cmd, check=False)


def main() -> None:
    args = parse_args()

    target = resolve_target(device=args.device, host=args.host, ip=args.ip)
    username, password = resolve_credentials(username=args.username, password=args.password)

    print(f"Connecting to {target.host}:{args.port} as {username}...")
    ssh = connect_ssh(target.host, username, password, port=args.port)

    try:
        stop_one(ssh, remote_dir=args.remote_dir, role="left")
        stop_one(ssh, remote_dir=args.remote_dir, role="right")
        print("Stop command sent for left and right canvas processes.")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
