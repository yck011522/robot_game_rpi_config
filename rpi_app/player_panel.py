#!/usr/bin/env python3
"""Portrait (480x1920) pygame UI that renders minimal player state from UDP.

Preferred input is Display Broadcast Protocol v1:
    {"v": 1, "seq": <int>, "ts_wall_ns": <int>, "state": {...}}

During migration this receiver also accepts the old flat payload format.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Literal

import pygame

import draw
from canvas_elements import Context


PROTOCOL_VERSION = 1
PI_PANEL_SIZE = (480, 1920)  # Native portrait panel size used by each Raspberry Pi display.
CURSOR_HIDE_DELAY_S = 3.0  # Hide the mouse pointer after this many seconds without movement.
WINDOW_MODE = Literal["auto", "fullscreen", "windowed"]
DEVICES_CSV = Path(__file__).resolve().parent / "devices.csv"  # Deployed alongside the app.


def parse_args() -> argparse.Namespace:
    """Parse command-line options that select the display, UDP socket, and panel labels."""

    parser = argparse.ArgumentParser(description="Run a portrait player panel on a selected display.")
    parser.add_argument("--display", type=int, default=0, help="Pygame display index (fallback when --output is unset/unmatched).")
    parser.add_argument(
        "--output",
        default=None,
        help="Physical connector to render on, e.g. HDMI-A-1. Selected via SDL display name; "
        "stable across reboots regardless of pygame display-index ordering.",
    )
    parser.add_argument(
        "--require-outputs",
        default=None,
        help="Comma-separated connector names (e.g. HDMI-A-1,HDMI-A-2) that must all be present "
        "before opening the window. Prevents the boot-time race where panels launch before the "
        "compositor has brought up every output.",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=90.0,
        help="Max seconds to wait for --require-outputs before proceeding anyway.",
    )
    parser.add_argument(
        "--window-mode",
        choices=("auto", "fullscreen", "windowed"),
        default="auto",
        help="Use fullscreen on the Pi panel in auto mode; otherwise open a 480x1920 window.",
    )
    parser.add_argument("--role", default="left", help="Which panel this process drives (left/right).")
    parser.add_argument(
        "--team",
        default=None,
        help="Team to render (A/B). Defaults to the hostname-mapped team; set to override in development.",
    )
    parser.add_argument(
        "--joint",
        type=int,
        default=None,
        help="Joint number to render. Defaults to the hostname-mapped joint; set to override in development.",
    )
    parser.add_argument("--bind", default="0.0.0.0", help="UDP bind address.")
    parser.add_argument("--port", type=int, default=49200, help="UDP port.")
    parser.add_argument("--fps", type=int, default=60, help="Render FPS cap.")
    parser.add_argument(
        "--debug-overlay",
        action="store_true",
        help="Show the diagnostics text overlay above every other panel layer.",
    )
    return parser.parse_args()


def read_latest(sock: socket.socket) -> dict[str, Any] | None:
    """Drain all waiting UDP packets and return the newest valid JSON object."""

    latest: dict[str, Any] | None = None
    while True:
        try:
            raw, _ = sock.recvfrom(65536)
        except BlockingIOError:
            break
        except OSError:
            break

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

        if isinstance(payload, dict):
            latest = payload

    return latest


def _sdl_display_names() -> list[str]:
    """Return SDL's per-display name strings (which embed the connector name).

    Uses ctypes against the already-loaded SDL2 library, since pygame does not
    expose ``SDL_GetDisplayName``. On platforms/builds where SDL2 cannot be
    loaded (e.g. a Windows dev box), an empty list is returned so callers fall
    back to the numeric display index.
    """

    import ctypes

    sdl = None
    for lib in ("libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so", "SDL2.dll"):
        try:
            sdl = ctypes.CDLL(lib)
            break
        except OSError:
            continue
    if sdl is None:
        return []

    sdl.SDL_GetDisplayName.restype = ctypes.c_char_p
    names: list[str] = []
    for i in range(sdl.SDL_GetNumVideoDisplays()):
        raw = sdl.SDL_GetDisplayName(i)
        names.append(raw.decode() if isinstance(raw, bytes) else (raw or ""))
    return names


def resolve_display_index(output: str | None, fallback: int) -> int:
    """Map a physical connector name (e.g. ``HDMI-A-1``) to a pygame display index.

    SDL reports names like ``'___ ZeroMOD 0x645 (HDMI-A-1)'``; we match ``output``
    case-insensitively against those. This keeps selection tied to the physical
    HDMI port rather than SDL's index ordering, which can differ between boots
    when both panels share an identical EDID. Falls back to ``fallback`` when no
    output is requested or no name matches.
    """

    if not output:
        return fallback

    names = _sdl_display_names()
    target = output.strip().lower()
    for index, name in enumerate(names):
        if target in name.lower():
            return index

    print(f"output {output!r} not found in {names}; falling back to display {fallback}", flush=True)
    return fallback


def wait_for_outputs(required: list[str], timeout_s: float, settle_s: float = 2.0, poll_s: float = 1.0) -> None:
    """Block until every connector in ``required`` is present and stable.

    At cold boot the panels can launch before the Wayland compositor has brought
    up both outputs; creating fullscreen surfaces during that window lets SDL
    assign them to the wrong monitor. Waiting until the full display topology is
    present (and still present after a short settle) reproduces the stable
    desktop state under which placement is reliable.

    The video subsystem is re-initialised each poll so SDL re-scans outputs
    rather than reusing a stale display list. On timeout we return anyway and let
    selection fall back to the numeric index.
    """

    if not required:
        return

    def all_present() -> bool:
        names = _sdl_display_names()
        return all(any(req.lower() in name.lower() for name in names) for req in required)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pygame.display.quit()
        pygame.display.init()
        if all_present():
            time.sleep(settle_s)
            pygame.display.quit()
            pygame.display.init()
            if all_present():
                print(f"outputs ready: {required}", flush=True)
                return
        time.sleep(poll_s)

    print(f"timed out waiting for outputs {required}; proceeding with current displays", flush=True)


def choose_window_settings(
    display: int,
    window_mode: WINDOW_MODE,
) -> tuple[tuple[int, int], int, str, tuple[int, int]]:
    """Choose Pygame window size and flags for Raspberry Pi or development screens.

    In auto mode, a selected desktop that is exactly 480x1920 is treated as the
    Raspberry Pi panel and opened fullscreen. Any other desktop is treated as a
    development machine and opened as a normal 480x1920 window.
    """

    desktop_sizes = pygame.display.get_desktop_sizes()
    if display < 0 or display >= len(desktop_sizes):
        raise ValueError(f"display index {display} is not available; detected displays: {desktop_sizes}")

    desktop_size = desktop_sizes[display]  # Physical desktop size reported by Pygame for the selected display.
    use_fullscreen = window_mode == "fullscreen" or (window_mode == "auto" and desktop_size == PI_PANEL_SIZE)

    if use_fullscreen:
        return (0, 0), pygame.FULLSCREEN, "fullscreen", desktop_size

    return PI_PANEL_SIZE, 0, "windowed", desktop_size


def extract_state(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``state.full`` body from a protocol-v1 envelope, or ``None``.

    A legacy flat payload (``game_state`` / ``timer_s``) is wrapped into a
    minimal state body so older senders still drive the display during migration.
    """

    # Preferred schema: protocol envelope + nested state body.
    if (
        packet.get("v") == PROTOCOL_VERSION
        and type(packet.get("seq")) is int
        and type(packet.get("ts_wall_ns")) is int
        and isinstance(packet.get("state"), dict)
    ):
        return packet["state"]

    # Temporary migration fallback: older dummy sender schema.
    if "game_state" in packet or "timer_s" in packet:
        stage = str(packet.get("game_state", "daydreaming"))
        timer_raw = packet.get("timer_s", 0)
        timer = int(timer_raw) if isinstance(timer_raw, (int, float)) else 0
        return {"stage": stage, "active_stage": stage, "countdown_s": timer}

    return None


