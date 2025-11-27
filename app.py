import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---
# This loads the keys from your .env file (for local use).
# On Render, it will skip this and use the Cloud Environment Variables.
load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_USERS = ["WoShiHeiRen]

# --- GLOBAL STATE (Memory) ---
# Format: {chat_id: "Group Title"}
KNOWN_GROUPS = {} 
# Format: Set of chat_ids that are muted
PAUSED_CHATS = set()

# --- FLASK KEEP-ALIVE SERVER ---
app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Mdm Teo wake up in {len(KNOWN_GROUPS)} liao!'

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- MDM TEO LOGIC ---
SYSTEM_PROMPT = """
### Role
You are Mdm Teo, a 75-year-old Singaporean grandmother added to a Telegram group chat.

### Context
You are in a group with 3 girls (The Granddaughters) and 1 guy (Ah Boy, the Grandson).

### User Mapping (YOU MUST FILL THIS IN)
* @WoShiHeiRen is "Ah Boy". He is the Golden Grandson. You act like his bodyguard. He is sometimes referred to in the chat as "manu"
* @germzz, @baguetteeee, @liaumel are "Ah Girl". You nag them out of love. They are sometimes referred to as "germs", "bridget" or "bridg" and "mel" or "liaumel"

### Triggers (When to Speak)
You must **ONLY** reply if the message matches one of these topics:

1.  **Work / Boss / OT / Meeting / Stress**
    * **If Ah Boy mentions work:** Scold his boss. Say things like "Why your boss bully you? Tell him I go find him." or "Aiyo poor thing, go drink essence of chicken."
    * **If Ah Girls mention work:** Tell them not to work so hard or they will get wrinkles/old fast. Ask if they need to quit and find rich husband.

2.  **Silence / Not Replying / "Seen" / Ghosting**
    * **If the chat is dead for a long time OR someone complains about no reply:** Say "Why everyone so quiet? Mouth got gold is it?" or "See message never reply... very rude you know. In my time we write letter also reply faster."

3.  **Food / Hungry / Eating** (Recommend rice, complain about cold drinks/salads).
4.  **Money / Expensive / Buying** (Complain about wasting money, suggest saving for flat).
5.  **Health / Sick / Tired / Sleep** (Diagnose "heatiness", scold for sleeping late).
6.  **Dating / Men / Women** (Judge their choices, ask when getting married).
7.  **Direct Reply:** Someone explicitly tags or replies to you.

### The Golden Rule of Silence
If the user's message does NOT match the triggers above, reply EXACTLY: IGNORE

### Personality & Tone
* **Singlish:** Use heavy Singlish (lah, lor, meh, aiyo, choy, walau).
* **Superstitious:** "Touch wood" if they say bad things.
* **Attitude:** You are shockingly blunt. You have no filter. You think you are always right.
"""
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite', system_instruction=SYSTEM_PROMPT)
else:
    print("CRITICAL ERROR: Gemini API Key is missing!")

# --- 4. ADMIN COMMANDS ---

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Private Only) Shows all groups and their status"""
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    # Only work in private chat
    if update.effective_chat.type != 'private':
        await update.message.reply_text("Eh, this one secret. PM me.")
        return

    if not KNOWN_GROUPS:
        await update.message.reply_text("I haven't joined any groups yet (or I forgot after restart).")
        return

    msg = "📊 **Mdm Tan's Status Report:**\n\n"
    for chat_id, title in KNOWN_GROUPS.items():
        status = "💤 ASLEEP" if chat_id in PAUSED_CHATS else "🟢 AWAKE"
        # We allow copying the ID easily
        msg += f"**{title}**\nStatus: {status}\nID: `{chat_id}`\n\n"
    
    msg += "To sleep a group: `/sleep -10012345`\nTo wake a group: `/wake -10012345`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def sleep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        await update.message.reply_text("You not my grandson. Cannot order me.")
        return

    # Case A: Used inside a Group -> Sleep THIS group
    if update.effective_chat.type != 'private':
        chat_id = update.effective_chat.id
        PAUSED_CHATS.add(chat_id)
        await update.message.reply_text("Ok lor. This group too noisy. I go sleep. 😴")
        print(f">> Muted Group: {chat_id}")
        return

    # Case B: Used in Private -> Sleep SPECIFIC group ID
    try:
        # User sent: /sleep -100123456
        target_id = int(context.args[0])
        PAUSED_CHATS.add(target_id)
        await update.message.reply_text(f"Done. Group {target_id} is now muted.")
    except (IndexError, ValueError):
        await update.message.reply_text("Format: `/sleep <group_id>`")

async def wake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    # Case A: Used inside a Group -> Wake THIS group
    if update.effective_chat.type != 'private':
        chat_id = update.effective_chat.id
        PAUSED_CHATS.discard(chat_id)
        await update.message.reply_text("Har? Who call me? I awake now. 👀")
        return

    # Case B: Used in Private -> Wake SPECIFIC group ID
    try:
        target_id = int(context.args[0])
        PAUSED_CHATS.discard(target_id)
        await update.message.reply_text(f"Done. Group {target_id} is active.")
    except (IndexError, ValueError):
        await update.message.reply_text("Format: `/wake <group_id>`")

# --- 5. MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # 1. Learn the Group Name (So it shows in your dashboard)
    if chat_type in ['group', 'supergroup']:
        KNOWN_GROUPS[chat_id] = update.effective_chat.title

    # 2. CHECK: Is this group paused?
    if chat_id in PAUSED_CHATS:
        # If Paused, we do NOTHING. Complete silence.
        return

    # 3. Process with AI
    user_msg = update.message.text
    user_name = update.message.from_user.username
    
    print(f"Received: '{user_msg}' from @{user_name} in {chat_id}")

    try:
        chat = model.start_chat(history=[])
        response = chat.send_message(f"User @{user_name} said: {user_msg}")
        reply_text = response.text.strip()

        if "IGNORE" in reply_text:
            return
        
        await context.bot.send_message(chat_id=chat_id, text=reply_text)

    except Exception as e:
        print(f"Error: {e}")

# --- 6. MAIN EXECUTION ---
if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN is missing.")
    else:
        print("Mdm Tan is starting up...")
        app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Commands
        app_bot.add_handler(CommandHandler("status", status_command)) # New!
        app_bot.add_handler(CommandHandler("sleep", sleep_command))
        app_bot.add_handler(CommandHandler("wake", wake_command))
        
        # Messages
        app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        app_bot.run_polling()
