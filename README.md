# robot_game_rpi_config

## 1. Intended goal of this repository

This repository records and automates the initial configuration of the Raspberry Pi 5 devices used in the robot game hardware setup.

Its scope is limited to preparing each Raspberry Pi and its microSD card so that the device can boot for the first time with the correct system-level configuration:

- Raspberry Pi OS selection
- static Ethernet network configuration
- unique hostname and device identity
- SSH username/password access
- display-related system configuration
- Raspberry Pi 5 power/current setting
- first-boot validation steps

This repository should not contain the Pygame dashboard/game implementation. The game software, file transfer, remote launching, and runtime game logic should live in a separate repository. This repository only prepares the Raspberry Pi devices so that they are reachable, identifiable, and ready for later software deployment.

## 2. Minimal setup workflow

The intended workflow is:

1. Flash a microSD card using Raspberry Pi Imager.
2. Use Raspberry Pi OS with Desktop, 64-bit.
    hostname rpi5-11 (see below)
    username: pi
    password: pi1234
3. Reinsert the flashed card into the host computer.
4. Run `scripts/prepare_card.py` on the boot partition of the flashed card.
5. Boot the Raspberry Pi on the closed LAN.
6. Validate SSH, static IP, hostname, display detection, USB microphones, and power status.

The current static network plan is:

```text
Host computer: 192.168.0.10/24

rpi5-11: 192.168.0.11/24
rpi5-12: 192.168.0.12/24
rpi5-13: 192.168.0.13/24
rpi5-14: 192.168.0.14/24
rpi5-15: 192.168.0.15/24
rpi5-16: 192.168.0.16/24
```

Example usage after flashing one card:

```bash
python scripts/prepare_card.py --device 1 --boot D:\\ --username pi --password pi1234
```

On macOS/Linux, the boot partition path may look like:

```bash
python scripts/prepare_card.py --device 1 --boot /Volumes/bootfs --username pi --password pi1234
```

The script writes first-boot configuration files to the boot partition. It does not write the Raspberry Pi OS image itself; that is still handled by Raspberry Pi Imager.
