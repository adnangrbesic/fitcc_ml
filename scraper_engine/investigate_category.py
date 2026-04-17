import asyncio
import json
import re
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # Search for "Auto" category (id 18)
        await page.goto('https://olx.ba/pretraga?kategorija=18', wait_until='domcontentloaded')
        
        # Check __INITIAL_STATE__
        state = await page.evaluate('''() => {
            if (window.__INITIAL_STATE__) return window.__INITIAL_STATE__;
            if (window.__PRELOADED_STATE__) return window.__PRELOADED_STATE__;
            return null;
        }''')
        
        if state:
            with open('state.json', 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            print("Saved state to state.json")
        
        html = await page.inner_html('body')
        urls = set(re.findall(r'href="(/artikal/\d+.*?)"', html))
        print('Found URLs:', list(urls)[:5])
        
        await browser.close()

asyncio.run(run())
