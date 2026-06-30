#!/usr/bin/env python3
"""Start the two player-panel processes directly over SSH (no systemd).

A development/diagnostic alternative to the systemd services: each panel is
launched as a detached background process from an SSH *login* shell, the way
panels were started before the service migration. This runs them with the full
interactive session environment rather than the minimal systemd one, which is
useful for confirming whether per-output placement depends on the launch
context.

Stop the systemd services first (``stop_remote_service.py``), then use this to
launch the panels, and ``stop_remote_process.py`` to stop them again. Devices
are taken from ``devices.csv`` by index and serviced concurrently, the same way
``deploy_app.py`` works: with no ``--devices`` the whole fleet is started.
"""

from __future__ import annotations

import argparse
import shlex
import time

from rpi_remote_common import (
    ROLE_DISPLAY,
    ROLE_OUTPUT,
    resolve_credentials,
    run_on_devices,
    run_remote,
    select_targets,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start player-panel processes directly on Raspberry Pis over SSH.")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to start, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    parser.add_argument("--wayland-display", default="wayland-0", help="Remote WAYLAND_DISPLAY value.")
    parser.add_argument(
        "--stagger",
        type=float,
        default=1.0,
        help="Seconds to wait between launching the left and right panels.",
    )
    return parser.parse_args()


def start_one(ssh, remote_dir: str, wayland_display: str, role: str) -> None:
    """Launch a single detached player-panel process and record its PID.

    The panel inherits ``--output``/``--require-outputs``/``--display`` exactly
    like the systemd unit, plus ``SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0`` so two
    fullscreen panels stay mapped. Output goes to ``logs/canvas_<role>.log`` and
    the PID is written to ``run/canvas_<role>.pid`` for ``stop_remote_process``.
    """

    output = ROLE_OUTPUT[role]
    display_idx = ROLE_DISPLAY[role]
    require = ",".join(ROLE_OUTPUT[r] for r in ROLE_DISPLAY)
    app = f"{remote_dir}/rpi_app/player_panel.py"
    pid_file = f"{remote_dir}/run/canvas_{role}.pid"
    log_file = f"{remote_dir}/logs/canvas_{role}.log"

    launch = (
        "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
        f"export WAYLAND_DISPLAY={shlex.quote(wayland_display)}; "
        "export SDL_VIDEODRIVER=wayland; "
        "export SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0; "
        f"nohup python3 -u {shlex.quote(app)} --role {shlex.quote(role)} "
        f"--output {shlex.quote(output)} --require-outputs {shlex.quote(require)} "
        f"--display {display_idx} > {shlex.quote(log_file)} 2>&1 < /dev/null & "
        f"echo $! > {shlex.quote(pid_file)}"
    )

    script = (
        "set -e; "
        f"mkdir -p {shlex.quote(remote_dir)}/logs {shlex.quote(remote_dir)}/run; "
        f"if [ -f {shlex.quote(pid_file)} ]; then "
        f"  old=$(cat {shlex.quote(pid_file)}); "
        "  if ps -p $old >/dev/null 2>&1; then kill $old 2>/dev/null || true; fi; "
        "fi; "
        f"{launch}; "
        "sleep 0.5; "
        f"pid=$(cat {shlex.quote(pid_file)}); "
        "ps -p $pid >/dev/null 2>&1"
    )

    run_remote(ssh, "bash -lc " + shlex.quote(script))


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    targets = select_targets(args.devices)

    print(f"Starting player-panel processes on {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets))

    def worker(ssh, log) -> None:
        log("Starting player-panel processes...")
        start_one(ssh, remote_dir=args.remote_dir, wayland_display=args.wayland_display, role="left")
        if args.stagger > 0:
            time.sleep(args.stagger)
        start_one(ssh, remote_dir=args.remote_dir, wayland_display=args.wayland_display, role="right")
        log(f"Started (left, right). Logs: {args.remote_dir}/logs/canvas_left.log and canvas_right.log")

    run_on_devices(
        targets,
        worker,
        username=username,
        password=password,
        port=args.port,
        summary_label="Start complete",
    )


if __name__ == "__main__":
    main()
