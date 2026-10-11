"""The angle and range words the snapshot speaks in.

Pure functions: given the same radians or distance they always return the same word, which is what the prompt contract pins."""

from __future__ import annotations

import math


def _angle(value: float) -> float:
    return (value + math.pi) % math.tau - math.pi

def _bearing_word(value: float) -> str:
    degrees = math.degrees(value)
    if abs(degrees) <= 8:
        return "aligned"
    if abs(degrees) <= 25:
        return "left-small" if degrees > 0 else "right-small"
    if abs(degrees) <= 70:
        return "left" if degrees > 0 else "right"
    if abs(degrees) <= 120:
        return "far-left" if degrees > 0 else "far-right"
    return "behind-left" if degrees > 0 else "behind-right"

def _distance_word(value: float) -> str:
    if value < 96:
        return "contact"
    if value < 240:
        return "near"
    if value < 560:
        return "medium"
    return "far"
