from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None


@dataclass
class Listing:
    listing_id: str | int
    item_id: str | None = None
    seller_id: str | None = None
    product_id: str | None = None
    title: str | None = None
    description: str | None = None
    price: float | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    is_active: bool | None = None
    is_new: bool | None = None
    scraped_at: str | None = None
    price_histories: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Listing":
        listing_id = data.get("id")
        if listing_id is None:
            listing_id = data.get("listingId", data.get("listing_id"))

        raw_metadata = data.get("rawMetadata")
        if raw_metadata is None:
            raw_metadata = data.get("raw_metadata", {})
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}

        price_histories = data.get("priceHistories", data.get("price_histories", []))
        if not isinstance(price_histories, list):
            price_histories = []

        return cls(
            listing_id=listing_id,
            item_id=data.get("itemId", data.get("item_id")),
            seller_id=data.get("sellerId", data.get("seller_id")),
            product_id=data.get("productId", data.get("product_id")),
            title=data.get("title"),
            description=data.get("description"),
            price=_to_float(data.get("price")),
            raw_metadata=raw_metadata,
            is_active=data.get("isActive", data.get("is_active")),
            is_new=data.get("isNew", data.get("is_new")),
            scraped_at=data.get("scrapedAt", data.get("scraped_at")),
            price_histories=price_histories,
        )


@dataclass(frozen=True)
class Subscores:
    seller_score: float
    consistency_score: float
    condition_score: float
    pricing_score: float
    writing_score: float


@dataclass(frozen=True)
class ScoreResult:
    listing_id: str | int
    trust_score: float
    confidence: float
    reasons: list[str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "listingId": self.listing_id,
            "trustScore": self.trust_score,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }
