import os
import asyncio
import io
import sys
import re
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from datetime import datetime, time, timedelta, timezone
from dotenv import load_dotenv
from google import genai
import PIL.Image
import yfinance as yf
from database import Database
from pdf_export import generate_pdf
from image_export import generate_image
from quikstrike_scraper import fetch_quikstrike_data
from macro_news import get_combined_macro_news
from accuracy_report import generate_accuracy_dashboard

# --- LOGGING SETUP ---
def log_msg(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg, flush=True)
    with open("bot_debug.log", "a", encoding="utf-8") as f:
        f.write(full_msg + "\n")

# Load .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("STANDALONE_BOT_TOKEN")
MY_CHAT_ID = os.getenv("USER_CHAT_ID")

# ดึง Token ของบอทตัวแรก
MAIN_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
main_bot_client = Bot(token=MAIN_BOT_TOKEN) if MAIN_BOT_TOKEN else None

log_msg(f"Bot config loaded. Target Chat ID: {MY_CHAT_ID}")
if main_bot_client:
    log_msg("✅ Main Bot Token detected. Forwarding configuration active.")

# --- GEMINI & DATABASE SETUP ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None

db = Database()
user_photos = {}
user_context = {}  # {user_id: {"last_analysis": str, "timestamp": str}}

def get_system_prompt():
    """Load the system prompt from gold_options_prompt.md"""
    try:
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gold_options_prompt.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are an AI assistant analyzing Gold Options images."

async def get_macro_context():
    """Fetch current macro data (Yields, DXY, COT)"""
    context = ""
    try:
        # Fetch US 10Y Yield and DXY
        yield_ticker = yf.Ticker("^TNX")
        dxy_ticker = yf.Ticker("DX-Y.NYB")
        
        y_data = yield_ticker.history(period="1d")
        d_data = dxy_ticker.history(period="1d")
        
        cur_yield = y_data['Close'].iloc[-1] if not y_data.empty else "N/A"
        cur_dxy = d_data['Close'].iloc[-1] if not d_data.empty else "N/A"
        
        context += f"--- Real-time Macro Data ---\n"
        context += f"US 10Y Yield: {cur_yield}\n"
        context += f"Dollar Index (DXY): {cur_dxy}\n\n"
        
        # Fetch latest COT from DB
        cot_record = await db.get_macro_data("cot_summary")
        if cot_record:
            context += f"--- Institutional Sentiment (COT) ---\n"
            context += f"Updated: {cot_record['updated_at']}\n"
            context += f"{cot_record['value']}\n\n"
            
        # Fetch Macro News
        context += get_combined_macro_news()
        
    except Exception as e:
        log_msg(f"⚠️ Error fetching macro context: {e}")
        
    return context

