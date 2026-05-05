import os
import asyncio
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

QS_USER = os.getenv("QS_USER")
QS_PASS = os.getenv("QS_PASS")

async def fetch_quikstrike_data():
    """Logs into QuikStrike and captures screenshots of Gold Options data"""
    if not QS_USER or not QS_PASS:
        return None, "Missing QS_USER or QS_PASS in environment variables."

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1000})
        page = await context.new_page()

        try:
            # 1. Go to Login Page
            print("🚀 Navigating to QuikStrike Login...")
            await page.goto("https://cmegroup.quikstrike.net/Account/Login.aspx", wait_until="networkidle")

            # 2. Perform Login (SSO)
            # Standard CME SSO fields
            if await page.query_selector("input#email"):
                await page.fill("input#email", QS_USER)
                await page.click("button#nextButton") # Sometimes there is a next button
                await page.wait_for_timeout(1000)
                
            if await page.query_selector("input#password"):
                await page.fill("input#password", QS_PASS)
                await page.click("button#loginButton")
            else:
                # Direct ASP.NET login
                await page.fill("input[name*='UserName']", QS_USER)
                await page.fill("input[name*='Password']", QS_PASS)
                await page.click("input[type='submit']")

            await page.wait_for_load_state("networkidle")
            print("✅ Login Successful")

            # 3. Navigate to Gold Options Tool
            # This URL might need adjustment based on the specific QuikStrike tool used
            gold_url = "https://cmegroup.quikstrike.net/User/QuikStrikeView.aspx?view=GoldOptions" # Placeholder
            await page.goto(gold_url, wait_until="networkidle")
            
            # 4. Capture Screenshots
            screenshots = []
            
            # Example: Capture Intraday Volume
            # We would need to click the right tabs here
            await page.screenshot(path="qs_volume.png")
            screenshots.append("qs_volume.png")
            
            # Example: Capture OI
            # await page.click("text=Open Interest")
            # await page.wait_for_timeout(2000)
            # await page.screenshot(path="qs_oi.png")
            # screenshots.append("qs_oi.png")

            await browser.close()
            return screenshots, None

        except Exception as e:
            await browser.close()
            return None, str(e)

if __name__ == "__main__":
    # Test run
    imgs, err = asyncio.run(fetch_quikstrike_data())
    if err:
        print(f"❌ Error: {err}")
    else:
        print(f"✅ Success! Captured {len(imgs)} images.")
