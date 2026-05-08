# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Core Engine
# ---------------------------------------------------------------------------
"""Async scraper engine with session management, resource blocking, retry
logic, and proxy support.

Architecture
~~~~~~~~~~~~
::

    ScraperEngine
    ├── start()        → launches browser + creates stealth context
    ├── scrape_listing(url)  → navigate → parse → validate → ListingData
    ├── scrape_batch(urls)   → concurrent scraping with semaphore
    └── stop()         → graceful shutdown

Resource blocking intercepts images, CSS, fonts, analytics, and ad
networks at the request level via ``page.route()``, cutting bandwidth
by ~70% on typical OLX pages.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from scraper.models import ListingData, ScraperConfig
from scraper.parser import Parser
from scraper.stealth import (
    apply_stealth,
    get_random_ua,
    get_random_viewport,
    human_delay,
    simulate_mouse_movement,
)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Blocked resource patterns (images, CSS, fonts, trackers, ads)
# -------------------------------------------------------------------------
_BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {"image", "stylesheet", "font", "media", "imageset"}
)

_BLOCKED_URL_PATTERNS: tuple[str, ...] = (
    # Analytics
    "google-analytics.com",
    "googletagmanager.com",
    "analytics.",
    "hotjar.com",
    "facebook.net",
    "connect.facebook",
    "doubleclick.net",
    # Ad networks
    "googlesyndication.com",
    "adservice.google",
    "pubmatic.com",
    "criteo.com",
    "outbrain.com",
    "taboola.com",
    # Tracking pixels
    "pixel.",
    "bat.bing.com",
    "clarity.ms",
)


class ScraperEngine:
    """High-level async scraper for OLX.ba listings.

    Usage::

        config = ScraperConfig(headless=True, proxy_url="socks5://...")
        engine = ScraperEngine(config)
        await engine.start()
        listing = await engine.scrape_listing("https://olx.ba/artikal/12345678")
        await engine.stop()

    Or use as an async context manager::

        async with ScraperEngine(config) as engine:
            listing = await engine.scrape_listing(url)
    """

    def __init__(self, config: ScraperConfig | None = None) -> None:
        self.config = config or ScraperConfig()
        self._parser = Parser()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._seller_cache: dict[str, dict[str, int]] = {}
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_pages)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser and prepare the engine for scraping."""
        logger.info("Starting ScraperEngine (headless=%s)", self.config.headless)
        self._playwright = await async_playwright().start()

        launch_kwargs: dict = {
            "headless": self.config.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }

        # Proxy placeholder — plug in your rotating proxy provider
        if self.config.proxy_url:
            launch_kwargs["proxy"] = {"server": self.config.proxy_url}
            logger.info("Using proxy: %s", self.config.proxy_url)

        if self._playwright:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            logger.info("Browser launched successfully")

    async def stop(self) -> None:
        """Gracefully close browser and Playwright."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("ScraperEngine stopped")

    async def __aenter__(self) -> "ScraperEngine":
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Context Factory
    # ------------------------------------------------------------------

    async def _new_context(self) -> BrowserContext:
        """Create a fresh browser context with randomized fingerprint."""
        assert self._browser is not None, "Engine not started — call start() first"

        viewport = get_random_viewport(
            self.config.viewport_width_range,
            self.config.viewport_height_range,
        )
        user_agent = get_random_ua()

        context = await self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale="bs-BA",
            timezone_id="Europe/Sarajevo",
            # Appear as if we accept Bosnian + English
            extra_http_headers={
                "Accept-Language": "bs-BA,bs;q=0.9,hr;q=0.8,en-US;q=0.7,en;q=0.6",
            },
        )

        logger.debug(
            "New context: UA=%s, viewport=%dx%d",
            user_agent[:50],
            viewport["width"],
            viewport["height"],
        )
        return context

    # ------------------------------------------------------------------
    # Resource Blocking
    # ------------------------------------------------------------------

    @staticmethod
    async def _block_resources(route, request) -> None:  # noqa: ANN001
        """Intercept and abort unnecessary resource requests."""
        if request.resource_type in _BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return

        url_lower = request.url.lower()
        for pattern in _BLOCKED_URL_PATTERNS:
            if pattern in url_lower:
                await route.abort()
                return

        await route.continue_()

    # ------------------------------------------------------------------
    # Single Listing Scraper
    # ------------------------------------------------------------------

    async def scrape_listing(self, url: str) -> Optional[ListingData]:
        """Scrape a single OLX.ba listing with retry + exponential backoff.

        Returns a validated ``ListingData`` or ``None`` if all retries fail.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.max_retries + 1):
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            try:
                context = await self._new_context()
                page = await context.new_page()

                # Apply stealth patches
                await apply_stealth(page)

                # Block heavy resources
                await page.route("**/*", self._block_resources)

                # Human-like pre-navigation delay
                if attempt > 1:
                    backoff = self._backoff_delay(attempt)
                    logger.info("Retry %d/%d — backing off %.1fs",
                                attempt, self.config.max_retries, backoff)
                    await asyncio.sleep(backoff)

                # Navigate
                response: Optional[Response] = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.config.timeout_ms,
                )

                # Check HTTP status
                if response:
                    status = response.status
                    if status == 429:
                        # Too Many Requests — respect Retry-After
                        retry_after = response.headers.get("retry-after", "60")
                        wait = int(retry_after) if retry_after.isdigit() else 60
                        logger.warning("429 Too Many Requests — waiting %ds", wait)
                        await asyncio.sleep(wait)
                        continue

                    if status == 403:
                        logger.warning(
                            "403 Forbidden — possible IP block. "
                            "Consider rotating proxy."
                        )
                        # Rotate fingerprint on next attempt (new context)
                        continue

                    if status >= 400:
                        logger.warning("HTTP %d for %s", status, url)
                        continue

                # Check for anti-bot challenges (even if status is 200)
                page_text = await page.content()
                if any(x in page_text for x in ["Checking your browser", "Please enable cookies", "Ray ID", "unusual activity"]):
                    logger.warning("Anti-bot challenge detected on %s, retrying with new context...", url)
                    continue

                # Wait for critical content to load
                await self._wait_for_content(page)

                # Simulate human behavior
                await simulate_mouse_movement(page)
                await human_delay(
                    self.config.min_human_delay_s,
                    self.config.max_human_delay_s,
                )

                # Parse listing
                raw_data = await self._parser.parse_listing(page)
                
                # Check if we actually got a listing. If title is missing, it's a fail.
                if not raw_data.get("title"):
                    logger.warning("Parser failed to find title for %s (possible block or failed load)", url)
                    # Trigger retry
                    raise ValueError("Empty parse result")

                # Fetch/Update seller feedback
                seller_username = raw_data.get("seller_name")
                if seller_username and seller_username != "Nepoznato":
                    if seller_username not in self._seller_cache:
                        # Attempt to fetch feedback
                        try:
                            # profil/{username}/dojmovi works for both shops and private users
                            feedback_url = f"https://olx.ba/profil/{seller_username}/dojmovi"
                            logger.info("  ↳ Fetching feedback for %s...", seller_username)
                            
                            # Navigate to dojmovi
                            await page.goto(feedback_url, wait_until="domcontentloaded", timeout=15000)
                            # Wait for Nuxt to hydrate/render the feedback summary
                            await asyncio.sleep(1.5)
                            
                            feedback = await self._parser.parse_seller_feedback(page)
                            self._seller_cache[seller_username] = feedback
                            logger.info("  ↳ Success: +%d/neutral:%d/-%d", 
                                        feedback.get("positive_feedback", 0),
                                        feedback.get("neutral_feedback", 0),
                                        feedback.get("negative_feedback", 0))
                        except Exception as e:
                            logger.warning("  ↳ Could not fetch feedback for %s: %s", seller_username, e)
                            self._seller_cache[seller_username] = {"positive_feedback": 0, "neutral_feedback": 0, "negative_feedback": 0}
                    
                    # Apply cached feedback
                    raw_data.update(self._seller_cache[seller_username])

                listing = ListingData(**raw_data)

                logger.info("✓ Scraped: %s — %s (Delivs: %d, FB: +%d/-%d, V: %s%s%s)", 
                            listing.item_id, listing.title, 
                            listing.successful_deliveries,
                            listing.positive_feedback, listing.negative_feedback,
                            "E" if listing.is_email_verified else "-",
                            "P" if listing.is_phone_verified else "-",
                            "A" if listing.is_address_verified else "-")
                return listing

            except PlaywrightTimeout:
                last_error = PlaywrightTimeout(f"Timeout on attempt {attempt}")
                logger.warning("Timeout on attempt %d for %s", attempt, url)

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.error(
                    "Error on attempt %d for %s: %s", attempt, url, exc,
                    exc_info=True,
                )

            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()

        logger.error("All %d attempts failed for %s", self.config.max_retries, url)
        if last_error:
            logger.error("Last error: %s", last_error)
        return None

    # ------------------------------------------------------------------
    # Batch Scraper
    # ------------------------------------------------------------------

    async def scrape_batch(
        self, urls: list[str]
    ) -> list[Optional[ListingData]]:
        """Scrape multiple listings concurrently (bounded by semaphore).

        Args:
            urls: List of OLX.ba listing URLs.

        Returns:
            List of ``ListingData`` (or ``None`` for failed URLs),
            in the same order as the input.
        """
        async def _bounded_scrape(url: str) -> Optional[ListingData]:
            async with self._semaphore:
                return await self.scrape_listing(url)

        tasks = [asyncio.create_task(_bounded_scrape(u)) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)

    # ------------------------------------------------------------------
    # Category / Search Crawler
    # ------------------------------------------------------------------

    async def scrape_category(
        self, category_url: str, max_pages: int = 1
    ) -> list[str]:
        """Extract URLs from a category/search page and scrape them.

        Args:
            category_url: Base search URL (e.g. https://olx.ba/pretraga?kategorija=18)
            max_pages: Number of pagination pages to crawl. 0 means infinite.
            
        Returns:
            List of listing URLs across all crawled pages.
        """
        all_urls: set[str] = set()
        page_num = 1
        
        while True:
            if max_pages > 0 and page_num > max_pages:
                break
            # If the URL already specifies a page, use it directly and stop after one iteration
            if "page=" in category_url:
                url = category_url
                if page_num > 1:
                    break
            else:
                separator = "&" if "?" in category_url else "?"
                url = f"{category_url}{separator}page={page_num}"
            
            logger.info("Fetching category page %d: %s", page_num, url)
            
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            try:
                context = await self._new_context()
                page = await context.new_page()
                
                await apply_stealth(page)
                await page.route("**/*", self._block_resources)
                
                # Navigate
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                
                # Wait for at least one listing link or the main content area
                try:
                    await page.wait_for_selector('a[href*="/artikal/"]', timeout=10000)
                except Exception:
                    logger.debug("Listing links didn't appear after 10s, trying anyway")
                
                # Small buffer for multiple results to render
                await asyncio.sleep(1.0)
                
                # Extract all unique links containing "/artikal/"
                # We use properties (a.href) for absolute URLs and attributes for relative ones, then resolve.
                page_urls = await page.evaluate(
                    """() => {
                        return Array.from(document.querySelectorAll('a[href*="/artikal/"]'))
                            .map(a => a.href)
                            .filter(h => h.includes('/artikal/'));
                    }"""
                )
                
                logger.info("Found %d listing URLs on page %d", len(page_urls), page_num)
                if not page_urls:
                    logger.info("No more listings found on page %d. Stopping pagination.", page_num)
                    break
                    
                all_urls.update(page_urls)
                
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to extract URLs from %s: %s", url, exc)
                break # Stop on error to prevent infinite loops on broken pages
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()
                    
            # Human delay between pagination
            await human_delay(1.5, 4.0)
            page_num += 1
                
        # Return all unique URLs extracted
        logger.info("Total unique URLs extracted: %d.", len(all_urls))
        return list(all_urls)

    async def validate_listings(self, listings: list[ListingData]) -> list[ListingData]:
        """
        Re-visit a list of listings and update their is_active status.
        Useful for checking if 'missing' items were sold or deleted.
        """
        if not listings:
            return []
            
        logger.info("Validating status for %d potential zombie listings...", len(listings))
        
        urls = [f"https://olx.ba/artikal/{l.item_id}" for l in listings]
        
        # We can use scrape_batch which handles concurrency and returns updated ListingData
        updated = await self.scrape_batch(urls)
        
        # Return only the ones that were successfully checked
        return [u for u in updated if u is not None]

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _wait_for_content(self, page: Page) -> None:
        """Wait for key OLX listing elements to appear.

        Uses a short timeout so we don't hang on missing elements —
        the parser handles absent fields gracefully.
        """
        critical_selectors = [
            "h4[data-cy='ad_title'], h1",
            "[data-testid='ad-price-container'], .css-12vqlj3",
        ]
        for sel in critical_selectors:
            try:
                await page.wait_for_selector(sel, timeout=8_000)
            except PlaywrightTimeout:
                logger.debug("Selector not found within 8s: %s", sel)

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter.

        Formula: base_delay × 2^(attempt-1) + uniform(0, 1)

        This prevents the "thundering herd" problem when multiple workers
        retry simultaneously.
        """
        base = self.config.base_delay_s * (2 ** (attempt - 1))
        jitter = random.uniform(0, 1)
        return min(base + jitter, 60.0)  # Cap at 60 seconds