def extract_summary(text):
    """Extract a short bias summary from the analysis result"""
    patterns = [
        r'สรุป Bias.*?\n\*?\*?\[?(Bullish|Bearish|Neutral[^\]]*)\]?\*?\*?',
        r'\*\*(Bullish|Bearish|Neutral)[^\*]*\*\*',
        r'(Bullish|Bearish|Neutral)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:100]
    return "วิเคราะห์เสร็จสมบูรณ์"

def extract_z5_score(text):
    """Extract Total Score / Sentiment Score from the scorecard or trade setup"""
    patterns = [
        r'TOTAL SCORE\s*\|\s*[^\|]*\s*\|\s*\[?([-+]?\d+)/7\]?',
        r'Score\s*\[?([-+]?\d+)/7\]?',
        r'Score\s*([-+]?\d+)/7'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None

def extract_key_levels(text):
    """Extract Max Pain and GEX Flip Zone from the text"""
    max_pain = None
    gex_zone = None
    
    mp_match = re.search(r'Max Pain(?:\s*Zone)?:\s*(?:Strike\s*)?\[?(\d+\.?\d*)\]?', text, re.IGNORECASE)
    if mp_match:
        max_pain = float(mp_match.group(1))
        
    gex_match = re.search(r'GEX Flip(?:\s*Zone|\s*Level)?:\s*(?:Strike\s*)?\[?(\d+\.?\d*)\]?', text, re.IGNORECASE)
    if gex_match:
        gex_zone = float(gex_match.group(1))
        
    return max_pain, gex_zone

def extract_expected_range(text):
    """Extract 1SD Expected Range from the table"""
    high = None
    low = None
    
    pattern = r'1SD \(68%\)\s*\|\s*(\d+\.?\d*)\s*\|\s*(\d+\.?\d*)'
    match = re.search(pattern, text)
    if match:
        high = float(match.group(1))
        low = float(match.group(2))
        
    return high, low

async def safe_reply(message, text):
    """Send message with Markdown using message.reply_text"""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode='Markdown')
        except Exception:
            try:
                await message.reply_text(chunk)
            except Exception as e:
                log_msg(f"❌ safe_reply error: {e}")

async def safe_send(context_bot, chat_id, text):
    """Send message with Markdown using bot.send_message"""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await context_bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
        except Exception:
            try:
                await context_bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as e:
                log_msg(f"❌ safe_send error: {e}")

async def run_and_save_analysis(user_id, photos):
    """Core logic to run analysis and save to DB/PDF"""
    try:
        if not gemini_client:
            return None, "Missing Gemini API Key"

        async def generate_with_retry(contents, model_name='gemini-2.5-flash', max_retries=4):
            backoff_times = [5, 15, 45, 90]  # exponential backoff in seconds
            for i in range(max_retries):
                try:
                    # Run synchronous Gemini SDK in a thread to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: gemini_client.models.generate_content(
                            model=model_name,
                            contents=contents
                        )
                    )
                    return resp, None
                except Exception as e:
                    err_str = str(e)
                    is_quota = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
                    if is_quota and i < max_retries - 1:
                        wait_time = backoff_times[i]
                        log_msg(f"⚠️ Quota hit (429). Retrying in {wait_time}s... (Attempt {i+1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                    return None, err_str
            return None, "Max retries exceeded"

        # Open image files/bytes
        images = []
        for p in photos:
            if isinstance(p, (bytes, bytearray)):
                images.append(PIL.Image.open(io.BytesIO(p)))
            elif isinstance(p, str):  # file path
                images.append(PIL.Image.open(p))
            else:
                images.append(p)

        prompt = get_system_prompt()
        
        # Add Macro Context
        macro_ctx = await get_macro_context()
        
        # Fetch previous analysis context from database if exists
        prev_analysis_ctx = ""
        try:
            prev_analysis = await db.get_latest_analysis(user_id)
            if prev_analysis and prev_analysis['result_text']:
                prev_analysis_ctx = (
                    "\n--- ข้อมูลผลวิเคราะห์รอบก่อนหน้า (ใช้สำหรับเปรียบเทียบแนวโน้ม/การขยับของเกณฑ์และ Strike) ---\n"
                    f"บันทึกเมื่อ: {prev_analysis['timestamp']}\n"
                    f"{prev_analysis['result_text']}\n"
                    "--- สิ้นสุดข้อมูลผลวิเคราะห์รอบก่อนหน้า ---\n\n"
                )
                log_msg(f"Loaded previous analysis (ID: {prev_analysis['id']}) for user {user_id}")
        except Exception as e:
            log_msg(f"⚠️ Error loading previous analysis from DB: {e}")

        full_prompt = f"{prompt}\n\n{macro_ctx}\n\n{prev_analysis_ctx}โปรดวิเคราะห์รูปภาพที่แนบมาโดยใช้ข้อมูล Macro และเปรียบเทียบความเปลี่ยนแปลงจากประวัติการวิเคราะห์ก่อนหน้า (ถ้ามี)"
        
        response, a_err = await generate_with_retry([full_prompt] + images)
        if a_err:
            return None, a_err
        
        result = response.text

        # Save context for follow-up chat
        now_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d %H:%M:%S')
        user_context[user_id] = {
            "last_analysis": result,
            "timestamp": now_str,
        }

        # Extract stats for DB
        summary = extract_summary(result)
        z5 = extract_z5_score(result)
        max_pain, gex = extract_key_levels(result)
        high_1sd, low_1sd = extract_expected_range(result)
        
        analysis_id = await db.save_analysis(user_id, result, len(photos), summary, z5, gex, max_pain, high_1sd, low_1sd)
        await db.cleanup_old_history(user_id, keep_count=20)

        # Generate Image
        img_bytes = generate_image(result, now_str)
        
        # Generate PDF
        pdf_bytes = generate_pdf(result, now_str)
        filename = f"Gold_Analysis_{analysis_id}_{now_str.split(' ')[0]}.pdf"
        filepath = os.path.join("exports", filename)
        os.makedirs("exports", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)

        return {
            "id": analysis_id,
            "text": result,
            "image_bytes": img_bytes,
            "pdf_path": filepath
        }, None

    except Exception as e:
        return None, str(e)


# --- CONFIG ---
BANGKOK_TZ = timezone(timedelta(hours=7))

# ช่วงเวลาให้บอทส่งรูปอัตโนมัติ
DAILY_START_HOUR = 8    # 0DTE เริ่ม 08:00
DAILY_END_HOUR = 23     # 0DTE สิ้นสุด 23:30
WEEKLY_HOUR = 7         # Weekly ทุกวันทำการ 07:00
WEEKLY_MINUTE = 0

MARKET_CLOSED_DAYS = {5, 6}  # เสาร์ = 5, อาทิตย์ = 6
MONTHLY_DAYS = {1, 15}       # วันที่ 1 และ 15 ของเดือน = ส่ง Monthly ด้วย

def is_market_open() -> bool:
    return datetime.now(BANGKOK_TZ).weekday() not in MARKET_CLOSED_DAYS

def get_expiry_types_for_now() -> list:
    """
    กำหนดประเภทสัญญาที่จะดึงตามวันและเวลา
    
    07:00 น. ทุกวันทำการ:
      - ส่ง Weekly เสมอ
      - ถ้าวันที่ 1 หรือ 15 ให้ส่ง Monthly ด้วย
    
    08:00 - 23:30 ทุก 30 นาที:
      - ส่ง Daily (0DTE) เท่านั้น
    """
    now = datetime.now(BANGKOK_TZ)
    # รอบ 07:00 = Weekly (และ Monthly ถ้าวันที่ตรง)
    if now.hour == WEEKLY_HOUR and now.minute < 30:
        types = ["weekly"]
        if now.day in MONTHLY_DAYS:
            types.append("monthly")
        return types
    return ["daily"]

def get_seconds_until_next_run():
    """
    คำนวณวินาทีจนถึงรอบทำงานถัดไป:
    - 07:00 (Weekly/Monthly)
    - 08:00, 08:30, 09:00, ... 23:30 (Daily)
    """
    now = datetime.now(BANGKOK_TZ)
    candidates = []

    # สร้าง target สำหรับ 07:00
    t0700 = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if t0700 <= now:
        t0700 += timedelta(days=1)
    candidates.append(t0700)

    # สร้าง target สำหรับนาทีที่ 00 หรือ 30 ช่วง 08:00–23:30
    target = now.replace(minute=0, second=0, microsecond=0)
    if target <= now:
        target = now.replace(minute=30, second=0, microsecond=0)
        if target <= now:
            target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    # เฉพาะช่วงเวลาที่เปิดทำการ
    if DAILY_START_HOUR <= target.hour <= DAILY_END_HOUR:
        candidates.append(target)

    # เลือก target ที่ใกล้ที่สุด
    upcoming = min(candidates)
    return int((upcoming - now).total_seconds())

async def _send_images_for_expiry(context_bot, chat_id, images, expiry_type, label):
    """ส่งรูปชุดหนึ่งไปยัง User และ Main Bot"""
    # แจ้งก่อน
    emoji = {"daily": "📊", "weekly": "📅", "monthly": "📆"}.get(expiry_type, "📊")
    await context_bot.send_message(
        chat_id=chat_id,
        text=f"{emoji} **QuikStrike Update — {label}**\nดึงข้อมูลสำเร็จ {len(images)} รูปครับ",
        parse_mode="Markdown"
    )

    if main_bot_client:
        try:
            await main_bot_client.send_message(
                chat_id=chat_id,
                text=f"🔄 ได้รับข้อมูล {label} ชุดใหม่จาก QuikStrike กำลังวิเคราะห์ Vol2Vol & Expected Range อัตโนมัติ..."
            )
        except Exception as e:
            log_msg(f"⚠️ ไม่สามารถส่งข้อความเตือนไปยังบอทตัวแรก: {e}")

    for img_path in images:
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    img_data = f.read()

                await context_bot.send_photo(
                    chat_id=chat_id,
                    photo=io.BytesIO(img_data),
                    read_timeout=60,
                    write_timeout=60,
                    pool_timeout=60
                )

                if main_bot_client:
                    try:
                        await main_bot_client.send_photo(
                            chat_id=chat_id,
                            photo=io.BytesIO(img_data),
                            read_timeout=60,
                            write_timeout=60,
                            pool_timeout=60
                        )
                    except Exception as e:
                        log_msg(f"❌ ส่งต่อไปยังบอทหลักไม่สำเร็จ: {e}")

                await asyncio.sleep(1.5)
            except Exception as e:
                log_msg(f"❌ ส่งรูป {img_path} ไม่สำเร็จ: {e}")

    # --- วิเคราะห์รูปภาพ QuikStrike ที่ดึงมาโดยอัตโนมัติด้วย Gemini ---
    if gemini_client and images:
        try:
            log_msg(f"Running auto-analysis on scraped images for {label}")
            await context_bot.send_message(
                chat_id=chat_id,
                text=f"🧠 **Gemini Auto-Analysis**\nกำลังเริ่มต้นวิเคราะห์รูปภาพ {label} ด้วย AI... (อาจใช้เวลา 10-30 วินาที)"
            )
            await context_bot.send_chat_action(chat_id=chat_id, action='typing')
            
            data, err = await run_and_save_analysis(chat_id, images)
            if err:
                log_msg(f"❌ Auto-analysis failed: {err}")
                await context_bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ภาพอัตโนมัติ: {err}"
                )
            else:
                # ส่งข้อความผลลัพธ์
                await safe_send(context_bot, chat_id, data['text'])
                
                # ส่งภาพสรุป
                if data.get('image_bytes'):
                    await context_bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(data['image_bytes']),
                        caption=f"📊 ภาพสรุปผลวิเคราะห์อัตโนมัติ — {label}"
                    )
                
                # ส่งรายงาน PDF
                if data.get('pdf_path') and os.path.exists(data['pdf_path']):
                    try:
                        with open(data['pdf_path'], "rb") as f:
                            await context_bot.send_document(
                                chat_id=chat_id,
                                document=f,
                                filename=os.path.basename(data['pdf_path']),
                                caption=f"📄 รายงานวิเคราะห์ {label} (PDF)"
                            )
                    except Exception as e:
                        log_msg(f"⚠️ ไม่สามารถส่งไฟล์ PDF ได้: {e}")
        except Exception as e:
            log_msg(f"❌ Exception during auto-analysis: {e}")


