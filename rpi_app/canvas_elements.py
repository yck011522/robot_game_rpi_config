#!/usr/bin/env python3
"""Reusable canvas primitives for the player-panel renderer.

This module is the small animation/layout toolkit used by ``draw.py``:

* ``lerp`` / ``remap`` math helpers.
* ``resolve`` plus the ``Keyframes`` driver, which let any animatable property
  (x, y, alpha) be a constant, a keyframed value, or a custom
  ``Context -> number`` callable. The single ``resolve`` rule is what lets the
  three forms be mixed freely on the same element.
* ``Context``, the per-frame data bundle handed to every draw function. It always
  carries the raw ``state`` body from the latest UDP message and an open
  ``values`` dict for ad-hoc parameters a draw function wants to animate against.
* ``TextElement``, the first drawable. Image and number-strip elements are added
  when the per-state scenes actually need them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import pygame


def lerp(a: float, b: float, t: float) -> float:
    """Linearly interpolate from ``a`` to ``b`` for ``t`` in [0, 1]."""

    return a + (b - a) * t


def remap(value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """Map ``value`` from [in_min, in_max] onto [out_min, out_max], clamped to the ends."""

    if in_max == in_min:
        return out_min
    if value <= in_min:
        return out_min
    if value >= in_max:
        return out_max
    return lerp(out_min, out_max, (value - in_min) / (in_max - in_min))


def format_signed(value: float, digits: int = 3) -> str:
    """Format a number as a sign character plus a zero-padded integer magnitude.

    For example 180 -> ``+180``, -5 -> ``-005``, 0 -> ``+000``. The result is a
    fixed ``digits + 1`` characters wide, which keeps a monospace label visually
    stable as the value changes.
    """

    rounded = int(round(value))
    sign = "-" if rounded < 0 else "+"
    return f"{sign}{abs(rounded):0{digits}d}"


def resolve(value: Any, context: "Context") -> float:
    """Resolve an animatable property to a number.

    Accepts a plain number, a ``Keyframes`` object, or any ``Context -> number``
    callable. This single rule lets x, y and alpha each independently be a
    constant, a keyframed value, or a fully custom function.
    """

    if callable(value):
        return value(context)
    return value


class Keyframes:
    """Map a driver value to an output through interpolated control points.

    ``driver`` reads one number out of the ``Context`` (for example the haptic
    dial position, the tutorial progress percentage, the countdown timer, or a
    custom parameter stored in ``Context.values``). ``points`` is a list of
    ``(driver_value, output_value)`` pairs; the driver value is clamped to the
    first and last point.

    A non-linear easing hook is intentionally left as a seam: an ``ease``
    callable mapping a 0..1 segment fraction to a 0..1 eased fraction can be
    added later (for example so a number strip lingers on a digit before
    snapping to the next one) without changing any call sites.
    """

    def __init__(
        self,
        driver: Callable[["Context"], float],
        points: list[tuple[float, float]],
        ease: Callable[[float], float] | None = None,
    ) -> None:
        self.driver = driver
        self.points = sorted(points, key=lambda p: p[0])
        self.ease = ease

    def __call__(self, context: "Context") -> float:
        if not self.points:
            return 0.0

        x = self.driver(context)
        points = self.points
        if x <= points[0][0]:
            return points[0][1]
        if x >= points[-1][0]:
            return points[-1][1]

        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= x <= x1:
                span = x1 - x0
                fraction = 0.0 if span == 0 else (x - x0) / span
                if self.ease is not None:
                    fraction = self.ease(fraction)
                return lerp(y0, y1, fraction)
        return points[-1][1]


@dataclass
class Context:
    """Per-frame data handed to every draw function.

    ``state`` is the raw ``state.full`` body from the latest UDP packet, or
    ``None`` before the first valid packet. ``team`` and ``index`` identify which
    single player this process renders (index is 0-based). ``fresh`` reports
    whether a valid packet arrived recently. ``elapsed_s`` is the wall time in
    seconds since the display application started, for animations that depend on
    local time rather than game state. ``values`` is an open key/value store for
    ad-hoc parameters a draw function wants to animate against; it is kept empty
    until a feature needs it.
    """

    state: dict[str, Any] | None
    team: str = "a"
    index: int = 0
    fresh: bool = False
    elapsed_s: float = 0.0
    values: dict[str, Any] = field(default_factory=dict)

    def _team_joint(self, group: str, key: str) -> Any:
        """Return ``state.teams[team][group][key][index]`` or ``None`` if absent."""

        try:
            return self.state["teams"][self.team][group][key][self.index]  # type: ignore[index]
        except (TypeError, KeyError, IndexError):
            return None

    def active_stage(self) -> str:
        """Return the authoritative lifecycle stage, or an empty string when unknown."""

        if isinstance(self.state, dict):
            return str(self.state.get("active_stage") or self.state.get("stage") or "")
        return ""

    def countdown_s(self) -> int | None:
        """Return the integer countdown seconds, or ``None`` when unavailable."""

        if isinstance(self.state, dict):
            value = self.state.get("countdown_s")
            if isinstance(value, (int, float)):
                return int(value)
        return None

    def dial_deg(self) -> float | None:
        """Return this player's raw haptic dial position in degrees, or ``None``."""

        value = self._team_joint("haptic", "dial_deg")
        return float(value) if isinstance(value, (int, float)) else None

    def dial_robot_deg(self) -> float | None:
        """Return the dial position mapped to robot-space degrees, or ``None``.

        This is ``haptic.dial_robot_deg``: the measured dial position already run
        through the configured per-axis gear ratio, so it reflects robot-space
        direction and scaling and needs no further unit conversion.
        """

        value = self._team_joint("haptic", "dial_robot_deg")
        return float(value) if isinstance(value, (int, float)) else None

    def tutorial_progress_pct(self) -> float | None:
        """Return this player's tutorial progress (nominally 0..100), or ``None``."""

        value = self._team_joint("haptic", "tutorial_progress_pct")
        return float(value) if isinstance(value, (int, float)) else None

    def robot_deg(self) -> float | None:
        """Return this player's robot joint angle in degrees, or ``None``."""

        value = self._team_joint("robot", "q_rad")
        return math.degrees(value) if isinstance(value, (int, float)) else None

    def prox_zone(self) -> dict | None:
        """Return this player's joint collision-zone object, or ``None``.

        This is ``collision.prox_zones[index]``: the display-ready proximity
        bands for the joint this panel renders. Returns ``None`` when the field
        is missing so a draw function can fall back to the neutral background.
        """

        zone = self._team_joint("collision", "prox_zones")
        return zone if isinstance(zone, dict) else None

    def speed_scalar(self) -> float | None:
        """Return the team's combined speed fraction, or ``None``.

        This is ``collision.final_scalar``: one team-level number (not per-joint)
        nominally in ``0.0..1.0`` where ``1.0`` means full speed. It already
        folds the path and proximity collision checks into a single value.
        """

        try:
            value = self.state["teams"][self.team]["collision"]["final_scalar"]  # type: ignore[index]
        except (TypeError, KeyError):
            return None
        return float(value) if isinstance(value, (int, float)) else None

    def paused(self) -> bool:
        """Return whether the game is currently paused (E-stop / barrier / etc.)."""

        return bool(self.state.get("paused")) if isinstance(self.state, dict) else False

    def _team_group(self, group: str) -> Any:
        """Return ``state.teams[team][group]`` or ``None`` if absent."""

        try:
            return self.state["teams"][self.team][group]  # type: ignore[index]
        except (TypeError, KeyError):
            return None

    def practice_in_practice(self) -> bool:
        """Return whether this team is still in the one-player-at-a-time practice."""

        practice = self._team_group("practice")
        return bool(practice.get("in_practice")) if isinstance(practice, dict) else False

    def practice_active_player(self) -> int | None:
        """Return the 1-based player number whose practice turn it is, or ``None``."""

        practice = self._team_group("practice")
        if isinstance(practice, dict) and isinstance(practice.get("active_player"), int):
            return practice["active_player"]
        return None

    def practice_completed(self) -> bool:
        """Return whether this player's practice turn has latched complete."""

        value = self._team_joint("practice", "completed")
        return value is True

    def practice_target_deg(self) -> float | None:
        """Return this player's practice target in absolute joint degrees, or ``None``."""

        value = self._team_joint("practice", "target_pose_deg")
        return float(value) if isinstance(value, (int, float)) else None


class TextElement:
    """A single line of text with animatable position and opacity.

    ``text`` may be a string or a ``Context -> str`` callable. ``x``, ``y`` and
    ``alpha`` each accept a constant, a ``Keyframes`` object, or a custom
    callable. ``align`` positions the text horizontally relative to ``x``
    (``left`` / ``center`` / ``right``); ``valign`` does the same vertically
    relative to ``y`` (``top`` / ``center`` / ``bottom``).
    """

    def __init__(
        self,
        text: Any,
        x: Any,
        y: Any,
        font: pygame.font.Font,
        color: Any = (235, 245, 255),
        align: str = "left",
        valign: str = "top",
        alpha: Any = 255,
    ) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.font = font
        self.color = color
        self.align = align
        self.valign = valign
        self.alpha = alpha

    def draw(self, surface: pygame.Surface, context: Context) -> None:
        """Render the text onto ``surface`` using values resolved from ``context``."""

        text = self.text(context) if callable(self.text) else self.text
        glyphs = self.font.render(str(text), True, self.color)
        glyphs.set_alpha(int(max(0, min(255, resolve(self.alpha, context)))))

        x = resolve(self.x, context)
        y = resolve(self.y, context)
        width, height = glyphs.get_size()
        if self.align == "center":
            x -= width / 2
        elif self.align == "right":
            x -= width
        if self.valign == "center":
            y -= height / 2
        elif self.valign == "bottom":
            y -= height
        surface.blit(glyphs, (int(x), int(y)))


