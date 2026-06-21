#!/usr/bin/env python3
"""Deploy the minimal Raspberry Pi app files over SSH/SFTP."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi_remote_common import REPO_ROOT, connect_ssh, resolve_credentials, resolve_target, run_remote, upload_tree


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy rpi_app to a Raspberry Pi over SSH.")
    parser.add_argument("--device", default="11", help="Device selector. Supports index (1) or hostname suffix (11).")
    parser.add_argument("--host", help="Override SSH host/IP directly.")
    parser.add_argument("--ip", help="Override IP directly.")
    parser.add_argument("--username", help="SSH username. Defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="SSH password. Defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--remote-dir", default="/home/pi/robot_game", help="Remote deployment root path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target = resolve_target(device=args.device, host=args.host, ip=args.ip)
    username, password = resolve_credentials(username=args.username, password=args.password)

    local_root = REPO_ROOT
    include_paths = [local_root / "rpi_app"]

    print(f"Connecting to {target.host}:{args.port} as {username}...")
    ssh = connect_ssh(target.host, username, password, port=args.port)
    try:
        run_remote(ssh, f"mkdir -p {args.remote_dir}/logs {args.remote_dir}/run")

        with ssh.open_sftp() as sftp:
            upload_tree(sftp, local_root=local_root, remote_root=args.remote_dir, include=include_paths)

        print("Upload complete.")

        code, out, err = run_remote(
            ssh,
            f"python3 -c \"import pygame; print(pygame.__version__)\"",
            check=False,
        )
        if code == 0:
            print(f"Remote pygame version: {out.strip()}")
        else:
            print("Remote pygame import check failed. Install pygame on the Pi if needed.")
            if err.strip():
                print(err.strip())

        print(f"Deployed app to: {args.remote_dir}")
        print(f"Target host:     {target.host}")
        if target.ip:
            print(f"Target ip:       {target.ip}")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