async def send_qs_updates(context: ContextTypes.DEFAULT_TYPE):
    """ฟังก์ชันหลักในการดึงรูปและส่ง"""
    chat_id = context.job.chat_id if context.job else MY_CHAT_ID
    if not chat_id:
        log_msg("❌ ไม่พบ Chat ID ที่จะส่งรูปให้")
        return

    # เช็ควันหยุดสุดสัปดาห์
    if context.job and not is_market_open():
        log_msg("🏖️ Weekend: ตลาดทองปิด ข้ามการดึงรูปอัตโนมัติ")
        return

    now = datetime.now(BANGKOK_TZ)
    current_hour = now.hour

    # เช็คช่วงเวลาทำการ (07:00–23:30)
    if context.job and not (WEEKLY_HOUR <= current_hour <= DAILY_END_HOUR):
        log_msg(f"💤 นอกเวลาทำงาน ({now.strftime('%H:%M')}), ข้ามการส่งรูปอัตโนมัติ")
        return

    # กำหนดประเภทสัญญาที่จะดึง
    if context.job:
        expiry_types = get_expiry_types_for_now()
    else:
        expiry_types = ["daily"]  # Manual /sync ดึงแค่ Daily

    labels = {
        "daily":   "0DTE / Daily",
        "weekly":  "Weekly",
        "monthly": "Monthly"
    }

    for expiry_type in expiry_types:
        label = labels.get(expiry_type, expiry_type)
        log_msg(f"Syncing QuikStrike [{label}] for {chat_id}...")

        images, err = await fetch_quikstrike_data(expiry_type)

        if err:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ ดึงข้อมูล {label} ไม่สำเร็จ: {err}"
            )
            log_msg(f"❌ Error fetching {expiry_type}: {err}")
            continue

        if not images:
            log_msg(f"⚠️ ได้ 0 รูปสำหรับ {label} — อาจมีปัญหาการโหลดหน้าเว็บ")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ ดึงข้อมูล {label} ได้ 0 รูป — QuikStrike อาจโหลดช้า กรุณาลองใหม่ในรอบถัดไป"
            )
            continue

        await _send_images_for_expiry(context.bot, chat_id, images, expiry_type, label)
        log_msg(f"✅ Done sending {label}: {len(images)} images")

        # รอระหว่างการดึงสัญญาแต่ละประเภท
        if len(expiry_types) > 1:
            await asyncio.sleep(3)


