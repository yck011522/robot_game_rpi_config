#!/usr/bin/env python3
"""Repair Raspberry Pi eth0 static profile from /etc/rpi-node.conf.

Run this locally on a Pi when NetworkManager shows eth0 disconnected and no IPv4.
It recreates/updates the Wired connection profile and brings it up.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

NODE_CONF = Path("/etc/rpi-node.conf")
CONNECTION_NAME = "Wired connection 1"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run as root: sudo python3 repair_local_network_profile.py")


def parse_node_ip(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Missing {path}; cannot determine static IP")

    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^DEVICE_IP=(.+)$", text, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"DEVICE_IP not found in {path}")

    ip = match.group(1).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip):
        raise SystemExit(f"Invalid DEVICE_IP value in {path}: {ip}")
    return ip


def ensure_connection_exists(name: str) -> None:
    show = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    if show.returncode != 0:
        raise SystemExit(f"nmcli connection show failed: {show.stderr.strip()}")

    existing = {line.strip() for line in show.stdout.splitlines() if line.strip()}
    if name in existing:
        return

    add = run(["nmcli", "connection", "add", "type", "ethernet", "ifname", "eth0", "con-name", name])
    if add.returncode != 0:
        raise SystemExit(f"Failed to add connection {name}: {add.stderr.strip()}")


def configure_connection(name: str, ip: str) -> None:
    modify_cmd = [
        "nmcli",
        "connection",
        "modify",
        name,
        "connection.interface-name",
        "eth0",
        "connection.autoconnect",
        "yes",
        "ipv4.method",
        "manual",
        "ipv4.addresses",
        f"{ip}/24",
        "ipv4.gateway",
        "",
        "ipv4.dns",
        "",
        "ipv4.ignore-auto-dns",
        "yes",
        "ipv6.method",
        "ignore",
    ]
    modified = run(modify_cmd)
    if modified.returncode != 0:
        raise SystemExit(f"Failed to configure {name}: {modified.stderr.strip()}")


def bring_up_connection(name: str) -> None:
    up = run(["nmcli", "connection", "up", name])
    if up.returncode != 0:
        raise SystemExit(f"Failed to bring up {name}: {up.stderr.strip()}")


def main() -> None:
    require_root()
    ip = parse_node_ip(NODE_CONF)

    ensure_connection_exists(CONNECTION_NAME)
    configure_connection(CONNECTION_NAME, ip)
    bring_up_connection(CONNECTION_NAME)

    print("Repaired NetworkManager profile.")
    print("Expected IPv4:", ip)

    for cmd in (
        ["nmcli", "device", "status"],
        ["nmcli", "-f", "NAME,UUID,TYPE,DEVICE,AUTOCONNECT", "connection", "show"],
        ["ip", "-br", "addr", "show", "eth0"],
        ["ip", "route"],
    ):
        result = run(cmd)
        print("\n$", " ".join(cmd))
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print("STDERR:")
            print(result.stderr.strip())


if __name__ == "__main__":
    main()
