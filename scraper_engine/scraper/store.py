# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Persistent Storage
# ---------------------------------------------------------------------------
"""JSON-based persistence for tracking listing history across runs."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from scraper.models import ListingData

logger = logging.getLogger(__name__)


class JSONStore:
    """Manages a JSON file containing a history of all seen listings."""

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        self.data: Dict[str, ListingData] = {}
        self.load()

    def load(self) -> None:
        """Load listings from the JSON file."""
        if not self.file_path.exists():
            self.data = {}
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                if not isinstance(raw_list, list):
                    logger.warning("Store file %s is not a list, starting fresh", self.file_path)
                    self.data = {}
                    return
                
                self.data = {
                    item["item_id"]: ListingData(**item)
                    for item in raw_list
                }
            logger.info("Loaded %d listings from history (%s)", len(self.data), self.file_path)
        except Exception as e:
            logger.error("Failed to load history from %s: %s", self.file_path, e)
            self.data = {}

    def save(self) -> None:
        """Save the current state to the JSON file."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            # Sort by last_seen_at desc for easier manual inspection
            sorted_items = sorted(
                self.data.values(),
                key=lambda x: x.last_seen_at,
                reverse=True
            )
            raw_list = [item.model_dump(mode="json") for item in sorted_items]
            
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(raw_list, f, indent=2, ensure_ascii=False, default=str)
            logger.info("Saved %d listings to %s", len(self.data), self.file_path)
        except Exception as e:
            logger.error("Failed to save history to %s: %s", self.file_path, e)

    def upsert(self, listing: ListingData) -> None:
        """Update an existing listing or insert a new one."""
        self.data[listing.item_id] = listing

    def get_all(self) -> List[ListingData]:
        """Return all stored listings."""
        return list(self.data.values())

    def get_by_id(self, item_id: str) -> Optional[ListingData]:
        """Fetch a specific listing by ID."""
        return self.data.get(item_id)

    def get_stale_active_listings(self, current_run_ids: List[str], query: Optional[str] = None) -> List[ListingData]:
        """
        Identify listings that are marked as active but weren't seen in the current run.
        If a query is provided, only check listings that match that query context.
        """
        stale = []
        for item_id, listing in self.data.items():
            if not listing.is_active:
                continue
            if item_id in current_run_ids:
                continue
            
            # If we are doing a specific query (e.g. S25), only check items 
            # that were originally found for that query to avoid checking everything.
            if query:
                q_lower = query.lower()
                if q_lower not in listing.title.lower():
                    continue
            
            stale.append(listing)
        return stale