# -------- IMAGE ANALYSIS HANDLERS --------

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive photos and auto-analyze when 3 are collected"""
    user_id = update.message.chat_id

    if user_id not in user_photos:
        user_photos[user_id] = []

    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()
    user_photos[user_id].append(photo_bytes)
    count = len(user_photos[user_id])

    if count < 3:
        await update.message.reply_text(
            f"📸 ได้รับภาพที่ {count}/3\n"
            "ส่งเพิ่มหรือพิมพ์ /analyze เพื่อวิเคราะห์เลย"
        )
    elif count == 3:
        await do_analysis(update, context, user_id, user_photos[user_id])
    else:
        # More than 3 → reset and start new session
        user_photos[user_id] = [photo_bytes]
        await update.message.reply_text(
            "📸 เริ่มเซสชันใหม่ ได้รับภาพที่ 1/3"
        )

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger analysis on whatever photos have been sent"""
    user_id = update.message.chat_id
    photos = user_photos.get(user_id, [])
    if not photos:
        await update.message.reply_text("📭 ยังไม่มีรูปภาพในคิว ส่งรูป QuikStrike มาก่อนนะครับ")
        return
    await do_analysis(update, context, user_id, photos)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the photo queue for the user"""
    user_id = update.message.chat_id
    user_photos[user_id] = []
    await update.message.reply_text("🗑️ เคลียร์คิวรูปภาพเรียบร้อยแล้ว เริ่มส่งใหม่ได้เลยครับ")

async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set an alert: /alert gold > 2350"""
    user_id = update.message.chat_id
    try:
        parts = update.message.text.split()[1:]
        if len(parts) != 3:
            await update.message.reply_text("❌ รูปแบบคำสั่งไม่ถูกต้อง\nวิธีใช้: /alert [symbol] [>|<] [price]\nเช่น: /alert gold > 2350")
            return
        
        symbol, condition, threshold_str = parts
        threshold = float(threshold_str)
        if condition not in ['>', '<']:
            await update.message.reply_text("❌ เงื่อนไขต้องเป็น > หรือ < เท่านั้น")
            return
            
        alert_id = await db.add_alert(user_id, symbol.lower(), condition, threshold)
        await update.message.reply_text(f"✅ ตั้งเตือนสำเร็จ! (ID: {alert_id})\nเมื่อ {symbol} {condition} {threshold} ระบบจะแจ้งเตือน")
    except ValueError:
        await update.message.reply_text("❌ ราคาต้องเป็นตัวเลข")
    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {e}")

