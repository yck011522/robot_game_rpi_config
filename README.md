# robot_game_rpi_config

## 1. Repository intent and current system assumptions

This repository is for preparing and running the Raspberry Pi side of the robot game display system.

The repository now has two related responsibilities:

1. **Raspberry Pi provisioning**
   - prepare Raspberry Pi OS microSD cards
   - set hostname and static Ethernet IP
   - enable SSH username/password access
   - configure Raspberry Pi 5 system settings
   - validate display, microphone, network, and power status after first boot

2. **Minimal Raspberry Pi runtime application**
   - host the Python application files that will later be copied to the Raspberry Pis
   - run two local processes per Pi, one per display role
   - listen for UDP game/status broadcast packets
   - eventually launch automatically using systemd services

This repository is not intended to contain the host-side game controller or broadcaster. The broadcaster is assumed to be a separate application running on the host computer.

### Hardware assumptions

Each Raspberry Pi 5 has:

- Raspberry Pi 5, 8 GB RAM
- Raspberry Pi OS with Desktop, 64-bit
- two HDMI portrait displays
- two USB microphones
- Ethernet connection to a closed local switch
- no router
- no DHCP
- no internet requirement during runtime
- SSH access from the host computer

### Network assumptions

Closed LAN:

```text
Host computer: 192.168.0.10/24

rpi5-11: 192.168.0.11/24
rpi5-12: 192.168.0.12/24
rpi5-13: 192.168.0.13/24
rpi5-14: 192.168.0.14/24
rpi5-15: 192.168.0.15/24
rpi5-16: 192.168.0.16/24
```

The host-side broadcaster is expected to send UDP packets to:

```text
192.168.0.255:49200
```

The Raspberry Pi listener processes should bind locally to:

```text
0.0.0.0:49200
```

The listeners should keep running even if the broadcaster starts late, stops, disconnects, or restarts. Since this is UDP, there is no persistent connection. Packets sent while a listener is down are simply lost.

Protocol note:

- The canonical payload is the Display Broadcast Protocol v1 envelope:
   - top level fields: `v`, `seq`, `ts_wall_ns`, `state`
   - game fields (for example stage/timer) are read from `state`, typically
      `state.stage` or `state.active_stage` and `state.countdown_s`
- During migration, some local scripts may still accept the legacy flat test
   payload (`game_state`, `timer_s`) as a temporary fallback.

### Current verified state on `rpi5-11`

The first test Pi has successfully booted with:

```text
hostname:        rpi5-11
static IP:       192.168.0.11/24
SSH:             working
config file:     /etc/rpi-node.conf
USB current:     usb_max_current_enable=1
throttle state:  throttled=0x0
```

Detected display layout from `wlr-randr`:

```text
HDMI-A-1:
  mode:      480x1920 @ 60 Hz
  position:  0,0
  transform: normal

HDMI-A-2:
  mode:      480x1920 @ 60 Hz
  position:  480,0
  transform: normal
```

This means the OS currently sees the two portrait displays as an extended desktop of approximately:

```text
960x1920
```

Detected microphones from PipeWire:

```text
MIC11 Analog Stereo
MIC12 Analog Stereo
```

The exact mapping between physical display, Pygame display index, and player role still needs to be tested.

## 2. Development and testing plan

### A. Existing SD-card provisioning workflow

1. Flash the microSD card using Raspberry Pi Imager.
2. Use Raspberry Pi OS with Desktop, 64-bit.
3. In Raspberry Pi Imager, configure:
   - hostname matching `devices.csv`
   - username
   - password
   - SSH enabled
   - Wi-Fi disabled / blank
   - Raspberry Pi Connect disabled
4. Reinsert the flashed card into the host computer.
5. Run:

```bash
python scripts/prepare_card.py --device 1 --boot R:\ --username pi --password "<shared-password>"
```

On macOS/Linux, the boot partition path may look like:

```bash
python scripts/prepare_card.py --device 1 --boot /Volumes/bootfs --username pi --password "<shared-password>"
```

The script writes first-boot configuration files to the boot partition. It does not write the Raspberry Pi OS image itself; Raspberry Pi Imager handles OS flashing.

The script currently writes:

```text
meta-data
network-config
user-data
config.txt patch: usb_max_current_enable=1
THIS_CARD_IS_<hostname>_<ip>.txt
```

Important: do not commit real passwords to this repository. Pass the password on the command line during local provisioning only.

### B. Immediate validation after boot

After booting a prepared Pi, connect from the host computer:

```bash
ssh pi@192.168.0.11
```

If the SD card has been reflashed, remove the old host key first:

