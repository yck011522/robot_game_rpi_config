#!/usr/bin/env python3
"""Per-state rendering for the player panel.

``player_panel.py`` owns the window and the UDP feed; this module owns every
pixel. ``render`` clears the screen, dispatches on the lifecycle stage to one
function per state, then draws the diagnostics overlay on top.

Each state function currently draws a centered placeholder label so the whole
pipeline can be validated before the real scenes are designed. The functions are
deliberately separate so that changing one state never affects another.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from canvas_elements import Context, ImageElement, TextElement, lerp


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONT_PATH = ASSETS_DIR / "font" / "Roboto-VariableFont_wdth,wght.ttf"

BACKGROUND = pygame.Color("#081220")
BLACK = pygame.Color("#000000")
PLACEHOLDER_COLOR = pygame.Color("#ebf5ff")
OVERLAY_COLOR = pygame.Color("#9fb3c8")
OVERLAY_FRESH = pygame.Color("#28f0b4")
OVERLAY_STALE = pygame.Color("#ffc857")
OVERLAY_ALPHA = 180

# Daydreaming-state assets and layout (top-left anchored coordinates).
BEGIN_TEXT_IMAGE = ASSETS_DIR / "BeginText.png"
SCROLL_ARROW_IMAGE = ASSETS_DIR / "ScrollArrow.png"
BEGIN_TEXT_POS = (103, 677)
SCROLL_ARROW_X = 26
SCROLL_ARROW_Y_REST = 830
SCROLL_ARROW_Y_END = 772


@dataclass
class Fonts:
    """Bundled font instances sized relative to the panel height."""

    placeholder: pygame.font.Font
    overlay: pygame.font.Font


def load_fonts(height: int) -> Fonts:
    """Load the bundled Roboto font at sizes scaled to the panel height."""

    placeholder_size = max(48, int(height * 0.05))
    overlay_size = max(18, int(height * 0.014))
    try:
        placeholder = pygame.font.Font(str(FONT_PATH), placeholder_size)
        overlay = pygame.font.Font(str(FONT_PATH), overlay_size)
    except FileNotFoundError:
        placeholder = pygame.font.Font(None, placeholder_size)
        overlay = pygame.font.Font(None, overlay_size)
    return Fonts(placeholder=placeholder, overlay=overlay)


def _draw_placeholder(surface: pygame.Surface, fonts: Fonts, context: Context, label: str) -> None:
    """Draw a single centered label; shared scaffolding for the placeholder states."""

    width, height = surface.get_size()
    element = TextElement(
        label,
        width / 2,
        height / 2,
        fonts.placeholder,
        color=PLACEHOLDER_COLOR,
        align="center",
        valign="center",
    )
    element.draw(surface, context)


def draw_daydreaming(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Attract / screensaver state: white art on black, with a bobbing scroll hint."""

    surface.fill(BLACK)
    ImageElement(BEGIN_TEXT_IMAGE, *BEGIN_TEXT_POS).draw(surface, context)
    ImageElement(SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y).draw(surface, context)


def _scroll_arrow_y(context: Context) -> float:
    """Animate the scroll arrow's Y from local app time: move, pause, repeat.

    Driven only by ``context.elapsed_s`` (not by game state). Each cycle slides
    from the rest position to the end position over ``MOVE_S`` seconds, then holds
    there for the rest of ``CYCLE_S`` before snapping back and repeating. Swap the
    two Y constants above to flip the travel direction. The fraction is linear;
    wrap it in an easing function (see the hint in the chat) to soften the ends.
    """

    cycle_s = 1.6
    move_s = 1.0
    phase = context.elapsed_s % cycle_s
    if phase >= move_s:
        return SCROLL_ARROW_Y_END
    fraction = phase / move_s
    return lerp(SCROLL_ARROW_Y_REST, SCROLL_ARROW_Y_END, fraction)


def draw_idle(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Waiting-for-player state."""

    _draw_placeholder(surface, fonts, context, "IDLE")


def draw_tutorial(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Interactive tutorial state."""

    _draw_placeholder(surface, fonts, context, "TUTORIAL")


def draw_play(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Timed gameplay state."""

    _draw_placeholder(surface, fonts, context, "PLAY")


def draw_reset(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Robot rewind / return state."""

    _draw_placeholder(surface, fonts, context, "RESET")


def draw_conclusion(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Bucket counting and final-score presentation state."""

    _draw_placeholder(surface, fonts, context, "CONCLUSION")


_STATE_DRAW = {
    "daydreaming": draw_daydreaming,
    "idle": draw_idle,
    "tutorial": draw_tutorial,
    "play": draw_play,
    "reset": draw_reset,
    "conclusion": draw_conclusion,
}


def render(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Clear the surface, draw the current state, then draw the debug overlay."""

    surface.fill(BACKGROUND)
    draw_state = _STATE_DRAW.get(context.active_stage(), draw_daydreaming)
    draw_state(surface, fonts, context)
    draw_debug_overlay(surface, fonts, context)


def _format_deg(value: float | None) -> str:
    """Format an angle in degrees, or ``n/a`` when missing."""

    return "n/a" if value is None else f"{value:7.1f} deg"


def _format_timer(value: int | None) -> str:
    """Format a countdown in seconds, or ``n/a`` when missing."""

    return "n/a" if value is None else f"{value} s"


def draw_debug_overlay(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Print diagnostics in the top-left corner on top of the rendered state."""

    player_no = context.index + 1
    lines = [
        (f"Team {context.team.upper()} player {player_no}", OVERLAY_COLOR),
        (f"state: {context.active_stage() or '-'}", OVERLAY_COLOR),
        (
            f"udp: {'fresh' if context.fresh else 'stale'}",
            OVERLAY_FRESH if context.fresh else OVERLAY_STALE,
        ),
        (f"dial: {_format_deg(context.dial_deg())}", OVERLAY_COLOR),
        (f"robot axis {player_no}: {_format_deg(context.robot_deg())}", OVERLAY_COLOR),
        (f"timer: {_format_timer(context.countdown_s())}", OVERLAY_COLOR),
        (f"fps: {context.values.get('fps', 0.0):.0f}", OVERLAY_COLOR),
    ]

    x = 12
    y = 12
    line_height = fonts.overlay.get_linesize()
    for text, color in lines:
        glyphs = fonts.overlay.render(text, True, color)
        glyphs.set_alpha(OVERLAY_ALPHA)
        surface.blit(glyphs, (x, y))
        y += line_height
