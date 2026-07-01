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
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pygame
from canvas_elements import (
    Context,
    ImageElement,
    Keyframes,
    OdometerElement,
    TextElement,
    blit_image_left,
    blit_image_slice,
    lerp,
    remap,
)


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

# Idle-state assets. The idle screen content is a full-page image drawn over the
# black background with no offset (top-left anchored at the panel origin).
IDLE_SCREEN_IMAGE = ASSETS_DIR / "IdleScreenContent.png"

# Daydreaming-state overlays. Both states reuse the full play scene and then draw
# one of these full-page semi-transparent overlays at the panel origin.
DAYDREAM_PLAYBACK_OVERLAY = ASSETS_DIR / "daydream_playback_overlay.png"
DAYDREAM_REWIND_OVERLAY = ASSETS_DIR / "daydream_rewind_overlay.png"


def draw_daydreaming(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Attract / screensaver playback: the full play scene with a playback overlay.

    The bugs track the robot's current position. A semi-transparent playback
    overlay and the bobbing scroll hint encourage the player to grab the knob.
    """

    _draw_play_scene(surface, context)
    ImageElement(DAYDREAM_PLAYBACK_OVERLAY, 0, 0).draw(surface, context)
    ImageElement(SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y).draw(surface, context)


def draw_daydream_interrupted(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Attract mode interrupted: the full play scene with a rewind overlay.

    Identical to the daydreaming scene but with the rewind overlay and without the
    scroll hint, since the robot is returning to the start.
    """

    _draw_play_scene(surface, context)
    ImageElement(DAYDREAM_REWIND_OVERLAY, 0, 0).draw(surface, context)



def draw_idle(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Waiting-for-player state: full-page idle art with a bobbing scroll hint."""

    surface.fill(BLACK)
    ImageElement(IDLE_SCREEN_IMAGE, 0, 0).draw(surface, context)
    ImageElement(SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y).draw(surface, context)

# Tutorial-state assets and layout (top-left anchored coordinates).
TUTORIAL_PAGE1_IMAGE = ASSETS_DIR / "TutorialPage1.png"
# Page 2 art is player-specific; index + 1 selects P1..P6.
TUTORIAL_PAGE2_IMAGES = {n: ASSETS_DIR / f"TutorialPage2P{n}.png" for n in range(1, 7)}

# Each of the eleven tutorial pages is anchored to a progress setpoint, one per
# 10% increment.
TUTORIAL_PAGE1_PCT = 0.0
TUTORIAL_PAGE2_PCT = 10.0

# Page 3 spans several detents (20pct..60pct). Its background holds solid across
# the whole span and then fades out, while five text overlays each appear at
# their own 10% detent.
TUTORIAL_PAGE3_BG_IMAGE = ASSETS_DIR / "Tutorial3_background.png"
TUTORIAL_PAGE3_TEXT_IMAGES = {
    20.0: ASSETS_DIR / "Tutorial3a_text.png",
    30.0: ASSETS_DIR / "Tutorial3b_text.png",
    40.0: ASSETS_DIR / "Tutorial3c_text.png",
    50.0: ASSETS_DIR / "Tutorial3d_text.png",
    60.0: ASSETS_DIR / "Tutorial3e_text.png",
}
# The background uses a wide, slide-free fade window: solid across the 20..60 span
# (centre 40, solid half-width 20), with only a narrow margin so it fades in just
# before 20pct and fades out just after 60pct.
TUTORIAL_PAGE3_BG_PCT = 40.0
TUTORIAL_PAGE3_BG_SOLID_PCT = 20.0
TUTORIAL_PAGE3_BG_EDGE_PCT = 22.0

# Page 4 layered composition (no slide on any layer). A red background fades in
# 66..69pct and out 86..89pct; a partial-gauge overlay sits on it at (23, 830),
# fading in 76..79pct and out 91..94pct; two extracted text overlays fade in/out
# at their own windows. Each fade is the symmetric window (centre, solid, edge).
TUTORIAL_PAGE4_BG_IMAGE = ASSETS_DIR / "Tutorial4_background.png"
TUTORIAL_PAGE4_BG_FADE = (77.5, 8.5, 11.5)  # in 66..69, out 86..89
TUTORIAL_PAGE4_GAUGE_IMAGE = ASSETS_DIR / "Tutorial4_partial_gauge.png"
TUTORIAL_PAGE4_GAUGE_POS = (23, 830)
TUTORIAL_PAGE4_GAUGE_FADE = (85.0, 6.0, 9.0)  # in 76..79, out 91..94
TUTORIAL_PAGE4_TEXT_A_IMAGE = ASSETS_DIR / "Tutorial4a_text.png"
TUTORIAL_PAGE4_TEXT_A_FADE = (70.0, 1.0, 4.0)  # in 66..69, out 71..74
TUTORIAL_PAGE4_TEXT_B_IMAGE = ASSETS_DIR / "Tutorial4b_text.png"
TUTORIAL_PAGE4_TEXT_B_FADE = (85.0, 6.0, 9.0)  # in 76..79, out 91..94
# Page 4 speed-bar demo: the play-state speed widget fed a scripted scalar. Its
# own background track sits above the red background but below the speed bar.
TUTORIAL_SPEED_BAR_BG_IMAGE = ASSETS_DIR / "SpeedBarBackground.png"
TUTORIAL_SPEED_BAR_BG_POS = (23, 356)
TUTORIAL_SPEED_BAR_BG_FADE = (80.0, 11.0, 14.0)  # in 66..69, out 91..94
TUTORIAL_SPEED_BAR_POINTS = [(66.0, 0.30), (79.0, 0.10), (81.0, 0.10), (89.0, 0.90)]
TUTORIAL_SPEED_BAR_FADE = (80.0, 11.0, 14.0)
# Page 5: a full-page image that fades in 96..99pct and then stays visible (the
# Keyframes clamps to full alpha above 99pct, so it never fades out).
TUTORIAL_PAGE5_IMAGE = ASSETS_DIR / "Tutorial 5.png"
TUTORIAL_PAGE5_ALPHA_POINTS = [(96.0, 0.0), (99.0, 255.0)]

# Tutorial countdown timer: a centred readout driven by the phase countdown, in
# the same font family as the play timer. It shows throughout the tutorial (no
# fade); only its y position animates, sliding from near the bottom up to
# mid-screen as progress crosses 92..96pct.
TUTORIAL_TIMER_FONT_SIZE = 80  # Placeholder size; tune to taste.
TUTORIAL_TIMER_Y_POINTS = [(92.0, 1850.0), (96.0, 880.0)]
# Default symmetric fade-in / hold / fade-out envelope for tutorial page objects,
# in progress-percent units around each object's setpoint. ``SOLID`` is the
# half-width that stays fully opaque; ``EDGE`` is the half-width at which the
# object has faded fully out. With the defaults an object fades in from
# (setpoint - 4) to (setpoint - 1), holds solid across the setpoint, then fades
# out from (setpoint + 1) to (setpoint + 4).
TUTORIAL_FADE_SOLID_PCT = 1.0
TUTORIAL_FADE_EDGE_PCT = 4.0

# Vertical travel for a sliding page: it sits ``+PX`` below its setpoint, reaches
# ``0`` (its full-page resting position) at the setpoint, then continues to
# ``-PX`` above it, so scrolling forward pushes the page upward off-screen.
TUTORIAL_SLIDE_PX = 50.0


def _tutorial_progress(context: Context) -> float:
    """Tutorial progress percent for this player, defaulting to 0 when unknown."""

    value = context.tutorial_progress_pct()
    return value if value is not None else 0.0


def fade_window(
    setpoint: float,
    solid: float = TUTORIAL_FADE_SOLID_PCT,
    edge: float = TUTORIAL_FADE_EDGE_PCT,
    driver: Callable[[Context], float] = _tutorial_progress,
    peak: float = 255.0,
) -> Keyframes:
    """Build a symmetric fade-in / hold / fade-out opacity driver around ``setpoint``.

    The returned ``Keyframes`` maps the driver value (tutorial progress percent by
    default) to an alpha in ``0..peak``: zero at or below ``setpoint - edge``,
    rising to ``peak`` by ``setpoint - solid``, holding ``peak`` until ``setpoint
    + solid``, then falling back to zero by ``setpoint + edge``. The result plugs
    straight into an element's ``alpha`` so the same envelope can later drive
    position or other animatable properties.
    """

    return Keyframes(
        driver,
        [
            (setpoint - edge, 0.0),
            (setpoint - solid, peak),
            (setpoint + solid, peak),
            (setpoint + edge, 0.0),
        ],
    )


def slide_window(
    setpoint: float,
    span: float = TUTORIAL_SLIDE_PX,
    edge: float = TUTORIAL_FADE_EDGE_PCT,
    driver: Callable[[Context], float] = _tutorial_progress,
) -> Keyframes:
    """Build a linear scroll-position driver around ``setpoint``.

    The returned ``Keyframes`` maps the driver value (tutorial progress percent by
    default) to an offset that slides from ``+span`` at ``setpoint - edge`` through
    ``0`` at the setpoint to ``-span`` at ``setpoint + edge``. Plug it into an
    element's ``x`` or ``y`` to scroll it past its resting position as progress
    crosses the setpoint.
    """

    return Keyframes(
        driver,
        [
            (setpoint - edge, span),
            (setpoint + edge, -span),
        ],
    )


def draw_tutorial(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Interactive tutorial state: full-page pages that cross-fade by progress.

    The game controller publishes this player's ``tutorial_progress_pct``; each
    page is a full-page image anchored to a 10% setpoint and faded in/out by
    ``fade_window`` so neighbouring pages briefly cross-fade as the player scrolls.
    """

    # Page 1 at 0pct
    surface.fill(BLACK)
    ImageElement(
        TUTORIAL_PAGE1_IMAGE, 0, slide_window(TUTORIAL_PAGE1_PCT), alpha=fade_window(TUTORIAL_PAGE1_PCT)
    ).draw(surface, context)
    ImageElement(
        SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y, alpha=fade_window(TUTORIAL_PAGE1_PCT)
    ).draw(surface, context)

    # Page 2 at 10pct; the page image is player-specific.
    page2 = TUTORIAL_PAGE2_IMAGES.get(context.index + 1)
    if page2 is not None:
        ImageElement(
            page2, 0, slide_window(TUTORIAL_PAGE2_PCT), alpha=fade_window(TUTORIAL_PAGE2_PCT)
        ).draw(surface, context)
        ImageElement(
            SCROLL_ARROW_IMAGE, SCROLL_ARROW_X, _scroll_arrow_y, alpha=fade_window(TUTORIAL_PAGE2_PCT)
        ).draw(surface, context)

# Page 3 at 20pct..60pct: a long-lived background with five text detents. The
    # background holds solid across the span (no slide), and each text overlay
    # slides and fades in at its own detent.
    ImageElement(
        TUTORIAL_PAGE3_BG_IMAGE,
        0,
        0,
        alpha=fade_window(
            TUTORIAL_PAGE3_BG_PCT,
            solid=TUTORIAL_PAGE3_BG_SOLID_PCT,
            edge=TUTORIAL_PAGE3_BG_EDGE_PCT,
        ),
    ).draw(surface, context)
    for setpoint, text_image in TUTORIAL_PAGE3_TEXT_IMAGES.items():
        ImageElement(text_image, 0, slide_window(setpoint), alpha=fade_window(setpoint)).draw(
            surface, context
        )
    _draw_tutorial_bug(
        surface, context, LEFT_BUG_IMAGE, LEFT_BUG_X, TUTORIAL_LEFT_ODOMETER,
        TUTORIAL_LEFT_BUG_ANGLE_POINTS, TUTORIAL_LEFT_BUG_FADE,
    )
    _draw_tutorial_bug(
        surface, context, RIGHT_BUG_IMAGE, RIGHT_BUG_X, TUTORIAL_RIGHT_ODOMETER,
        TUTORIAL_RIGHT_BUG_ANGLE_POINTS, TUTORIAL_RIGHT_BUG_FADE,
    )

    # Page 4 at 66..94pct: a red background with a partial gauge and two extracted
    # text overlays, plus the scripted speed-bar widget. All layers are
    # fixed-position (no slide); each fades on its own window.
    ImageElement(TUTORIAL_PAGE4_BG_IMAGE, 0, 0, alpha=fade_window(*TUTORIAL_PAGE4_BG_FADE)).draw(
        surface, context
    )
    ImageElement(
        TUTORIAL_PAGE4_GAUGE_IMAGE, *TUTORIAL_PAGE4_GAUGE_POS, alpha=fade_window(*TUTORIAL_PAGE4_GAUGE_FADE)
    ).draw(surface, context)
    ImageElement(TUTORIAL_PAGE4_TEXT_A_IMAGE, 0, 0, alpha=fade_window(*TUTORIAL_PAGE4_TEXT_A_FADE)).draw(
        surface, context
    )
    ImageElement(TUTORIAL_PAGE4_TEXT_B_IMAGE, 0, 0, alpha=fade_window(*TUTORIAL_PAGE4_TEXT_B_FADE)).draw(
        surface, context
    )
    ImageElement(
        TUTORIAL_SPEED_BAR_BG_IMAGE, *TUTORIAL_SPEED_BAR_BG_POS, alpha=fade_window(*TUTORIAL_SPEED_BAR_BG_FADE)
    ).draw(surface, context)
    bar_scalar = Keyframes(_tutorial_progress, TUTORIAL_SPEED_BAR_POINTS)(context)
    bar_alpha = int(fade_window(*TUTORIAL_SPEED_BAR_FADE)(context))
    _render_speed_bar(surface, context, bar_scalar, bar_alpha)

    # A second, independent bug pair guides the motion on the speed page.
    _draw_tutorial_bug(
        surface, context, LEFT_BUG_IMAGE, LEFT_BUG_X, TUTORIAL_PAGE4_LEFT_ODOMETER,
        TUTORIAL_PAGE4_LEFT_BUG_ANGLE_POINTS, TUTORIAL_PAGE4_LEFT_BUG_FADE,
    )
    _draw_tutorial_bug(
        surface, context, RIGHT_BUG_IMAGE, RIGHT_BUG_X, TUTORIAL_PAGE4_RIGHT_ODOMETER,
        TUTORIAL_PAGE4_RIGHT_BUG_ANGLE_POINTS, TUTORIAL_PAGE4_RIGHT_BUG_FADE,
    )

    # Page 5 at 96pct: a full-page image that fades in and then stays visible.
    ImageElement(
        TUTORIAL_PAGE5_IMAGE, 0, 0, alpha=Keyframes(_tutorial_progress, TUTORIAL_PAGE5_ALPHA_POINTS)
    ).draw(surface, context)

    # The countdown timer is drawn last so it sits on top of every page.
    _draw_tutorial_timer(surface, context)


def _draw_tutorial_timer(surface: pygame.Surface, context: Context) -> None:
    """Draw the phase countdown, centred, sliding from the bottom to mid-screen.

    The value comes from the phase ``countdown_s`` so it keeps counting wherever
    it sits; only the y position animates with tutorial progress. Nothing is drawn
    when no countdown is available.
    """

    seconds = context.countdown_s()
    if seconds is None:
        return
    TextElement(
        str(seconds),
        surface.get_width() / 2,
        Keyframes(_tutorial_progress, TUTORIAL_TIMER_Y_POINTS),
        _tutorial_timer_font(),
        color=TIMER_COLOR,
        align="center",
        valign="center",
    ).draw(surface, context)


@lru_cache(maxsize=1)
def _tutorial_timer_font() -> pygame.font.Font:
    """Return the tutorial countdown font (play-timer family, smaller size)."""

    try:
        return pygame.font.Font(str(FONT_PATH), TUTORIAL_TIMER_FONT_SIZE)
    except FileNotFoundError:
        return pygame.font.Font(None, TUTORIAL_TIMER_FONT_SIZE)



# Page 3 guided bugs. Each bug reuses the play-state art, geometry, and odometer
# behaviour, but its angle is scripted from tutorial progress to walk the player
# through the motion. The angle->y mapping is the play-state one, so each bug and
# its odometer move and read exactly as they would in play. Each fade is the
# symmetric window given as (centre_pct, solid_pct, edge_pct).
#
# Left bug (dial): slides in from 0deg to 30deg over 16..20pct, holds to 50pct,
# rises to 75deg by 60pct, then holds. Fade in 16..19pct, out 61..64pct.
TUTORIAL_LEFT_BUG_ANGLE_POINTS = [(16.0, 0.0), (20.0, 30.0), (50.0, 30.0), (60.0, 75.0)]
TUTORIAL_LEFT_BUG_FADE = (40.0, 21.0, 24.0)
# Right bug (robot): slides in from -30deg to -15deg over 26..29pct, holds to
# 41pct, moves to +30deg by 49pct, holds to 51pct, rises to +50deg by 55pct, then
# holds. Fade in 26..29pct, out 61..64pct.
TUTORIAL_RIGHT_BUG_ANGLE_POINTS = [
    (26.0, -30.0), (49.0, 30.0), (51.0, 30.0), (55.0, 50.0),
]
TUTORIAL_RIGHT_BUG_FADE = (45.0, 16.0, 19.0)

# Page 4 guided bugs: a second, independent left/right pair on the speed page.
# They share the play-state geometry and the _draw_tutorial_bug helper but keep
# their own odometers and profiles. Both fade in 76..79pct and out 91..94pct
# (symmetric window centred on 85pct, solid=6, edge=9).
# Left bug (dial): holds at -60deg, then moves to +15deg over 81..89pct.
TUTORIAL_PAGE4_LEFT_BUG_ANGLE_POINTS = [(81.0, -60.0), (88.0, 15.0)]
TUTORIAL_PAGE4_LEFT_BUG_FADE = (85.0, 6.0, 9.0)
# Right bug (robot): holds at -28deg, then moves to +15deg over 84..89pct.
TUTORIAL_PAGE4_RIGHT_BUG_ANGLE_POINTS = [(85.0, -28.0), (89.0, 15.0)]
TUTORIAL_PAGE4_RIGHT_BUG_FADE = (85.0, 6.0, 9.0)


def _draw_tutorial_bug(
    surface: pygame.Surface,
    context: Context,
    image_path: Path,
    x: int,
    odometer: OdometerElement,
    angle_points: list[tuple[float, float]],
    fade: tuple[float, float, float],
) -> None:
    """Draw a guided bug whose angle and fade are scripted from tutorial progress."""

    angle = Keyframes(_tutorial_progress, angle_points)(context)
    setpoint, solid, edge = fade
    alpha = int(fade_window(setpoint, solid=solid, edge=edge)(context))
    if alpha <= 0:
        return
    y = remap(angle, PLAY_ANGLE_BOTTOM, PLAY_ANGLE_TOP, BUG_Y_BOTTOM, BUG_Y_TOP)
    ImageElement(image_path, x, y, alpha=alpha).draw(surface, context)
    odometer.draw(surface, x, y, angle, context.elapsed_s, alpha)


# Gameplay-state assets and layout (top-left anchored coordinates).
PLAY_BG_IMAGE = ASSETS_DIR / "GameBgGrey.png"  # Base lane; shows untested zones.
PLAY_BG_GREEN = ASSETS_DIR / "GameBgGreen.png"  # Collision-free band source.
PLAY_BG_RED = ASSETS_DIR / "GameBgRed.png"  # Blocked band source.
LEFT_BUG_IMAGE = ASSETS_DIR / "LeftBug.png"
RIGHT_BUG_IMAGE = ASSETS_DIR / "RightBug.png"
SIGN_SCROLL_IMAGE = ASSETS_DIR / "SignScroll.png"
NUMBER_SCROLL_IMAGE = ASSETS_DIR / "NumberScroll.png"
LEFT_BUG_X = 118  # Left bug tracks the player's haptic dial.
RIGHT_BUG_X = 245  # Right bug tracks the robot's current joint angle.
BUG_Y_TOP = 568  # Top-left y when the joint is at +180 deg.
BUG_Y_BOTTOM = 1720  # Top-left y when the joint is at -180 deg.
PLAY_ANGLE_TOP = 180.0
PLAY_ANGLE_BOTTOM = -180.0

# Top banner naming this panel's joint, chosen by joint number (index + 1).
PLAY_BANNER_IMAGES = {joint: ASSETS_DIR / f"Joint{joint}.png" for joint in range(1, 7)}
PLAY_BANNER_X = 23
PLAY_BANNER_Y = 71

# Absolute-degree scale printed on the background art: +180 deg sits at y=596 and
# the scale is 1152 px tall, so -180 deg sits at y=1748. Used to place the green
# and red collision bands, which are given in absolute joint degrees.
PROX_SCALE_TOP_Y = 596.0
PROX_SCALE_SPAN_PX = 1152.0
PROX_SCALE_TOP_DEG = 180.0
PROX_SCALE_RANGE_DEG = 360.0

# Scrolling readouts inside each bug; offsets are from the bug's top-left corner.
# These hold their own animation state, so build them once and reuse them.
LEFT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=22, base_dy=8)
RIGHT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=8, base_dy=8)
# A separate left-bug odometer for the tutorial demo, so its snap animation state
# stays independent of the play-state readout.
TUTORIAL_LEFT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=22, base_dy=8)
TUTORIAL_RIGHT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=8, base_dy=8)
# A second, independent tutorial pair for the bugs shown on page 4.
TUTORIAL_PAGE4_LEFT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=22, base_dy=8)
TUTORIAL_PAGE4_RIGHT_ODOMETER = OdometerElement(SIGN_SCROLL_IMAGE, NUMBER_SCROLL_IMAGE, base_dx=8, base_dy=8)