async def list_alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List active alerts: /alerts"""
    user_id = update.message.chat_id
    alerts = await db.get_alerts(user_id)
    if not alerts:
        await update.message.reply_text("📭 คุณไม่มีการตั้งเตือนที่ทำงานอยู่")
        return
        
    msg = "📋 **รายการแจ้งเตือนของคุณ**\n\n"
    for a in alerts:
        msg += f"ID: {a['id']} | {a['symbol'].upper()} {a['condition']} {a['threshold']}\n"
    msg += "\nยกเลิกการแจ้งเตือนพิมพ์ `/del_alert [ID]`"
    await safe_reply(update.message, msg)

async def del_alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete an alert: /del_alert 1"""
    user_id = update.message.chat_id
    try:
        parts = update.message.text.split()[1:]
        if not parts:
            await update.message.reply_text("❌ รูปแบบไม่ถูกต้อง\nวิธีใช้: /del_alert [ID]")
            return
            
        alert_id = int(parts[0])
        await db.delete_alert(alert_id, user_id)
        await update.message.reply_text(f"🗑️ ลบการแจ้งเตือน ID {alert_id} เรียบร้อยแล้ว")
    except ValueError:
        await update.message.reply_text("❌ ID ต้องเป็นตัวเลข")
    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {e}")

async def do_analysis(update, context, user_id, photos):
    """Handler for manual photo collection analysis"""
    count = len(photos)
    await update.message.reply_text(
        f"⏳ กำลังวิเคราะห์ {count} ภาพด้วย AI...\n"
        "อาจใช้เวลา 10-30 วินาทีครับ"
    )
    await context.bot.send_chat_action(chat_id=user_id, action='typing')

    data, err = await run_and_save_analysis(user_id, photos)
    
    # Reset queue
    user_photos[user_id] = []

    if err:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {err}")
        return

    # Send result text
    await safe_reply(update.message, data['text'])

    # Send result image
    if data.get('image_bytes'):
        await update.message.reply_photo(
            photo=io.BytesIO(data['image_bytes']),
            caption=f"📊 สรุปผลวิเคราะห์ #{data['id']}\n\nระบบวิเคราะห์เสร็จสิ้นเรียบร้อยครับ"
        )

    # Send PDF report
    if data.get('pdf_path') and os.path.exists(data['pdf_path']):
        try:
            with open(data['pdf_path'], "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(data['pdf_path']),
                    caption="📄 รายงานการวิเคราะห์ (PDF)"
                )
        except Exception as e:
            log_msg(f"⚠️ ไม่สามารถส่งไฟล์ PDF ได้: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Follow-up chat: send text questions to Gemini with analysis context"""
    user_id = update.message.chat_id
    user_text = update.message.text

    if not user_text or user_text.startswith('/'):
        return

    ctx = user_context.get(user_id)

    if not ctx or not ctx.get("last_analysis"):
        return

    await context.bot.send_chat_action(chat_id=user_id, action='typing')

    try:
        if not gemini_client:
            await update.message.reply_text("❌ ขาด Gemini API Key")
            return

        # Build follow-up prompt with previous analysis as context
        followup_prompt = (
            "คุณเป็น Senior Gold Options Analyst\n"
            "ด้านล่างคือผลวิเคราะห์ล่าสุดที่คุณทำไว้:\n\n"
            "--- ผลวิเคราะห์ ---\n"
            f"{ctx['last_analysis']}\n"
            "--- จบผลวิเคราะห์ ---\n\n"
            f"คำถามจาก user: {user_text}\n\n"
            "ตอบเป็นภาษาไทย กระชับ ตรงประเด็น อ้างอิงข้อมูลจากผลวิเคราะห์ข้างต้น"
        )

        response = None
        for i in range(3):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: gemini_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=followup_prompt
                    )
                )
                break
            except Exception as e:
                if "429" in str(e) and i < 2:
                    await asyncio.sleep((i + 1) * 2)
                    continue
                raise e
        await safe_reply(update.message, response.text)

    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {str(e)}")


