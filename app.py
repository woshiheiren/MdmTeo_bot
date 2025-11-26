import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---
# This loads the keys from your .env file (for local use).
# On Render, it will skip this and use the Cloud Environment Variables.
load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- FLASK KEEP-ALIVE SERVER ---
app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Mdm Teo wake up liao!'

def run_flask():
    # Render assigns a port automatically via os.environ.get('PORT')
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ignore updates that aren't text messages
    if not update.message or not update.message.text:
        return

    user_msg = update.message.text
    user_name = update.message.from_user.username
    
    # Print to console (so you can see what's happening locally/in logs)
    print(f"Received: '{user_msg}' from @{user_name}")

    try:
        # 1. Send message to Gemini
        chat = model.start_chat(history=[])
        response = chat.send_message(f"User @{user_name} said: {user_msg}")
        reply_text = response.text.strip()

        # 2. Check for the "Silence" rule
        if "IGNORE" in reply_text:
            print(">> Mdm Tan ignored this.")
            return
        
        # 3. Send reply to Telegram
        await context.bot.send_message(chat_id=update.effective_chat.id, text=reply_text)

    except Exception as e:
        print(f"Error handling message: {e}")

# --- 6. MAIN EXECUTION ---
if __name__ == '__main__':
    # Start Flask in a background thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN is missing. Check your .env file or Render settings.")
    else:
        print("Mdm Tan is starting up...")
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Filter: Handle text messages that are NOT commands
        msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        application.add_handler(msg_handler)
        
        # Run the bot
        application.run_polling()