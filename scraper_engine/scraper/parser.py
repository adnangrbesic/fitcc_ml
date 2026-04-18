# ---------------------------------------------------------------------------
# BuyGuardian Scraper — DOM Parser for OLX.ba
# ---------------------------------------------------------------------------
"""Extracts listing data from OLX.ba pages using CSS selectors and
``window.__INITIAL_STATE__`` JSON extraction.

Design decisions
~~~~~~~~~~~~~~~~
- **__INITIAL_STATE__ first**: OLX.ba often embeds the full listing payload
  (including phone numbers) in a ``<script>`` tag as JSON. Parsing this is
  faster, stealthier (no button clicks), and more reliable than DOM queries.
- **DOM fallback**: If the JSON blob is missing or incomplete, fall back to
  CSS selector-based extraction.
- **Never throw**: Every extraction method returns ``None`` on failure so the
  caller always gets a partial result rather than an exception.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# CSS Selector Map — single source of truth for all OLX.ba selectors.
# Update these when OLX.ba changes its markup.
# -------------------------------------------------------------------------
SELECTORS: dict[str, str] = {
    "title": "h1.main-title-listing, h4[data-cy='ad_title'], .css-1juynto, h1.css-1soizd2",
    "price": "span.price-heading, [data-testid='ad-price-container'] h3, .css-12vqlj3 h3, .css-90xrc0",
    "currency": "span.price-heading, [data-testid='ad-price-container'] p, .css-12vqlj3 p",
    "description": "div.ad-description, div[data-cy='ad_description'] div, .css-1t507yq div",
    "seller_name": ".user-info__username, h4[data-cy='seller_card_name'], .css-1lcz6o7 h4",
    "seller_link": "a.user-info__username, a[data-cy='seller_card_name'], a[href*='/profil/']",
    "seller_rating": "[data-testid='seller-rating'], .css-1dp4137",
    "account_age": ".medals-wrap, [data-cy='seller_card_since'], .css-16h6te1",
    "location": ".btn-pill.city, p[data-testid='location-date'], .css-1cju8pu",
    "promoted_badge": "[data-testid='ad-promoted-label'], .css-1kfqt1f, [data-cy='promoted']",
    "phone_reveal_btn": "button[data-cy='ad-contact-phone'], button[data-testid='show-phone']",
    "phone_number": "[data-testid='phone-number'], .css-1ij4lbz",
}


class Parser:
    """Stateless parser — extracts listing data from an OLX.ba page.

    Usage::

        parser = Parser()
        data = await parser.parse_listing(page)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse_listing(self, page: Page) -> dict[str, Any]:
        """Extract all listing fields from the current page.

        Strategy:
        1. Try ``window.__INITIAL_STATE__`` for structured JSON.
        2. Fill gaps via CSS selector queries.
        3. Compute ML-ready meta-fields (caps ratio, exclamation count).

        Returns a ``dict`` ready to be validated by ``ListingData(**data)``.
        """
        initial_state = await self._extract_initial_state(page)

        dom_data = await self._extract_from_dom(page)

        merged = {**dom_data, **(initial_state or {})}

        desc = merged.get("description") or ""
        # Clean HTML from description
        merged["description"] = self._strip_html(desc)
        
        # Detect if active
        page_content = await page.content()
        merged["is_active"] = "Oglas je završen" not in page_content and "Artikal izbrisan" not in page_content
        
        merged["description_caps_ratio"] = self._caps_ratio(merged["description"])
        merged["description_exclamation_count"] = merged["description"].count("!")

        # Parse account age to months
        if merged.get("account_age"):
            merged["account_age_months"] = self._parse_account_age(merged["account_age"])

        # Extract item_id from the URL as fallback
        if not merged.get("item_id"):
            merged["item_id"] = self._extract_item_id_from_url(page.url)

        return merged

    # ------------------------------------------------------------------
    # __INITIAL_STATE__ Extraction
    # ------------------------------------------------------------------

    async def _extract_initial_state(self, page: Page) -> Optional[dict[str, Any]]:
        """Parse ``window.__INITIAL_STATE__`` or similar JSON blobs.

        OLX.ba sometimes embeds the entire listing payload in a script tag.
        Extracting it avoids clicking "Prikaži broj" and is stealthier.
        """
        try:
            raw = await page.evaluate(
                """() => {
                    if (window.__NUXT__) return JSON.stringify(window.__NUXT__);
                    if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__);
                    if (window.__PRELOADED_STATE__) return JSON.stringify(window.__PRELOADED_STATE__);
                    if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
                    // Fallback: look for JSON-LD structured data
                    const ld = document.querySelector('script[type="application/ld+json"]');
                    if (ld) return ld.textContent;
                    return null;
                }"""
            )
            if not raw:
                return None

            blob = json.loads(raw)
            return self._normalise_initial_state(blob)
        except Exception:
            logger.debug("__INITIAL_STATE__ extraction failed, falling back to DOM")
            return None

    @staticmethod
    def _normalise_initial_state(blob: dict) -> dict[str, Any]:
        """Map the raw JSON struct to our flat field schema.

        The exact key paths depend on OLX's frontend framework version and
        may change. We search broadly and tolerate missing keys.
        """
        result: dict[str, Any] = {}

        def _deep_get(d: Any, *keys: str | int) -> Any:
            """Drill into nested dicts/lists safely."""
            for k in keys:
                if isinstance(d, dict) and isinstance(k, str):
                    d = d.get(k)
                elif isinstance(d, list) and isinstance(k, int):
                    try:
                        d = d[k]
                    except IndexError:
                        return None
                else:
                    return None
            return d

        # Attempt common OLX JSON paths
        # Nuxt path: blob.data[0].listing
        nuxt_data = _deep_get(blob, "data", 0, "listing")
        ad = nuxt_data or _deep_get(blob, "ad", "ad") or _deep_get(blob, "ad") or blob

        if isinstance(ad, dict):
            result["item_id"] = str(ad.get("id", ""))
            result["title"] = ad.get("title") or ad.get("subject")
            price_obj = ad.get("price") or {}
            if isinstance(price_obj, dict):
                result["price"] = price_obj.get("value") or price_obj.get("amount")
                result["currency"] = price_obj.get("currency") or price_obj.get("displayCurrency")
            elif isinstance(price_obj, (int, float)):
                result["price"] = float(price_obj)
            
            # Nuxt often uses display_price string
            if not result.get("price") and ad.get("display_price"):
                # display_price is often "1.320 KM"
                dp = str(ad["display_price"])
                parsed_p = Parser._parse_price(dp)
                result.update(parsed_p)
            
            desc = ad.get("description") or _deep_get(ad, "additional", "description")
            result["description"] = Parser._strip_html(desc) if desc else ""
            
            result["location"] = (
                _deep_get(ad, "location", "cityName")
                or _deep_get(ad, "location", "name")
                or _deep_get(ad, "user", "location", "name")
            )

            # Phone number — the main prize of __INITIAL_STATE__
            result["phone_number"] = (
                _deep_get(ad, "contact", "phone")
                or _deep_get(ad, "phones", 0)
            )

            # Seller info
            user = ad.get("user") or ad.get("seller") or {}
            if isinstance(user, dict):
                result["seller_id"] = str(user.get("id", ""))
                result["seller_name"] = user.get("name") or user.get("login")
                
                # Feedback counts (Dojmovi)
                result["positive_feedback"] = user.get("positive_reviews") or user.get("positiveReviews") or 0
                result["negative_feedback"] = user.get("negative_reviews") or user.get("negativeReviews") or 0
                
                # In Nuxt, medals often contain the age info and delivery count
                medals = user.get("medals") or []
                age_str = ""
                delivery_count = 0
                email_v = False
                phone_v = False
                address_v = False

                if isinstance(medals, list):
                    for m in medals:
                        if not isinstance(m, dict):
                            continue
                        m_type = m.get("type", "").lower()
                        m_text = m.get("text", "")
                        
                        if m_type == "years":
                            age_str = m_text
                        elif m_type == "delivery":
                            delivery_count = m.get("value") or 0
                        elif m_type == "verification":
                            if "email" in m_text.lower():
                                email_v = True
                            if "telefon" in m_text.lower() or "broj" in m_text.lower():
                                phone_v = True
                        elif "adres" in m_text.lower() or m_type == "address":
                            address_v = True
                
                result["account_age"] = age_str
                if not result["account_age"]:
                    # Fallback to a readable date if timestamp exists
                    raw_created = user.get("createdAt") or user.get("since")
                    if raw_created and (isinstance(raw_created, int) or str(raw_created).isdigit()):
                        try:
                            result["account_age"] = datetime.fromtimestamp(int(raw_created)).strftime("%d.%m.%Y")
                        except Exception:
                            result["account_age"] = str(raw_created)
                    else:
                        result["account_age"] = str(raw_created or "Nepoznato")

                result["successful_deliveries"] = delivery_count
                result["is_email_verified"] = email_v
                result["is_phone_verified"] = phone_v
                result["is_address_verified"] = address_v

            result["is_promoted"] = bool(ad.get("isPromoted") or ad.get("promoted"))

        # Strip None values so they don't overwrite DOM data in the merge
        return {k: v for k, v in result.items() if v is not None}

    # ------------------------------------------------------------------
    # DOM-based Extraction
    # ------------------------------------------------------------------

    async def parse_seller_feedback(self, page: Page) -> dict[str, int]:
        """Extract feedback counts from the /dojmovi page."""
        try:
            return await page.evaluate(
                """() => {
                    const getCount = (selector, textFallback) => {
                        let el = document.querySelector(selector);
                        if (el) {
                            const match = el.textContent.match(/\\d+/);
                            if (match) return parseInt(match[0], 10);
                        }
                        
                        // Fallback: find the label and look for a number in the same component
                        const allNodes = Array.from(document.querySelectorAll('p, span, div, h1, h2'));
                        const labelNode = allNodes.find(n => n.innerText && n.innerText.trim() === textFallback);
                        if (labelNode) {
                            // Look for the large number (usually h1/h2 or bold) in the same parent/container
                            const parent = labelNode.parentElement;
                            if (parent) {
                                const countEl = parent.querySelector('h1, h2, .text-xl, .font-bold, .count');
                                if (countEl) {
                                    const m = countEl.innerText.match(/\\d+/);
                                    if (m) return parseInt(m[0], 10);
                                }
                                // Second fallback: search within the parent for any digits that aren't the label itself
                                const digits = parent.innerText.replace(textFallback, '').match(/\\d+/);
                                if (digits) return parseInt(digits[0], 10);
                            }
                        }
                        return 0;
                    };
                    
                    return {
                        positive_feedback: getCount('.feedback-summary-item.positive .count, .dojmovi-zeleni', 'Pozitivni dojmovi'),
                        neutral_feedback: getCount('.feedback-summary-item.neutral .count, .dojmovi-plavi', 'Neutralni dojmovi'),
                        negative_feedback: getCount('.feedback-summary-item.negative .count, .dojmovi-crveni', 'Negativni dojmovi')
                    };
                }"""
            )
        except Exception:
            return {"positive_feedback": 0, "neutral_feedback": 0, "negative_feedback": 0}

    async def _extract_from_dom(self, page: Page) -> dict[str, Any]:
        """Extract fields via CSS selectors — the reliable fallback."""
        data: dict[str, Any] = {}

        data["title"] = await self._text(page, SELECTORS["title"])
        data["location"] = await self._text(page, SELECTORS["location"])
        data["description"] = await self._text(page, SELECTORS["description"])
        data["seller_name"] = await self._text(page, SELECTORS["seller_name"])
        data["account_age"] = await self._text(page, SELECTORS["account_age"])

        # Seller ID from profile link href
        data["seller_id"] = await self._extract_seller_id(page)

        # Seller rating
        rating_text = await self._text(page, SELECTORS["seller_rating"])
        if rating_text:
            try:
                data["seller_rating"] = float(re.sub(r"[^\d.]", "", rating_text))
            except ValueError:
                data["seller_rating"] = None

        # Price + currency
        price_text = await self._text(page, SELECTORS["price"])
        if price_text:
            data.update(self._parse_price(price_text))

        # Promoted badge
        promoted_el = await page.query_selector(SELECTORS["promoted_badge"])
        data["is_promoted"] = promoted_el is not None

        # Strip None/empty values
        return {k: v for k, v in data.items() if v is not None and v != ""}

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    @staticmethod
    async def _text(page: Page, selector: str) -> Optional[str]:
        """Safely extract text content from the first matching element."""
        try:
            el = await page.query_selector(selector)
            if el:
                text = await el.text_content()
                return text.strip() if text else None
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    async def _extract_seller_id(page: Page) -> Optional[str]:
        """Extract seller ID from the profile link href."""
        try:
            el = await page.query_selector(SELECTORS["seller_link"])
            if el:
                href = await el.get_attribute("href")
                if href:
                    match = re.search(r"/profil/([^/?#]+)", href)
                    return match.group(1) if match else href.split("/")[-1]
        except Exception:  
            pass
        return None

    @staticmethod
    def _parse_price(raw: str) -> dict[str, Any]:
        """Parse price string like '1.800 KM' into numeric value + currency."""
        result: dict[str, Any] = {}
        clean = raw.replace("\xa0", " ").strip()

        num_match = re.search(r"([\d.,]+)", clean)
        if num_match:
            num_str = num_match.group(1)
            if "." in num_str and "," in num_str:
                num_str = num_str.replace(".", "").replace(",", ".")
            elif "." in num_str:
                parts = num_str.split(".")
                if len(parts[-1]) == 3:
                    num_str = num_str.replace(".", "")
            elif "," in num_str:
                num_str = num_str.replace(",", ".")
            try:
                result["price"] = float(num_str)
            except ValueError:
                pass

        # Extract currency (KM, EUR, etc.)
        currency_match = re.search(r"(KM|EUR|€|USD|\$|BAM)", clean, re.IGNORECASE)
        if currency_match:
            result["currency"] = currency_match.group(1).upper()

        return result

    @staticmethod
    def _extract_item_id_from_url(url: str) -> str:
        """Extract listing ID from a URL like olx.ba/artikal/12345678."""
        match = re.search(r"/artikal/(\d+)", url)
        if match:
            return match.group(1)
        nums = re.findall(r"(\d{5,})", url)
        return nums[-1] if nums else url.split("/")[-1]

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and normalise whitespace for NLP."""
        if not text:
            return ""
        # Remove tags
        clean = re.sub(r"<[^>]*>", " ", text)
        # Normalise entities (some basic ones)
        clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
        # Collapse whitespace
        return re.sub(r"\s+", " ", clean).strip()

    @staticmethod
    def _parse_account_age(text: str) -> int:
        """Convert account age string to total months.
        
        Handles:
        - "više od 10 godina" -> 120
        - "5 godina" -> 60
        - "6 mjeseci" -> 6
        - "2015-04-01" or "april 2015" -> computed difference
        """
        if not text:
            return 0
        
        text = text.lower()
        
        # 1. Check for years
        year_match = re.search(r"(\d+)\s*godin", text)
        if year_match:
            return int(year_match.group(1)) * 12
            
        # 2. Check for months
        month_match = re.search(r"(\d+)\s*mjesec", text)
        if month_match:
            return int(month_match.group(1))
            
        # 3. Check for dates (e.g. "2015-04-10")
        date_match = re.search(r"(\d{4})[-.](\d{2})", text)
        if date_match:
            from datetime import datetime
            y, m = int(date_match.group(1)), int(date_match.group(2))
            now = datetime.now()
            return (now.year - y) * 12 + (now.month - m)
            
        return 0

    @staticmethod
    def _caps_ratio(text: str) -> float:
        """Compute the ratio of uppercase letters in a string (0.0–1.0)."""
        if not text:
            return 0.0
        alpha = [c for c in text if c.isalpha()]
        if not alpha:
            return 0.0
        return sum(1 for c in alpha if c.isupper()) / len(alpha)
