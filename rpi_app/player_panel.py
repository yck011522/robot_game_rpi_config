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
from typing import Any

import pygame


PROTOCOL_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a portrait player panel on a selected display.")
    parser.add_argument("--display", type=int, default=0, help="Pygame display index.")
    parser.add_argument("--role", default="left", help="Role label for diagnostics (left/right).")
    parser.add_argument("--team", default="A", help="Team label to render, e.g. A or B.")
    parser.add_argument("--joint", type=int, default=1, help="Joint number to render.")
    parser.add_argument("--bind", default="0.0.0.0", help="UDP bind address.")
    parser.add_argument("--port", type=int, default=49200, help="UDP port.")
    parser.add_argument("--fps", type=int, default=30, help="Render FPS cap.")
    return parser.parse_args()


def mmss(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    m, s = divmod(total_seconds, 60)
    return f"{m:02d}:{s:02d}"


def read_latest(sock: socket.socket) -> dict[str, Any] | None:
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


def extract_panel_fields(packet: dict[str, Any], fallback_state: str, fallback_timer: int) -> tuple[str, int]:
    """Extract display fields from protocol-v1 envelope or legacy flat payload."""

    # Preferred schema: protocol envelope + nested state body.
    if (
        packet.get("v") == PROTOCOL_VERSION
        and type(packet.get("seq")) is int
        and type(packet.get("ts_wall_ns")) is int
        and isinstance(packet.get("state"), dict)
    ):
        state_body = packet["state"]
        stage_raw = state_body.get("stage") or state_body.get("active_stage") or fallback_state
        stage = str(stage_raw)
        timer_raw = state_body.get("countdown_s", fallback_timer)
        timer = int(timer_raw) if isinstance(timer_raw, (int, float)) else fallback_timer
        return stage, timer

    # Temporary migration fallback: older dummy sender schema.
    stage = str(packet.get("game_state", fallback_state))
    timer_raw = packet.get("timer_s", fallback_timer)
    timer = int(timer_raw) if isinstance(timer_raw, (int, float)) else fallback_timer
    return stage, timer


def main() -> None:
    args = parse_args()

    pygame.init()
    pygame.font.init()

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, display=args.display)
    pygame.display.set_caption(f"Player Panel {args.role}")
    width, height = screen.get_size()

    # Tuned for portrait displays around 480x1920 while still scaling on others.
    title_font = pygame.font.Font(None, max(54, int(height * 0.046)))
    state_font = pygame.font.Font(None, max(86, int(height * 0.08)))
    timer_font = pygame.font.Font(None, max(168, int(height * 0.145)))
    meta_font = pygame.font.Font(None, max(38, int(height * 0.028)))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
    sock.bind((args.bind, args.port))
    sock.setblocking(False)

    game_state = "daydreaming"
    timer_s = 0
    last_rx = 0.0
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
            game_state, timer_s = extract_panel_fields(packet, game_state, timer_s)
            last_rx = time.monotonic()

        stale = (time.monotonic() - last_rx) > 1.5 if last_rx else True

        bg = pygame.Color("#081220")
        card = pygame.Color("#10253f")
        accent = pygame.Color("#28f0b4")
        text = pygame.Color("#ebf5ff")
        warning = pygame.Color("#ffc857")

        screen.fill(bg)

        margin = max(20, int(width * 0.04))
        section_gap = max(20, int(height * 0.02))
        section_h = (height - margin * 2 - section_gap * 2) // 3

        top_rect = pygame.Rect(margin, margin, width - 2 * margin, section_h)
        mid_rect = pygame.Rect(margin, top_rect.bottom + section_gap, width - 2 * margin, section_h)
        bot_rect = pygame.Rect(margin, mid_rect.bottom + section_gap, width - 2 * margin, section_h)

        for rect in (top_rect, mid_rect, bot_rect):
            pygame.draw.rect(screen, card, rect, border_radius=26)

        pygame.draw.line(screen, accent, (top_rect.left + 24, top_rect.top + 24), (top_rect.right - 24, top_rect.top + 24), 6)

        top_title = title_font.render("PLAYER", True, accent)
        top_body = state_font.render(f"TEAM {args.team} / JOINT {args.joint}", True, text)
        screen.blit(top_title, (top_rect.left + 24, top_rect.top + 42))
        screen.blit(top_body, (top_rect.left + 24, top_rect.top + 120))

        mid_title = title_font.render("GAME STATE", True, accent)
        mid_state = state_font.render(game_state.upper(), True, text)
        screen.blit(mid_title, (mid_rect.left + 24, mid_rect.top + 42))
        screen.blit(mid_state, (mid_rect.left + 24, mid_rect.top + 120))

        bot_title = title_font.render("TIMER", True, accent)
        bot_timer = timer_font.render(mmss(timer_s), True, text)
        rx_text = "UDP: WAITING" if stale else "UDP: LIVE"
        rx_color = warning if stale else accent
        rx_surface = meta_font.render(rx_text, True, rx_color)

        timer_x = bot_rect.left + (bot_rect.width - bot_timer.get_width()) // 2
        screen.blit(bot_title, (bot_rect.left + 24, bot_rect.top + 42))
        screen.blit(bot_timer, (timer_x, bot_rect.top + 130))
        screen.blit(rx_surface, (bot_rect.left + 24, bot_rect.bottom - 70))

        pygame.display.flip()
        clock.tick(max(1, args.fps))

    sock.close()
    pygame.quit()


if __name__ == "__main__":
    main()