```bash
ssh-keygen -R 192.168.0.11
```

Run these validation commands on the Pi:

```bash
hostname
ip addr show eth0
cat /etc/rpi-node.conf
groups
sudo whoami
vcgencmd get_config usb_max_current_enable
vcgencmd get_throttled
wlr-randr
wpctl status
arecord -l
lsusb
ls -l /dev/snd/by-id || true
ls -l /dev/snd/by-path || true
```

Expected sudo result:

```text
sudo whoami -> root
```

A previous version of `scripts/prepare_card.py` created the user without sudo access. This has been fixed; future cards should include the user in the `sudo` group.

### C. Planned repository structure for runtime code

Do not create these files until development resumes in VS Code. This is the proposed structure:

```text
robot_game_rpi_config/
├── README.md
├── devices.csv
├── scripts/
│   ├── prepare_card.py
│   ├── deploy_app.py              # future
│   └── install_services.sh        # future
├── rpi_app/                       # future
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── udp_listener.py
│   └── display_stub.py
└── systemd/                       # future
    ├── robot-game-left.service
    └── robot-game-right.service
```

### D. Minimal runtime application plan

The first runtime application should be deliberately small.

Initial command shape:

```bash
python3 -m rpi_app.main --role left --display 0
python3 -m rpi_app.main --role right --display 1
```

Each process should:

- read `/etc/rpi-node.conf`
- know its role: `left` or `right`
- know its intended Pygame display index: `0` or `1`
- bind to UDP `0.0.0.0:49200`
- keep listening forever
- print received packets to stdout or logs
- later filter packets by role/player ID
- later draw status information with Pygame

Socket behavior to test:

- Multiple Pis should all receive UDP broadcast packets sent to `192.168.0.255:49200`.
- Two local processes on the same Pi may need `SO_REUSEADDR` and/or `SO_REUSEPORT` to bind to the same UDP port.
- It must be tested whether both local processes receive each broadcast packet reliably on Raspberry Pi OS.
- If only one process receives the packet, use a fallback architecture: one local receiver process listens on UDP `49200` and forwards messages to the two display processes over localhost or another local IPC method.

### E. UDP broadcaster test from host computer

A minimal host-side test sender can later send packets to:

```text
192.168.0.255:49200
```

The Pi-side listener should bind to:

```text
0.0.0.0:49200
```

The listener should not assume that the broadcaster is always running.

### F. Pygame display testing plan

Before writing real dashboard graphics, create a minimal Pygame test that:

1. prints `pygame.display.get_num_displays()`
2. prints `pygame.display.get_desktop_sizes()`
3. opens a fullscreen color window on display `0`
4. opens a fullscreen color window on display `1`
5. records which physical screen corresponds to each Pygame display index

Known OS display state on the first tested Pi:

```text
HDMI-A-1 at x=0,   480x1920
HDMI-A-2 at x=480, 480x1920
```

The unresolved mapping is:

```text
Pygame display 0 -> physical display ?
Pygame display 1 -> physical display ?
```

### G. systemd service plan

Eventually each Pi should run two services:

```text
robot-game-left.service
robot-game-right.service
```

Conceptual commands:

```bash
python3 -m rpi_app.main --role left --display 0
python3 -m rpi_app.main --role right --display 1
```

The service files should:

- start after the graphical session is available, if Pygame requires it
- restart automatically after crashes
- log to `journalctl`
- use the normal Pi user rather than root

The first systemd milestone should be simple:

```bash
systemctl status robot-game-left.service
systemctl status robot-game-right.service
journalctl -u robot-game-left.service -f
journalctl -u robot-game-right.service -f
```

### H. Development milestones

1. **Provisioning validation**
   - confirm `rpi5-11` can be reflashed, provisioned, SSHed into, and can use `sudo`

2. **UDP listener without Pygame**
   - run one listener process manually
   - send UDP broadcast from host
   - confirm packet reception

3. **Two listeners on the same Pi**
   - run two listener processes manually
   - both bind to `0.0.0.0:49200`
   - test whether both receive every broadcast packet

4. **Minimal Pygame display test**
   - confirm display count and desktop sizes
   - map display index `0` and `1` to physical screens

5. **Combined minimal app**
   - each process listens for UDP packets
   - each process opens its assigned display
   - each process displays basic text/status only

6. **systemd service setup**
   - install files to the Pi
   - enable two services
   - reboot and confirm both services auto-start

7. **Scale to all six Pis**
   - repeat provisioning
   - deploy same runtime code
   - verify unique IP/hostname/device identity
   - verify all Pis receive broadcast packets
