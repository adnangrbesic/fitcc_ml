from __future__ import annotations

import re
from typing import Any

from ml_service_listing.domain.models import Listing


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return cleaned.strip()


def manufacturer_mismatch(
    raw_manufacturer: str | None,
    canonical_name: str | None,
    title: str | None,
) -> bool | None:
    if not raw_manufacturer:
        return None
    target = canonical_name or title
    if not target:
        return None

    raw_norm = _normalize_text(str(raw_manufacturer))
    target_norm = _normalize_text(str(target))
    if not raw_norm or not target_norm:
        return None

    if raw_norm in target_norm or target_norm in raw_norm:
        return False
    return True


def title_spec_consistency(title: str | None, storage_gb: float | None) -> bool | None:
    if not title or storage_gb is None:
        return None
    matches = re.findall(r"\b(\d{2,4})\s*gb\b", title.lower())
    if not matches:
        return None
    try:
        storage_int = int(storage_gb)
    except (TypeError, ValueError):
        return None
    return storage_int in {int(value) for value in matches}


def suspicious_price(overpay_ratio: float | None) -> bool | None:
    if overpay_ratio is None:
        return None
    return overpay_ratio < -0.6 or overpay_ratio > 1.5


def missing_critical_specs(
    category: str | None,
    storage_gb: float | None,
    ram_gb: float | None,
) -> bool | None:
    if storage_gb is None and ram_gb is None and not category:
        return None

    category_value = (category or "").lower()
    is_phone = any(token in category_value for token in ["phone", "mobile", "mobitel", "mobiteli"])
    if is_phone and storage_gb is None:
        return True
    if storage_gb is None and ram_gb is None:
        return True
    return False


def validate_listing_data(listing: Listing) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if listing.listing_id in (None, ""):
        errors.append("missing listing_id")
    if not listing.title:
        errors.append("missing title")
    if listing.price is None or listing.price < 0:
        errors.append("invalid price")
    return len(errors) == 0, errors
