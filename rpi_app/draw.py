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

from canvas_elements import Context, ImageElement, TextElement, format_signed, lerp, remap


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONT_PATH = ASSETS_DIR / "font" / "Roboto-VariableFont_wdth,wght.ttf"

BACKGROUND = pygame.Color("#081220")
BLACK = pygame.Color("#000000")
PLACEHOLDER_COLOR = pygame.Color("#ebf5ff")
OVERLAY_COLOR = pygame.Color("#9fb3c8")
OVERLAY_FRESH = pygame.Color("#28f0b4")
OVERLAY_STALE = pygame.Color("#ffc857")
OVERLAY_ALPHA = 128
OVERLAY_FONT_SIZE = 16  # Fixed-size diagnostics text.
MONO_FONT_SIZE = 40  # Fixed-size numeric labels inside the 120x54 bugs.


@dataclass
class Fonts:
    """Bundled font instances sized relative to the panel height."""

    placeholder: pygame.font.Font
    overlay: pygame.font.Font
    mono: pygame.font.Font


def load_fonts(height: int) -> Fonts:
    """Load the bundled Roboto font at sizes scaled to the panel height."""

    placeholder_size = max(48, int(height * 0.05))
    try:
        placeholder = pygame.font.Font(str(FONT_PATH), placeholder_size)
        overlay = pygame.font.Font(str(FONT_PATH), OVERLAY_FONT_SIZE)
    except FileNotFoundError:
        placeholder = pygame.font.Font(None, placeholder_size)
        overlay = pygame.font.Font(None, OVERLAY_FONT_SIZE)
    # Numeric labels want fixed-width glyphs; fall back through common monospace
    # families and finally pygame's default if none are installed.
    mono = pygame.font.SysFont("monospace,dejavusansmono,couriernew,consolas", MONO_FONT_SIZE)
    return Fonts(placeholder=placeholder, overlay=overlay, mono=mono)


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

# Daydreaming-state assets and layout (top-left anchored coordinates).
BEGIN_TEXT_IMAGE = ASSETS_DIR / "BeginText.png"
SCROLL_ARROW_IMAGE = ASSETS_DIR / "ScrollArrow.png"
BEGIN_TEXT_POS = (103, 677)
SCROLL_ARROW_X = 26
SCROLL_ARROW_Y_REST = 830
SCROLL_ARROW_Y_END = 772


