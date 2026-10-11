"""The screen's zones, one class per region of the sinoptic.

``Dashboard`` mixes them together, so every widget stays an attribute of the
one object the geometry invariant is measured on; each zone keeps its own
file and its own responsibility."""

from __future__ import annotations

from .banner import BannerSection
from .decision import DecisionSection
from .events import EventsSection
from .game import GameSection
from .link import LinkSection

SECTIONS = (BannerSection, GameSection, DecisionSection, LinkSection, EventsSection)

__all__ = [
    "SECTIONS", "BannerSection", "GameSection", "DecisionSection",
    "LinkSection", "EventsSection",
]
