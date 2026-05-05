import os
import io
import re
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from google import genai
import PIL.Image
from database import Database
from pdf_export import generate_pdf
from image_export import generate_image
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Bangkok timezone (UTC+7)
BANGKOK_TZ = timezone(timedelta(hours=7))

# Initialize Gemini
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None

# Per-user state (in-memory)
user_photos = {}
user_context = {}  # {user_id: {"last_analysis": str, "timestamp": str}}

# Database instance
db = Database()


# ===================== HELPERS =====================

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
            
    except Exception as e:
        print(f"⚠️ Error fetching macro context: {e}")
        
    return context


async def fetch_cot_report(context: ContextTypes.DEFAULT_TYPE = None):
    """Weekly job to fetch and summarize the COT report for Gold"""
    # For now, we'll use a placeholder summary. 
    # In a production environment, this could be connected to an automated CFTC scraper.
    cot_summary = (
        "Gold COT (Legacy): Managed Money (Hedge Funds) are currently Net Long 185k contracts (+5k from last week). "
        "Commercials (Producers/Swaps) are Net Short 210k contracts (Hedging increase). "
        "Sentiment: Bullish bias from Funds remains strong, but Commercial hedging is rising at 2400+ levels."
    )
    await db.save_macro_data("cot_summary", cot_summary)
    print("✅ COT Report Updated")


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
    """Extract Z5 Composite Score from the Z-Score Summary table"""
    match = re.search(r'Z5 Composite\s*\|\s*([-+]?\d*\.?\d+)', text)
    if match:
        return float(match.group(1))
    return None


def extract_key_levels(text):
    """Extract Max Pain and GEX Flip Zone from the Key Levels section"""
    max_pain = None
    gex_zone = None
    
    mp_match = re.search(r'Max Pain Zone:\s*\[?(\d+\.?\d*)\]?', text)
    if mp_match:
        max_pain = float(mp_match.group(1))
        
    gex_match = re.search(r'GEX Flip Zone:\s*\[?(\d+\.?\d*)\]?', text)
    if gex_match:
        gex_zone = float(gex_match.group(1))
        
    return max_pain, gex_zone


def extract_expected_range(text):
    """Extract 1SD Expected Range from the table"""
    high = None
    low = None
    
    # Looking for 1SD (68%) | [high] | [low] | ...
    pattern = r'1SD \(68%\)\s*\|\s*(\d+\.?\d*)\s*\|\s*(\d+\.?\d*)'
    match = re.search(pattern, text)
    if match:
        high = float(match.group(1))
        low = float(match.group(2))
        
    return high, low


async def safe_reply(message, text):
    """Send message with Markdown. Fallback to plain text if parse fails."""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode='Markdown')
        except Exception:
            try:
                await message.reply_text(chunk)
            except Exception:
                await message.reply_text("❌ ไม่สามารถส่งข้อความได้ ลองพิมพ์ /history แล้วดูผ่าน PDF แทนครับ")


# ===================== CORE ANALYSIS =====================