def draw_daydreaming(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Attract / screensaver state: white art on black, with a bobbing scroll hint."""

    surface.fill(BLACK)
    ImageElement(BEGIN_TEXT_IMAGE, *BEGIN_TEXT_POS).draw(surface, context)
    ImageElement(SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y).draw(surface, context)



def draw_idle(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Waiting-for-player state."""

    surface.fill(BLACK)
    ImageElement(BEGIN_TEXT_IMAGE, *BEGIN_TEXT_POS).draw(surface, context)
    ImageElement(SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y).draw(surface, context)

# Tutorial-state assets and layout (top-left anchored coordinates).


def draw_tutorial(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Interactive tutorial state."""

    _draw_placeholder(surface, fonts, context, "TUTORIAL")

# Gameplay-state assets and layout (top-left anchored coordinates).
PLAY_BG_IMAGE = ASSETS_DIR / "GameBgGrey.png"
LEFT_BUG_IMAGE = ASSETS_DIR / "LeftBug.png"
RIGHT_BUG_IMAGE = ASSETS_DIR / "RightBug.png"
LEFT_BUG_X = 118  # Left bug tracks the player's haptic dial.
RIGHT_BUG_X = 245  # Right bug tracks the robot's current joint angle.
BUG_W = 120
BUG_H = 54
BUG_Y_TOP = 568  # Top-left y when the joint is at +180 deg.
BUG_Y_BOTTOM = 1720  # Top-left y when the joint is at -180 deg.
PLAY_ANGLE_TOP = 180.0
PLAY_ANGLE_BOTTOM = -180.0
PLAY_LABEL_COLOR = pygame.Color("#ffffff")

# Countdown timer readout, sized to fill a fixed rectangle (top-left anchored).
TIMER_BOX_W = 410  # Rendered text width is fitted to within this many pixels.
TIMER_BOX_H = 175  # Rendered text height is fitted to within this many pixels.
TIMER_BOX_TOP = 280  # Top y of the rectangle; it is centered horizontally.
TIMER_COLOR = pygame.Color("#ffffff")

_TIMER_FONT_CACHE: dict[int, pygame.font.Font] = {}  # Roboto by point size.
_TIMER_SIZE_CACHE: dict[str, int] = {}  # Fitted point size per timer string.


def draw_play(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Timed gameplay: a fixed grey background with two angle-tracking bugs.

    The left bug follows the haptic dial in robot-space degrees
    (``dial_robot_deg``, already gear-ratio mapped); the right bug follows the
    robot's current joint angle in degrees. The remaining seconds are shown in a
    large readout fitted to a fixed rectangle near the top.
    """

    ImageElement(PLAY_BG_IMAGE, 0, 0).draw(surface, context)

    _draw_play_bug(surface, fonts, context, LEFT_BUG_IMAGE, LEFT_BUG_X, context.dial_robot_deg())
    _draw_play_bug(surface, fonts, context, RIGHT_BUG_IMAGE, RIGHT_BUG_X, context.robot_deg())
    _draw_play_timer(surface, context)


def _draw_play_bug(
    surface: pygame.Surface,
    fonts: Fonts,
    context: Context,
    image_path: Path,
    x: int,
    angle_deg: float | None,
) -> None:
    """Place a bug image and its centered four-character label by a joint angle.

    ``angle_deg`` maps +180 deg to the top of the travel and -180 deg to the
    bottom. The bug is skipped for this frame when its angle is unavailable.
    """

    if angle_deg is None:
        return
    y = remap(angle_deg, PLAY_ANGLE_BOTTOM, PLAY_ANGLE_TOP, BUG_Y_BOTTOM, BUG_Y_TOP)
    ImageElement(image_path, x, y).draw(surface, context)
    TextElement(
        format_signed(angle_deg),
        x + BUG_W / 2,
        y + BUG_H / 2,
        fonts.mono,
        color=PLAY_LABEL_COLOR,
        align="center",
        valign="center",
    ).draw(surface, context)


def _timer_font(size: int) -> pygame.font.Font:
    """Return a cached bundled-Roboto font at ``size`` points."""

    font = _TIMER_FONT_CACHE.get(size)
    if font is None:
        try:
            font = pygame.font.Font(str(FONT_PATH), size)
        except FileNotFoundError:
            font = pygame.font.Font(None, size)
        _TIMER_FONT_CACHE[size] = font
    return font


def _fitted_timer_font(text: str) -> pygame.font.Font:
    """Largest cached Roboto font whose rendered ``text`` fits the timer box.

    The chosen point size is cached per string, so the binary search only runs
    when the displayed value changes (about once per second).
    """

    size = _TIMER_SIZE_CACHE.get(text)
    if size is None:
        low, high, size = 8, 400, 8
        while low <= high:
            mid = (low + high) // 2
            width, height = _timer_font(mid).size(text)
            if width <= TIMER_BOX_W and height <= TIMER_BOX_H:
                size = mid
                low = mid + 1
            else:
                high = mid - 1
        _TIMER_SIZE_CACHE[text] = size
    return _timer_font(size)


def _draw_play_timer(surface: pygame.Surface, context: Context) -> None:
    """Draw the remaining seconds, fitted to and centered in the timer box.

    The readout is skipped when no countdown value is available so a missing
    field never blanks the rest of the scene.
    """

    seconds = context.countdown_s()
    if seconds is None:
        return
    text = str(seconds)
    TextElement(
        text,
        surface.get_width() / 2,
        TIMER_BOX_TOP + TIMER_BOX_H / 2,
        _fitted_timer_font(text),
        color=TIMER_COLOR,
        align="center",
        valign="center",
    ).draw(surface, context)


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