def load_panel_map() -> dict[str, dict[str, str]]:
    """Read the hostname -> left/right panel table deployed next to the app.

    Returns an empty map when ``devices.csv`` is missing, so a development
    machine simply falls back to defaults or explicit CLI overrides.
    """

    mapping: dict[str, dict[str, str]] = {}
    if not DEVICES_CSV.exists():
        return mapping
    with DEVICES_CSV.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            host = (row.get("hostname") or "").strip().lower()
            if host:
                mapping[host] = {
                    "left": (row.get("left_panel") or "").strip(),
                    "right": (row.get("right_panel") or "").strip(),
                }
    return mapping


def parse_panel(panel: str) -> tuple[str, int] | None:
    """Split a panel label such as ``a1`` into ``("a", 1)``, or ``None``."""

    panel = panel.strip().lower()
    if len(panel) < 2 or not panel[1:].isdigit():
        return None
    return panel[0], int(panel[1:])


def detect_panel(role: str) -> tuple[str, int] | None:
    """Resolve this Pi's ``(team, joint)`` for ``role`` from its own hostname.

    The OS hostname (case-insensitive, domain stripped) is matched against
    ``devices.csv``; ``role`` selects the left or right panel column. Returns
    ``None`` when the host is unknown or its panel label is malformed.
    """

    try:
        host = socket.gethostname().split(".")[0].strip().lower()
    except OSError:
        return None
    entry = load_panel_map().get(host)
    if entry is None:
        return None
    panel = entry.get("right" if role == "right" else "left", "")
    return parse_panel(panel) if panel else None