async def monitor_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Check prices and trigger Auto Volatility & ATR Alerts"""
    try:
        # Get all users to notify (from active schedules or just MY_CHAT_ID)
        # We can use active schedules
        schedules = await db.get_all_active_schedules()
        if not schedules:
            if MY_CHAT_ID:
                users = [int(MY_CHAT_ID)]
            else:
                return
        else:
            users = [s['user_id'] for s in schedules]

        # Fetch GC=F data for ATR and current price
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if hist.empty or len(hist) < 15:
            return
            
        # Calculate ATR(14)
        high_low = hist['High'] - hist['Low']
        high_close = (hist['High'] - hist['Close'].shift()).abs()
        low_close = (hist['Low'] - hist['Close'].shift()).abs()
        tr = high_low.combine(high_close, max).combine(low_close, max)
        atr_14 = tr.rolling(window=14).mean().iloc[-2] # use yesterday's ATR as baseline for today
        
        today_high = hist['High'].iloc[-1]
        today_low = hist['Low'].iloc[-1]
        today_close = hist['Close'].iloc[-1]
        today_range = today_high - today_low
        
        atr_pct = (today_range / atr_14) * 100 if atr_14 > 0 else 0
        
        current_atr_level = 0
        if atr_pct >= 100: current_atr_level = 100
        elif atr_pct >= 75: current_atr_level = 75
        elif atr_pct >= 50: current_atr_level = 50
        
        today_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d')
        
        for user_id in users:
            # Get latest analysis for SD bands
            latest_analysis = await db.get_latest_analysis(user_id)
            sd_state = None
            
            if latest_analysis and latest_analysis['range_high_1sd'] and latest_analysis['range_low_1sd']:
                high_1sd = latest_analysis['range_high_1sd']
                low_1sd = latest_analysis['range_low_1sd']
                spot = (high_1sd + low_1sd) / 2
                dist_1sd = high_1sd - spot
                
                high_2sd = spot + 2 * dist_1sd
                high_3sd = spot + 3 * dist_1sd
                low_2sd = spot - 2 * dist_1sd
                low_3sd = spot - 3 * dist_1sd
                
                if today_close >= high_3sd: sd_state = "+3SD"
                elif today_close >= high_2sd: sd_state = "+2SD"
                elif today_close >= high_1sd: sd_state = "+1SD"
                elif today_close <= low_3sd: sd_state = "-3SD"
                elif today_close <= low_2sd: sd_state = "-2SD"
                elif today_close <= low_1sd: sd_state = "-1SD"
            
            # Fetch daily state
            state = await db.get_daily_alert_state(user_id, today_str)
            max_atr_alerted = state['max_atr_alerted'] if state else 0
            last_sd_state = state['sd_alert_state'] if state else None
            
            alerts_triggered = []
            new_max_atr = max_atr_alerted
            new_sd_state = last_sd_state
            
            # Check ATR
            if current_atr_level > max_atr_alerted:
                alerts_triggered.append(f"📊 **ATR Alert:** วันนี้ราคาวิ่งไปแล้ว **{atr_pct:.1f}%** ของความผันผวนปกติ (ATR14 = {atr_14:.1f})")
                new_max_atr = current_atr_level
                
            # Check SD
            if sd_state and sd_state != last_sd_state:
                alerts_triggered.append(f"🎯 **Volatility Alert:** ราคาปัจจุบัน ({today_close:.1f}) ทะลุกรอบ **{sd_state}** ของการวิเคราะห์ล่าสุดแล้ว!")
                new_sd_state = sd_state
                
            # Check custom alerts (optional, legacy)
            custom_alerts = await db.get_alerts(user_id)
            if custom_alerts:
                for ca in custom_alerts:
                    sym = ca['symbol'].lower()
                    if sym == 'gold' or sym == 'gc=f':
                        cond = ca['condition']
                        thresh = ca['threshold']
                        if (cond == '>' and today_close > thresh) or (cond == '<' and today_close < thresh):
                            alerts_triggered.append(f"🚨 **Custom Alert:** GOLD {cond} {thresh} (ปัจจุบัน {today_close:.1f})")
                            await db.delete_alert(ca['id'])

            if alerts_triggered:
                msg = "⚠️ **SMART AUTO ALERTS** ⚠️\n\n" + "\n\n".join(alerts_triggered)
                await safe_send(context.bot, user_id, msg)
                await db.update_daily_alert_state(user_id, today_str, new_max_atr, new_sd_state)

    except Exception as e:
        import traceback
        log_msg(f"⚠️ Error in monitor_alerts: {e}\n{traceback.format_exc()}")

async def evaluate_accuracy(context: ContextTypes.DEFAULT_TYPE):
    """Evaluate past analyses and update accuracy"""
    try:
        unevaluated = await db.get_unevaluated_history()
        if not unevaluated:
            return
            
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if hist.empty:
            return
            
        for row in unevaluated:
            analysis_id = row['id']
            summary = row['summary']
            if not summary:
                continue
                
            analysis_date = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S').date()
            date_str = analysis_date.strftime('%Y-%m-%d')
            
            try:
                # Get close on analysis day
                past_price = hist.loc[date_str:]['Close'].iloc[0]
                # Get current price
                current_price = hist['Close'].iloc[-1]
                
                is_bullish = 'Bullish' in summary or 'bullish' in summary.lower()
                is_bearish = 'Bearish' in summary or 'bearish' in summary.lower()
                
                if not is_bullish and not is_bearish:
                    move_pct = abs(current_price - past_price) / past_price
                    was_accurate = move_pct < 0.005 # neutral means it shouldn't move much
                else:
                    if is_bullish:
                        was_accurate = current_price > past_price
                    else:
                        was_accurate = current_price < past_price
                
                await db.update_accuracy(analysis_id, was_accurate)
                log_msg(f"Evaluated analysis {analysis_id}: {was_accurate}")
            except Exception as e:
                continue
                
    except Exception as e:
        log_msg(f"Error in evaluate_accuracy: {e}")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate accuracy dashboard: /report"""
    user_id = update.message.chat_id
    stats = await db.get_performance_stats(user_id)
    
    if not stats or stats['total_analyzed'] == 0:
        await update.message.reply_text("📭 ยังไม่มีข้อมูลสถิติที่เพียงพอสำหรับการสร้างรายงานครับ\n(ระบบจะประเมินผลวันละ 1 ครั้ง สำหรับผลวิเคราะห์ที่ผ่านไปแล้วอย่างน้อย 1 วัน)")
        return
        
    img_bytes = generate_accuracy_dashboard(stats['total_analyzed'], stats['total_accurate'])
    await update.message.reply_photo(
        photo=io.BytesIO(img_bytes),
        caption="📊 **AI Accuracy Dashboard**\nนี่คือสรุปความแม่นยำของ AI จากการวิเคราะห์ที่ผ่านมาครับ",
        parse_mode="Markdown"
    )


