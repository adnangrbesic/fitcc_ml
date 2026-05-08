# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Worker Mode
# ---------------------------------------------------------------------------
"""Standalone worker that reads URLs from a file or Redis queue and
scrapes them concurrently.

Usage (file mode — no Redis needed)::

    python -m scraper.worker --urls urls.txt --concurrency 10 --output results.json

Usage (Redis mode — for distributed deployment)::

    python -m scraper.worker --redis redis://localhost:6379 --queue olx:urls --concurrency 10

In Docker Compose each replica runs this worker, pulling URLs from the
shared Redis queue so no two workers scrape the same URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional
import httpx

from scraper.engine import ScraperEngine
from scraper.models import ScraperConfig
from scraper.publisher import RabbitMqPublisher
from scraper.llm.enricher import build_enricher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scraper.worker")

# Worker ID for logging (set by Docker Compose replica index or hostname)
WORKER_ID = os.environ.get("WORKER_ID", os.environ.get("HOSTNAME", "worker-0"))


# ---------------------------------------------------------------------
# File-based URL source (simple mode — no Redis dependency)
# ---------------------------------------------------------------------

async def run_file_mode(
    urls: list[str],
    config: ScraperConfig,
    output_path: Optional[str],
) -> None:
    """Scrape a list of URLs from a file, write results to JSON."""
    logger.info("[%s] File mode — %d URLs, concurrency=%d",
                WORKER_ID, len(urls), config.max_concurrent_pages)

    async with ScraperEngine(config) as engine:
        results = await engine.scrape_batch(urls)

    serialized = [
        r.model_dump(mode="json") if r else None
        for r in results
    ]

    success = sum(1 for r in serialized if r is not None)
    logger.info("[%s] Done: %d/%d scraped", WORKER_ID, success, len(urls))

    output_json = json.dumps(serialized, indent=2, ensure_ascii=False, default=str)
    if output_path:
        Path(output_path).write_text(output_json, encoding="utf-8")
        logger.info("[%s] Results written to %s", WORKER_ID, output_path)
    else:
        print(output_json)


# ---------------------------------------------------------------------
# Redis queue consumer (distributed mode)
# ---------------------------------------------------------------------

async def process_single_url(
    url: str,
    engine: ScraperEngine,
    publisher: RabbitMqPublisher,
    client,  # Redis client
    http_client: httpx.AsyncClient,
    api_base_url: str,
    queue_name: str,
    is_search: bool = False,
) -> bool:
    """Scrape a single URL, publish raw data, and queue for enrichment if needed."""
    listing = await engine.scrape_listing(url)
    if listing:
        # Check if we need LLM enrichment
        needs_enrichment = True
        try:
            resp = await http_client.get(
                f"{api_base_url}/api/Listings/{listing.item_id}/needs-enrichment",
                timeout=5.0
            )
            if resp.status_code == 200:
                needs_enrichment = resp.json().get("needsEnrichment", True)
        except Exception as e:
            logger.warning("[%s] Failed to check enrichment status for %s: %s", WORKER_ID, listing.item_id, e)

        if needs_enrichment:
            # Push to Redis for Batch Enrichment (LLM)
            await client.lpush(
                "olx:raw_listings",
                listing.model_dump_json(),
            )
            logger.info("[%s] ✓ %s — Queued in Redis for LLM enrichment", WORKER_ID, listing.item_id)
        else:
            # If no LLM enrichment is needed (scraped < 24h), we can publish directly as it already has LLM data
            publisher.publish_listing(listing.model_dump())
            logger.info("[%s] ✓ %s — Raw published to MQ. Skipped LLM enrichment (<24h).", WORKER_ID, listing.item_id)
        return True
    else:
        if not is_search:
            await client.lpush(f"{queue_name}:failed", url)
            logger.warning("[%s] ✗ Failed: %s", WORKER_ID, url)
        return False


async def run_redis_mode(
    redis_url: str,
    queue_name: str,
    config: ScraperConfig,
) -> None:
    """Continuously consume URLs from a Redis list and scrape them.

    Uses BRPOP (blocking pop) so multiple workers share the queue
    without duplicating work. Runs until the queue is empty + timeout.
    """
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "Redis mode requires the 'redis' package. "
            "Install with: pip install redis"
        )
        return

    client = aioredis.from_url(redis_url, decode_responses=True)
    publisher = RabbitMqPublisher()
    publisher.connect()
    
    # Initialize LLM Enricher
    enricher = build_enricher(category="general")
    
    logger.info("[%s] Redis mode — queue=%s, concurrency=%d",
                WORKER_ID, queue_name, config.max_concurrent_pages)

    API_BASE_URL = os.environ.get("API_BASE_URL", "http://api")

    async with ScraperEngine(config) as engine:
        idle_count = 0
        async with httpx.AsyncClient() as http_client:
            while True:
                # BRPOP: blocking pop with 10s timeout
                # Listen to both category tasks and listing URLs
                result = await client.brpop(["olx:category_tasks", queue_name], timeout=10)

                if result is None:
                    idle_count += 1
                    logger.debug("[%s] Queue empty, idle count=%d", WORKER_ID, idle_count)
                    if idle_count >= 6:  # 60s of no work → exit
                        logger.info("[%s] Queue empty for 60s — shutting down", WORKER_ID)
                        break
                    continue

                idle_count = 0
                qname, data = result  # BRPOP returns (queue_name, value)
                data = data.strip()
                if not data:
                    continue

                if qname == "olx:category_tasks":
                    try:
                        task = json.loads(data)
                        cat_url = task.get("Url")
                        page_num = task.get("Page", 1)
                        if cat_url:
                            logger.info("[%s] 📂 Category Page Task: %s (Page=%d)", WORKER_ID, cat_url, page_num)
                            
                            # Construct specific page URL
                            separator = "&" if "?" in cat_url else "?"
                            page_url = f"{cat_url}{separator}page={page_num}"
                            
                            urls_found = await engine.scrape_category(page_url, max_pages=1)
                            logger.info("[%s] 📂 Category Page Task found %d URLs for page %d", WORKER_ID, len(urls_found), page_num)
                            
                            for listing_url in urls_found:
                                # Check if early stop is requested
                                stop_requested = await client.get("olx:stop_requested")
                                if stop_requested == "true":
                                    logger.info("[%s] 🛑 Stop requested. Aborting category page %d loop early.", WORKER_ID, page_num)
                                    break
                                
                                logger.info("[%s] 📂 Category Page sequential processing: %s", WORKER_ID, listing_url)
                                await process_single_url(
                                    listing_url, engine, publisher, client, http_client, API_BASE_URL, queue_name
                                )
                    except Exception as e:
                        logger.error("[%s] Failed to parse/process category task: %s", WORKER_ID, e)
                    continue

                url = data
                logger.info("[%s] Processing: %s", WORKER_ID, url)
                
                # Detect if it's a search query or a direct listing URL
                is_search = False
                target_url = url
                
                if not url.startswith("http"):
                    # Treat as search term
                    from urllib.parse import quote
                    target_url = f"https://olx.ba/pretraga?q={quote(url)}"
                    is_search = True
                    logger.info("[%s] 🔍 Search term detected, constructed URL: %s", WORKER_ID, target_url)
                elif "/pretraga" in url:
                    is_search = True
                    logger.info("[%s] 🔍 Search URL detected: %s", WORKER_ID, target_url)

                if is_search:
                    # Get URLs from search page (legacy search support from olx:urls, max_pages=1)
                    urls_to_process = await engine.scrape_category(target_url, max_pages=1)
                    logger.info("[%s] Found %d URLs to process from search", WORKER_ID, len(urls_to_process))
                    for current_url in urls_to_process:
                        stop_requested = await client.get("olx:stop_requested")
                        if stop_requested == "true":
                            logger.info("[%s] 🛑 Stop requested. Aborting search loop early.", WORKER_ID)
                            break
                        await process_single_url(
                            current_url, engine, publisher, client, http_client, API_BASE_URL, queue_name, is_search=True
                        )
                else:
                    await process_single_url(
                        target_url, engine, publisher, client, http_client, API_BASE_URL, queue_name, is_search=False
                    )

    await client.aclose()


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scraper.worker",
        description="BuyGuardian Scraper Worker",
    )

    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--urls",
        help="Path to a text file with one URL per line.",
    )
    source.add_argument(
        "--redis",
        help="Redis URL (e.g. redis://localhost:6379).",
    )

    p.add_argument("--queue", default="olx:urls",
                    help="Redis queue name (default: olx:urls).")
    p.add_argument("--concurrency", type=int, default=5,
                    help="Max concurrent pages per worker (default: 5).")
    p.add_argument("--proxy", default=None,
                    help="Proxy URL.")
    p.add_argument("--output", default=None,
                    help="Output JSON file (file mode only).")
    return p


def main() -> None:
    args = build_argparser().parse_args()

    config = ScraperConfig(
        headless=True,
        proxy_url=args.proxy,
        max_concurrent_pages=args.concurrency,
    )

    if args.urls:
        urls = Path(args.urls).read_text(encoding="utf-8").strip().splitlines()
        urls = [u.strip() for u in urls if u.strip()]
        asyncio.run(run_file_mode(urls, config, args.output))
    else:
        asyncio.run(run_redis_mode(args.redis, args.queue, config))


if __name__ == "__main__":
    main()
