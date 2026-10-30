import os
import io
import json
import zipfile
import asyncio
import threading
from flask import Flask
from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ---------------------------------------------------------
# Flask Server for Render Port Binding
# ---------------------------------------------------------
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "TV Automation Bot is Running!", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ---------------------------------------------------------
# Admin & Service Configuration
# ---------------------------------------------------------
ADMIN_USERNAME = "Akk_Taiyou_Asano".lower()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # Can be 0 if using username check

STOCK_DIR = "stock"
COOKIES_DIR = os.path.join(STOCK_DIR, "cookies")
os.makedirs(COOKIES_DIR, exist_ok=True)

SERVICES = {
    "netflix": {
        "name": "Netflix 🔴",
        "url": "https://www.netflix.com/tv2",
        "cookie_domain": ".netflix.com"
    },
    "crunchyroll": {
        "name": "Crunchyroll 🟠",
        "url": "https://www.crunchyroll.com/activate",
        "cookie_domain": ".crunchyroll.com"
    }
}

def is_admin(user) -> bool:
    if user.username and user.username.lower() == ADMIN_USERNAME:
        return True
    if ADMIN_ID and user.id == ADMIN_ID:
        return True
    return False

def get_service_folder(service_key: str) -> str:
    path = os.path.join(COOKIES_DIR, service_key)
    os.makedirs(path, exist_ok=True)
    return path

def count_stock(service_key: str) -> int:
    folder = get_service_folder(service_key)
    return len([f for f in os.listdir(folder) if f.endswith(".json")])

def pop_stock_cookie(service_key: str):
    folder = get_service_folder(service_key)
    files = [f for f in os.listdir(folder) if f.endswith(".json")]
    if not files:
        return None, None
    target_file = files[0]
    filepath = os.path.join(folder, target_file)
    with open(filepath, "r", encoding="utf-8") as f:
        cookie_data = json.load(f)
    os.remove(filepath)  # Consume the cookie from stock
    return cookie_data, target_file

# ---------------------------------------------------------
# Browser Automation Engine (Playwright)
# ---------------------------------------------------------
async def automate_tv_activation(service_key: str, cookies: list, tv_code: str) -> bytes | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # Format and inject cookies
        formatted_cookies = []
        for c in cookies:
            cookie_dict = {
                "name": c.get("name"),
                "value": c.get("value"),
                "domain": c.get("domain", SERVICES[service_key]["cookie_domain"]),
                "path": c.get("path", "/")
            }
            formatted_cookies.append(cookie_dict)
            
        await context.add_cookies(formatted_cookies)
        page = await context.new_page()

        try:
            if service_key == "netflix":
                await page.goto("https://www.netflix.com/tv2", wait_until="networkidle", timeout=30000)
                # If redirected to login, the cookie is expired
                if "login" in page.url:
                    await browser.close()
                    return None
                
                # Fill TV activation inputs
                # Netflix usually has multiple input boxes or a single unified code box
                inputs = await page.locator("input[data-uia*='code-input'], input[name*='code'], input[type='text']").all()
                if len(inputs) == 1:
                    await inputs[0].fill(tv_code)
                elif len(inputs) > 1:
                    for i, char in enumerate(tv_code[:len(inputs)]):
                        await inputs[i].fill(char)
                
                await page.keyboard.press("Enter")
                await asyncio.sleep(4)  # Wait for submission and confirmation

            elif service_key == "crunchyroll":
                await page.goto("https://www.crunchyroll.com/activate", wait_until="networkidle", timeout=30000)
                if "login" in page.url:
                    await browser.close()
                    return None

                await page.locator("input[type='text']").first.fill(tv_code)
                await page.keyboard.press("Enter")
                await asyncio.sleep(4)

            # Capture live visual proof of the activation screen
            screenshot_bytes = await page.screenshot(full_page=False)
            await browser.close()
            return screenshot_bytes

        except Exception as e:
            print(f"Automation Error: {e}")
            await browser.close()
            return None

# ---------------------------------------------------------
# Bot Command Handlers
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome to the Automated TV Activation Bot!**\n\n"
        "To activate your device, type:\n"
        "`/tv <TV_CODE>`\n\n"
        "**Example:**\n`/tv 839210`",
        parse_mode="Markdown"
    )