# -------- COMMAND HANDLERS --------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    log_msg(f"DEBUG: USER CHAT ID IS: {user_id}")
    with open("chat_id.txt", "w") as f:
        f.write(str(user_id))
    await update.message.reply_text(
        f"🚀 บอทส่งรูป QuikStrike เริ่มทำงานแล้ว!\n"
        f"Your Chat ID: {user_id}\n\n"
        "📋 คำสั่งที่ใช้ได้:\n"
        "/sync — ดึงรูป 0DTE ทันที\n"
        "/sync_weekly — ดึงรูป Weekly ทันที\n"
        "/sync_monthly — ดึงรูป Monthly ทันที\n"
        "/auto_on — เปิดระบบอัตโนมัติ\n"
        "/auto_off — ปิดระบบอัตโนมัติ\n"
        "/analyze — วิเคราะห์รูปภาพในคิว\n"
        "/reset — เคลียร์คิวรูปภาพที่ส่งเข้ามา\n\n"
        "📸 การใช้งานการวิเคราะห์:\n"
        "- ส่งรูปภาพเข้ามาในแชท (บอทจะวิเคราะห์อัตโนมัติเมื่อครบ 3 รูป)\n"
        "- หรือส่งรูปเข้ามาแล้วพิมพ์ /analyze เพื่อวิเคราะห์รูปทั้งหมดที่มี\n"
        "- หรือพิมพ์ถามคำถามเพื่อคุยต่อเนื่องหลังจากวิเคราะห์ได้\n\n"
        "🚨 ระบบแจ้งเตือน (Smart Alerts):\n"
        "/alert [symbol] [>|<] [price] — เช่น /alert gold > 2350\n"
        "/alerts — ดูรายการแจ้งเตือนทั้งหมด\n"
        "/del_alert [ID] — ลบการแจ้งเตือน\n\n"
        "📈 สถิติความแม่นยำ:\n"
        "/report — ดู Dashboard สรุปความแม่นยำของ AI\n\n"
        "⏰ ตารางอัตโนมัติ:\n"
        "• 07:00 น. — Weekly (+ Monthly วันที่ 1 และ 15)\n"
        "• 08:00–23:30 ทุก 30 นาที — 0DTE/Daily"
    )

async def sync_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ กำลังดึงข้อมูล 0DTE... อาจใช้เวลา 60-90 วินาทีครับ")
    dummy_context = context
    dummy_context.job = None
    log_msg(f"Manual sync (daily) requested by {update.message.chat_id}")
    await send_qs_updates(dummy_context)

