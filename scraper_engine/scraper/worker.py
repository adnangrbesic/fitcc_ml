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

from scraper.engine import ScraperEngine
from scraper.models import ScraperConfig

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
    logger.info("[%s] Redis mode — queue=%s, concurrency=%d",
                WORKER_ID, queue_name, config.max_concurrent_pages)

    async with ScraperEngine(config) as engine:
        idle_count = 0
        while True:
            # BRPOP: blocking pop with 10s timeout
            result = await client.brpop(queue_name, timeout=10)

            if result is None:
                idle_count += 1
                logger.debug("[%s] Queue empty, idle count=%d", WORKER_ID, idle_count)
                if idle_count >= 6:  # 60s of no work → exit
                    logger.info("[%s] Queue empty for 60s — shutting down", WORKER_ID)
                    break
                continue

            idle_count = 0
            _, url = result  # BRPOP returns (queue_name, value)
            url = url.strip()
            if not url:
                continue

            logger.info("[%s] Scraping: %s", WORKER_ID, url)
            listing = await engine.scrape_listing(url)

            if listing:
                # Push result back to Redis as JSON (or write to DB here)
                await client.lpush(
                    f"{queue_name}:results",
                    listing.model_dump_json(),
                )
                logger.info("[%s] ✓ %s — %s", WORKER_ID, listing.item_id, listing.title)
            else:
                # Push failed URL to dead-letter queue
                await client.lpush(f"{queue_name}:failed", url)
                logger.warning("[%s] ✗ Failed: %s", WORKER_ID, url)

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
