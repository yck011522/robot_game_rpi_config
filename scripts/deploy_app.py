#!/usr/bin/env python3
"""Stop, deploy, and restart the Raspberry Pi app over SSH/SFTP.

Each selected device is fully serviced in one pass: running canvas processes are
stopped, ``rpi_app`` is uploaded, and the player-panel processes are started
again. Devices are always taken from ``devices.csv`` by index and serviced
concurrently, so a single run can refresh the whole fleet.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from rpi_remote_common import (
    REPO_ROOT,
    Target,
    connect_ssh,
    load_devices,
    parse_indices,
    resolve_credentials,
    resolve_targets,
    run_remote,
    upload_tree,
)
from start_remote_service import start_one
from stop_remote_service import stop_one


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop, deploy, and restart rpi_app on Raspberry Pis over SSH.")
    parser.add_argument(
        "--devices",
        nargs="+",
        default=None,
        metavar="INDEX",
        help="devices.csv indices to deploy to, e.g. 1 2 3 or 1-6. Defaults to all devices.",
    )
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    return parser.parse_args()


def deploy_one(
    index: int,
    target: Target,
    username: str,
    password: str,
    port: int,
    remote_dir: str,
) -> tuple[bool, list[str]]:
    """Stop, upload, and restart the app on a single device.

    Returns whether the pass succeeded along with the buffered log lines, so the
    caller can print each device's output as one uninterrupted block.
    """

    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(f"[{index}:{target.host}] {message}")

    try:
        ssh = connect_ssh(target.host, username, password, port=port)
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED to connect: {exc}")
        return False, lines

    try:
        log("Stopping canvas services...")
        stop_one(ssh, role="left")
        stop_one(ssh, role="right")

        log("Uploading rpi_app...")
        run_remote(ssh, f"mkdir -p {remote_dir}/logs {remote_dir}/run")
        with ssh.open_sftp() as sftp:
            upload_tree(sftp, local_root=REPO_ROOT, remote_root=remote_dir, include=[REPO_ROOT / "rpi_app"])
        log("Upload complete.")

        log("Starting canvas services...")
        start_one(ssh, role="left")
        start_one(ssh, role="right")
        log("Started. Deploy complete.")
        return True, lines
    except Exception as exc:  # noqa: BLE001 - report and keep other devices going.
        log(f"FAILED: {exc}")
        return False, lines
    finally:
        ssh.close()


def main() -> None:
    args = parse_args()

    username, password = resolve_credentials(username=args.username, password=args.password)
    all_indices = sorted(int(row["index"]) for row in load_devices())
    indices = parse_indices(args.devices, all_indices)
    targets = resolve_targets(indices)

    print(f"Deploying to {len(targets)} device(s): " + ", ".join(f"{i}:{t.host}" for i, t in targets))

    print_lock = Lock()
    results: dict[int, bool] = {}

    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        futures = {
            executor.submit(
                deploy_one,
                index,
                target,
                username,
                password,
                args.port,
                args.remote_dir,
            ): index
            for index, target in targets
        }

        for future in as_completed(futures):
            index = futures[future]
            ok, lines = future.result()
            results[index] = ok
            with print_lock:
                print("\n".join(lines))

    succeeded = sorted(i for i, ok in results.items() if ok)
    failed = sorted(i for i, ok in results.items() if not ok)
    print()
    print(f"Done. Succeeded: {succeeded or 'none'}. Failed: {failed or 'none'}.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
