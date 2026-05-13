import os
import asyncio
import json
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

QS_USER = os.getenv("QS_USER")
QS_PASS = os.getenv("QS_PASS")

async def fetch_quikstrike_data():
    """Advanced QuikStrike Scraper - Vol2Vol Focused"""
    if not QS_USER or not QS_PASS:
        return None, "❌ ยังไม่ได้ตั้งค่า QS_USER หรือ QS_PASS ในไฟล์ .env"

    screenshots = []

    async with async_playwright() as p:
        print("Launching Vol2Vol Scraper...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            device_scale_factor=2, # เพิ่มความชัดเป็น 2 เท่า
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Login Flow (Proven method)
            print("Logging in...")
            await page.goto("https://cmegroup.quikstrike.net/Account/Login.aspx")
            await page.wait_for_load_state("networkidle")
            
            try:
                await page.get_by_text("Continue").first.click(timeout=10000)
            except:
                await page.click("a:has-text('Continue'), .login-button, #ContinueButton, input[value='Continue']")
            
            print("Filling credentials...")
            try:
                # Try multiple ways to fill Email
                try:
                    await page.get_by_label("EMAIL / USER ID").fill(QS_USER, timeout=5000)
                except:
                    await page.locator("input[type='text'], input[type='email'], #Username, #Email").first.fill(QS_USER)
                
                # Try multiple ways to fill Password
                try:
                    await page.get_by_label("PASSWORD").fill(QS_PASS, timeout=5000)
                except:
                    await page.locator("input[type='password'], #Password").first.fill(QS_PASS)
                    
                await page.get_by_role("button", name="LOG IN").click()
            except Exception as e:
                print(f"❌ Login filling failed: {e}")
                await page.screenshot(path="login_error_debug.png")
                raise e
            
            await page.wait_for_timeout(5000)

            # 2. Handle Disclaimer
            try:
                checkbox = await page.wait_for_selector("input[type='checkbox']", timeout=5000)
                if checkbox:
                    await checkbox.check()
                    await page.locator("input[value='Continue'], button:has-text('Continue')").first.click()
                    await page.wait_for_timeout(5000)
            except: pass

            # 3. Direct to Vol2Vol Gold Options
            print("Accessing Vol2Vol Gold Options...")
            # PID 40 is Gold, pf 6 is Vol2Vol often, but let's go to the main PID 40 first then click Vol2Vol
            await page.goto("https://cmegroup-sso.quikstrike.net//User/QuikStrikeView.aspx?pid=40&pf=6", wait_until="networkidle")
            await page.wait_for_timeout(5000)

            # Ensure we are on Vol2Vol tab
            try:
                await page.get_by_role("link", name="QUIKOPTIONS VOL2VOL").click(timeout=5000)
                await page.wait_for_timeout(5000)
            except: pass

            # 4. Capture 3 Views from the Sidebar within Vol2Vol
            # ปรับปรุง: พยายามเจาะจงถ่ายเฉพาะส่วนตารางข้อมูลหลัก (#quikstrike-view-main)
            main_selector = "#quikstrike-view-main, .qs-view-container, #form1"
            
            async def capture_optimized(name):
                try:
                    element = page.locator(main_selector).first
                    if await element.is_visible():
                        await element.screenshot(path=name)
                    else:
                        await page.screenshot(path=name)
                except:
                    await page.screenshot(path=name)

            # View A: Intraday (Default often)
            print("Capturing Intraday...")
            try:
                await page.get_by_text("Intraday", exact=True).first.click(timeout=3000)
                await page.wait_for_timeout(3000)
                path = "qs_intraday.png"
                await capture_optimized(path)
                screenshots.append(path)
            except: pass

            # View B: OI
            print("Capturing OI...")
            try:
                await page.get_by_text("OI", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(5000)
                path = "qs_oi.png"
                await capture_optimized(path)
                screenshots.append(path)
            except: pass

            # View C: OI Change
            print("Capturing OI Change...")
            try:
                await page.get_by_text("OI Change", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(5000)
                path = "qs_oichange.png"
                await capture_optimized(path)
                screenshots.append(path)
            except: pass

            await browser.close()
            # Remove duplicates and ensure order: Intraday, OI, OI Change
            unique_screenshots = list(dict.fromkeys(screenshots))
            return unique_screenshots, None

        except Exception as e:
            await browser.close()
            return None, str(e)

if __name__ == "__main__":
    import asyncio
    print("--- Vol2Vol Scraper Test ---")
    imgs, err = asyncio.run(fetch_quikstrike_data())
    print(f"Results: {imgs}, Error: {err}")
