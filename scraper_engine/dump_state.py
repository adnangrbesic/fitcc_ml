import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.3"
        )
        await page.goto('https://olx.ba/artikal/75731603', wait_until='networkidle')
        
        state = await page.evaluate('''() => {
            if (window.__INITIAL_STATE__) return window.__INITIAL_STATE__;
            if (window.__PRELOADED_STATE__) return window.__PRELOADED_STATE__;
            if (window.__NEXT_DATA__) return window.__NEXT_DATA__;
            return null;
        }''')
        
        with open('olx_state.json', 'w', encoding='utf-8') as f:
            json.dump(state or {}, f, indent=2)
        
        await browser.close()

asyncio.run(main())
