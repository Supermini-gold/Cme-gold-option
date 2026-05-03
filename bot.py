import os
import io
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
import PIL.Image

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize APIs
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
else:
    gemini_model = None

# Store user photos
user_photos = {}

def get_system_prompt():
    try:
        with open("gold_options_prompt.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are an AI assistant analyzing images."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_photos[user_id] = []
    await update.message.reply_text(
        "สวัสดีครับ! ส่งภาพหน้าจอ QuikStrike (Volume, OI, OI Change) รวม 3 รูปมาให้ผมได้เลยครับ\n"
        "เมื่อส่งครบ 3 รูป ผมจะให้ Gemini ทำการวิเคราะห์ให้ทันทีครับ"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    
    if user_id not in user_photos:
        user_photos[user_id] = []
        
    # Get the highest resolution photo
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()
    
    user_photos[user_id].append(photo_bytes)
    count = len(user_photos[user_id])
    
    if count < 3:
        await update.message.reply_text(f"ได้รับภาพที่ {count}/3 แล้วครับ ส่งมาเพิ่มได้เลย")
    elif count == 3:
        await update.message.reply_text("ได้รับครบ 3 ภาพแล้วครับ! ⏳ กำลังส่งข้อมูลให้ Gemini 2.5 Flash วิเคราะห์... อาจใช้เวลา 10-30 วินาทีครับ")
        
        photos = user_photos[user_id]
        prompt = get_system_prompt()
        
        try:
            if not gemini_model:
                await update.message.reply_text("❌ ขาด Gemini API Key ในไฟล์ .env")
                user_photos[user_id] = []
                return
                
            images = [PIL.Image.open(io.BytesIO(pb)) for pb in photos]
            response = gemini_model.generate_content([prompt] + images)
            result = response.text
                
            # Send result (handle long texts if over Telegram limit)
            if len(result) > 4000:
                for i in range(0, len(result), 4000):
                    await update.message.reply_text(result[i:i+4000], parse_mode='Markdown')
            else:
                await update.message.reply_text(result, parse_mode='Markdown')
                
        except Exception as e:
            await update.message.reply_text(f"❌ เกิดข้อผิดพลาดระหว่างวิเคราะห์: {str(e)}")
            
        # Clear photos after analysis
        user_photos[user_id] = []
    else:
        # If they send more than 3, reset and start over
        user_photos[user_id] = [photo_bytes]
        await update.message.reply_text("เริ่มเซสชันใหม่ ได้รับภาพที่ 1/3 แล้วครับ")

def main():
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "your_telegram_bot_token_here":
        print("⚠️ ข้อผิดพลาด: ไม่พบ TELEGRAM_BOT_TOKEN ในไฟล์ .env")
        print("กรุณาเปิดไฟล์ .env แล้วนำ Token ที่ได้จาก @BotFather มาใส่ครับ")
        return
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("✅ บอทกำลังทำงาน... เปิด Telegram แล้วพิมพ์ /start ได้เลยครับ")
    print("กด Ctrl+C เพื่อปิดบอท")
    app.run_polling()

if __name__ == "__main__":
    main()
