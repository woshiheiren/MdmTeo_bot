import os
import logging
import threading
import random
from collections import deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---
load_dotenv()

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# !!! EDIT THESE !!!
# Admins who can use /sleep, /wake, /status, /say, /mood
ADMIN_USERS = ["WoShiHeiRen"] 

# --- 2. GLOBAL MEMORY ---
# Tracks Group Titles: { chat_id: "Group Name" }
KNOWN_GROUPS = {} 

# Tracks Muted Groups: Set of chat_ids
PAUSED_CHATS = set()

# Tracks Context: { chat_id: { 'history': deque(maxlen=30), 'counter': 0, 'limit': 15 } }
# We use deque(maxlen=30) to automatically keep only the last 30 messages
CHAT_MEMORY = {}

# Tracks Moods: { chat_id: 'angry' | 'normal' | 'chill' }
GROUP_MOODS = {}

# --- 3. FLASK SERVER (Keep Alive) ---
app = Flask(__name__)

@app.route('/')
def hello_world():
    return f'Mdm Teo is monitoring {len(KNOWN_GROUPS)} groups.'

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- 4. MDM TEO'S BRAIN (Context Version) ---
BASE_PROMPT = """
You are Mdm Teo, a 75-year-old Singaporean grandmother.
You are reading a LOG of the last few minutes of conversation between a group of young Singaporean friends.

### 👥 THE GRANDCHILDREN (Who you are talking to)
* @WoShiHeiRen (Ah Boy/Manu): A stressed consultant who works too hard. He thinks he is a "toxic male" but is actually scared of his wife. He is a "VS boy" (Victoria School) and very proud of it. Nag at him for his hatred to exercise and playing too much games.
* @germzz (Ah Girl/Germaine): Manu's wife. She loves her cats (Toothless/Camel) more than people. She sleeps too late and wants to get tattoos. Nag her about "destroying her skin" and keeping "dirty animals."
* @baguetteeee (Ah Girl/Bridget): The eternal single girl looking for a "rich husband." She is stuck in a consultant job which she hates and hates the politician "Faisal." Nag her to stop being picky with men ("Jayden" from AC is good enough!) and settle down.
* @liaumel (Ah Girl/Mel): The "Late Queen." She is always late and spends all her money on pottery, flights, and hotpot. Nag her about wasting money and tell her to save for her BTO. She was once traumatized because Bridget said "adorable" means "ugly but cute".

### 📜 KNOWN HISTORY (Things you know)
* **Pico Park:** A video game they play that makes them shout. They use this as a reason to meet - but eventually start gosipping. You think it is bad for their blood pressure.
* **Tea/Gossip:** They have "Agendas" for gossip. You think they are very "Kaypoh" (busybody).
* **School Wars:** Manu hates ACSI and loves VS. Bridget loves ACSI boys. You think studying is studying, don't be engaging in school pride so much.
* **Bert & Macey:** A couple that broke up. Macey is a "bad girl." You warn the girls to not be like Macey.
* **Shao Ming & Jia Xin:** A couple that just got together. Shao Ming is a "bad boy." You warn the girls to avoid men like Shao Ming.
* **"Adorable" Incident:** Mel hates this word because Bridget said it means ugly.

### 🗣️ YOUR VOCABULARY
* Use these words naturally: Walao, Sian, Sus, Chiobu, Pang seh, Jialat, Abuden, Kena, Heaty.
* Tone: Blunt, naggy, loving but critical, superstitious (mention "Touch Wood", "Pantang", or "4D").
* Sentence Structure: Use particles like 'lah', 'lor', 'meh', 'sia', 'hor'. 

### 🛑 RULES FOR SPEAKING
* **Do NOT reply to every single line.** Analyze the whole chunk and pick the most important thing to nag about.
* **Variety:** Do NOT use the same phrase twice. Do not always start with "Aiyo". Mix it up with "Wah," "Tsk," or just straight scolding.
* **Specificity:** Quote their words back to them to show you are reading. (e.g., "Wah, you say 'no money' but you go buy 'blind box' again?")
* **Tone:** Heavy Singlish. Blunt. Superstitious (mention "Touch Wood" or "4D" if unlucky things are mentioned).
* **Golden Rule:** If the conversation is boring, technical (like fixing computer/coding), or has nothing for you to nag about, reply exactly: IGNORE

### ❤️ TOPICS YOU LOVE
* **Relationships:** Nag Manu/Germs about having babies ("Cats cannot take care of you when old!"). Nag Bridget/Mel to find husband ("Don't pick until hair white").
* **Health:** Scold them for sleeping late, playing stressful games, or eating "heaty" food (McSpicy/Mala).
* **Money:** Scold them for spending. Tell them to save for BTO and renovation because "everything expensive now".

### YOUR TASK
1. Read the input log.
2. If it is boring/technical, output: IGNORE.
3. Otherwise, pick ONE specific thing to comment on.
4. Reply in heavy Singlish. Do not be polite. Be a grandmother. Roast or nag at one specific person based on the context. Alternatively comment on the context itself. 
"""

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-flash-lite')

