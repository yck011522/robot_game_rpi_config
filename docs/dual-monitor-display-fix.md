# Dual-Monitor Panel Placement — Problem & Fix

> Why some Raspberry Pi units showed both player panels on the **same** monitor
> (or one monitor blank) when started as systemd user services, and how we
> fixed it. Keep this — it took a long time to diagnose and the symptoms are
> misleading.

## Hardware / software context

- Each Pi (Raspberry Pi OS **Bookworm**, user `pi`) drives **two** 480×1920
  portrait HDMI monitors — one per player.
- The two monitors have **identical EDID** (`___ ZeroMOD`, serial
  `0x00000645`). This matters: they are indistinguishable by name/serial.
- Compositor is **labwc 0.9.7** (wlroots / Wayland), session `rpd-labwc`,
  `WAYLAND_DISPLAY=wayland-0`.
- App: `rpi_app/player_panel.py` on **pygame 2.6.1 / SDL 2.32.4 / Python 3.13**.
- Each Pi runs two systemd **user** services: `robot-game-left.service` and
  `robot-game-right.service` (installed by `scripts/configure_auto_start.py`).
- Connector convention: **player 1 → `HDMI-A-1`**, **player 2 → `HDMI-A-2`**.

## Symptoms

- Run the panels manually from an SSH login shell → both monitors correct.
- Run the panels via the systemd user services (or at boot) → **both panels
  land on `HDMI-A-1`**; the second monitor is blank, or only one panel is
  visible.
- Alt/Ctrl+Tab between the two fullscreen windows made one of them vanish.
- Behaviour was inconsistent across reboots and across devices (2 of 6 failed).

## Root causes — there were **three** stacked bugs

All three had to be fixed; fixing only one or two still left failures.

### 1. SDL minimizes a fullscreen window on focus loss

By default SDL sets `SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=1`. With two fullscreen
panels, whichever loses keyboard focus (e.g. on Alt/Ctrl+Tab, or simply at
boot when the second window grabs focus) gets **minimized** — so it looks like
"only one panel started".

**Fix:** force `SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0`.

### 2. (THE decisive one) systemd user services inherit `DISPLAY=:0` → XWayland

The systemd **user manager** holds `DISPLAY=:0` in its activation environment
(`systemctl --user show-environment`). Any service it starts inherits it.
When `DISPLAY` is set, **SDL picks the `x11` (XWayland) backend instead of
native Wayland**. Under XWayland the two monitors are presented as a single
combined X root, so per-output fullscreen **collapses both panels onto
`HDMI-A-1`**.

A login-shell SSH launch (PPID 1, `XDG_SESSION_TYPE=tty`) has **no `DISPLAY`**,
so SDL used native Wayland and placed the panels correctly — which is why
manual launches "worked" and the service didn't.

**Proof:**

```text
# native Wayland (DISPLAY unset)
video_driver: wayland
display names: '___ ZeroMOD 0x00000645 (HDMI-A-1)', '... (HDMI-A-2)'

# with DISPLAY=:0
video_driver: x11
display names: 'HDMI-A-1 7"', 'HDMI-A-2 7"'
```

**Fix:** force the native backend regardless of inherited `DISPLAY` with
`SDL_VIDEODRIVER=wayland`.

### 3. Display index ↔ connector ordering is unstable across processes/boots

With two **identical-EDID** monitors, each pygame process enumerates displays
independently and the numeric display index → physical connector mapping can
differ between processes and between boots. So even "display 0 / display 1"
could put the wrong panel on the wrong monitor.

**Fix:** select the target display by **physical connector name** rather than by
index. `player_panel.py` takes `--output HDMI-A-1` / `--output HDMI-A-2` and
matches it (case-insensitive substring) against the per-display
`SDL_GetDisplayName` strings (read via `ctypes`, since pygame exposes no API for
this). The connector token (`HDMI-A-1`) appears in the SDL name under **both**
the Wayland and X11 backends, so the match is robust either way. The numeric
`--display` is kept only as a fallback.

### Bonus: boot-time topology race

At cold boot the panels can start before the compositor has brought up **both**
outputs. `player_panel.py` therefore accepts `--require-outputs HDMI-A-1,HDMI-A-2`
and waits (re-scanning the display subsystem each poll) until all required
connectors are present **and stable** before opening its window.

## What changed in the code

### `rpi_app/player_panel.py`

- `os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")` before
  `pygame.init()`.
- New args: `--output` (connector to target), `--require-outputs`
  (comma-separated connectors that must all be present), `--ready-timeout`.
- `_sdl_display_names()` — reads per-display names via `ctypes` + `libSDL2`.
- `resolve_display_index(output, fallback)` — connector-name → index, with
  numeric fallback.
- `wait_for_outputs(...)` — waits for the required connectors to appear/settle.

### `scripts/configure_auto_start.py` (systemd unit generation)

Each unit now includes:

```ini
[Service]
Environment=WAYLAND_DISPLAY=wayland-0
Environment=SDL_VIDEODRIVER=wayland
Environment=SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0
ExecStart=<python3> rpi_app/player_panel.py \
    --role <left|right> --output <HDMI-A-1|HDMI-A-2> \
    --require-outputs HDMI-A-1,HDMI-A-2 --display <0|1>
Restart=always
RestartSec=2
```

### `scripts/rpi_remote_common.py`

- `ROLE_OUTPUT = {"left": "HDMI-A-1", "right": "HDMI-A-2"}` — role → connector.
- `ROLE_DISPLAY = {"left": 0, "right": 1}` — role → fallback index.

## How to roll out / re-apply

```powershell
# 1. push the updated app code to every device
python scripts\deploy_app.py --devices 1-6

# 2. (re)install the systemd units with the corrected ExecStart + env
python scripts\configure_auto_start.py --devices 1-6
```

`deploy_app.py` only uploads code and restarts services; it does **not** rewrite
units. `configure_auto_start.py` rewrites the unit files. After a fresh change to
the unit template you must run **both**.

## Verifying a device

- `scripts/start_remote_process.py` / `stop_remote_process.py` launch the panels
  **directly over SSH (no systemd)** — handy for A/B comparison against the
  service path.
- Confirm the backend on a running panel: its process environment should contain
  `SDL_VIDEODRIVER=wayland`. A quick check is forcing the opposite and observing
  the driver:

  ```bash
  DISPLAY=:0 python3 -c "import pygame; pygame.init(); print(pygame.display.get_driver())"  # -> x11
  unset DISPLAY; python3 -c "import pygame; pygame.init(); print(pygame.display.get_driver())"  # -> wayland
  ```

- **Reboot** at least one device and confirm both monitors come up correctly —
  the cold-boot path is where all three bugs surfaced together.

## Caveats / future work

- The role → connector mapping is fixed (`left=HDMI-A-1`, `right=HDMI-A-2`). If a
  device is **cabled the opposite way** (player-1 monitor on the second HDMI
  port) its panels will appear swapped. The fix is not recabling but making
  `ROLE_OUTPUT` overridable per device (e.g. an extra column in
  `rpi_app/devices.csv`) — not yet implemented.
- User-service stdout is **not** persisted (`journalctl --user` reports "No
  journal files"). Use `systemctl --user status` (shows the last lines while the
  service runs) or redirect to a log file for debugging.