def resolve_identity(role: str, team_arg: str | None, joint_arg: int | None) -> tuple[str, int]:
    """Combine hostname auto-detection with optional CLI overrides.

    Auto-detection from the hostname provides the production defaults; an
    explicitly supplied ``--team`` or ``--joint`` overrides the matching field
    for development. Anything still unresolved falls back to team ``a`` joint 1.
    """

    detected = detect_panel(role)
    det_team, det_joint = detected if detected else (None, None)

    team = team_arg if team_arg is not None else det_team
    joint = joint_arg if joint_arg is not None else det_joint

    team_char = (str(team).strip().lower() or "a")[:1] if team is not None else "a"
    joint_num = max(1, int(joint)) if joint is not None else 1
    return team_char, joint_num


def main() -> None:

    """Run the Pygame event loop, read UDP state, and redraw the player panel."""

    args = parse_args()

    # SDL minimizes a fullscreen window when it loses keyboard focus by default.
    # On this dual-panel setup that hides the unfocused panel (and at boot leaves
    # only the panel that won focus visible), so keep both surfaces mapped.
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")

    pygame.init()
    pygame.font.init()

    required_outputs = [token.strip() for token in (args.require_outputs or "").split(",") if token.strip()]
    wait_for_outputs(required_outputs, timeout_s=args.ready_timeout)

    display_idx = resolve_display_index(args.output, args.display)
    window_size, window_flags, mode_label, desktop_size = choose_window_settings(display_idx, args.window_mode)
    print(
        f"display={display_idx} output={args.output} desktop={desktop_size} mode={mode_label} window={window_size}",
        flush=True,
    )

    screen = pygame.display.set_mode(window_size, window_flags, display=display_idx)
    pygame.display.set_caption(f"Player Panel {args.role}")
    _width, height = screen.get_size()

    # Kiosk display: keep the pointer off the panel. Start hidden, then reveal it
    # briefly whenever the mouse moves and hide again once it has been idle.
    pygame.mouse.set_visible(False)
    cursor_visible = False
    last_pointer_move = 0.0

    fonts = draw.load_fonts(height)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    reuse_port = getattr(socket, "SO_REUSEPORT", None)  # Optional Linux socket flag that lets Pi processes share one UDP port.
    if reuse_port is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, reuse_port, 1)
        except OSError:
            pass
    sock.bind((args.bind, args.port))
    sock.setblocking(False)

    team, joint = resolve_identity(args.role, args.team, args.joint)
    index = max(0, joint - 1)
    print(f"role={args.role} team={team} joint={joint} index={index}", flush=True)
    state_body: dict[str, Any] | None = None
    last_rx = 0.0
    start_mono = time.monotonic()
    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEMOTION:
                last_pointer_move = time.monotonic()
                if not cursor_visible:
                    pygame.mouse.set_visible(True)
                    cursor_visible = True

        if cursor_visible and (time.monotonic() - last_pointer_move) > CURSOR_HIDE_DELAY_S:
            pygame.mouse.set_visible(False)
            cursor_visible = False

        packet = read_latest(sock)
        if packet is not None:
            new_state = extract_state(packet)
            if new_state is not None:
                state_body = new_state
                last_rx = time.monotonic()

        fresh = (time.monotonic() - last_rx) <= 1.5 if last_rx else False

        context = Context(
            state=state_body,
            team=team,
            index=index,
            fresh=fresh,
            elapsed_s=time.monotonic() - start_mono,
            values={
                "debug_overlay": args.debug_overlay,  # Enables the topmost diagnostics text when requested.
                "fps": clock.get_fps(),  # Last measured render rate, shown only by the diagnostics overlay.
            },
        )

        draw.render(screen, fonts, context)
        pygame.display.flip()
        clock.tick(max(1, args.fps))

    sock.close()
    pygame.quit()


if __name__ == "__main__":
    main()