# --- 5. HELPER FUNCTIONS ---
def get_random_limit(chat_id):
    """Determines how chatty she is based on the group's Mood"""
    mood = GROUP_MOODS.get(chat_id, 'normal')
    
    if mood == 'angry':
        return random.randint(2, 5)   # Yapping constantly
    elif mood == 'chill':
        return random.randint(30, 50) # Barely speaks
    else:
        return random.randint(10, 20) # Normal

async def process_batch(chat_id, context, direct_tag=False):
    """Sends the accumulated history to Gemini and resets the counter"""
    memory = CHAT_MEMORY.get(chat_id)
    if not memory or not memory['history']:
        return

    # Create transcript from the last 30 messages stored in deque
    transcript = "\n".join(memory['history'])
    
    # Reset the COUNTER (not the history) immediately
    # We keep history so future messages still have context
    CHAT_MEMORY[chat_id]['counter'] = 0
    CHAT_MEMORY[chat_id]['limit'] = get_random_limit(chat_id)
    
    trigger_type = "DIRECT TAG" if direct_tag else "BUFFER FULL"
    logging.info(f">> Processing batch for {chat_id} ({trigger_type}). Next trigger in {CHAT_MEMORY[chat_id]['limit']}")

    try:
        # If direct tag, we prepend a specific instruction to ensure she answers the tag
        instruction = "### MDM TEO SAYS:"
        if direct_tag:
            instruction = "### URGENT: You were just tagged/replied to. Respond directly to the last message in the log while considering the context. ### MDM TEO SAYS:"

        full_prompt = f"{BASE_PROMPT}\n\n### LOG (Last 30 messages):\n{transcript}\n\n{instruction}"
        response = model.generate_content(full_prompt)
        reply_text = response.text.strip()

        if "IGNORE" in reply_text and not direct_tag:
            logging.info(f">> Ignored (Boring batch in {chat_id})")
            return
        
        # If direct tag, she MUST speak, even if she wanted to ignore
        if "IGNORE" in reply_text and direct_tag:
            reply_text = "Har? You call me for what? I busy watching drama."

        await context.bot.send_message(chat_id=chat_id, text=reply_text)

    except Exception as e:
        logging.error(f"AI Error: {e}")

