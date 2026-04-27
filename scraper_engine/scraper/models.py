# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Pydantic Data Models
# ---------------------------------------------------------------------------
"""Validated data models for scraped OLX.ba listings and runtime config."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ListingData(BaseModel):
    """Validated output model for a single OLX.ba listing.

    Every field that may be absent on the page is ``Optional`` so the
    parser never throws — downstream consumers (Marko's ML pipeline)
    decide how to handle missing values.
    """

    item_id: str = Field(..., description="OLX listing ID extracted from the URL or DOM")
    title: str = Field(..., description="Listing headline")
    price: float = Field(0.0, description="Numeric price (0.0 if 'Po dogovoru' or unknown)")
    currency: str = Field("KM", description="Currency code")
    seller_id: str = Field("nepoznato", description="Seller username or profile ID")
    seller_name: str = Field("Nepoznato", description="Display name of the seller")
    is_email_verified: bool = Field(False, description="True if email is verified")
    is_phone_verified: bool = Field(False, description="True if phone is verified")
    is_address_verified: bool = Field(False, description="True if physical address is verified")
    positive_feedback: int = Field(0, description="Number of positive reviews/dojmovi")
    neutral_feedback: int = Field(0, description="Number of neutral reviews/dojmovi")
    negative_feedback: int = Field(0, description="Number of negative reviews/dojmovi")
    successful_deliveries: int = Field(0, description="Number of successful OLX deliveries")
    account_age: str = Field("Nepoznato", description="Account creation date or '5 godina' text")
    account_age_months: int = Field(0, description="Account age converted to total months")
    location: str = Field("Nepoznato", description="City / canton string")
    description: str = Field("", description="Full listing description text (sanitized)")
    phone_number: str = Field("", description="Phone if extracted from __INITIAL_STATE__")
    is_promoted: bool = Field(False, description="True if the listing has a promoted/TOP badge")
    is_active: bool = Field(True, description="True if the listing is still available on OLX")
    is_new: bool = Field(False, description="True if the product is marked as NOVO")
    breadcrumbs: str = Field("", description="Category path (e.g. Nakit i Satovi > Ručni Satovi)")
    raw_specs: dict[str, str] = Field(default_factory=dict, description="Raw technical specs table from DOM")
    views: str = Field("", description="Number of views for the listing")
    last_renewed: str = Field("", description="Last renewed date string from OLX")
    condition_text: str = Field("", description="Human-readable condition (e.g. Korišteno, Novo)")

    last_seen_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when the listing was last seen in search results"
    )
    scraped_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when the full listing details were last fetched",
    )

    description_caps_ratio: Optional[float] = Field(
        None,
        description=(
            "Ratio of uppercase characters in description (0.0–1.0). "
            "High values correlate with spam/scam patterns."
        ),
    )
    description_exclamation_count: Optional[int] = Field(
        None,
        description="Number of '!' in description — another scam signal.",
    )

    llm_enrichment: Optional[dict[str, Any]] = Field(
        None,
        description="Strictly validated LLM enrichment payload for this listing.",
    )
    llm_meta: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "LLM call metadata such as provider/model/status/attempts/latency/error."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "item_id": "12345678",
                "title": "iPhone 15 Pro Max 256GB",
                "price": 1800.0,
                "currency": "KM",
                "seller_id": "korisnik123",
                "seller_name": "Korisnik 123",
                "seller_rating": 4.8,
                "account_age": "3 godine",
                "location": "Sarajevo",
                "description": "Prodajem telefon, malo korišten...",
                "phone_number": "+38761234567",
                "is_promoted": False,
                "description_caps_ratio": 0.12,
                "description_exclamation_count": 2,
            }
        }


class ScraperConfig(BaseModel):
    """Runtime configuration for the scraper engine."""

    headless: bool = Field(True, description="Run browser in headless mode")
    timeout_ms: int = Field(30_000, description="Navigation timeout in milliseconds")
    max_retries: int = Field(3, description="Max retry attempts per URL")
    base_delay_s: float = Field(1.0, description="Base delay for exponential backoff (seconds)")
    min_human_delay_s: float = Field(0.8, description="Minimum human-like delay between actions")
    max_human_delay_s: float = Field(2.5, description="Maximum human-like delay between actions")
    proxy_url: Optional[str] = Field(
        None,
        description=(
            "SOCKS5/HTTP proxy URL. Example: 'socks5://user:pass@proxy.example.com:1080'. "
            "Leave None to connect directly."
        ),
    )
    viewport_width_range: tuple[int, int] = Field(
        (1280, 1920), description="Random viewport width range"
    )
    viewport_height_range: tuple[int, int] = Field(
        (720, 1080), description="Random viewport height range"
    )
    max_concurrent_pages: int = Field(
        5,
        description=(
            "Max pages open simultaneously. "
            "Keep at 5–10 per container for RAM stability."
        ),
    )
