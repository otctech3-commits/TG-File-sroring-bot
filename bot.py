import asyncio
import os
import secrets
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ===== CONFIG FROM ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BUTTON_1_URL = os.getenv("BUTTON_1_URL", "https://t.me/mkbots")
BUTTON_2_URL = os.getenv("BUTTON_2_URL", "https://mk-bots.blogspot.com")
DELETE_AFTER = int(os.getenv("DELETE_AFTER", "180")) # 3 minutes

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== IN-MEMORY STORAGE =====
file_storage = {}
batch_mode = defaultdict(list)
delete_queue = {}

# ===== START COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith('file_'):
        token = args[0][5:]
        await send_stored_files(update, context, token)
        return

    keyboard = [
        [InlineKeyboardButton("📢 Channel", url=BUTTON_1_URL),
         InlineKeyboardButton("🌐 Website", url=BUTTON_2_URL)],
        [InlineKeyboardButton("📦 Batch Mode", callback_data="batch_mode"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    welcome_text = """
🎉 **Welcome to 𝙈𝙆 BOTS File Store**

I store your files and give you a shareable link.
Files auto-delete 3 minutes after someone downloads them.

**How to use:**
1. Send me any file/document/video/photo
2. I’ll give you a private link
3. Share the link. File deletes 3 min after opening

**Batch Mode:** Use /batch to store multiple files in one link

⚠️ **Note:** Files are temporary. Download within 3 min of opening link.
"""
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ===== BATCH COMMANDS =====
async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    batch_mode[user_id] = []
    await update.message.reply_text("📦 **Batch Mode Activated**\n\nSend files now. Use /done when finished, /cancel to abort.", parse_mode='Markdown')

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not batch_mode.get(user_id):
        await update.message.reply_text("❌ No files in batch. Send files first or use /batch")
        return
    token = secrets.token_urlsafe(8)
    file_storage[token] = {
        'files': batch_mode[user_id].copy(),
        'user_id': user_id,
        'created': datetime.now()
    }
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=file_{token}"
    file_count = len(batch_mode[user_id])
    batch_mode[user_id] = []
    await update.message.reply_text(f"✅ **Batch Link Created**\n\n📦 Files: {file_count}\n🔗 `{link}`\n\n⚠️ Deletes 3 min after opening", parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    batch_mode[user_id] = []
    await update.message.reply_text("❌ Batch mode cancelled.")

# ===== HANDLE FILES =====
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    file_id, file_name = None, "File"

    if message.document:
        file_id, file_name = message.document.file_id, message.document.file_name or "Document"
    elif message.video:
        file_id, file_name = message.video.file_id, "Video"
    elif message.photo:
        file_id, file_name = message.photo[-1].file_id, "Photo"
    elif message.audio:
        file_id, file_name = message.audio.file_id, message.audio.file_name or "Audio"
    elif message.voice:
        file_id, file_name = message.voice.file_id, "Voice"
    else:
        await message.reply_text("❌ Unsupported file type")
        return

    if batch_mode.get(user_id) is not None and isinstance(batch_mode[user_id], list):
        batch_mode[user_id].append({'id': file_id, 'name': file_name})
        await message.reply_text(f"✅ Added: {file_name}\n📦 Total: {len(batch_mode[user_id])} files\nSend /done to get link")
        return

    token = secrets.token_urlsafe(8)
    file_storage[token] = {'files': [{'id': file_id, 'name': file_name}], 'user_id': user_id, 'created': datetime.now()}
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=file_{token}"
    await message.reply_text(f"✅ **File Stored**\n\n📄 {file_name}\n🔗 `{link}`\n\n⚠️ Deletes 3 min after opening\n💡 Use /batch for multiple files", parse_mode='Markdown')

# ===== SEND FILES + AUTO DELETE =====
async def send_stored_files(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user = update.effective_user
    if token not in file_storage:
        await update.message.reply_text("❌ **Link Expired**\n\nFile deleted or invalid link.", parse_mode='Markdown')
        return

    data = file_storage.pop(token) # One-time use
    files = data['files']
    sent_messages = []
    await update.message.reply_text(f"📦 **Sending {len(files)} file(s)...**\n⏰ Auto-delete in {DELETE_AFTER//60} min", parse_mode='Markdown')

    for file in files:
        try:
            sent = await context.bot.send_document(chat_id=user.id, document=file['id'], caption=f"📄 {file['name']}\n⏰ Deleting in {DELETE_AFTER//60} min")
            sent_messages.append(sent.message_id)
        except Exception as e:
            logger.error(f"Send error: {e}")

    delete_time = datetime.now() + timedelta(seconds=DELETE_AFTER)
    asyncio.create_task(delete_messages_later(context, sent_messages, user.id, delete_time))

async def delete_messages_later(context: ContextTypes.DEFAULT_TYPE, message_ids: list, chat_id: int, delete_at: datetime):
    await asyncio.sleep((delete_at - datetime.now()).total_seconds())
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass
    try:
        await context.bot.send_message(chat_id=chat_id, text="🗑️ **Files deleted**\n\nTemporary files removed for privacy.", parse_mode='Markdown')
    except:
        pass

# ===== BUTTONS =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "batch_mode":
        await batch_command(query, context)
    elif query.data == "help":
        help_text = """
❓ **Help - 𝙈𝙆 BOTS File Store**

**Commands:**
/start - Show menu
/batch - Start batch mode
/done - Finish batch
/cancel - Cancel batch

**How it works:**
1. Send file → Get link
2. Share link → Receiver gets file
3. File auto-deletes after 3 minutes

**Limits:** 2GB max per file. Links are one-time use.
"""
        await query.message.reply_text(help_text, parse_mode='Markdown')

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN env variable not set")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.Video | filters.Photo | filters.Audio | filters.Voice, handle_file))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info(f"🤖 Bot Started | Auto-delete: {DELETE_AFTER}s")
    app.run_polling()

if __name__ == '__main__':
    main()
