#!/usr/bin/env python3
"""Stop the remote player-panel systemd user services over SSH.

Devices are taken from ``devices.csv`` by index and serviced concurrently, the
same way ``deploy_app.py`` works: with no ``--devices`` the whole fleet is
stopped.
"""

from __future__ import annotations

import argparse

from rpi_remote_common import (
    resolve_credentials,
    run_on_devices,
    select_targets,
    service_name,
    user_systemctl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop canvas services on Raspberry Pis over SSH.")
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
    return parser.parse_args()


def stop_one(ssh, role: str) -> None:
    """Stop the canvas service for a single role (``left``/``right``).

    ``check=False`` so stopping a service that is missing or already inactive is
    a no-op rather than an error.
    """

    user_systemctl(ssh, f"stop {service_name(role)}", check=False)


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    targets = select_targets(args.devices)

    print(f"Stopping canvas services on {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets))

    def worker(ssh, log) -> None:
        log("Stopping canvas services...")
        stop_one(ssh, role="left")
        stop_one(ssh, role="right")
        log("Stopped: " + ", ".join(service_name(r) for r in ("left", "right")))

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
