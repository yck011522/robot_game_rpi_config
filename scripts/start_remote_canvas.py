#!/usr/bin/env python3
"""Start two remote pygame player-panel processes over SSH."""

from __future__ import annotations

import argparse
import shlex

from rpi_remote_common import connect_ssh, resolve_credentials, resolve_target, run_remote


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start player-panel processes on a Raspberry Pi over SSH.")
    parser.add_argument("--device", default="11", help="Device selector. Supports index (1) or hostname suffix (11).")
    parser.add_argument("--host", help="Override SSH host/IP directly.")
    parser.add_argument("--ip", help="Override IP directly.")
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    parser.add_argument("--wayland-display", default="wayland-0", help="Remote WAYLAND_DISPLAY value.")
    return parser.parse_args()


def start_one(ssh, remote_dir: str, wayland_display: str, role: str, display_idx: int, team: str, joint: int) -> None:
    pid_file = f"{remote_dir}/run/canvas_{role}.pid"
    log_file = f"{remote_dir}/logs/canvas_{role}.log"
    app = f"{remote_dir}/rpi_app/player_panel.py"

    cmd = (
        "bash -lc "
        + shlex.quote(
            "set -e; "
            f"mkdir -p {shlex.quote(remote_dir)}/logs {shlex.quote(remote_dir)}/run; "
            f"if [ -f {shlex.quote(pid_file)} ]; then "
            f"  old_pid=$(cat {shlex.quote(pid_file)}); "
            "  if ps -p $old_pid >/dev/null 2>&1; then kill $old_pid || true; fi; "
            "fi; "
            f"nohup env XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY={shlex.quote(wayland_display)} "
            f"python3 {shlex.quote(app)} --role {shlex.quote(role)} --display {display_idx} --team {shlex.quote(team)} --joint {joint} "
            f"> {shlex.quote(log_file)} 2>&1 < /dev/null & "
            f"echo $! > {shlex.quote(pid_file)}; "
            "sleep 0.4; "
            f"pid=$(cat {shlex.quote(pid_file)}); "
            "ps -p $pid >/dev/null 2>&1"
        )
    )

    run_remote(ssh, cmd)


def main() -> None:
    args = parse_args()

    target = resolve_target(device=args.device, host=args.host, ip=args.ip)
    username, password = resolve_credentials(username=args.username, password=args.password)

    print(f"Connecting to {target.host}:{args.port} as {username}...")
    ssh = connect_ssh(target.host, username, password, port=args.port)

    try:
        start_one(
            ssh,
            remote_dir=args.remote_dir,
            wayland_display=args.wayland_display,
            role="left",
            display_idx=0,
            team="A",
            joint=1,
        )
        start_one(
            ssh,
            remote_dir=args.remote_dir,
            wayland_display=args.wayland_display,
            role="right",
            display_idx=1,
            team="A",
            joint=2,
        )

        print("Started two player-panel processes.")
        print(f"Logs: {args.remote_dir}/logs/canvas_left.log and canvas_right.log")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
