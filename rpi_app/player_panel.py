#!/usr/bin/env python3
"""Portrait (480x1920) pygame UI that renders minimal player state from UDP.

Preferred input is Display Broadcast Protocol v1:
    {"v": 1, "seq": <int>, "ts_wall_ns": <int>, "state": {...}}

During migration this receiver also accepts the old flat payload format.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from typing import Any, Literal

import pygame

import draw
from canvas_elements import Context


PROTOCOL_VERSION = 1
PI_PANEL_SIZE = (480, 1920)  # Native portrait panel size used by each Raspberry Pi display.
WINDOW_MODE = Literal["auto", "fullscreen", "windowed"]


def parse_args() -> argparse.Namespace:
    """Parse command-line options that select the display, UDP socket, and panel labels."""

    parser = argparse.ArgumentParser(description="Run a portrait player panel on a selected display.")
    parser.add_argument("--display", type=int, default=0, help="Pygame display index.")
    parser.add_argument(
        "--window-mode",
        choices=("auto", "fullscreen", "windowed"),
        default="auto",
        help="Use fullscreen on the Pi panel in auto mode; otherwise open a 480x1920 window.",
    )
    parser.add_argument("--role", default="left", help="Role label for diagnostics (left/right).")
    parser.add_argument("--team", default="A", help="Team label to render, e.g. A or B.")
    parser.add_argument("--joint", type=int, default=1, help="Joint number to render.")
    parser.add_argument("--bind", default="0.0.0.0", help="UDP bind address.")
    parser.add_argument("--port", type=int, default=49200, help="UDP port.")
    parser.add_argument("--fps", type=int, default=30, help="Render FPS cap.")
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


def main() -> None:
    """Run the Pygame event loop, read UDP state, and redraw the player panel."""

    args = parse_args()

    pygame.init()
    pygame.font.init()

    window_size, window_flags, mode_label, desktop_size = choose_window_settings(args.display, args.window_mode)
    print(f"display={args.display} desktop={desktop_size} mode={mode_label} window={window_size}", flush=True)

    screen = pygame.display.set_mode(window_size, window_flags, display=args.display)
    pygame.display.set_caption(f"Player Panel {args.role}")
    _width, height = screen.get_size()

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

    team = (str(args.team).strip().lower() or "a")[:1]
    index = max(0, args.joint - 1)
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
            values={"fps": clock.get_fps()},
        )

        draw.render(screen, fonts, context)
        pygame.display.flip()
        clock.tick(max(1, args.fps))

    sock.close()
    pygame.quit()


if __name__ == "__main__":
    main()
