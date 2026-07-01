#!/usr/bin/env python3
"""Stagger-reset HDMI outputs on remote Raspberry Pis over SSH.

This script toggles both HDMI connectors in sequence to recover displays that
occasionally fail to wake after boot:
1) turn HDMI-A-1 off
2) wait ``--between-delay`` seconds
3) turn HDMI-A-2 off
4) wait ``--settle-delay`` seconds
5) turn HDMI-A-1 on
6) wait ``--between-delay`` seconds
7) turn HDMI-A-2 on

Devices are selected by ``devices.csv`` index. With no ``--devices`` argument,
all known devices are processed concurrently.
"""

from __future__ import annotations

import argparse
import shlex
import time

from rpi_remote_common import ROLE_OUTPUT, resolve_credentials, run_on_devices, run_remote, select_targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stagger-reset HDMI outputs on Raspberry Pis over SSH.")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to reset, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument(
        "--between-delay",
        type=float,
        default=1.0,
        help="Seconds to wait between turning individual outputs off/on (default: 1.0).",
    )
    parser.add_argument(
        "--settle-delay",
        type=float,
        default=2.0,
        help="Seconds to wait after both outputs are off before turning them back on (default: 2.0).",
    )
    args = parser.parse_args()

    if args.between_delay < 0:
        parser.error("--between-delay must be >= 0")
    if args.settle_delay < 0:
        parser.error("--settle-delay must be >= 0")
    return args


def _run_wlr_randr(ssh, output: str, enabled: bool) -> None:
    action = "--on" if enabled else "--off"

    # SSH sessions often miss compositor env vars; try common Wayland socket names.
    base = (
        'export XDG_RUNTIME_DIR="/run/user/$(id -u)"; '
        "for sock in wayland-1 wayland-0; do "
        f'  if WAYLAND_DISPLAY="$sock" wlr-randr --output {shlex.quote(output)} {action}; then exit 0; fi; '
        "done; "
        f'echo "wlr-randr failed for output {output} ({action}) on wayland-1/wayland-0" >&2; '
        "exit 1"
    )
    cmd = "bash -lc " + shlex.quote(base)
    run_remote(ssh, cmd)


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    targets = select_targets(args.devices)

    print(
        f"Resetting displays on {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets)
    )

    left_output = ROLE_OUTPUT["left"]
    right_output = ROLE_OUTPUT["right"]

    def worker(ssh, log) -> None:
        log(f"Turning off {left_output}...")
        _run_wlr_randr(ssh, left_output, enabled=False)

        if args.between_delay > 0:
            log(f"Waiting {args.between_delay:.1f}s before next output...")
            time.sleep(args.between_delay)

        log(f"Turning off {right_output}...")
        _run_wlr_randr(ssh, right_output, enabled=False)

        if args.settle_delay > 0:
            log(f"Waiting {args.settle_delay:.1f}s before power-on sequence...")
            time.sleep(args.settle_delay)

        log(f"Turning on {left_output}...")
        _run_wlr_randr(ssh, left_output, enabled=True)

        if args.between_delay > 0:
            log(f"Waiting {args.between_delay:.1f}s before next output...")
            time.sleep(args.between_delay)

        log(f"Turning on {right_output}...")
        _run_wlr_randr(ssh, right_output, enabled=True)
        log("Display reset sequence complete.")

    run_on_devices(
        targets,
        worker,
        username=username,
        password=password,
        port=args.port,
        summary_label="Display reset complete",
    )


if __name__ == "__main__":
    main()
