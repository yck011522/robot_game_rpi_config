#!/usr/bin/env python3
"""Collect local network diagnostics on a Raspberry Pi.

Run this directly on a Pi (keyboard attached) to capture a snapshot of Ethernet,
NetworkManager profile state, and key system settings used by this project.

Examples:
  python3 scripts/local_pi_network_diagnose.py
  python3 scripts/local_pi_network_diagnose.py --out /tmp/pi-net-report.txt
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect local Raspberry Pi network diagnostics.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/pi-network-diagnose.txt"),
        help="Report output path (default: /tmp/pi-network-diagnose.txt).",
    )
    return parser.parse_args()


def run(cmd: str) -> tuple[int, str, str]:
    result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def section(title: str, cmd: str) -> str:
    code, out, err = run(cmd)
    lines = [f"===== {title} =====", f"$ {cmd}"]
    lines.append(out if out else "<no stdout>")
    if err:
        lines.append("STDERR:")
        lines.append(err)
    lines.append(f"[exit {code}]")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    now = datetime.now(timezone.utc).isoformat()

    blocks = [
        f"Report UTC: {now}",
        section("identity", "hostname; whoami; id"),
        section("project node config", "cat /etc/rpi-node.conf 2>/dev/null || true"),
        section("link and addresses", "ip -br link; ip -br addr"),
        section("eth0 details", "ip addr show eth0; ethtool eth0 2>/dev/null || true"),
        section("routes", "ip route"),
        section("networkmanager status", "systemctl is-active NetworkManager; nmcli -t general status"),
        section("networkmanager devices", "nmcli device status"),
        section("networkmanager connections", "nmcli -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT connection show"),
        section(
            "active eth0 profile",
            "active=$(nmcli -t -f GENERAL.CONNECTION device show eth0 | sed 's/^GENERAL.CONNECTION://'); "
            "if [ -n \"$active\" ] && [ \"$active\" != \"--\" ]; then "
            "nmcli -f connection.id,connection.uuid,connection.type,connection.interface-name,connection.autoconnect,"
            "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,ipv4.route-metric connection show \"$active\"; "
            "else echo 'No active eth0 connection'; fi",
        ),
        section("networkmanager profile files", "sudo -n ls -l /etc/NetworkManager/system-connections 2>/dev/null || ls -l /etc/NetworkManager/system-connections || true"),
        section("cloud-init status", "cloud-init status --long 2>/dev/null || true"),
        section("kernel cmdline", "cat /proc/cmdline"),
        section("dmesg network snippets", "dmesg -T | egrep -i 'eth0|link up|link down|r8169|NetworkManager|dhcp' | tail -n 120"),
    ]

    report = "\n\n".join(blocks) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8", newline="\n")

    print(f"Wrote report to: {args.out}")


if __name__ == "__main__":
    main()
