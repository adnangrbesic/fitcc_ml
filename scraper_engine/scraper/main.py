# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Async Entrypoint
# ---------------------------------------------------------------------------
"""CLI-style entrypoint for single-listing and batch scraping.

Usage
~~~~~
::

    # Single listing
    python -m scraper.main --url https://olx.ba/artikal/12345678

    # Batch (multiple URLs)
    python -m scraper.main --url https://olx.ba/artikal/111 --url https://olx.ba/artikal/222

    # With proxy
    python -m scraper.main --url https://olx.ba/artikal/12345678 --proxy socks5://user:pass@host:1080

    # Headful mode (for debugging)
    python -m scraper.main --url https://olx.ba/artikal/12345678 --headful
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime

from scraper.engine import ScraperEngine
from scraper.models import ScraperConfig, ListingData
from scraper.store import JSONStore

# -------------------------------------------------------------------------
# Logging Setup
# -------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scraper")


def build_argparser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="scraper",
        description="BuyGuardian OLX.ba Scraper Engine",
    )
    
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        action="append",
        help="OLX.ba listing URL(s) to scrape. Can be specified multiple times.",
    )
    group.add_argument(
        "--category-url",
        help="OLX.ba category/search URL to scrape all listings from.",
    )
    group.add_argument(
        "--query", "-q",
        help="Search query (e.g. 'Samsung Galaxy S25').",
    )
    
    p.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of pagination pages to crawl for a category (default: 1).",
    )
    p.add_argument(
        "--proxy",
        default=None,
        help="Proxy URL (e.g. socks5://user:pass@host:1080). Default: direct.",
    )
    p.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in headful mode for visual debugging.",
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retry attempts per URL (default: 3).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Navigation timeout in milliseconds (default: 30000).",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent pages (default: 5).",
    )
    p.add_argument(
        "--min-price",
        type=float,
        default=0.0,
        help="Minimum price filter to exclude accessories (default: 0).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output JSON file path for current run. Default: sdtout.",
    )
    p.add_argument(
        "--history",
        default="scraper_history.json",
        help="Persistent JSON file to track all seen listings (default: scraper_history.json).",
    )
    p.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the validation check for missing (zombie) listings.",
    )
    p.add_argument(
        "--llm-category",
        default=None,
        help=(
            "Enable LLM enrichment using templates in scraper/llm_templates/<category>."
        ),
    )
    p.add_argument(
        "--llm-prompt-template",
        default=None,
        help="Override prompt template path (.txt or .py).",
    )
    p.add_argument(
        "--llm-output-template",
        default=None,
        help="Override output-template JSON path.",
    )
    p.add_argument(
        "--llm-output-schema",
        default=None,
        help="Override strict output-schema JSON path.",
    )
    p.add_argument(
        "--llm-skip-schema-validation",
        action="store_true",
        help="Skip JSON-schema validation of LLM output.",
    )
    return p


async def run(args: argparse.Namespace) -> None:
    """Execute the scraping pipeline."""
    config = ScraperConfig(
        headless=not args.headful,
        proxy_url=args.proxy,
        max_retries=args.max_retries,
        timeout_ms=args.timeout,
        max_concurrent_pages=args.concurrency,
    )

    # Initialize persistent storage
    store = JSONStore(args.history)

    enricher = None
    if args.llm_category:
        from scraper.llm.config import LLMConfigurationError
        from scraper.llm.enricher import build_enricher

        try:
            enricher = build_enricher(
                category=args.llm_category,
                prompt_template_path=args.llm_prompt_template,
                output_template_path=args.llm_output_template,
                output_schema_path=args.llm_output_schema,
                validate_output_schema=(
                    False if args.llm_skip_schema_validation else None
                ),
            )
        except LLMConfigurationError as exc:
            logger.error("LLM enrichment config error: %s", exc)
            raise

        if args.llm_skip_schema_validation:
            logger.warning("LLM output schema validation is DISABLED for this run")

        # Operational visibility: verify provider/model reachability before scraping.
        await enricher.log_status()

    async with ScraperEngine(config) as engine:
        current_listings: list[ListingData] = []
        
        if args.query:
            # Construct search URL
            query_encoded = args.query.replace(" ", "%20")
            search_url = f"https://olx.ba/pretraga?q={query_encoded}"
            logger.info("Search mode for query: '%s' (url: %s)", args.query, search_url)
            current_listings = await engine.scrape_category(search_url, max_pages=args.pages)
        elif args.category_url:
            logger.info("Category scrape mode for %s (pages=%d)", args.category_url, args.pages)
            current_listings = await engine.scrape_category(args.category_url, max_pages=args.pages)
        elif args.url and len(args.url) == 1:
            # Single listing
            listing = await engine.scrape_listing(args.url[0])
            current_listings = [listing] if listing else []
        elif args.url:
            # Batch scraping
            logger.info("Batch scraping %d URLs (concurrency=%d)",
                        len(args.url), config.max_concurrent_pages)
            current_listings = await engine.scrape_batch(args.url)

        # Remove Nones
        current_listings = [l for l in current_listings if l is not None]
        
        # 1. Update history with current findings
        current_ids = []
        for l in current_listings:
            l.last_seen_at = datetime.utcnow()
            store.upsert(l)
            current_ids.append(l.item_id)
        
        # 2. Identify and validate zombies (missing items)
        if not args.no_validate and (args.query or args.category_url):
            stale = store.get_stale_active_listings(current_ids, query=args.query)
            if stale:
                logger.info("Found %d potential zombies to validate", len(stale))
                validated = await engine.validate_listings(stale)
                for v in validated:
                    # Update the store with the latest status (is_active=False etc)
                    store.upsert(v)
        
        # Filtering logic
        filtered_listings = []
        excluded_keywords = {
            "maska", "maskica", "punjač", "punjac", "staklo", "zastitno", "zaštitno",
            "folija", "kabal", "kabl", "case", "cover", "futrola", "slušalice",
            "slusalice", "kutija", "adapter", "oprema", "dijelovi", "dijelove"
        }
        
        for l in current_listings:
            title_lower = l.title.lower()
            
            # 1. Price check
            if l.price and l.price < args.min_price:
                logger.debug("Filtered out %s due to price: %.2f < %.2f", l.title, l.price, args.min_price)
                continue
            
            # 2. Keyword check
            if any(kw in title_lower for kw in excluded_keywords):
                # Optimization: check if query itself contains the keyword (e.g. user *wants* a charger)
                query_words = set((args.query or "").lower().split())
                actual_keywords = [kw for kw in excluded_keywords if kw in title_lower and kw not in query_words]
                
                if actual_keywords:
                    logger.debug("Filtered out %s due to accessory keywords: %s", l.title, actual_keywords)
                    continue
            
            filtered_listings.append(l)

        # Optional LLM enrichment stage (after filtering)
        if enricher is not None:
            logger.info(
                "LLM enrichment enabled for category '%s' (%d listings)",
                args.llm_category,
                len(filtered_listings),
            )

            filtered_listings = await enricher.enrich(filtered_listings)
            success_count = sum(
                1
                for listing in filtered_listings
                if listing.llm_meta and listing.llm_meta.get("status") == "ok"
            )
            logger.info(
                "LLM enrichment finished: %d/%d successful",
                success_count,
                len(filtered_listings),
            )

            # Persist enriched payloads in history state.
            for listing in filtered_listings:
                store.upsert(listing)

        # Save combined state after optional enrichment updates.
        store.save()

        results = [l.model_dump(mode="json") for l in filtered_listings]

    # Output results
    output_json = json.dumps(results, indent=2, ensure_ascii=False, default=str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        logger.info("Results written to %s", args.output)
    else:
        print(output_json)

    # Summary
    success = len(results)
    filtered = len(current_listings) - success
    logger.info("Done: %d listings scraped successfully. Filtered out %d accessories.", success, filtered)


def main() -> None:
    """Synchronous entry point."""
    parser = build_argparser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
