# ---------------------------------------------------------------------------
# BuyGuardian ML Service — Database Access Layer
# ---------------------------------------------------------------------------
"""Async PostgreSQL connection pool using psycopg 3.

All queries are read-only: the ML service never writes to the main DB.
Anomaly results are returned via HTTP and persisted by the C# API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


async def init_pool() -> None:
    """Create the global async connection pool."""
    global _pool
    if _pool is not None:
        return
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()
    logger.info("PostgreSQL connection pool opened (%s)", settings.database_url.split("@")[-1])


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


@asynccontextmanager
async def get_conn():
    """Yield an async connection from the pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    async with _pool.connection() as conn:
        yield conn


# ── Query helpers ─────────────────────────────────────────────────────────


async def fetch_listings_for_product(product_id: UUID) -> list[dict[str, Any]]:
    """Fetch all active listings for a product, including seller and LLM metadata.

    Returns a flat list of dicts with all columns needed for feature engineering.
    """
    query = """
        SELECT
            l."Id"              AS listing_id,
            l."ItemId"          AS item_id,
            l."Price"           AS price,
            l."ScrapedAt"       AS scraped_at,
            l."RawMetadata"     AS raw_metadata,
            s."SuccessfulDeliveries"  AS successful_deliveries,
            s."AccountAgeMonths"     AS account_age_months,
            s."PositiveFeedback"     AS positive_feedback,
            s."NegativeFeedback"     AS negative_feedback
        FROM "Listings" l
        JOIN "Sellers" s ON l."SellerId" = s."Id"
        WHERE l."ProductId" = %s
          AND l."IsActive" = TRUE
        ORDER BY l."ScrapedAt" DESC
    """
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (str(product_id),))
            return await cur.fetchall()


async def fetch_price_history(listing_id: UUID) -> list[float]:
    """Fetch price history for a single listing, ordered chronologically."""
    query = """
        SELECT "Price"::float AS price
        FROM "PriceHistories"
        WHERE "ListingId" = %s
        ORDER BY "RecordedAt" ASC
    """
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (str(listing_id),))
            rows = await cur.fetchall()
            return [r["price"] for r in rows]


async def fetch_product_by_item_id(item_id: str) -> dict[str, Any] | None:
    """Lookup product_id and category contamination for a listing's item_id."""
    query = """
        SELECT
            l."Id"          AS listing_id,
            l."ProductId"   AS product_id,
            p."AvgPrice"    AS avg_price,
            p."ListingsCount" AS listings_count,
            p."CategoryName"  AS category_name,
            COALESCE(c."IFContamination", %s) AS contamination
        FROM "Listings" l
        LEFT JOIN "Products" p ON l."ProductId" = p."Id"
        LEFT JOIN "Categories" c ON p."CategoryId" = c."Id"
        WHERE l."ItemId" = %s
        LIMIT 1
    """
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (settings.if_contamination, item_id))
            return await cur.fetchone()


async def fetch_all_product_ids_with_min_listings(min_count: int) -> list[dict[str, Any]]:
    """Return all product_ids that have at least `min_count` active listings.

    Also returns per-category contamination override if set.
    """
    query = """
        SELECT
            p."Id"            AS product_id,
            p."CanonicalName" AS canonical_name,
            p."ListingsCount" AS listings_count,
            COALESCE(c."IFContamination", %s) AS contamination
        FROM "Products" p
        LEFT JOIN "Categories" c ON p."CategoryId" = c."Id"
        WHERE p."ListingsCount" >= %s
    """
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (settings.if_contamination, min_count))
            return await cur.fetchall()