# Speed-override bar: a left-to-right fill over a grey track printed on the
# background. ``collision.final_scalar`` (0..1) sets the fill width. At or above
# the threshold the green "OK" art is used; below it, the red "bad" art. The
# coloured fill is cropped from the left; the label is overlaid at full size.
SPEED_BAR_GREEN = ASSETS_DIR / "ColliGreen.png"
SPEED_BAR_RED = ASSETS_DIR / "ColliRed.png"
SPEED_OK_TEXT = ASSETS_DIR / "ColliOKText.png"
SPEED_BAD_TEXT = ASSETS_DIR / "ColliBadText.png"
SPEED_BAR_X = 43  # Top-left of the track on the background.
SPEED_BAR_Y = 396
SPEED_BAR_W = 394  # Full bar width at 100%; ColliGreen/ColliRed are 394x76.
SPEED_BAR_THRESHOLD = 0.35  # Below this fraction, use the red / bad artwork.

# Countdown timer readout, sized to fill a fixed rectangle (top-left anchored).
TIMER_BOX_W = 410  # Rendered text width is fitted to within this many pixels.
TIMER_BOX_H = 175  # Rendered text height is fitted to within this many pixels.
TIMER_CENTER_Y = 265  # Vertical center of the readout in the new background box.
TIMER_COLOR = pygame.Color("#ffffff")
TIMER_FONT_SIZE = 149  # Static size determined from the current 480x1920 panel.


