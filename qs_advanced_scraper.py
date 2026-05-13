import os
import asyncio
import json
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

QS_USER = os.getenv("QS_USER")
QS_PASS = os.getenv("QS_PASS")

async def fetch_qs_advanced():
    """Advanced QuikStrike Scraper for Open Interest Profile and Intraday Data"""
    if not QS_USER or not QS_PASS:
        return None, "❌ Missing QS_USER or QS_PASS in .env"

    results = {
        "screenshots": [],
        "data": {}
    }

    async with async_playwright() as p:
        print("Launching Browser with bot evasion...")
        browser = await p.chromium.launch(headless=True)
        # Use a real-looking User Agent
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Login
            print("Logging in to QuikStrike...")
            await page.goto("https://cmegroup.quikstrike.net/Account/Login.aspx")
            await page.wait_for_load_state("networkidle")
            
            # Click 'Continue' on the initial landing page
            print("Clicking Continue on landing page...")
            try:
                await page.get_by_text("Continue").first.click(timeout=10000)
            except:
                await page.click("a:has-text('Continue'), .login-button, #ContinueButton, input[value='Continue']")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            
            await page.screenshot(path="login_page_real.png")
            print("Filling credentials on real login page...")
            
            # Fill by labels or generic selectors
            try:
                await page.get_by_label("EMAIL / USER ID").fill(QS_USER)
                await page.get_by_label("PASSWORD").fill(QS_PASS)
            except:
                await page.locator("input[type='text'], input[type='email']").first.fill(QS_USER)
                await page.locator("input[type='password']").first.fill(QS_PASS)
                
            print("Clicking LOG IN button...")
            await page.get_by_role("button", name="LOG IN").click()
            
            # Wait for navigation or error
            await page.wait_for_timeout(5000)
            await page.screenshot(path="after_login.png")
            await page.wait_for_load_state("networkidle")

            # Handle Agreement
            try:
                print("Checking for disclaimer agreement...")
                checkbox = await page.wait_for_selector("input[type='checkbox']", timeout=10000)
                if checkbox:
                    await checkbox.check()
                    print("Checked the agreement box")
                    # Find the Continue button in the disclaimer
                    await page.wait_for_timeout(1000)
                    btn = page.locator("input[value='Continue'], button:has-text('Continue'), button:has-text('Accept')").first
                    await btn.click()
                    print("Clicked disclaimer Continue button")
                    await page.wait_for_timeout(5000)
                    await page.screenshot(path="after_disclaimer.png")
                    await page.wait_for_load_state("networkidle")
            except Exception as e:
                print(f"No disclaimer found or already accepted: {e}")

            # 2. Go to Gold Options (PID 40) - Re-navigate just in case
            print("Navigating to Gold Options (PID 40)...")
            await page.goto("https://cmegroup-sso.quikstrike.net//User/QuikStrikeView.aspx?pid=40&pf=6", wait_until="networkidle")
            await page.wait_for_timeout(5000)
            await page.screenshot(path="gold_page_debug.png")

            # 3. View 1: OI (Open Interest)
            print("Accessing OI...")
            try:
                # Click 'OPEN INTEREST' in the top menu to be sure
                await page.get_by_role("link", name="OPEN INTEREST").click(timeout=5000)
                await page.wait_for_timeout(3000)
                
                # Try clicking OI in sidebar with various selectors
                await page.get_by_text("OI", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(5000)
                
                path_oi = "qs_oi.png"
                await page.screenshot(path=path_oi, full_page=True)
                results["screenshots"].append(path_oi)
                print(f"Captured: {path_oi}")
            except Exception as e:
                print(f"Could not capture OI: {e}")

            # 4. View 2: OI Change
            print("Accessing OI Change...")
            try:
                await page.get_by_text("OI Change", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(5000)
                
                path_oichg = "qs_oichange.png"
                await page.screenshot(path=path_oichg, full_page=True)
                results["screenshots"].append(path_oichg)
                print(f"Captured: {path_oichg}")
            except Exception as e:
                print(f"Could not capture OI Change: {e}")

            # 5. View 3: Intraday (VOL2VOL)
            print("Accessing Intraday (VOL2VOL)...")
            try:
                await page.get_by_role("link", name="QUIKOPTIONS VOL2VOL").click(timeout=5000)
                await page.wait_for_timeout(5000)
                
                path_intra = "qs_intraday.png"
                await page.screenshot(path=path_intra, full_page=True)
                results["screenshots"].append(path_intra)
                print(f"Captured: {path_intra}")
            except Exception as e:
                print(f"Could not capture Intraday: {e}")

            # 5. Bonus: Volatility Smile
            print("Accessing Volatility Smile...")
            try:
                await page.get_by_text("Volatility Smile", exact=False).first.click(timeout=5000)
                await page.wait_for_timeout(3000)
                
                path_smile = "qs_smile.png"
                await page.screenshot(path=path_smile)
                results["screenshots"].append(path_smile)
                print(f"Captured: {path_smile}")
            except Exception: pass

            await browser.close()
            return results, None

        except Exception as e:
            await page.screenshot(path="qs_error.png")
            await browser.close()
            return None, str(e)

if __name__ == "__main__":
    import asyncio
    print("--- Advanced Scraper Test ---")
    res, err = asyncio.run(fetch_qs_advanced())
    if err: print(f"Error: {err}")
    else: print(f"Success! Data: {json.dumps(res['data'], indent=2)}")
