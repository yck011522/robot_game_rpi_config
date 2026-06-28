#!/usr/bin/env python3
"""Start the remote player-panel systemd user services over SSH.

The two player-panel services (``robot-game-left`` / ``robot-game-right``) are
installed by ``configure_auto_start.py``. This script simply starts them on
demand; run the configure script first if the units do not yet exist.
"""

from __future__ import annotations

import argparse

from rpi_remote_common import (
    connect_ssh,
    resolve_credentials,
    resolve_target,
    service_name,
    user_systemctl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start canvas services on a Raspberry Pi over SSH.")
    parser.add_argument("--device", default="11", help="Device selector. Supports index (1) or hostname suffix (11).")
    parser.add_argument("--host", help="Override SSH host/IP directly.")
    parser.add_argument("--ip", help="Override IP directly.")
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    return parser.parse_args()


def start_one(ssh, role: str) -> None:
    """Start the canvas service for a single role (``left``/``right``)."""

    user_systemctl(ssh, f"start {service_name(role)}")


def main() -> None:
    args = parse_args()

    target = resolve_target(device=args.device, host=args.host, ip=args.ip)
    username, password = resolve_credentials(username=args.username, password=args.password)

    print(f"Connecting to {target.host}:{args.port} as {username}...")
    ssh = connect_ssh(target.host, username, password, port=args.port)

    try:
        start_one(ssh, role="left")
        start_one(ssh, role="right")
        print("Started canvas services: " + ", ".join(service_name(r) for r in ("left", "right")))
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
