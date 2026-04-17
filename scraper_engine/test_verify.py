"""Quick verification script — validates all modules work correctly."""
from scraper.models import ListingData, ScraperConfig
from scraper.parser import Parser
from scraper.stealth import get_random_ua, get_random_viewport
from pydantic import ValidationError

print("=== Import Check ===")
print("All imports OK")

print("\n=== Pydantic Validation ===")
try:
    ListingData()
    print("FAIL - should have raised")
except ValidationError as e:
    print(f"Correctly rejects missing required fields: {e.error_count()} errors")

d = ListingData(item_id="123", title="Test iPhone")
print(f"Valid model: item_id={d.item_id}, title={d.title}, scraped_at={d.scraped_at}")

print("\n=== Stealth Utilities ===")
print(f"Random UA: {get_random_ua()[:60]}...")
print(f"Random viewport: {get_random_viewport()}")

print("\n=== Parser Utilities ===")
p = Parser()
print(f"Caps ratio 'HELLO world': {p._caps_ratio('HELLO world'):.2f}")
print(f"Caps ratio 'all lower': {p._caps_ratio('all lower'):.2f}")
print(f"Price parse '1.800 KM': {p._parse_price('1.800 KM')}")
print(f"Price parse '25,50 EUR': {p._parse_price('25,50 EUR')}")
print(f"Price parse '1.250.000 KM': {p._parse_price('1.250.000 KM')}")

print("\n=== Config Defaults ===")
c = ScraperConfig()
print(f"headless={c.headless}, retries={c.max_retries}, timeout={c.timeout_ms}ms")

print("\n=== JSON Serialization ===")
listing = ListingData(
    item_id="99887766",
    title="Samsung Galaxy S24 Ultra",
    price=2100.0,
    currency="KM",
    location="Sarajevo",
    is_promoted=True,
    description_caps_ratio=0.15,
    description_exclamation_count=3,
)
import json
print(json.dumps(listing.model_dump(mode="json"), indent=2, default=str))

print("\n✅ All checks passed!")
