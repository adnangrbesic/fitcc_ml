import asyncio
from playwright.async_api import async_playwright
from scraper.stealth import apply_stealth

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.3',
            viewport={'width':1920,'height':1080}
        )
        page = await context.new_page()
        # await apply_stealth(page) # Temporarily disabled to test just raw fetch. Or maybe I should enable it to mimic the engine.
        from scraper.stealth import apply_stealth
        # Since apply_stealth uses playwright_stealth.Stealth().apply_stealth_async we don't import it here but just call it
        
        await page.goto('https://olx.ba/artikal/75731603', wait_until='networkidle')
        await page.screenshot(path='test_cf.png')
        html = await page.inner_html('body')
        
        # Test the parser
        from scraper.parser import Parser
        import json
        parser = Parser()
        res = await parser.parse_listing(page)
        
        with open('test_cf.html', 'w', encoding='utf-8') as f:
            f.write(html)
            f.write("\n\n=== PARSER RESULT ===\n")
            f.write(json.dumps(res, indent=2))
        
        await browser.close()

asyncio.run(main())
