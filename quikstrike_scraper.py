import os
import sys
import asyncio
import json
from playwright.async_api import async_playwright
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


load_dotenv()

QS_USER = os.getenv("QS_USER")
QS_PASS = os.getenv("QS_PASS")

async def fetch_quikstrike_data(expiry_type="daily", max_retries=2):
    """
    Advanced QuikStrike Scraper with automatic retry logic if 0 images are returned.
    """
    last_err = None
    for attempt in range(1, max_retries + 2):
        if attempt > 1:
            print(f"[RETRY] Attempt {attempt} of {max_retries + 1} for {expiry_type} after failure/0 images...")
            await asyncio.sleep(20) # wait 20 seconds before retry
            
        images, err = await _fetch_quikstrike_data_once(expiry_type)
        if not err and images and len(images) > 0:
            return images, None
            
        last_err = err if err else "Returned 0 images"
        print(f"[WARNING] Attempt {attempt} failed: {last_err}")
        
    return None, f"Failed after {max_retries + 1} attempts. Last error: {last_err}"


async def _fetch_quikstrike_data_once(expiry_type="daily"):
    """
    Advanced QuikStrike Scraper - Vol2Vol Focused (single attempt)
    
    expiry_type: "daily"   = สัญญา 0DTE/รายวัน (default)
                 "weekly"  = สัญญารายสัปดาห์ (หมดอายุวันศุกร์)
                 "monthly" = สัญญารายเดือน (หมดอายุสิ้นเดือน)
    """
    if not QS_USER or not QS_PASS:
        return None, "❌ ยังไม่ได้ตั้งค่า QS_USER หรือ QS_PASS ในไฟล์ .env"

    screenshots = []
    prefix = {"daily": "qs", "weekly": "qs_weekly", "monthly": "qs_monthly"}.get(expiry_type, "qs")


    async with async_playwright() as p:
        print(f"Launching Vol2Vol Scraper (expiry_type={expiry_type})...")
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
            viewport={'width': 1280, 'height': 900},
            device_scale_factor=2,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Login Flow
            print("Logging in...")
            # เพิ่ม timeout เป็น 60 วินาที และ wait_until=domcontentloaded เพื่อป้องกัน timeout
            await page.goto(
                "https://cmegroup.quikstrike.net/Account/Login.aspx",
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_timeout(3000)

            try:
                await page.get_by_text("Continue").first.click(timeout=15000)
                await page.wait_for_timeout(3000)
            except:
                try:
                    await page.click("a:has-text('Continue'), .login-button, #ContinueButton, input[value='Continue']", timeout=5000)
                    await page.wait_for_timeout(2000)
                except:
                    pass

            print("Filling credentials...")
            try:
                try:
                    await page.get_by_label("EMAIL / USER ID").fill(QS_USER, timeout=10000)
                except:
                    await page.locator("input[type='text'], input[type='email'], #Username, #Email").first.fill(QS_USER)

                try:
                    await page.get_by_label("PASSWORD").fill(QS_PASS, timeout=10000)
                except:
                    await page.locator("input[type='password'], #Password").first.fill(QS_PASS)

                await page.get_by_role("button", name="LOG IN").click()
            except Exception as e:
                print(f"[ERROR] Login filling failed: {e}")
                await page.screenshot(path="login_error_debug.png")
                raise e

            await page.wait_for_timeout(8000)

            # 2. Handle Disclaimer (Post-Login)
            await _handle_disclaimer(page, timeout=5000)

            # 3. Navigate to Vol2Vol Gold Options
            print("Accessing Vol2Vol Gold Options...")
            await page.goto(
                "https://cmegroup-sso.quikstrike.net//User/QuikStrikeView.aspx?pid=40&pf=6",
                wait_until="domcontentloaded",
                timeout=120000
            )
            await page.wait_for_timeout(10000)

            # Handle Disclaimer (Post-Navigation)
            await _handle_disclaimer(page, timeout=15000)

            # Ensure we are on Vol2Vol tab
            try:
                await page.get_by_role("link", name="QUIKOPTIONS VOL2VOL").click(timeout=15000)
                await page.wait_for_timeout(20000)
            except:
                pass

            # 4. เลือก Expiry Tab ตาม expiry_type
            if expiry_type != "daily":
                await _select_expiry_tab(page, expiry_type)

            # 5. Capture 3 Views: Intraday, OI, OI Change
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

            # View A: Intraday
            print("Capturing Intraday...")
            try:
                await page.get_by_text("Intraday", exact=True).first.click(timeout=15000)
                await page.wait_for_timeout(20000)
                path = f"{prefix}_intraday.png"
                await capture_optimized(path)
                screenshots.append(path)
            except:
                pass

            # View B: OI
            print("Capturing OI...")
            try:
                await page.get_by_text("OI", exact=True).first.click(timeout=15000)
                await page.wait_for_timeout(20000)
                path = f"{prefix}_oi.png"
                await capture_optimized(path)
                screenshots.append(path)
            except:
                pass

            # View C: OI Change
            print("Capturing OI Change...")
            try:
                await page.get_by_text("OI Change", exact=True).first.click(timeout=15000)
                await page.wait_for_timeout(20000)
                path = f"{prefix}_oichange.png"
                await capture_optimized(path)
                screenshots.append(path)
            except:
                pass

            await browser.close()
            unique_screenshots = list(dict.fromkeys(screenshots))
            print(f"[SUCCESS] Done: {len(unique_screenshots)} screenshots captured.")
            return unique_screenshots, None

        except Exception as e:
            try:
                await browser.close()
            except:
                pass
            return None, str(e)


async def _select_expiry_tab(page, expiry_type):
    """
    พยายามคลิก Tab สัญญาให้ตรงกับ expiry_type ที่ต้องการ
    QuikStrike แสดง Tab รายสัญญาเป็น row ของ expiry dates
    - weekly:  คลิก Tab ที่มี DTE มากที่สุด (สัปดาห์หน้า/สัปดาห์นี้ = DTE ~5-7)
    - monthly: คลิก Tab ที่มี DTE มากที่สุดในรายการ (เดือนนี้/เดือนหน้า = DTE ~20-45)
    """
    print(f"Selecting expiry tab: {expiry_type}...")
    try:
        # ก่อนอื่นเปลี่ยน label dropdown ให้แสดง DTE เพื่อให้อ่าน tab ง่ายขึ้น
        ddl = page.locator("#ctl00_MainContent_ucViewControl_OptionsInfo_ucExpirationTabs_ddlLabels")
        await ddl.select_option(label="DTE", timeout=5000)
        await page.wait_for_timeout(3000)
    except:
        pass

    try:
        # ดึง Tab ทั้งหมดบนหน้า (expiry tabs ของ QuikStrike มักเป็น li หรือ a ในกลุ่ม tab container)
        tabs = await page.evaluate("""() => {
            const results = [];
            // หาปุ่มหรือลิงก์ที่อยู่ใน tab list ของ expiration
            const tabContainers = document.querySelectorAll(
                'ul.expiration-tabs li, .expiration-tab, .qs-expiry-tab, ' +
                '[id*="expiry"] a, [id*="Expiry"] a, [class*="expiry-tab"], ' +
                'ul.nav-tabs li a, .tab-content, #tabstrip li'
            );
            tabContainers.forEach((el, idx) => {
                results.push({
                    idx,
                    tag: el.tagName,
                    id: el.id || '',
                    className: el.className || '',
                    text: (el.innerText || '').trim(),
                    href: el.href || ''
                });
            });
            return results;
        }""")

        if tabs:
            print(f"Found {len(tabs)} expiry tabs:")
            for t in tabs[:20]:
                print(f"  [{t['idx']}] {t['tag']} text='{t['text']}' id='{t['id']}'")
        else:
            print("No expiry tabs found via standard selectors, trying fallback...")
    except Exception as e:
        print(f"Tab search error: {e}")

    # Fallback: หา Tab ด้วย text ที่บ่งบอกถึงประเภทสัญญา
    if expiry_type == "weekly":
        # Weekly options มักมี text ว่า "W" หรือวันที่ในสัปดาห์ข้างหน้า
        for selector_text in ["Weekly", "W1", "Wk"]:
            try:
                await page.get_by_text(selector_text, exact=False).first.click(timeout=3000)
                await page.wait_for_timeout(5000)
                print(f"[SUCCESS] Clicked weekly tab: {selector_text}")
                return
            except:
                pass
    elif expiry_type == "monthly":
        for selector_text in ["Monthly", "MON", "Front Month"]:
            try:
                await page.get_by_text(selector_text, exact=False).first.click(timeout=3000)
                await page.wait_for_timeout(5000)
                print(f"[SUCCESS] Clicked monthly tab: {selector_text}")
                return
            except:
                pass

    print(f"[WARNING] Could not auto-select {expiry_type} tab, using default (current front contract)")


async def _handle_disclaimer(page, timeout=8000):
    """
    เช็คและกดยอมรับข้อตกลง/คำเตือน (Disclaimer) หากปรากฏบนหน้าจอ
    """
    try:
        checkbox = await page.wait_for_selector("input[type='checkbox']", timeout=timeout)
        if checkbox:
            print("[INFO] Disclaimer checkbox found, checking it...")
            await checkbox.check()
            await page.wait_for_timeout(1000)
            btn = page.locator("input[value='Continue'], button:has-text('Continue'), button:has-text('Accept')").first
            await btn.click()
            print("[INFO] Clicked disclaimer Continue button.")
            await page.wait_for_timeout(5000)
            return True
    except:
        pass
    return False


if __name__ == "__main__":
    import asyncio
    print("--- Vol2Vol Scraper Test (daily) ---")
    imgs, err = asyncio.run(fetch_quikstrike_data("daily"))
    print(f"Results: {imgs}, Error: {err}")