def draw_play(surface: pygame.Surface, fonts: Fonts, context: Context) -> None:
    """Timed gameplay: a fixed grey background with two angle-tracking bugs.

    The left bug follows the haptic dial in robot-space degrees
    (``dial_robot_deg``, already gear-ratio mapped); the right bug follows the
    robot's current joint angle in degrees. The remaining seconds are shown in a
    large readout fitted to a fixed rectangle near the top.
    """

    _draw_play_scene(surface, context)


def _draw_play_scene(surface: pygame.Surface, context: Context) -> None:
    """Draw the shared play scene: background, banner, zones, bugs, and timer.

    Used by ``draw_play`` and by the daydreaming states, which layer their own
    overlays on top of this same scene.
    """

    ImageElement(PLAY_BG_IMAGE, 0, 0).draw(surface, context)
    _draw_play_banner(surface, context)
    _draw_collision_zones(surface, context)
    _draw_speed_bar(surface, context)

    _draw_play_bug(surface, context, LEFT_BUG_IMAGE, LEFT_BUG_X, context.dial_robot_deg(), LEFT_ODOMETER)
    _draw_play_bug(surface, context, RIGHT_BUG_IMAGE, RIGHT_BUG_X, context.robot_deg(), RIGHT_ODOMETER)
    _draw_play_timer(surface, context)


