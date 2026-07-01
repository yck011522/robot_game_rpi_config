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

Typical usage after Raspberry Pi Imager finishes flashing the card:
    python scripts/prepare_card.py --device 1 --boot E:\\
    python scripts/prepare_card.py --device 1 --boot R:\\
    python scripts/prepare_card.py --device 1 --boot /Volumes/bootfs

Credential override examples, when you intentionally do not want .env values:
    python scripts/prepare_card.py --device 1 --boot E:\\ --username pi --password "your-password"
    python scripts/prepare_card.py --device 3 --boot /Volumes/bootfs --username pi --password "your-password"

By default, the Linux username/password written into the card come from
PI_USERNAME and PI_PASSWORD in the repository .env file.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from rpi_remote_common import ENV_FILE, load_devices, load_dotenv
except ModuleNotFoundError:  # Allows import-based tests from the repository root.
    from scripts.rpi_remote_common import ENV_FILE, load_devices, load_dotenv


USB_CURRENT_LINE = "usb_max_current_enable=1"  # Raspberry Pi 5 config.txt setting that raises USB peripheral current.
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")  # Raspberry Pi username rule: lowercase, starts with a letter.


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
    plain_text_passwd: {password_yaml}

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

  - path: /etc/NetworkManager/system-connections/Wired connection 1.nmconnection
    owner: root:root
    permissions: "0600"
    content: |
      [connection]
      id=Wired connection 1
      type=ethernet
      interface-name=eth0
      autoconnect=true

      [ethernet]

      [ipv4]
      method=manual
      addresses={ip}/24

      [ipv6]
      method=ignore

      [proxy]

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
    """Return ``devices.csv`` rows keyed by card/device index.

    ``devices.csv`` is the single place to tune hostnames and static Ethernet
    IP addresses for the fleet. The ``index`` column is what you pass through
    ``--device`` while preparing one specific card.
    """

    device_rows = load_devices()  # Raw CSV rows shared with deploy/configure scripts; tune in rpi_app/devices.csv.
    devices: dict[int, dict[str, str]] = {}  # Lookup table from numeric device index to its hostname/IP row.
    for row in device_rows:
        index = int(row["index"])  # Stable device number chosen in devices.csv and passed as --device.
        devices[index] = row
    return devices


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text with Linux newlines and print the touched boot path."""

    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def append_usb_current_setting(config_txt: Path) -> None:
    """Add the Pi 5 USB current setting to ``config.txt`` if it is missing."""

    if not config_txt.exists():
        raise FileNotFoundError(f"Cannot find config.txt on boot partition: {config_txt}")

    content = config_txt.read_text(encoding="utf-8", errors="replace")  # Existing boot config; preserve all other lines.
    if USB_CURRENT_LINE in content:
        print(f"{USB_CURRENT_LINE} already present in {config_txt}")
        return

    if not content.endswith("\n"):
        content += "\n"
    content += f"\n# Raspberry Pi 5 USB peripheral current limit\n{USB_CURRENT_LINE}\n"
    config_txt.write_text(content, encoding="utf-8", newline="\n")
    print(f"appended {USB_CURRENT_LINE} to {config_txt}")


def resolve_card_credentials(username: str | None, password: str | None) -> tuple[str, str]:
    """Resolve the first-boot Linux account credentials for the card.

    Command-line values are intentional one-off overrides. When omitted,
    ``PI_USERNAME`` and ``PI_PASSWORD`` from ``.env`` are used so all scripts
    share the same SSH/login credentials.
    """

    env_values = load_dotenv()  # Local .env values; tune PI_USERNAME/PI_PASSWORD there for normal provisioning.
    resolved_username = username or env_values.get("PI_USERNAME")  # Linux user created on first boot; override with --username.
    resolved_password = password or env_values.get("PI_PASSWORD")  # Linux password written into user-data; override with --password.
    missing_keys: list[str] = []  # Human-readable list used to explain exactly what still needs configuration.

    if not resolved_username:
        missing_keys.append("PI_USERNAME")
    if not resolved_password:
        missing_keys.append("PI_PASSWORD")
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise ValueError(
            f"Missing card credentials: {missing}. Set them in {ENV_FILE} or pass --username/--password."
        )

    validate_username(resolved_username)
    return resolved_username, resolved_password


def validate_username(username: str) -> None:
    """Reject usernames that Raspberry Pi OS setup will not accept."""

    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Invalid username. Use 1-31 characters, start with a lowercase letter, "
            "and only include lowercase letters, numbers, underscores, or hyphens."
        )


def yaml_quote(value: str) -> str:
    """Return a YAML-safe quoted scalar for cloud-init template values."""

    return json.dumps(value)  # JSON string syntax is valid YAML and safely escapes punctuation.


def prepare_card(device_index: int, boot_path: Path, username: str, password: str) -> None:
    """Write first-boot provisioning files for one flashed card.

    ``device_index`` selects the row in ``devices.csv``. ``boot_path`` must be
    the mounted FAT boot partition created by Raspberry Pi Imager, not the Linux
    root partition. ``username`` and ``password`` become the first-boot account
    that later SSH scripts use.
    """

    devices = read_devices()
    if device_index not in devices:
        valid = ", ".join(str(i) for i in sorted(devices))
        raise ValueError(f"Unknown device index {device_index}. Valid indices: {valid}")

    if not boot_path.exists() or not boot_path.is_dir():
        raise NotADirectoryError(f"Boot partition does not exist or is not a directory: {boot_path}")

    device = devices[device_index]
    hostname = device["hostname"]
    ip = device["ip"]

    values = {  # Template fields written into cloud-init files on the card.
        "index": str(device_index),  # DEVICE_INDEX in /etc/rpi-node.conf; tune via --device/devices.csv.
        "hostname": hostname,  # Pi hostname; tune in rpi_app/devices.csv.
        "ip": ip,  # Static eth0 IP address; tune in rpi_app/devices.csv.
        "username": username,  # First-boot Linux username; tune in .env or with --username.
        "password_yaml": yaml_quote(password),  # YAML-safe password scalar for cloud-init user-data.
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
    print()
    print("After SSH works, deploy the app and install auto-start services from this computer:")
    print(f"  python scripts/deploy_app.py --devices {device_index}")
    print(f"  python scripts/configure_auto_start.py --devices {device_index}")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for selecting the card and optional credential overrides."""

    parser = argparse.ArgumentParser(description="Prepare a Raspberry Pi OS boot partition for one configured device.")
    parser.add_argument("--device", type=int, required=True, help="Device index from devices.csv, e.g. 1 for rpi5-11.")
    parser.add_argument("--boot", type=Path, required=True, help="Path to the boot partition, e.g. E:\\ or /Volumes/bootfs.")
    parser.add_argument("--username", help="Linux username to create on the Pi. Defaults to PI_USERNAME in .env.")
    parser.add_argument(
        "--password",
        help="Linux password to set on the Pi. Defaults to PI_PASSWORD in .env and is written into user-data on the SD card.",
    )
    return parser.parse_args()


def main() -> None:
    """Run card preparation from CLI arguments."""

    args = parse_args()  # Parsed CLI namespace; tune supported flags in parse_args().
    username, password = resolve_card_credentials(args.username, args.password)
    prepare_card(args.device, args.boot, username, password)


if __name__ == "__main__":
    main()