async def do_analysis(update, context, user_id, photos):
    """Run Gemini analysis on the collected photos"""
    count = len(photos)
    await update.message.reply_text(
        f"⏳ กำลังส่ง {count} ภาพให้ Gemini 2.5 Flash วิเคราะห์...\n"
        "อาจใช้เวลา 10-30 วินาทีครับ"
    )
    await context.bot.send_chat_action(chat_id=user_id, action='typing')

    try:
        if not gemini_client:
            await update.message.reply_text("❌ ขาด Gemini API Key ในไฟล์ .env")
            user_photos[user_id] = []
            return

        images = [PIL.Image.open(io.BytesIO(pb)) for pb in photos]
        prompt = get_system_prompt()
        
        # Add Macro Context
        macro_ctx = await get_macro_context()
        full_prompt = f"{prompt}\n\n{macro_ctx}\n\nโปรดวิเคราะห์รูปภาพที่แนบมาโดยใช้ข้อมูล Macro ข้างต้นประกอบด้วย"
        
        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[full_prompt] + images
        )
        result = response.text

        # Save context for follow-up chat
        now_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d %H:%M:%S')
        user_context[user_id] = {
            "last_analysis": result,
            "timestamp": now_str,
        }

        # Save to database
        summary = extract_summary(result)
        z5 = extract_z5_score(result)
        max_pain, gex = extract_key_levels(result)
        high_1sd, low_1sd = extract_expected_range(result)
        
        analysis_id = await db.save_analysis(user_id, result, count, summary, z5, gex, max_pain, high_1sd, low_1sd)
        await db.cleanup_old_history(user_id, keep_count=20)

        # Send result with safe markdown
        await safe_reply(update.message, result)

        # Auto-send Image
        try:
            await update.message.reply_text("🖼 กำลังสร้างรูปภาพสรุปผล...")
            await context.bot.send_chat_action(chat_id=user_id, action='upload_photo')
            img_bytes = generate_image(result, now_str)
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption=f"📊 สรุปผลวิเคราะห์ #{analysis_id}"
            )
        except Exception as img_e:
            await update.message.reply_text(f"❌ สร้างรูปภาพไม่สำเร็จ: {str(img_e)}")

        # Auto-save PDF to exports folder
        try:
            pdf_bytes = generate_pdf(result, now_str)
            filename = f"Gold_Analysis_{analysis_id}_{now_str.split(' ')[0]}.pdf"
            filepath = os.path.join("exports", filename)
            with open(filepath, "wb") as f:
                f.write(pdf_bytes)
        except Exception as pdf_e:
            print(f"⚠️ Auto-save PDF error: {pdf_e}")

        # Footer with tips
        await update.message.reply_text(
            f"✅ บันทึกผลวิเคราะห์ #{analysis_id} แล้ว\n\n"
            "💬 ส่งข้อความถามเพิ่มเติมได้เลย\n"
            "📄 /export_pdf — ดาวน์โหลด PDF\n"
            "📋 /history — ดูประวัติย้อนหลัง"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาดระหว่างวิเคราะห์: {str(e)}")

    # Clear photos after analysis
    user_photos[user_id] = []


# ===================== TRENDS & ALERTS =====================

async def trend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send a Sentiment Trend graph (Z5 Score)"""
    user_id = update.message.chat_id
    records = await db.get_history(user_id, limit=10)
    
    if not records:
        await update.message.reply_text("📭 ยังไม่มีข้อมูลวิเคราะห์สำหรับทำกราฟ")
        return
        
    # We need full records to get z5_score
    full_records = []
    for r in records:
        fr = await db.get_analysis_by_id(r['id'], user_id)
        if fr and fr['z5_score'] is not None:
            full_records.append(fr)
            
    if len(full_records) < 2:
        await update.message.reply_text("📊 ต้องการข้อมูลอย่างน้อย 2 รายการเพื่อทำกราฟครับ")
        return
        
    await update.message.reply_text("📈 กำลังประมวลผลกราฟเทรนด์...")
    
    try:
        df = pd.DataFrame([dict(r) for r in full_records])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')
        
        # Plot Z5 Score
        plt.plot(df['timestamp'], df['z5_score'], marker='o', linestyle='-', color='#00d2ff', linewidth=2, label='Z5 Score')
        
        # Fill regions
        plt.axhspan(2, 5, color='green', alpha=0.1, label='Extreme Bullish')
        plt.axhspan(-5, -2, color='red', alpha=0.1, label='Extreme Bearish')
        plt.axhline(0, color='white', linestyle='--', alpha=0.3)
        
        plt.title('Gold Sentiment Trend (Z5 Composite Score)', fontsize=14, pad=20)
        plt.xlabel('Date/Time', fontsize=10)
        plt.ylabel('Z5 Score', fontsize=10)
        plt.grid(True, alpha=0.2)
        plt.legend()
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=120)
        buf.seek(0)
        plt.close()
        
        await update.message.reply_photo(
            photo=buf,
            caption="📊 กราฟแนวโน้มความมั่นใจของ Smart Money (Z5 Score)\nย้อนหลังสูงสุด 10 รายการล่าสุด"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ ไม่สามารถสร้างกราฟได้: {str(e)}")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View bot performance statistics"""
    user_id = update.message.chat_id
    stats = await db.get_performance_stats(user_id)
    
    if not stats or stats['total_analyzed'] == 0:
        await update.message.reply_text("📊 ยังไม่มีสถิติการวิเคราะห์ครับ ต้องรอการตรวจสอบความแม่นยำหลังผ่านไป 24 ชม.")
        return
        
    win_rate = (stats['total_accurate'] / stats['total_analyzed']) * 100
    await update.message.reply_text(
        f"🏆 **Bot Performance Stats**\n\n"
        f"🎯 วิเคราะห์ทั้งหมด: {stats['total_analyzed']} ครั้ง\n"
        f"✅ อยู่ในกรอบที่คาดการณ์: {stats['total_accurate']} ครั้ง\n"
        f"📈 ความแม่นยำ (Hit Rate): {win_rate:.1f}%\n\n"
        f"🕒 อัปเดตล่าสุด: {stats['last_updated']}"
    )


async def verify_previous_analyses(context: ContextTypes.DEFAULT_TYPE):
    """Daily job to check if yesterday's ranges were accurate"""
    # Find all analyses from roughly 24h ago that haven't been verified
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        # Look for analyses older than 20h but younger than 48h that haven't been verified
        cursor = await conn.execute('''
            SELECT * FROM analysis_history 
            WHERE was_accurate IS NULL 
            AND timestamp < datetime('now', '-20 hours')
            AND range_high_1sd IS NOT NULL
        ''')
        rows = await cursor.fetchall()
        
    if not rows:
        return

    try:
        gold = yf.Ticker("GC=F")
        # Get historical data for the relevant period
        hist = gold.history(period="5d") # Get a few days to be safe
    except Exception as e:
        print(f"⚠️ Error fetching history for verification: {e}")
        return

    for row in rows:
        ts = pd.to_datetime(row['timestamp']).date()
        # Find the High/Low for that specific date in the history
        day_data = hist[hist.index.date == ts]
        
        if day_data.empty:
            continue
            
        actual_high = day_data['High'].max()
        actual_low = day_data['Low'].min()
        
        # Check if it was accurate (stayed within 1SD range)
        is_accurate = (actual_high <= row['range_high_1sd']) and (actual_low >= row['range_low_1sd'])
        
        await db.update_accuracy(row['id'], is_accurate)
        
        # Optionally notify user
        try:
            status_text = "✅ **ถูกต้อง!** ราคาเคลื่อนไหวในกรอบ" if is_accurate else "❌ **คลาดเคลื่อน** ราคาหลุดกรอบที่คาดการณ์"
            await context.bot.send_message(
                chat_id=row['user_id'],
                text=f"📊 **สรุปผลความแม่นยำย้อนหลัง**\n\n"
                     f"การวิเคราะห์เมื่อ: {row['timestamp']}\n"
                     f"กรอบที่ให้: {row['range_low_1sd']} - {row['range_high_1sd']}\n"
                     f"ราคาวันนั้น: {actual_low:.2f} - {actual_high:.2f}\n\n"
                     f"ผลลัพธ์: {status_text}"
            )
        except Exception:
            pass


async def check_price_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Job to check current Gold price against key levels (GEX/Max Pain)"""
    # This job runs for all users who have analyzed recently
    # For simplicity, we'll check users with active schedules or recent history
    schedules = await db.get_all_active_schedules()
    user_ids = [s['user_id'] for s in schedules]
    
    if not user_ids:
        return
        
    try:
        # Fetch current gold price (Gold Futures GC=F)
        gold = yf.Ticker("GC=F")
        price_data = gold.history(period="1d")
        if price_data.empty:
            return
        current_price = price_data['Close'].iloc[-1]
    except Exception as e:
        print(f"⚠️ Error fetching price: {e}")
        return

    for uid in user_ids:
        sched = await db.get_schedule(uid)
        if not sched or not sched['alerts_enabled']:
            continue
            
        record = await db.get_latest_analysis(uid)
        if not record or (record['gex_flip_zone'] is None and record['max_pain'] is None):
            continue
            
        gex = record['gex_flip_zone']
        mp = record['max_pain']
        
        alert_text = ""
        # Check GEX Flip Zone (within 0.5%)
        if gex and abs(current_price - gex) / gex < 0.005:
            alert_text += f"⚡ **ราคาเข้าใกล้ GEX Flip Zone: {gex}**\n(ปัจจุบัน: {current_price:.2f})\n\n"
            
        # Check Max Pain (within 0.5%)
        if mp and abs(current_price - mp) / mp < 0.005:
            alert_text += f"🟡 **ราคาเข้าใกล้ Max Pain: {mp}**\n(ปัจจุบัน: {current_price:.2f})\n\n"
            
        if alert_text:
            try:
                # Send alert (we need to handle cases where bot is blocked)
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"🚨 **PRICE ALERT!**\n\n{alert_text}กรุณาตรวจสอบหน้างานเพื่อความปลอดภัยครับ"
                )
            except Exception:
                pass


# ===================== COMMAND HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_photos[user_id] = []
    await update.message.reply_text(
        "🏆 Gold Options Analysis Bot\n\n"
        "สวัสดีครับ! ผมคือบอทวิเคราะห์ Gold Options จาก CME QuikStrike\n\n"
        "📸 วิธีใช้งาน:\n"
        "1. ส่งภาพหน้าจอ QuikStrike (Volume, OI, OI Change)\n"
        "2. ส่งครบ 3 รูป → วิเคราะห์อัตโนมัติ\n"
        "   หรือส่งกี่รูปก็ได้แล้วพิมพ์ /analyze\n"
        "3. รอ Gemini 2.5 Flash วิเคราะห์ ~10-30 วินาที\n"
        "4. ถามคำถามเพิ่มเติมได้ ส่งข้อความมาเลย!\n\n"
        "📈 /trend — ดูแนวโน้ม Sentiment ย้อนหลัง\n"
        "📋 พิมพ์ /help เพื่อดูคำสั่งทั้งหมดครับ"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 คำสั่งทั้งหมด\n\n"
        "🔹 พื้นฐาน\n"
        "/start — เริ่มต้นใช้งาน\n"
        "/help — แสดงคู่มือนี้\n"
        "/analyze — วิเคราะห์รูปที่ส่งไว้ (ไม่ต้องรอครบ 3)\n"
        "/reset — ล้างรูปเริ่มใหม่\n"
        "/status — ดูจำนวนรูปที่ส่งแล้ว\n\n"
        "🔹 ประวัติ & ส่งออก\n"
        "/history — ดู 10 ผลวิเคราะห์ล่าสุด\n"
        "/trend — ดูแนวโน้ม Sentiment ย้อนหลัง\n"
        "/detail <ID> — ดูผลวิเคราะห์เต็มตาม ID\n"
        "/export — ส่งรูปภาพผลวิเคราะห์ล่าสุด\n"
        "/export_pdf <ID> — ส่ง PDF ตาม ID\n\n"
        "🔹 ตั้งเวลาเตือน\n"
        "/schedule — เปิดเตือนทุก 3 ชม.\n"
        "/schedule_off — ปิดการเตือน\n"
        "/schedule_status — ดูสถานะเตือน\n\n"
        "💬 Follow-up: ส่งข้อความถามเพิ่มได้หลังวิเคราะห์เสร็จ"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    count = len(user_photos.get(user_id, []))
    if count == 0:
        await update.message.reply_text("📭 ยังไม่มีรูปในคิว ส่งรูป QuikStrike มาได้เลยครับ")
    else:
        await update.message.reply_text(
            f"📬 มีรูปในคิว {count} รูป\n"
            "ส่งเพิ่มหรือพิมพ์ /analyze เพื่อวิเคราะห์ได้เลยครับ"
        )


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_photos[user_id] = []
    await update.message.reply_text("🗑️ ล้างรูปทั้งหมดแล้ว ส่งรูปใหม่ได้เลยครับ")


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger analysis on whatever photos have been sent"""
    user_id = update.message.chat_id
    photos = user_photos.get(user_id, [])
    if not photos:
        await update.message.reply_text(
            "❌ ยังไม่มีรูป ส่งรูป QuikStrike มาก่อนแล้วพิมพ์ /analyze ครับ"
        )
        return
    await do_analysis(update, context, user_id, photos)


# ===================== HISTORY =====================

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    records = await db.get_history(user_id, limit=10)

    if not records:
        await update.message.reply_text("📭 ยังไม่มีประวัติ ส่งรูปมาวิเคราะห์ก่อนนะครับ")
        return

    text = "📋 ประวัติวิเคราะห์ 10 รายการล่าสุด\n\n"
    for r in records:
        rid = r['id']
        ts = r['timestamp']
        summary = r['summary'] or '-'
        n_img = r['num_images']
        text += f"#{rid}  |  {ts}\n  📸 {n_img} รูป  |  {summary}\n\n"

    text += "📖 /detail <ID> — ดูผลเต็ม\n📄 /export <ID> — ส่ง PDF"
    await update.message.reply_text(text)


async def detail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full analysis result by ID"""
    user_id = update.message.chat_id
    args = context.args

    if not args:
        await update.message.reply_text("❌ กรุณาระบุ ID เช่น /detail 5")
        return

    try:
        analysis_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID ต้องเป็นตัวเลข เช่น /detail 5")
        return

    record = await db.get_analysis_by_id(analysis_id, user_id)
    if not record:
        await update.message.reply_text("❌ ไม่พบผลวิเคราะห์ ID นี้")
        return

    header = f"📋 ผลวิเคราะห์ #{record['id']}  |  {record['timestamp']}\n{'─'*30}\n\n"
    await safe_reply(update.message, header + record['result_text'])


# ===================== IMAGE & PDF EXPORT =====================

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export analysis as Image"""
    user_id = update.message.chat_id
    args = context.args

    if args:
        try:
            analysis_id = int(args[0])
            record = await db.get_analysis_by_id(analysis_id, user_id)
        except ValueError:
            await update.message.reply_text("❌ ID ต้องเป็นตัวเลข เช่น /export 5")
            return
    else:
        record = await db.get_latest_analysis(user_id)

    if not record:
        await update.message.reply_text("❌ ไม่พบผลวิเคราะห์ ส่งรูปมาวิเคราะห์ก่อนนะครับ")
        return

    await update.message.reply_text("🖼 กำลังสร้างรูปภาพ...")
    await context.bot.send_chat_action(chat_id=user_id, action='upload_photo')

    try:
        img_bytes = generate_image(record['result_text'], record['timestamp'])
        await update.message.reply_photo(
            photo=io.BytesIO(img_bytes),
            caption=f"📊 Gold Options Analysis Report #{record['id']}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ สร้างรูปภาพไม่สำเร็จ: {str(e)}")


async def export_pdf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export analysis as PDF"""
    user_id = update.message.chat_id
    args = context.args

    # Determine which analysis to export
    if args:
        try:
            analysis_id = int(args[0])
            record = await db.get_analysis_by_id(analysis_id, user_id)
        except ValueError:
            await update.message.reply_text("❌ ID ต้องเป็นตัวเลข เช่น /export_pdf 5")
            return
    else:
        record = await db.get_latest_analysis(user_id)

    if not record:
        await update.message.reply_text("❌ ไม่พบผลวิเคราะห์ ส่งรูปมาวิเคราะห์ก่อนนะครับ")
        return

    await update.message.reply_text("📄 กำลังสร้าง PDF...")
    await context.bot.send_chat_action(chat_id=user_id, action='upload_document')

    try:
        pdf_bytes = generate_pdf(record['result_text'], record['timestamp'])
        
        # Save to exports folder for long-term storage
        filename = f"Gold_Analysis_{record['id']}_{record['timestamp'].replace(':', '-').replace(' ', '_')}.pdf"
        filepath = os.path.join("exports", filename)
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)

        await update.message.reply_document(
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption=f"📊 Gold Options Analysis Report #{record['id']}\n(บันทึกไฟล์ลงคลังระบบเรียบร้อยครับ)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ สร้าง PDF ไม่สำเร็จ: {str(e)}")


# ===================== SCHEDULE =====================

async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable reminder every 3 hours (and price alerts)"""
    user_id = update.message.chat_id

    # Save to DB (both enabled by default)
    await db.save_schedule(user_id, interval_hours=3, reminders=True, alerts=True)

    # Remove old job if exists
    current_jobs = context.job_queue.get_jobs_by_name(f"reminder_{user_id}")
    for job in current_jobs:
        job.schedule_removal()

    # Schedule repeating job every 3 hours
    context.job_queue.run_repeating(
        send_reminder,
        interval=timedelta(hours=3),
        first=timedelta(hours=3),
        chat_id=user_id,
        name=f"reminder_{user_id}",
        data={"user_id": user_id}
    )

    await update.message.reply_text(
        "⏰ เปิดระบบแจ้งเตือนแล้ว!\n\n"
        "✅ แจ้งเตือนส่งรูปทุก 3 ชม.: เปิด\n"
        "✅ แจ้งเตือนราคาทอง (GEX/Max Pain): เปิด\n\n"
        "📌 จัดการแยกกันได้ด้วย:\n"
        "/reminders_off — ปิดเตือนส่งรูป\n"
        "/alerts_off — ปิดเตือนราคา\n"
        "/schedule_off — ปิดทั้งหมด"
    )


async def reminders_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable only 3-hour reminders"""
    user_id = update.message.chat_id
    sched = await db.get_schedule(user_id)
    if sched:
        await db.save_schedule(user_id, sched['interval_hours'], reminders=False, alerts=sched['alerts_enabled'])
        await update.message.reply_text("🔕 ปิดการเตือนส่งรูปทุก 3 ชม. แล้วครับ (แต่ยังเตือนราคาอยู่)")
    else:
        await update.message.reply_text("❌ คุณยังไม่ได้เปิดระบบแจ้งเตือน พิมพ์ /schedule เพื่อเริ่ม")


async def alerts_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable only price alerts"""
    user_id = update.message.chat_id
    sched = await db.get_schedule(user_id)
    if sched:
        await db.save_schedule(user_id, sched['interval_hours'], reminders=sched['reminders_enabled'], alerts=False)
        await update.message.reply_text("🔕 ปิดการเตือนราคาทองแล้วครับ (แต่ยังเตือนส่งรูปอยู่)")
    else:
        await update.message.reply_text("❌ คุณยังไม่ได้เปิดระบบแจ้งเตือน พิมพ์ /schedule เพื่อเริ่ม")


async def alerts_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable price alerts"""
    user_id = update.message.chat_id
    sched = await db.get_schedule(user_id)
    if sched:
        await db.save_schedule(user_id, sched['interval_hours'], reminders=sched['reminders_enabled'], alerts=True)
    else:
        await db.save_schedule(user_id, interval_hours=3, reminders=False, alerts=True)
    await update.message.reply_text("🔔 เปิดการเตือนราคาทอง (GEX/Max Pain) เรียบร้อยครับ")


async def schedule_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable reminder"""
    user_id = update.message.chat_id
    await db.delete_schedule(user_id)

    current_jobs = context.job_queue.get_jobs_by_name(f"reminder_{user_id}")
    for job in current_jobs:
        job.schedule_removal()

    await update.message.reply_text("🔕 ปิดการเตือนแล้วครับ")


async def schedule_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check schedule status"""
    user_id = update.message.chat_id
    sched = await db.get_schedule(user_id)

    if sched:
        rem_status = "เปิด ✅" if sched['reminders_enabled'] else "ปิด ❌"
        alert_status = "เปิด ✅" if sched['alerts_enabled'] else "ปิด ❌"
        await update.message.reply_text(
            f"⏰ **สถานะระบบแจ้งเตือน**\n\n"
            f"📸 เตือนส่งรูป (3 ชม.): {rem_status}\n"
            f"🔔 เตือนราคาทอง: {alert_status}\n\n"
            f"🔁 ความถี่หลัก: ทุก {sched['interval_hours']} ชั่วโมง\n"
            f"🔕 /schedule_off เพื่อปิดทั้งหมด"
        )
    else:
        await update.message.reply_text(
            "🔕 สถานะ: ปิดอยู่ทั้งหมด\n"
            "⏰ /schedule เพื่อเปิดระบบ"
        )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Callback for scheduled reminder"""
    job = context.job
    chat_id = job.chat_id
    
    # Check if reminders are enabled for this user
    sched = await db.get_schedule(chat_id)
    if not sched or not sched['reminders_enabled']:
        return

    now = datetime.now(BANGKOK_TZ).strftime('%H:%M')
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏰ เตือนวิเคราะห์ Gold Options ({now} น.)\n\n"
            "📸 ส่งรูป QuikStrike มาได้เลยครับ:\n"
            "1. Intraday Volume\n"
            "2. Open Interest\n"
            "3. OI Change\n\n"
            "ส่งครบ 3 รูปวิเคราะห์อัตโนมัติ หรือพิมพ์ /analyze"
        )
    )