def _draw_play_banner(surface: pygame.Surface, context: Context) -> None:
    """Draw the top banner naming this panel's joint.

    The joint number is ``index + 1``; an out-of-range index (1..6 expected)
    simply draws no banner rather than failing.
    """

    image = PLAY_BANNER_IMAGES.get(context.index + 1)
    if image is None:
        return
    ImageElement(image, PLAY_BANNER_X, PLAY_BANNER_Y).draw(surface, context)


def _prox_deg_to_y(deg: float) -> float:
    """Map an absolute joint angle to its y on the background's degree scale."""

    y = PROX_SCALE_TOP_Y + (PROX_SCALE_TOP_DEG - deg) / PROX_SCALE_RANGE_DEG * PROX_SCALE_SPAN_PX
    bottom = PROX_SCALE_TOP_Y + PROX_SCALE_SPAN_PX
    return min(bottom, max(PROX_SCALE_TOP_Y, y))


def _draw_collision_zones(surface: pygame.Surface, context: Context) -> None:
    """Overlay this joint's green free band and red blocked bands on the lane.

    Bands come from ``collision.prox_zones`` in absolute joint degrees. The grey
    base already shows the neutral "untested" lane, so an invalid or missing zone
    draws nothing. The green band spans ``free_min_deg``..``free_max_deg``; a red
    band is added above and/or below only when the matching ``blocked_*`` edge is
    present, leaving everything past the tested window as the neutral base.
    """

    zone = context.prox_zone()
    if not zone or not zone.get("valid"):
        return
    free_min = zone.get("free_min_deg")
    free_max = zone.get("free_max_deg")
    if not isinstance(free_min, (int, float)) or not isinstance(free_max, (int, float)):
        return

    blit_image_slice(surface, PLAY_BG_GREEN, _prox_deg_to_y(free_max), _prox_deg_to_y(free_min))

    blocked_above = zone.get("blocked_above_till_deg")
    if isinstance(blocked_above, (int, float)):
        blit_image_slice(surface, PLAY_BG_RED, _prox_deg_to_y(blocked_above), _prox_deg_to_y(free_max))

    blocked_below = zone.get("blocked_below_till_deg")
    if isinstance(blocked_below, (int, float)):
        blit_image_slice(surface, PLAY_BG_RED, _prox_deg_to_y(free_min), _prox_deg_to_y(blocked_below))