_IMAGE_CACHE: dict[str, pygame.Surface] = {}


def load_image(path: Any) -> pygame.Surface:
    """Load a PNG (with its alpha channel) once and cache it by path.

    Requires the pygame display to be initialised so ``convert_alpha`` can match
    the screen's pixel format. Drawing the same asset every frame is therefore a
    cheap dictionary lookup rather than a disk read.
    """

    key = str(path)
    surface = _IMAGE_CACHE.get(key)
    if surface is None:
        surface = pygame.image.load(key).convert_alpha()
        _IMAGE_CACHE[key] = surface
    return surface


def blit_image_slice(
    surface: pygame.Surface,
    image_path: Any,
    y_top: float,
    y_bottom: float,
) -> None:
    """Overlay the horizontal band ``[y_top, y_bottom)`` of a full-page image.

    The source rows are blitted at the same ``y`` on ``surface``, so a band cut
    from one full-screen layer (for example the green or red collision page)
    drops cleanly over an identically sized base layer. The range is clamped to
    the image and rounded to whole pixels; an empty band draws nothing.
    """

    image = load_image(image_path)
    width, height = image.get_size()
    top = max(0, min(height, int(round(y_top))))
    bottom = max(0, min(height, int(round(y_bottom))))
    if bottom <= top:
        return
    surface.blit(image.subsurface(pygame.Rect(0, top, width, bottom - top)), (0, top))


def blit_image_left(
    surface: pygame.Surface,
    image_path: Any,
    dest_x: float,
    dest_y: float,
    width: float,
    alpha: int = 255,
) -> None:
    """Blit the leftmost ``width`` columns of an image at ``(dest_x, dest_y)``.

    This drives a left-to-right progress fill: a coloured bar image is revealed
    from its left edge by ``width`` pixels over a track drawn on the background.
    ``width`` is clamped to the image and rounded to whole pixels; a non-positive
    width draws nothing. ``alpha`` (0..255) scales the whole slice for fades.
    """

    image = load_image(image_path)
    img_w, img_h = image.get_size()
    w = max(0, min(img_w, int(round(width))))
    if w <= 0:
        return
    slice_ = image.subsurface(pygame.Rect(0, 0, w, img_h))
    if alpha < 255:
        slice_ = slice_.copy()
        slice_.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(slice_, (int(dest_x), int(dest_y)))


