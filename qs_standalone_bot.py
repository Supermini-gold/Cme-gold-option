import os
import asyncio
import io
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime, time, timedelta, timezone
from dotenv import load_dotenv
from quikstrike_scraper import fetch_quikstrike_data

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
log_msg(f"Bot config loaded. Target Chat ID: {MY_CHAT_ID}")

# --- CONFIG: ตั้งเวลาทำงานตรงนี้ ---
BANGKOK_TZ = timezone(timedelta(hours=7))
START_TIME = time(6, 25)  # เริ่มส่งรอบแรก 6:30 (ใช้ 6:25 เผื่อดีเลย์)
END_TIME = time(23, 35)   # ส่งรอบสุดท้าย 23:30 (ใช้ 23:35 เผื่อดีเลย์)
# ------------------------------

def get_seconds_until_next_run():
    """คำนวณวินาทีที่เหลือก่อนถึงนาทีที่ 20 หรือ 50 ของชั่วโมง เพื่อตั้งเวลาส่งบอทรอบถัดไป"""
    now = datetime.now(BANGKOK_TZ)
    target = now.replace(minute=20, second=0, microsecond=0)
    if target <= now:
        target = now.replace(minute=50, second=0, microsecond=0)
        if target <= now:
            target = (now + timedelta(hours=1)).replace(minute=20, second=0, microsecond=0)
    return int((target - now).total_seconds())

async def send_qs_updates(context: ContextTypes.DEFAULT_TYPE):
    """ฟังก์ชันหลักในการดึงรูปและส่ง"""
    chat_id = context.job.chat_id if context.job else MY_CHAT_ID
    if not chat_id:
        log_msg("❌ ไม่พบ Chat ID ที่จะส่งรูปให้")
        return

    # เช็คเวลาทำงาน (เฉพาะงานอัตโนมัติ)
    if context.job:
        now = datetime.now(BANGKOK_TZ)
        current_time = now.time()
        if not (START_TIME <= current_time <= END_TIME):
            log_msg(f"💤 นอกเวลาทำงาน ({current_time.strftime('%H:%M')}), ข้ามการส่งรูปอัตโนมัติ")
            return

    log_msg(f"Syncing QuikStrike data for {chat_id}...")
    images, err = await fetch_quikstrike_data()
    
    if err:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ ดึงข้อมูลไม่สำเร็จ: {err}")
        return

    await context.bot.send_message(chat_id=chat_id, text=f"📊 **QuikStrike Update**\nดึงข้อมูลสำเร็จ {len(images)} รูปครับ")
    
    for img_path in images:
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id, 
                        photo=io.BytesIO(f.read()),
                        read_timeout=60,
                        write_timeout=60,
                        pool_timeout=60
                    )
                    await asyncio.sleep(1) # ป้องกันโดน Telegram flood limit
            except Exception as e:
                log_msg(f"❌ ส่งรูป {img_path} ไม่สำเร็จ: {e}")
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ ส่งรูป {img_path} ไม่สำเร็จ โปรดลองใหม่")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    log_msg(f"DEBUG: USER CHAT ID IS: {user_id}")
    with open("chat_id.txt", "w") as f:
        f.write(str(user_id))
    await update.message.reply_text(
        f"🚀 บอทส่งรูป QuikStrike เริ่มทำงานแล้ว!\nYour Chat ID: {user_id}\n\n"
        "ใช้คำสั่ง /sync เพื่อดึงรูปทันที\n"
        "ใช้คำสั่ง /auto_on เพื่อเปิดระบบส่งอัตโนมัติทุก 1 ชม."
    )

async def sync_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    log_msg(f"Manual sync requested by {user_id}")
    await update.message.reply_text("⏳ กำลังดึงข้อมูล... อาจใช้เวลา 30-60 วินาทีครับ")
    # สร้าง dummy context เพื่อเรียกใช้ฟังก์ชันส่ง
    class DummyJob:
        def __init__(self, cid): self.chat_id = cid
    
    dummy_context = context
    dummy_context.job = None # ต้องเป็น None เพื่อข้ามการเช็คเวลา
    log_msg(f"Starting sync for {user_id}...")
    await send_qs_updates(dummy_context)
    log_msg(f"Sync completed for {user_id}")

async def auto_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    # ลบงานเก่าถ้ามี
    current_jobs = context.job_queue.get_jobs_by_name(f"qs_sync_{chat_id}")
    for job in current_jobs: job.schedule_removal()
    
    first_delay = get_seconds_until_next_run()
    # ตั้งเวลาทุก 30 นาที
    context.job_queue.run_repeating(
        send_qs_updates,
        interval=1800, # 30 minutes
        first=first_delay,
        chat_id=chat_id,
        name=f"qs_sync_{chat_id}"
    )
    await update.message.reply_text("✅ เปิดระบบส่งรูปอัตโนมัติทุก 30 นาที (ตรงนาทีที่ 20 และ 50) เรียบร้อยครับ!")

async def auto_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    current_jobs = context.job_queue.get_jobs_by_name(f"qs_sync_{chat_id}")
    for job in current_jobs: job.schedule_removal()
    await update.message.reply_text("🔕 ปิดระบบส่งรูปอัตโนมัติแล้วครับ")

async def post_init(app):
    """รันตอนเริ่มบอท - เปิดระบบอัตโนมัติให้ MY_CHAT_ID ทันที"""
    if MY_CHAT_ID:
        log_msg(f"Auto-starting sync job for {MY_CHAT_ID}")
        first_delay = get_seconds_until_next_run()
        
        try:
            await app.bot.send_message(
                chat_id=MY_CHAT_ID,
                text=f"🤖 **Standalone Bot Online**\n"
                     f"เริ่มระบบส่งรูปอัตโนมัติเรียบร้อยแล้วครับ (ส่งรูปที่นาทีที่ 20 และ 50 ของแต่ละชั่วโมง)\n"
                     f"รอบแรกจะทำงานในอีก {first_delay // 60} นาที {first_delay % 60} วินาทีครับ"
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

def main():
    if not TELEGRAM_TOKEN:
        print("❌ ไม่พบ STANDALONE_BOT_TOKEN ใน .env")
        return

    print("QuikStrike Image Bot is starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sync", sync_now))
    app.add_handler(CommandHandler("auto_on", auto_on))
    app.add_handler(CommandHandler("auto_off", auto_off))

    app.run_polling()

if __name__ == "__main__":
    main()