async def restore_schedules(app):
    """Restore saved schedules after bot restart"""
    schedules = await db.get_all_active_schedules()
    for s in schedules:
        uid = s['user_id']
        hours = s['interval_hours']
        app.job_queue.run_repeating(
            send_reminder,
            interval=timedelta(hours=hours),
            first=timedelta(minutes=5),
            chat_id=uid,
            name=f"reminder_{uid}",
            data={"user_id": uid}
        )
    if schedules:
        print(f"⏰ Restored {len(schedules)} schedule(s)")


# ===================== MESSAGE HANDLERS =====================

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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Follow-up chat: send text questions to Gemini with analysis context"""
    user_id = update.message.chat_id
    user_text = update.message.text

    if not user_text or user_text.startswith('/'):
        return

    ctx = user_context.get(user_id)

    if not ctx or not ctx.get("last_analysis"):
        await update.message.reply_text(
            "💬 ยังไม่มีผลวิเคราะห์ให้ถาม ส่งรูป QuikStrike มาวิเคราะห์ก่อนนะครับ"
        )
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

        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=followup_prompt
        )
        await safe_reply(update.message, response.text)

    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {str(e)}")


# ===================== MAIN =====================

async def post_init(app):
    """Run after bot starts — init DB and restore schedules"""
    print("🚀 Initializing database...")
    await db.init_db()
    print("🚀 Restoring schedules...")
    await restore_schedules(app)
    
    print("🚀 Starting background jobs...")
    # Start background price alert job (every 15 minutes)
    app.job_queue.run_repeating(
        check_price_alerts,
        interval=timedelta(minutes=15),
        first=timedelta(seconds=10),
        name="price_alerts"
    )

    # Start daily accuracy verification (every 6 hours)
    app.job_queue.run_repeating(
        verify_previous_analyses,
        interval=timedelta(hours=6),
        first=timedelta(minutes=5),
        name="accuracy_verify"
    )

    # Start weekly COT fetch (every Saturday)
    app.job_queue.run_repeating(
        fetch_cot_report,
        interval=timedelta(days=7),
        first=timedelta(seconds=5), # Run once on startup
        name="cot_fetch"
    )

    # Set bot commands menu
    await app.bot.set_my_commands([
        BotCommand("start", "เริ่มต้นใช้งาน"),
        BotCommand("help", "คู่มือคำสั่ง"),
        BotCommand("analyze", "วิเคราะห์รูปที่ส่งไว้"),
        BotCommand("reset", "ล้างรูปเริ่มใหม่"),
        BotCommand("status", "ดูจำนวนรูปในคิว"),
        BotCommand("history", "ประวัติวิเคราะห์"),
        BotCommand("trend", "กราฟแนวโน้ม Sentiment"),
        BotCommand("stats", "สถิติความแม่นยำ"),
        BotCommand("detail", "ดูผลเต็มตาม ID"),
        BotCommand("export", "ส่งรูปภาพผลวิเคราะห์"),
        BotCommand("export_pdf", "ส่ง PDF ผลวิเคราะห์"),
        BotCommand("schedule", "เปิดระบบแจ้งเตือน"),
        BotCommand("alerts_on", "เปิดเตือนราคาทอง"),
        BotCommand("alerts_off", "ปิดเตือนราคาทอง"),
        BotCommand("reminders_off", "ปิดเตือนส่งรูป 3 ชม."),
        BotCommand("schedule_off", "ปิดการเตือนทั้งหมด"),
        BotCommand("schedule_status", "ดูสถานะเตือน"),
    ])


def main():
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "your_telegram_bot_token_here":
        print("⚠️ ไม่พบ TELEGRAM_BOT_TOKEN ในไฟล์ .env")
        return

    print("✅ Gold Options Bot กำลังเริ่มการทำงาน...")
    print("📋 Commands: /start /help /analyze /reset /status")
    print("📋 History:  /history /detail /export")
    print("📋 Schedule: /schedule /schedule_off /schedule_status")
    print("💬 Follow-up chat: ส่งข้อความถามได้หลังวิเคราะห์")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("detail", detail_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("export_pdf", export_pdf_cmd))
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("alerts_on", alerts_on_cmd))
    app.add_handler(CommandHandler("alerts_off", alerts_off_cmd))
    app.add_handler(CommandHandler("reminders_off", reminders_off_cmd))
    app.add_handler(CommandHandler("schedule_off", schedule_off_cmd))
    app.add_handler(CommandHandler("schedule_status", schedule_status_cmd))

    # Message handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Gold Options Bot กำลังทำงาน...")
    print("📋 Commands: /start /help /analyze /reset /status")
    print("📋 History:  /history /detail /export")
    print("📋 Schedule: /schedule /schedule_off /schedule_status")
    print("💬 Follow-up chat: ส่งข้อความถามได้หลังวิเคราะห์")
    print("กด Ctrl+C เพื่อปิดบอท")
    app.run_polling()


if __name__ == "__main__":
    main()
