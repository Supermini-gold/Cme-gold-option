import os
import asyncio
import io
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from telegram import Update, Bot
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

# ดึง Token ของบอทตัวแรก
MAIN_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
main_bot_client = Bot(token=MAIN_BOT_TOKEN) if MAIN_BOT_TOKEN else None

log_msg(f"Bot config loaded. Target Chat ID: {MY_CHAT_ID}")
if main_bot_client:
    log_msg("✅ Main Bot Token detected. Forwarding configuration active.")

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
        "/auto_off — ปิดระบบอัตโนมัติ\n\n"
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

    app.run_polling()


if __name__ == "__main__":
    main()
