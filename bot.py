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
import google.generativeai as genai
import PIL.Image
from database import Database
from pdf_export import generate_pdf
from image_export import generate_image

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Bangkok timezone (UTC+7)
BANGKOK_TZ = timezone(timedelta(hours=7))

# Initialize Gemini
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None

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
        if not gemini_model:
            await update.message.reply_text("❌ ขาด Gemini API Key ในไฟล์ .env")
            user_photos[user_id] = []
            return

        images = [PIL.Image.open(io.BytesIO(pb)) for pb in photos]
        prompt = get_system_prompt()
        response = gemini_model.generate_content([prompt] + images)
        result = response.text

        # Save context for follow-up chat
        now_str = datetime.now(BANGKOK_TZ).strftime('%Y-%m-%d %H:%M:%S')
        user_context[user_id] = {
            "last_analysis": result,
            "timestamp": now_str,
        }

        # Save to database
        summary = extract_summary(result)
        analysis_id = await db.save_analysis(user_id, result, count, summary)
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
        filename = f"gold_analysis_{record['id']}_{record['timestamp'][:10]}.pdf"

        await update.message.reply_document(
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption=f"📊 Gold Options Analysis Report #{record['id']}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ สร้าง PDF ไม่สำเร็จ: {str(e)}")


# ===================== SCHEDULE =====================

async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable reminder every 3 hours"""
    user_id = update.message.chat_id

    # Save to DB
    await db.save_schedule(user_id, interval_hours=3)

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
        "⏰ เปิดการเตือนแล้ว!\n\n"
        "📌 บอทจะเตือนให้ส่งรูปวิเคราะห์ทุก 3 ชั่วโมง\n"
        "🔕 พิมพ์ /schedule_off เพื่อปิด"
    )


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
        await update.message.reply_text(
            f"⏰ สถานะ: เปิดอยู่\n"
            f"🔁 เตือนทุก {sched['interval_hours']} ชั่วโมง\n"
            f"🔕 /schedule_off เพื่อปิด"
        )
    else:
        await update.message.reply_text(
            "🔕 สถานะ: ปิดอยู่\n"
            "⏰ /schedule เพื่อเปิดเตือนทุก 3 ชม."
        )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Callback for scheduled reminder"""
    job = context.job
    chat_id = job.chat_id
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
        if not gemini_model:
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

        response = gemini_model.generate_content(followup_prompt)
        await safe_reply(update.message, response.text)

    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {str(e)}")


# ===================== MAIN =====================

async def post_init(app):
    """Run after bot starts — init DB and restore schedules"""
    await db.init_db()
    await restore_schedules(app)

    # Set bot commands menu
    await app.bot.set_my_commands([
        BotCommand("start", "เริ่มต้นใช้งาน"),
        BotCommand("help", "คู่มือคำสั่ง"),
        BotCommand("analyze", "วิเคราะห์รูปที่ส่งไว้"),
        BotCommand("reset", "ล้างรูปเริ่มใหม่"),
        BotCommand("status", "ดูจำนวนรูปในคิว"),
        BotCommand("history", "ประวัติวิเคราะห์"),
        BotCommand("detail", "ดูผลเต็มตาม ID"),
        BotCommand("export", "ส่งรูปภาพผลวิเคราะห์"),
        BotCommand("export_pdf", "ส่ง PDF ผลวิเคราะห์"),
        BotCommand("schedule", "เปิดเตือนทุก 3 ชม."),
        BotCommand("schedule_off", "ปิดการเตือน"),
        BotCommand("schedule_status", "ดูสถานะเตือน"),
    ])


def main():
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "your_telegram_bot_token_here":
        print("⚠️ ไม่พบ TELEGRAM_BOT_TOKEN ในไฟล์ .env")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("detail", detail_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("export_pdf", export_pdf_cmd))
    app.add_handler(CommandHandler("schedule", schedule_cmd))
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
