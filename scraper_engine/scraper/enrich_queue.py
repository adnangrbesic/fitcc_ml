import asyncio
import json
import logging
import os
import time
from typing import List, Dict, Any

import redis.asyncio as aioredis
from scraper.publisher import RabbitMqPublisher
from scraper.llm.enricher import build_enricher
from scraper.models import ListingData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
)
logger = logging.getLogger("scraper.enrich_queue")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
API_BASE_URL = os.getenv("API_BASE_URL", "http://api:80")
RAW_QUEUE = "olx:raw_listings"
BATCH_WINDOW = 1
LLM_BATCH_TIMEOUT = 10.0  # seconds to wait before processing a partial batch

async def process_batch(batch: List[Dict[str, Any]], enrichers: Dict[str, Any], publisher: RabbitMqPublisher, redis_client):
    if not batch:
        return

    logger.info(f"Processing batch of {len(batch)} listings")
    
    tasks = []
    for raw_data in batch:
        try:
            listing = ListingData(**raw_data)
            
            # Select enricher based on category
            breadcrumbs = (listing.breadcrumbs or "").lower()
            if "mobiteli" in breadcrumbs or "phone" in breadcrumbs:
                enricher = enrichers.get("phones", enrichers["general"])
            else:
                enricher = enrichers["general"]
                
            tasks.append(enricher.enrich_listing(listing))
        except Exception as e:
            logger.error(f"Failed to parse raw listing: {e}")

    enriched_listings = await asyncio.gather(*tasks)

    for listing in enriched_listings:
        if not listing: continue
        
        # Check if LLM enrichment succeeded
        if not listing.llm_enrichment or (listing.llm_meta and listing.llm_meta.get("status") == "failed"):
            logger.warning(f"Enrichment failed for {listing.item_id}. Re-queueing back to Redis queue...")
            await redis_client.lpush("olx:raw_listings", listing.model_dump_json())
            await asyncio.sleep(2)  # Avoid hammering Ollama if starting or overloaded
            continue
            
        # Convert Pydantic model to dict and ensure ISO date formatting
        payload = listing.model_dump()
        
        # Ensure dates are strings for JSON serialization
        if payload.get("last_seen_at"):
            payload["last_seen_at"] = payload["last_seen_at"].isoformat()
        if payload.get("scraped_at"):
            payload["scraped_at"] = payload["scraped_at"].isoformat()

        # For backward compatibility and C# matching if needed
        payload["is_new"] = listing.is_new
        
        publisher.publish_listing(payload)

async def main():
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    publisher = RabbitMqPublisher()
    publisher.connect()
    
    # Initialize LLM Enrichers
    enrichers = {
        "general": build_enricher(category="general"),
        "phones": build_enricher(category="phones")
    }
    
    logger.info(f"Enrichment worker started. Watching {RAW_QUEUE}...")
    
    batch = []
    last_batch_time = time.time()
    
    while True:
        try:
            # BRPOP with timeout
            result = await redis.brpop(RAW_QUEUE, timeout=1)
            
            if result:
                _, data_str = result
                if not data_str or not data_str.strip().startswith('{'):
                    logger.warning(f"Skipping non-JSON or invalid data from Redis: {data_str}")
                    continue
                    
                batch.append(json.loads(data_str))
                
            # Process if batch full or timeout reached
            if len(batch) >= BATCH_WINDOW or (batch and time.time() - last_batch_time > LLM_BATCH_TIMEOUT):
                # Filter batch to only include dicts
                valid_batch = [item for item in batch if isinstance(item, dict)]
                if valid_batch:
                    await process_batch(valid_batch, enrichers, publisher, redis)
                batch = []
                last_batch_time = time.time()
                
        except Exception as e:
            logger.error(f"Error in enrich worker loop: {e}")
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