def _draw_speed_bar(surface: pygame.Surface, context: Context) -> None:
    """Draw the combined speed-override fill and its OK/bad label.

    ``collision.final_scalar`` (0..1) sets how far the coloured bar fills from the
    left over the grey track printed on the background. The fill and the overlaid
    label use the green / OK art at or above ``SPEED_BAR_THRESHOLD`` and the red /
    bad art below it. Nothing is drawn when the scalar is unavailable.
    """

    scalar = context.speed_scalar()
    if scalar is None:
        return
    _render_speed_bar(surface, context, scalar)


def _render_speed_bar(
    surface: pygame.Surface, context: Context, scalar: float, alpha: int = 255
) -> None:
    """Draw the speed-bar widget for an explicit ``scalar`` (0..1) and ``alpha``.

    Shared by the play state (fed ``collision.final_scalar``) and the tutorial,
    which overrides the scalar with a scripted value and fades the whole widget.
    """

    if alpha <= 0:
        return
    scalar = max(0.0, min(1.0, scalar))
    ok = scalar >= SPEED_BAR_THRESHOLD
    fill_image = SPEED_BAR_GREEN if ok else SPEED_BAR_RED
    text_image = SPEED_OK_TEXT if ok else SPEED_BAD_TEXT

    blit_image_left(surface, fill_image, SPEED_BAR_X, SPEED_BAR_Y, SPEED_BAR_W * scalar, alpha)
    ImageElement(text_image, SPEED_BAR_X, SPEED_BAR_Y, alpha=alpha).draw(surface, context)