async def sync_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await update.message.reply_text("⏳ กำลังดึงข้อมูล Weekly... อาจใช้เวลา 60-90 วินาทีครับ")
    log_msg(f"Manual sync (weekly) requested by {chat_id}")
    images, err = await fetch_quikstrike_data("weekly")
    if err:
        await update.message.reply_text(f"❌ ดึงข้อมูล Weekly ไม่สำเร็จ: {err}")
        return
    if not images:
        await update.message.reply_text("⚠️ ได้ 0 รูปสำหรับ Weekly — QuikStrike อาจโหลดช้า")
        return
    await _send_images_for_expiry(context.bot, chat_id, images, "weekly", "Weekly")

async def sync_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await update.message.reply_text("⏳ กำลังดึงข้อมูล Monthly... อาจใช้เวลา 60-90 วินาทีครับ")
    log_msg(f"Manual sync (monthly) requested by {chat_id}")
    images, err = await fetch_quikstrike_data("monthly")
    if err:
        await update.message.reply_text(f"❌ ดึงข้อมูล Monthly ไม่สำเร็จ: {err}")
        return
    if not images:
        await update.message.reply_text("⚠️ ได้ 0 รูปสำหรับ Monthly — QuikStrike อาจโหลดช้า")
        return
    await _send_images_for_expiry(context.bot, chat_id, images, "monthly", "Monthly")

async def auto_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    for job in context.job_queue.get_jobs_by_name(f"qs_sync_{chat_id}"):
        job.schedule_removal()

    first_delay = get_seconds_until_next_run()
    context.job_queue.run_repeating(
        send_qs_updates,
        interval=1800,
        first=first_delay,
        chat_id=chat_id,
        name=f"qs_sync_{chat_id}"
    )
    mins = first_delay // 60
    secs = first_delay % 60
    await update.message.reply_text(
        f"✅ เปิดระบบอัตโนมัติเรียบร้อยแล้วครับ!\n\n"
        f"⏰ ตารางงาน:\n"
        f"• 07:00 น. — 📅 Weekly (+ 📆 Monthly วันที่ 1/15)\n"
        f"• 08:00–23:30 ทุก 30 นาที — 📊 0DTE/Daily\n\n"
        f"รอบถัดไปจะทำงานในอีก {mins} นาที {secs} วินาทีครับ"
    )

async def auto_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    for job in context.job_queue.get_jobs_by_name(f"qs_sync_{chat_id}"):
        job.schedule_removal()
    await update.message.reply_text("🔕 ปิดระบบส่งรูปอัตโนมัติแล้วครับ")

async def post_init(app):
    """รันตอนเริ่มบอท - เปิดระบบอัตโนมัติให้ MY_CHAT_ID ทันที"""
    try:
        await db.init_db()
        log_msg("✅ Database initialized successfully.")
    except Exception as e:
        log_msg(f"❌ Database initialization failed: {e}")
    if MY_CHAT_ID:
        log_msg(f"Auto-starting sync job for {MY_CHAT_ID}")
        first_delay = get_seconds_until_next_run()

        try:
            await app.bot.send_message(
                chat_id=MY_CHAT_ID,
                text=f"🤖 **Standalone Bot Online**\n"
                     f"ระบบส่งรูปอัตโนมัติเริ่มทำงานแล้วครับ\n\n"
                     f"⏰ ตารางงาน:\n"
                     f"• 07:00 น. — 📅 Weekly (+ 📆 Monthly วันที่ 1/15)\n"
                     f"• 08:00–23:30 ทุก 30 นาที — 📊 0DTE/Daily\n\n"
                     f"รอบแรกจะทำงานในอีก {first_delay // 60} นาที {first_delay % 60} วินาทีครับ",
                parse_mode="Markdown"
            )
        except Exception as e:
            log_msg(f"❌ ไม่สามารถส่งข้อความต้อนรับได้: {e}")

        app.job_queue.run_repeating(
            send_qs_updates,
            interval=1800,
            first=first_delay,
            chat_id=MY_CHAT_ID,
            name=f"qs_sync_{MY_CHAT_ID}"
        )
        
        # Start Alert Monitor Job
        app.job_queue.run_repeating(
            monitor_alerts,
            interval=300, # 5 minutes
            first=10,
            name="monitor_alerts"
        )
        
        # Start Evaluate Accuracy Job
        app.job_queue.run_repeating(
            evaluate_accuracy,
            interval=86400, # 1 day
            first=30,
            name="evaluate_accuracy"
        )


def main():
    if not TELEGRAM_TOKEN:
        print("❌ ไม่พบ STANDALONE_BOT_TOKEN ใน .env")
        return

    print("QuikStrike Image Bot is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sync", sync_now))
    app.add_handler(CommandHandler("sync_weekly", sync_weekly))
    app.add_handler(CommandHandler("sync_monthly", sync_monthly))
    app.add_handler(CommandHandler("auto_on", auto_on))
    app.add_handler(CommandHandler("auto_off", auto_off))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", list_alerts_cmd))
    app.add_handler(CommandHandler("del_alert", del_alert_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    main()
