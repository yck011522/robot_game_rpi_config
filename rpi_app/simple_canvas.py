#!/usr/bin/env python3
"""Minimal full-screen pygame canvas for Raspberry Pi display bring-up tests."""

from __future__ import annotations

import argparse
import socket
import time

import pygame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a full-screen pygame window on a selected display.")
    parser.add_argument("--role", default="left", help="Logical role label, e.g. left/right.")
    parser.add_argument("--display", type=int, default=0, help="Pygame display index.")
    parser.add_argument("--title", default="Robot Game Canvas Test", help="Window title and label text.")
    parser.add_argument("--bg", default="#0b172a", help="Background color hex (e.g. #0b172a).")
    parser.add_argument("--fg", default="#d6f5ff", help="Text color hex (e.g. #d6f5ff).")
    parser.add_argument("--fps", type=int, default=30, help="Render FPS cap.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pygame.init()
    pygame.font.init()

    desktop_sizes = pygame.display.get_desktop_sizes()
    display_count = pygame.display.get_num_displays()

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, display=args.display)
    pygame.display.set_caption(args.title)

    headline = pygame.font.Font(None, 82)
    body = pygame.font.Font(None, 48)
    clock = pygame.time.Clock()

    host = socket.gethostname()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        screen.fill(pygame.Color(args.bg))

        lines = [
            args.title,
            f"role: {args.role}",
            f"display index: {args.display}",
            f"detected displays: {display_count}",
            f"desktop sizes: {desktop_sizes}",
            f"hostname: {host}",
            f"started: {started}",
            "press ESC to quit",
        ]

        y = 90
        for i, line in enumerate(lines):
            font = headline if i == 0 else body
            surface = font.render(line, True, pygame.Color(args.fg))
            screen.blit(surface, (40, y))
            y += 90 if i == 0 else 56

        pygame.display.flip()
        clock.tick(max(1, args.fps))

    pygame.quit()


if __name__ == "__main__":
    main()