class ImageElement:
    """A PNG image with animatable position and opacity.

    ``x``, ``y`` and ``alpha`` each accept a constant, a ``Keyframes`` object, or
    a custom callable. ``align`` positions the image horizontally relative to
    ``x`` (``left`` / ``center`` / ``right``); ``valign`` does the same vertically
    relative to ``y`` (``top`` / ``center`` / ``bottom``). The image keeps its own
    per-pixel alpha; a sub-255 ``alpha`` scales it uniformly for fades.
    """

    def __init__(
        self,
        image_path: Any,
        x: Any,
        y: Any,
        align: str = "left",
        valign: str = "top",
        alpha: Any = 255,
    ) -> None:
        self.image_path = str(image_path)
        self.x = x
        self.y = y
        self.align = align
        self.valign = valign
        self.alpha = alpha

    def draw(self, surface: pygame.Surface, context: Context) -> None:
        """Blit the image onto ``surface`` using values resolved from ``context``."""

        image = load_image(self.image_path)
        alpha = int(max(0, min(255, resolve(self.alpha, context))))
        if alpha != 255:
            # Scale every pixel's alpha by alpha/255 while preserving RGB and the
            # source's own per-pixel transparency (set_alpha is unreliable here).
            image = image.copy()
            image.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)

        x = resolve(self.x, context)
        y = resolve(self.y, context)
        width, height = image.get_size()
        if self.align == "center":
            x -= width / 2
        elif self.align == "right":
            x -= width
        if self.valign == "center":
            y -= height / 2
        elif self.valign == "bottom":
            y -= height
        surface.blit(image, (int(x), int(y)))


# Scrolling-digit geometry, shared by the sign and number strips.
DIGIT_W = 23  # Width of one cropped cell, in pixels.
DIGIT_H = 40  # Height of one cropped cell, in pixels.
STRIP_PERIOD = 10 * DIGIT_H  # Pixels of travel before the number strip repeats.

# Source columns of the visible glyphs inside each 32px-wide strip.
SIGN_SRC_X = 4
NUMBER_SRC_X = 4

# Crop-top positions that vertically centre each sign glyph in its cell.
SIGN_PLUS_TOP = 11.5  # ``+`` cell (shown for a value of zero or above).
SIGN_MINUS_TOP = 51.5  # ``-`` cell, one cell (40px) below the plus.


def _number_crop_top(value: float) -> float:
    """Crop-top (px) into the number strip for a continuous digit ``value``.

    The strip reads 0, 1, ... 9, 0 down its eleven cells, so cell ``c`` shows
    digit ``c % 10``. Digit ``d`` therefore lives at crop-top
    ``(d mod 10) * DIGIT_H``; a fractional value lands between two cells, and the
    trailing duplicate ``0`` cell makes the 9->0 seam continuous.
    """

    return (value % 10.0) * DIGIT_H


def _blit_strip_window(
    surface: pygame.Surface,
    image_path: Any,
    src_x: int,
    dest_x: float,
    dest_y: float,
    crop_top: float,
    alpha: int = 255,
) -> None:
    """Blit one ``DIGIT_W`` x ``DIGIT_H`` window of a vertical strip.

    ``crop_top`` is clamped so the window stays inside the strip, then rounded to
    the nearest pixel (positions are interpolated, but blits are integer-aligned).
    """

    strip = load_image(image_path)
    top = int(round(crop_top))
    top = max(0, min(strip.get_height() - DIGIT_H, top))
    window = strip.subsurface(pygame.Rect(src_x, top, DIGIT_W, DIGIT_H))
    if alpha < 255:
        window = window.copy()
        window.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(window, (int(dest_x), int(dest_y)))