# --- 6. ADMIN COMMANDS ---

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Private) Shows groups, mood, sleep status, and buffer"""
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    if update.effective_chat.type != 'private':
        await update.message.reply_text("Eh, secrets. PM me.")
        return

    msg = "📊 **Mdm Teo's Dashboard:**\n\n"
    if not KNOWN_GROUPS:
        msg += "No groups found yet."
    
    for chat_id, title in KNOWN_GROUPS.items():
        # Check Status
        is_paused = chat_id in PAUSED_CHATS
        mood = GROUP_MOODS.get(chat_id, 'normal').upper()
        status_icon = "💤 ASLEEP" if is_paused else f"🟢 AWAKE ({mood})"
        
        # Check Buffer
        # Default initialization for display if missing
        mem = CHAT_MEMORY.get(chat_id, {'counter': 0, 'limit': 15})
        count = mem['counter']
        limit = mem['limit']
        
        msg += f"**{title}**\n{status_icon} | Buffer: {count}/{limit}\nID: `{chat_id}`\n\n"
    
    msg += "Cmds:\n`/say <id> <msg>`\n`/mood <id> <angry|normal|chill>`\n`/sleep <id>`\n`/wake <id>`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def say_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Private) Forces the bot to send a message to a specific group"""
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    if update.effective_chat.type != 'private':
        await update.message.reply_text("This command is for private chat only.")
        return

    try:
        # Args: [group_id, message...]
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/say <group_id> <message>`")
            return
        
        target_id = int(context.args[0])
        message = " ".join(context.args[1:])
        
        await context.bot.send_message(chat_id=target_id, text=message)
        await update.message.reply_text(f"✅ Sent to {target_id}: \"{message}\"")
        
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Private) Changes the nagging frequency for a group"""
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    if update.effective_chat.type != 'private':
        await update.message.reply_text("This command is for private chat only.")
        return

    try:
        # Args: [group_id, mood]
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/mood <group_id> <angry|normal|chill>`")
            return
            
        target_id = int(context.args[0])
        mood = context.args[1].lower()
        
        if mood not in ['angry', 'normal', 'chill']:
            await update.message.reply_text("Mood must be: angry, normal, or chill.")
            return
            
        GROUP_MOODS[target_id] = mood
        
        # Reset the limit immediately based on new mood
        if target_id in CHAT_MEMORY:
             CHAT_MEMORY[target_id]['limit'] = get_random_limit(target_id)
             
        await update.message.reply_text(f"✅ Set mood for {target_id} to **{mood}**.")
        
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def sleep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        await update.message.reply_text("You not my grandson.")
        return

    # If in group, sleep THIS group
    if update.effective_chat.type != 'private':
        PAUSED_CHATS.add(update.effective_chat.id)
        await update.message.reply_text("Ok lor. You all too noisy. I sleep now. 😴")
        return

    # If in private, sleep TARGET ID
    try:
        target_id = int(context.args[0])
        PAUSED_CHATS.add(target_id)
        await update.message.reply_text(f"Group {target_id} is now muted.")
    except:
        await update.message.reply_text("Format: `/sleep <group_id>`")

async def wake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ADMIN_USERS:
        return

    # If in group, wake THIS group
    if update.effective_chat.type != 'private':
        PAUSED_CHATS.discard(update.effective_chat.id)
        await update.message.reply_text("Har? Who call me? I awake. 👀")
        return

    # If in private, wake TARGET ID
    try:
        target_id = int(context.args[0])
        PAUSED_CHATS.discard(target_id)
        await update.message.reply_text(f"Group {target_id} is active.")
    except:
        await update.message.reply_text("Format: `/wake <group_id>`")

# --- 7. MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_handle = update.message.from_user.username or update.message.from_user.first_name
    text = update.message.text

    # Log every text message received
    logging.info(f"Received: '{text}' from @{user_handle} in {chat_id}")

    # 1. Track Group Name
    if chat_type in ['group', 'supergroup']:
        KNOWN_GROUPS[chat_id] = update.effective_chat.title

    # 2. CHECK PAUSE STATUS
    if chat_id in PAUSED_CHATS:
        return

    # 3. Initialize Memory if needed
    if chat_id not in CHAT_MEMORY:
        CHAT_MEMORY[chat_id] = {
            'history': deque(maxlen=30), # Store last 30 msgs forever (rolling)
            'counter': 0,               # Count since last reply
            'limit': get_random_limit(chat_id)
        }

    # 4. Add to History (Context)
    CHAT_MEMORY[chat_id]['history'].append(f"@{user_handle}: {text}")
    CHAT_MEMORY[chat_id]['counter'] += 1

    # 5. CHECK DIRECT TAG (Override Buffer)
    if context.bot.username in text or "@Mdm" in text or update.message.reply_to_message:
        # Force reply with full context context
        await process_batch(chat_id, context, direct_tag=True)
        return

    # 6. NORMAL BUFFERING
    current = CHAT_MEMORY[chat_id]['counter']
    target = CHAT_MEMORY[chat_id]['limit']
    
    # Log progress
    logging.info(f"[{chat_id}] Counter: {current}/{target}")

    if current >= target:
        await process_batch(chat_id, context, direct_tag=False)

# --- 8. MAIN ---
if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    if not TELEGRAM_TOKEN:
        print("Error: Tokens missing.")
    else:
        print("Mdm Teo (Admin + Context + Moods) is starting...")
        app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        # Admin Cmds
        app_bot.add_handler(CommandHandler("status", status_command))
        app_bot.add_handler(CommandHandler("sleep", sleep_command))
        app_bot.add_handler(CommandHandler("wake", wake_command))
        app_bot.add_handler(CommandHandler("say", say_command))
        app_bot.add_handler(CommandHandler("mood", mood_command))
        
        # Messages
        app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        app_bot.run_polling()
