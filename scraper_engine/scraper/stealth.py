# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Stealth & Evasion Utilities
# ---------------------------------------------------------------------------
"""User-Agent rotation, viewport randomization, human-like delays, and
stealth script injection for anti-bot evasion.

Uses the ``playwright-stealth`` library for navigator patching instead of
hand-rolled JS — it covers webdriver, plugins, languages, mime-types, and
WebGL vendor/renderer in one call.
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

# -------------------------------------------------------------------------
# User-Agent Pool
# -------------------------------------------------------------------------
# Real-world UA strings from Chrome, Firefox, and Edge on Windows/macOS.
# Rotate per-context (not per-request) to stay consistent within a session.
_USER_AGENTS: list[str] = [
    # Chrome 120 — Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 120 — macOS Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 119 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome 118 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    # Firefox 120 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Firefox 119 — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1; rv:119.0) Gecko/20100101 Firefox/119.0",
    # Firefox 118 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
    # Edge 120 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Edge 119 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    # Chrome 120 — Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 117 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    # Firefox 117 — Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:117.0) Gecko/20100101 Firefox/117.0",
    # Chrome 116 — macOS Ventura
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    # Edge 118 — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.0.0",
    # Chrome 120 — Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.130 Safari/537.36",
]


def get_random_ua() -> str:
    """Return a random User-Agent string."""
    return random.choice(_USER_AGENTS)


def get_random_viewport(
    width_range: tuple[int, int] = (1280, 1920),
    height_range: tuple[int, int] = (720, 1080),
) -> dict[str, int]:
    """Return a randomized viewport size within realistic desktop ranges."""
    return {
        "width": random.randint(*width_range),
        "height": random.randint(*height_range),
    }


async def human_delay(
    min_seconds: float = 0.8,
    max_seconds: float = 2.5,
) -> None:
    """Sleep for a uniform-random duration to mimic human pacing."""
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


async def simulate_mouse_movement(page: Page, steps: int = 3) -> None:
    """Perform random mouse movements to look organic.

    Moves the cursor to 'steps' random positions within the viewport,
    with small variable delays between each move.
    """
    viewport = page.viewport_size or {"width": 1366, "height": 768}
    for _ in range(steps):
        x = random.randint(100, viewport["width"] - 100)
        y = random.randint(100, viewport["height"] - 100)
        await page.mouse.move(x, y, steps=random.randint(5, 15))
        await asyncio.sleep(random.uniform(0.05, 0.25))


async def apply_stealth(page: Page) -> None:
    """Apply playwright-stealth patches to the page.

    This replaces hand-rolled JS injection and covers:
    - navigator.webdriver removal
    - navigator.plugins spoofing
    - chrome.runtime patching
    - WebGL vendor/renderer spoofing
    - language & platform consistency
    """
    from playwright_stealth import Stealth  # type: ignore[import-untyped]

    await Stealth().apply_stealth_async(page)
