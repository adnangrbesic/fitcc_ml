import asyncio
from playwright.async_api import async_playwright
from scraper.parser import Parser
import json

async def test():
    url = "https://olx.ba/artikal/76101261"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"[+] Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")
        
        parser = Parser()
        print("[+] Parsing listing...")
        data = await parser.parse_listing(page)
        
        print("\n=== PARSED DATA ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