class _TimedScroller:
    """Roll a 1-D position to a new target over a fixed duration, then hold.

    This is the snap behaviour shared by the sign cell and the two left-hand
    number cells: the value they show jumps between discrete stops, but the crop
    position eases to the new stop instead of cutting. Re-targeting mid-roll just
    restarts the ease from wherever the position currently is.
    """

    def __init__(self, duration: float = 0.2) -> None:
        self.duration = duration
        self._pos: float | None = None
        self._from = 0.0
        self._target = 0.0
        self._start = 0.0

    @property
    def position(self) -> float | None:
        """The current crop position, or ``None`` before the first update."""

        return self._pos

    def update(self, target: float, now: float) -> float:
        """Advance toward ``target`` using the wall clock ``now`` (seconds)."""

        if self._pos is None:
            self._pos = self._from = self._target = target
            self._start = now
            return self._pos
        if target != self._target:
            self._from = self._pos
            self._target = target
            self._start = now
        if self.duration <= 0:
            self._pos = self._target
        else:
            fraction = (now - self._start) / self.duration
            fraction = 0.0 if fraction < 0 else 1.0 if fraction > 1 else fraction
            self._pos = lerp(self._from, self._target, fraction)
        return self._pos


class OdometerElement:
    """A four-cell scrolling readout: a sign cell plus three number cells.

    It shows a signed angle as a sign and three magnitude digits (hundreds,
    tens, units). The two left digits snap to whole numbers but roll there with a
    short animation; the units digit scrolls continuously like a car odometer, so
    it can sit between two digits to show a fraction. The sign rolls between
    ``+`` and ``-`` (``+`` at exactly zero) with the same short animation.

    The element keeps its own animation state between frames, so create it once
    and reuse it; do not rebuild it every frame like the stateless image and text
    elements. ``draw`` is given the bug's top-left origin, the signed value, and
    the current wall-clock seconds that drive the snap animations.
    """

    def __init__(
        self,
        sign_image: Any,
        number_image: Any,
        base_dx: int,
        base_dy: int,
        spacing: int = DIGIT_W,
        duration: float = 0.2,
    ) -> None:
        self.sign_image = str(sign_image)
        self.number_image = str(number_image)
        self.base_dx = base_dx
        self.base_dy = base_dy
        self.spacing = spacing
        self._sign = _TimedScroller(duration)
        self._hundreds = _TimedScroller(duration)
        self._tens = _TimedScroller(duration)

    def draw(
        self,
        surface: pygame.Surface,
        origin_x: float,
        origin_y: float,
        value: float,
        now: float,
        alpha: int = 255,
    ) -> None:
        """Draw the four cells for ``value`` at the bug's ``origin`` top-left."""

        magnitude = abs(value)
        sign_top = self._sign.update(
            SIGN_MINUS_TOP if value < 0 else SIGN_PLUS_TOP, now
        )
        hundreds_top = self._snap(self._hundreds, math.floor(magnitude / 100.0) % 10, now)
        tens_top = self._snap(self._tens, math.floor(magnitude / 10.0) % 10, now)
        units_top = _number_crop_top(magnitude % 10.0)

        x = origin_x + self.base_dx
        y = origin_y + self.base_dy
        _blit_strip_window(surface, self.sign_image, SIGN_SRC_X, x, y, sign_top, alpha)
        _blit_strip_window(
            surface, self.number_image, NUMBER_SRC_X, x + self.spacing, y,
            hundreds_top % STRIP_PERIOD, alpha,
        )
        _blit_strip_window(
            surface, self.number_image, NUMBER_SRC_X, x + 2 * self.spacing, y,
            tens_top % STRIP_PERIOD, alpha,
        )
        _blit_strip_window(
            surface, self.number_image, NUMBER_SRC_X, x + 3 * self.spacing, y,
            units_top, alpha,
        )

    @staticmethod
    def _snap(scroller: _TimedScroller, digit: int, now: float) -> float:
        """Roll ``scroller`` to ``digit`` along the shortest path around the strip.

        The number strip is periodic every ``STRIP_PERIOD`` pixels, so the target
        is shifted by whole periods to stay within half a turn of the current
        position. That keeps a 9->0 carry rolling forward by one cell instead of
        unwinding the long way.
        """

        target = _number_crop_top(float(digit))
        current = scroller.position
        if current is not None:
            while target - current > STRIP_PERIOD / 2:
                target -= STRIP_PERIOD
            while target - current < -STRIP_PERIOD / 2:
                target += STRIP_PERIOD
        return scroller.update(target, now)
