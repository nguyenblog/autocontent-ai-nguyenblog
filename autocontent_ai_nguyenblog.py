from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, ConversationHandler
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
from docx import Document
from openai import OpenAI
import os
from flask import Flask, request
import threading
import asyncio

# 🛠️ Load API Keys từ biến môi trường
TOKEN = os.getenv("TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# 🔹 Cấu hình Flask để chạy Webhook
app = Flask(__name__)

WEBHOOK_URL = "https://your-railway-app.up.railway.app/webhook"  # 🔄 Thay bằng URL từ Railway sau khi deploy

# Định nghĩa trạng thái cho ConversationHandler
AWAITING_PROMPT = 1

# Dictionary lưu trữ văn bản của từng người dùng
user_text_data = {}

async def query_openai(prompt, text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ]
        )  # ❌ Xóa max_tokens để không giới hạn token
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Lỗi OpenAI: {str(e)}")  # Log lỗi để debug
        return f"⚠️ Lỗi khi gọi API OpenAI: {str(e)}"

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.document.get_file()
        file_path = f"./{update.message.document.file_name}"

        await file.download(file_path)
        await update.message.reply_text("✅ Đã nhận file, đang xử lý...")

        full_text = ""
        
        if file_path.lower().endswith(".pdf"):
            pdf = fitz.open(file_path)
            for page_num in range(len(pdf)):
                page = pdf.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    full_text += text
                else:
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes()
                    img = Image.open(io.BytesIO(img_bytes))
                    ocr_text = pytesseract.image_to_string(img, lang="eng+vie")
                    full_text += ocr_text
            pdf.close()
        
        elif file_path.lower().endswith(".docx"):
            doc = Document(file_path)
            full_text = '\n'.join([para.text for para in doc.paragraphs])
        
        else:
            await update.message.reply_text("⚠️ Định dạng file không được hỗ trợ.")
            return

        user_text_data[update.message.chat_id] = full_text
        await update.message.reply_text("📌 Vui lòng nhập prompt để xử lý nội dung văn bản.")
        return AWAITING_PROMPT

    except Exception as e:
        print(f"⚠️ Lỗi xử lý file: {str(e)}")  # Log lỗi để debug
        await update.message.reply_text(f"⚠️ Đã xảy ra lỗi trong quá trình xử lý: {str(e)}")

async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in user_text_data:
        await update.message.reply_text("⚠️ Không tìm thấy nội dung văn bản. Vui lòng gửi lại file trước.")
        return ConversationHandler.END
    
    prompt = update.message.text
    full_text = user_text_data.pop(user_id)

    await update.message.reply_text("🤖 Đang gửi nội dung đến ChatGPT...")
    ai_response = await query_openai(prompt, full_text)
    
    response_file_path = f"response_{user_id}.txt"
    with open(response_file_path, "w", encoding="utf-8") as file:
        file.write(ai_response)
    
    with open(response_file_path, "rb") as file:
        await update.message.reply_document(file)
    
    return ConversationHandler.END

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

@app.route("/webhook", methods=["POST"])
async def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.update_queue.put(update)
        return "OK", 200
    except Exception as e:
        print(f"⚠️ Lỗi Webhook: {str(e)}")
        return "ERROR", 500

async def start_bot():
    global application
    application = Application.builder().token(TOKEN).build()

    await application.initialize()
    await application.bot.set_webhook(url=WEBHOOK_URL)

    print(f"🚀 Webhook đã được thiết lập tại: {WEBHOOK_URL}")
    await application.run_polling()

def run_flask():
    """ Chạy Flask trên một thread riêng để không chặn bot """
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    # Tạo và chạy bot trong một luồng asyncio riêng
    bot_thread = threading.Thread(target=lambda: asyncio.run(start_bot()), daemon=True)
    bot_thread.start()

    # Chạy Flask trên main thread
    run_flask()
