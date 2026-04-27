import asyncio
from playwright.async_api import async_playwright
from scraper.parser import Parser
import json
import sys

async def test_urls(urls):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        parser = Parser()
        
        results = []
        for url in urls:
            page = await context.new_page()
            print(f"[+] Testing: {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                data = await parser.parse_listing(page)
                
                results.append({
                    "url": url,
                    "title": data.get("title"),
                    "category": data.get("breadcrumbs"),
                    "specs_count": len(data.get("raw_specs", {})),
                    "sample_specs": dict(list(data.get("raw_specs", {}).items())[:5])
                })
            except Exception as e:
                print(f"[-] Failed {url}: {e}")
            finally:
                await page.close()
        
        print("\n=== TEST RESULTS ===")
        print(json.dumps(results, indent=2, ensure_ascii=False))
        await browser.close()

if __name__ == "__main__":
    test_list = [
        "https://olx.ba/artikal/75942148",
        "https://olx.ba/artikal/75266283",
        "https://olx.ba/artikal/75079842",
        "https://olx.ba/artikal/75843858",
        "https://olx.ba/artikal/75610858"
    ]
    asyncio.run(test_urls(test_list))
