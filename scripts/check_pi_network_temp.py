#!/usr/bin/env python3
"""
Temporarily inspect Raspberry Pi network settings over SSH.

Typical runs from this repository root:
    C:\\Users\\yck01\\miniconda3\\envs\\game\\python.exe scripts\\check_pi_network_temp.py --ip 192.168.0.11
    C:\\Users\\yck01\\miniconda3\\envs\\game\\python.exe scripts\\check_pi_network_temp.py --device 1
    C:\\Users\\yck01\\miniconda3\\envs\\game\\python.exe scripts\\check_pi_network_temp.py --device 11

Credentials are read from .env by default:
    PI_USERNAME=pi
    PI_PASSWORD=<password>
"""

from __future__ import annotations

import argparse

from rpi_remote_common import connect_ssh, resolve_credentials, resolve_target, run_remote


def parse_args() -> argparse.Namespace:
    """Parse the Pi selector and SSH options used by the diagnostic command."""
    parser = argparse.ArgumentParser(description="Inspect Raspberry Pi network settings over SSH.")
    parser.add_argument("--device", default="11", help="Device selector from devices.csv; supports index 1 or suffix 11.")
    parser.add_argument("--host", help="Optional SSH hostname override when devices.csv should not be used.")
    parser.add_argument("--ip", help="Optional SSH IP override, for example 192.168.0.11.")
    parser.add_argument("--username", help="Optional SSH username; defaults to PI_USERNAME in .env.")
    parser.add_argument("--password", help="Optional SSH password; defaults to PI_PASSWORD in .env.")
    parser.add_argument("--port", type=int, default=22, help="SSH port to connect to; default is 22.")
    return parser.parse_args()


def print_section(title: str, command: str, code: int, out: str, err: str) -> None:
    """Print one remote command result with a stable heading for easy scanning."""
    print(f"\n===== {title} =====")
    print(f"$ {command}")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:")
        print(err.rstrip())
    print(f"[exit {code}]")


def main() -> None:
    """Connect to the target Pi, run read-only network diagnostics, and print them."""
    args = parse_args()

    # target controls the SSH host/IP selected from CLI overrides or devices.csv.
    target = resolve_target(device=args.device, host=args.host, ip=args.ip)

    # username/password control SSH authentication; they normally come from .env.
    username, password = resolve_credentials(username=args.username, password=args.password)

    # commands controls the read-only remote inspections to run on the Pi.
    commands: list[tuple[str, str]] = [
        ("identity", "hostname; whoami; date"),
        ("project node config", "cat /etc/rpi-node.conf 2>/dev/null || true"),
        ("eth0 address", "ip -br addr show eth0; ip addr show eth0"),
        ("routes", "ip route"),
        ("networkmanager device summary", "nmcli device status"),
        (
            "networkmanager eth0 details",
            "nmcli -f GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show eth0",
        ),
        ("networkmanager connection list", "nmcli -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT connection show"),
        (
            "active eth0 connection profile",
            "active=$(nmcli -t -f GENERAL.CONNECTION device show eth0 | sed 's/^GENERAL.CONNECTION://'); "
            "if [ -n \"$active\" ] && [ \"$active\" != \"--\" ]; then "
            "nmcli -f connection.id,connection.uuid,connection.type,connection.interface-name,connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns connection show \"$active\"; "
            "else echo 'No active eth0 connection'; fi",
        ),
        (
            "networkmanager profile files",
            "sudo -n ls -l /etc/NetworkManager/system-connections 2>/dev/null || "
            "ls -l /etc/NetworkManager/system-connections 2>/dev/null || true",
        ),
        ("cloud-init status", "cloud-init status --long 2>/dev/null || true"),
    ]

    print(f"Connecting to {target.host}:{args.port} as {username}...")
    ssh = connect_ssh(target.host, username, password, port=args.port)
    try:
        for title, command in commands:
            code, out, err = run_remote(ssh, command, check=False)
            print_section(title=title, command=command, code=code, out=out, err=err)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
