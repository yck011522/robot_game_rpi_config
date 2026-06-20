#!/usr/bin/env python3
"""
Prepare a Raspberry Pi OS boot partition after Raspberry Pi Imager has flashed it.

This script does not flash the OS image. It writes the per-device first-boot
configuration files needed for this project:

- meta-data
- network-config
- user-data
- config.txt USB current setting
- a marker file identifying the card

Example:
    python scripts/prepare_card.py --device 1 --boot E:\\ --username victor --password "your-password"
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICES_CSV = REPO_ROOT / "devices.csv"
USB_CURRENT_LINE = "usb_max_current_enable=1"


USER_DATA_TEMPLATE = """#cloud-config
hostname: {hostname}
manage_etc_hosts: true

enable_ssh: true
ssh_pwauth: true

users:
  - name: {username}
    gecos: Raspberry Pi Config User
    groups: users,adm,sudo,dialout,audio,video,plugdev,gpio,i2c,spi,input,netdev
    sudo: ALL=(ALL:ALL) ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: {password}

write_files:
  - path: /etc/rpi-node.conf
    owner: root:root
    permissions: "0644"
    content: |
      DEVICE_INDEX={index}
      DEVICE_HOSTNAME={hostname}
      DEVICE_IP={ip}
      LEFT_DISPLAY_INDEX=0
      RIGHT_DISPLAY_INDEX=1

runcmd:
  - echo "Provisioned {hostname} at {ip}" > /var/log/rpi-node-provisioning.log
"""


NETWORK_CONFIG_TEMPLATE = """network:
  version: 2
  ethernets:
    eth0:
      renderer: NetworkManager
      dhcp4: false
      addresses:
        - {ip}/24
      optional: true
"""


META_DATA_TEMPLATE = """instance-id: {hostname}
local-hostname: {hostname}
"""


def read_devices() -> dict[int, dict[str, str]]:
    if not DEVICES_CSV.exists():
        raise FileNotFoundError(f"Cannot find device table: {DEVICES_CSV}")

    devices: dict[int, dict[str, str]] = {}
    with DEVICES_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            index = int(row["index"])
            devices[index] = row
    return devices


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def append_usb_current_setting(config_txt: Path) -> None:
    if not config_txt.exists():
        raise FileNotFoundError(f"Cannot find config.txt on boot partition: {config_txt}")

    content = config_txt.read_text(encoding="utf-8", errors="replace")
    if USB_CURRENT_LINE in content:
        print(f"{USB_CURRENT_LINE} already present in {config_txt}")
        return

    if not content.endswith("\n"):
        content += "\n"
    content += f"\n# Raspberry Pi 5 USB peripheral current limit\n{USB_CURRENT_LINE}\n"
    config_txt.write_text(content, encoding="utf-8", newline="\n")
    print(f"appended {USB_CURRENT_LINE} to {config_txt}")


def prepare_card(device_index: int, boot_path: Path, username: str, password: str) -> None:
    devices = read_devices()
    if device_index not in devices:
        valid = ", ".join(str(i) for i in sorted(devices))
        raise ValueError(f"Unknown device index {device_index}. Valid indices: {valid}")

    if not boot_path.exists() or not boot_path.is_dir():
        raise NotADirectoryError(f"Boot partition does not exist or is not a directory: {boot_path}")

    device = devices[device_index]
    hostname = device["hostname"]
    ip = device["ip"]

    values = {
        "index": str(device_index),
        "hostname": hostname,
        "ip": ip,
        "username": username,
        "password": password,
    }

    write_text(boot_path / "meta-data", META_DATA_TEMPLATE.format(**values))
    write_text(boot_path / "network-config", NETWORK_CONFIG_TEMPLATE.format(**values))
    write_text(boot_path / "user-data", USER_DATA_TEMPLATE.format(**values))

    append_usb_current_setting(boot_path / "config.txt")

    marker = boot_path / f"THIS_CARD_IS_{hostname}_{ip}.txt"
    write_text(marker, f"{hostname}\n{ip}\n")

    print()
    print("done")
    print(f"device:   {hostname}")
    print(f"ip:       {ip}/24")
    print(f"username: {username}")
    print()
    print("Next step: eject the card, insert it into the Raspberry Pi, boot it, then test:")
    print(f"  ping {ip}")
    print(f"  ssh {username}@{ip}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a Raspberry Pi OS boot partition for one configured device.")
    parser.add_argument("--device", type=int, required=True, help="Device index from devices.csv, e.g. 1 for rpi5-01.")
    parser.add_argument("--boot", type=Path, required=True, help="Path to the boot partition, e.g. E:\\ or /Volumes/bootfs.")
    parser.add_argument("--username", required=True, help="Linux username to create on the Pi.")
    parser.add_argument("--password", required=True, help="Linux password to set on the Pi. This is written into user-data on the SD card.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prepare_card(args.device, args.boot, args.username, args.password)


if __name__ == "__main__":
    main()