async def tv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide the TV code.\nExample: `/tv 839210`",
            parse_mode="Markdown"
        )
        return

    tv_code = context.args[0].strip()
    context.user_data["pending_tv_code"] = tv_code

    keyboard = []
    for key, info in SERVICES.items():
        qty = count_stock(key)
        keyboard.append([InlineKeyboardButton(f"{info['name']} ({qty} Available)", callback_data=f"act_{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📺 **Code:** `{tv_code}`\n\nSelect the service you want to activate:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    service_key = query.data.replace("act_", "")
    service_info = SERVICES.get(service_key)
    tv_code = context.user_data.get("pending_tv_code")

    if not tv_code:
        await query.edit_message_text("❌ Session expired. Type `/tv <CODE>` again.", parse_mode="Markdown")
        return

    cookie_data, cookie_file = pop_stock_cookie(service_key)
    if not cookie_data:
        await query.edit_message_text(
            f"❌ **{service_info['name']}** is currently out of stock!",
            parse_mode="Markdown"
        )
        return

    status_msg = await query.edit_message_text(
        f"🔄 **Automating {service_info['name']} activation...**\n"
        f"Logging into account and entering TV Code `{tv_code}` in browser...",
        parse_mode="Markdown"
    )

    # Perform automated browser entry and screenshot capture
    screenshot = await automate_tv_activation(service_key, cookie_data, tv_code)

    if not screenshot:
        await status_msg.edit_text(
            f"❌ The assigned account/cookie was invalid or session expired. Please contact support or try again.",
            parse_mode="Markdown"
        )
        return

    await status_msg.delete()
    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=screenshot,
        caption=(
            f"✅ **Activation Successful!**\n\n"
            f"📺 **Code Entered:** `{tv_code}`\n"
            f"🎬 **Service:** {service_info['name']}\n\n"
            f"Check your TV screen now - it should be connected!"
        ),
        parse_mode="Markdown"
    )

# ---------------------------------------------------------
# Admin Stock Management (ZIP & JSON Cookies)
# ---------------------------------------------------------
async def admin_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return

    msg = "📊 **Current Cookie Stock:**\n\n"
    for key, info in SERVICES.items():
        qty = count_stock(key)
        msg += f"• **{info['name']}**: `{qty}` accounts/cookies available\n"

    msg += (
        "\n📥 **Upload Instructions:**\n"
        "Send `.json` files or a `.zip` archive containing your exported JSON cookies.\n"
        "Set the file **Caption** to the target service (`netflix` or `crunchyroll`)."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return

    document = update.message.document
    caption = (update.message.caption or "").strip().lower()

    if caption not in SERVICES:
        await update.message.reply_text(
            f"⚠️ Invalid caption. Please set caption to: `{'` or `'.join(SERVICES.keys())}`",
            parse_mode="Markdown"
        )
        return

    file_name = document.file_name.lower()
    await update.message.reply_text("⏳ Processing and organizing cookies...")

    tg_file = await document.get_file()
    downloaded_bytes = await tg_file.download_as_bytearray()
    saved_count = 0
    target_dir = get_service_folder(caption)

    if file_name.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(downloaded_bytes)) as z:
                for z_name in z.namelist():
                    if z_name.endswith(".json"):
                        content = z.read(z_name).decode("utf-8", errors="ignore")
                        data = json.loads(content)
                        # Save each individual cookie file
                        save_name = f"cookie_{len(os.listdir(target_dir)) + 1}.json"
                        with open(os.path.join(target_dir, save_name), "w", encoding="utf-8") as out:
                            json.dump(data, out)
                        saved_count += 1
        except Exception as e:
            await update.message.reply_text(f"❌ Error unpacking ZIP: `{e}`", parse_mode="Markdown")
            return
    elif file_name.endswith(".json"):
        try:
            content = downloaded_bytes.decode("utf-8", errors="ignore")
            data = json.loads(content)
            save_name = f"cookie_{len(os.listdir(target_dir)) + 1}.json"
            with open(os.path.join(target_dir, save_name), "w", encoding="utf-8") as out:
                json.dump(data, out)
            saved_count = 1
        except Exception as e:
            await update.message.reply_text(f"❌ Error parsing JSON: `{e}`", parse_mode="Markdown")
            return

    await update.message.reply_text(
        f"✅ Successfully added `{saved_count}` cookie(s) to **{SERVICES[caption]['name']}**.\n"
        f"📦 Total in stock: `{count_stock(caption)}`",
        parse_mode="Markdown"
    )

# ---------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN!")

    threading.Thread(target=run_web, daemon=True).start()

    app = ApplicationBuilder().token(token).build()

    # User Routes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tv", tv_command))
    app.add_handler(CallbackQueryHandler(service_callback, pattern="^act_"))

    # Admin Routes
    app.add_handler(CommandHandler("stock", admin_stock))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_admin_upload))

    app.run_polling()

if __name__ == "__main__":
    main()