def _draw_play_bug(
    surface: pygame.Surface,
    context: Context,
    image_path: Path,
    x: int,
    angle_deg: float | None,
    odometer: OdometerElement,
) -> None:
    """Place a bug image and its scrolling four-cell readout by a joint angle.

    ``angle_deg`` maps +180 deg to the top of the travel and -180 deg to the
    bottom. The bug is skipped for this frame when its angle is unavailable. The
    odometer reads the same signed angle and follows the bug's moving top-left.
    """

    if angle_deg is None:
        return
    y = remap(angle_deg, PLAY_ANGLE_BOTTOM, PLAY_ANGLE_TOP, BUG_Y_BOTTOM, BUG_Y_TOP)
    ImageElement(image_path, x, y).draw(surface, context)
    odometer.draw(surface, x, y, angle_deg, context.elapsed_s)


@lru_cache(maxsize=1)
def _timer_font() -> pygame.font.Font:
    """Return the fixed Roboto timer font."""

    try:
        return pygame.font.Font(str(FONT_PATH), TIMER_FONT_SIZE)
    except FileNotFoundError:
        return pygame.font.Font(None, TIMER_FONT_SIZE)


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
        TIMER_CENTER_Y,
        _timer_font(),
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
    "daydream_interrupted": draw_daydream_interrupted,
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
