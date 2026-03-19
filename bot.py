from flask import Flask
import threading
import os
import psycopg
from psycopg.rows import dict_row

web = Flask(__name__)

@web.route("/")
def home():
    return "Bot is alive", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on port {port}")
    web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# =========================
# IMPORTS
# =========================

import asyncio
import random
import time
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

user_locks = {}
flip_busy = set()
flip_cooldown = {}

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6479017313

START_COINS = 0
DAILY_REWARD = 5000

KILL_REWARD = 500
REVIVE_COST = 500

GIVE_TAX = 0.1
ROB_PERCENT = 0.3

ROB_COOLDOWN = 300
KILL_COOLDOWN = 300

MIN_BET = 100
MAX_BET = 1000000

# =========================
# DATABASE
# =========================

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    global tax_pool

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid TEXT PRIMARY KEY,
                    name TEXT DEFAULT 'User',
                    coins BIGINT DEFAULT 0,
                    bank BIGINT DEFAULT 0,
                    kills BIGINT DEFAULT 0,
                    last_daily DOUBLE PRECISION DEFAULT 0,
                    dead_until DOUBLE PRECISION DEFAULT 0,
                    protected_until DOUBLE PRECISION DEFAULT 0,
                    last_rob DOUBLE PRECISION DEFAULT 0,
                    last_kill DOUBLE PRECISION DEFAULT 0,
                    last_bank_tax DOUBLE PRECISION DEFAULT 0,
                    last_flip DOUBLE PRECISION DEFAULT 0,
                    is_banned BOOLEAN DEFAULT FALSE
                )
            """)

            # OLD USERS KE LIYE
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS last_bank_tax DOUBLE PRECISION DEFAULT 0
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS last_flip DOUBLE PRECISION DEFAULT 0
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            cur.execute("""
                INSERT INTO bot_meta (key, value)
                VALUES ('tax_pool', '0')
                ON CONFLICT (key) DO NOTHING
            """)

        conn.commit()

    tax_pool = get_tax_pool()

def get_tax_pool():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM bot_meta WHERE key = 'tax_pool'")
            row = cur.fetchone()
            return int(row["value"]) if row else 0


def set_tax_pool(value):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_meta (key, value)
                VALUES ('tax_pool', %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
            """, (str(int(value)),))
        conn.commit()


def save():
    global tax_pool
    set_tax_pool(tax_pool)

def get_user(uid):
    uid = str(uid)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE uid = %s", (uid,))
            user = cur.fetchone()

            if not user:
                cur.execute("""
                    INSERT INTO users (
                        uid, name, coins, bank, kills,
                        last_daily, dead_until, protected_until,
                        last_rob, last_kill, last_bank_tax, last_flip
                    )
                    VALUES (%s, 'User', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                    RETURNING *
                """, (uid,))
                user = cur.fetchone()
                conn.commit()

    user["coins"] = int(user.get("coins", 0))
    user["bank"] = int(user.get("bank", 0))
    user["kills"] = int(user.get("kills", 0))
    user["last_daily"] = float(user.get("last_daily", 0))
    user["dead_until"] = float(user.get("dead_until", 0))
    user["protected_until"] = float(user.get("protected_until", 0))
    user["last_rob"] = float(user.get("last_rob", 0))
    user["last_kill"] = float(user.get("last_kill", 0))
    user["last_bank_tax"] = float(user.get("last_bank_tax", 0))
    user["last_flip"] = float(user.get("last_flip", 0))  # 🔥 NEW
    user["is_banned"] = bool(user.get("is_banned", False))
    user["name"] = str(user.get("name", "User"))

    return user

def save_user(uid, user):
    uid = str(uid)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET name=%s,
                    coins=%s,
                    bank=%s,
                    kills=%s,
                    last_daily=%s,
                    dead_until=%s,
                    protected_until=%s,
                    last_rob=%s,
                    last_kill=%s,
                    last_bank_tax=%s,
                    last_flip=%s,
                    is_banned=%s
                WHERE uid=%s
            """, (
                user.get("name", "User"),
                int(user.get("coins", 0)),
                int(user.get("bank", 0)),
                int(user.get("kills", 0)),
                float(user.get("last_daily", 0)),
                float(user.get("dead_until", 0)),
                float(user.get("protected_until", 0)),
                float(user.get("last_rob", 0)),
                float(user.get("last_kill", 0)),
                float(user.get("last_bank_tax", 0)),
                float(user.get("last_flip", 0)),
                bool(user.get("is_banned", False)),
                uid
            ))
        conn.commit()

def get_user_rank(uid):
    uid = str(uid)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rank
                FROM (
                    SELECT uid,
                           RANK() OVER (ORDER BY (coins + bank) DESC) AS rank
                    FROM users
                ) ranked
                WHERE uid = %s
            """, (uid,))
            row = cur.fetchone()
            return int(row["rank"]) if row else 0

def update_name_from_update(update: Update):
    uid = str(update.effective_user.id)
    user = get_user(uid)
    if update.effective_user.first_name:
        user["name"] = update.effective_user.first_name
        save_user(uid, user)


def is_dead(user):
    return time.time() < float(user.get("dead_until", 0))


def is_protected(user):
    return time.time() < float(user.get("protected_until", 0))


def fmt(x):
    return f"{int(x):,}"


def check_bet(u, bet):
    try:
        bet = int(bet)
    except:
        return "❌ Invalid bet amount"

    coins = int(u.get("coins", 0))

    if bet < MIN_BET:
        return f"❌ Minimum bet is ${fmt(MIN_BET)}"

    if bet > MAX_BET:
        return f"❌ Maximum bet is ${fmt(MAX_BET)}"

    if coins < bet:
        return "❌ Not enough coins"

    return None


init_db()

# =========================
# ADMIN CHECK SYSTEM
# =========================

MIN_GROUP_MEMBERS = 25

def admin_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        chat = update.effective_chat

        user = get_user(user_id)
        if user.get("is_banned", False):
            return await update.message.reply_text("❌ You are banned from using this bot")

        # DM me sirf owner allow
        if chat.type == "private":
            if user_id != OWNER_ID:
                return await update.message.reply_text("❌ Bot DM me sirf owner ke liye hai")
            return await func(update, context)

        # Sirf groups me checks
        if chat.type in ["group", "supergroup"]:
            try:
                member_count = await context.bot.get_chat_member_count(chat.id)
            except:
                member_count = 0

            if member_count < MIN_GROUP_MEMBERS:
                return await update.message.reply_text(
                    f"❌ Is bot ko use karne ke liye group me kam se kam {MIN_GROUP_MEMBERS} members hone chahiye.\n"
                    f"👥 Current members: {member_count}",
                    reply_to_message_id=update.message.id
                )

            try:
                bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            except:
                return await update.message.reply_text(
                    "⚠️ Bot admin status check failed",
                    reply_to_message_id=update.message.id
                )

            if bot_member.status not in ["administrator", "creator"]:
                return await update.message.reply_text(
                    "⚠️ Pehle mujhe group me admin do.\nTabhi main yahan work karunga.",
                    reply_to_message_id=update.message.id
                )

        return await func(update, context)

    return wrapper

# =========================
# START
# =========================

@admin_required
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    text = """
👑 Wᴇʟᴄᴏᴍᴇ ᴛᴏ Cᴀsʜɪɴᴏ Gᴏᴅ Eᴄᴏɴᴏᴍʏ ❤️‍🔥!

Yaha coins kamao, loot maro, kill karo aur games jeeto!

🪙 Cᴏɪɴ Cᴏᴍᴍᴀɴᴅs:
• /daily — Roz free coins
• /bal — Apna coins balance + rank
• /give <user_id> <amount> — Coins gift karo (10% tax)

💵 Cᴀsʜ Cᴏᴍᴍᴀɴᴅs:
• /cashbal — Wallet aur bank balance dekho
• /deposit <amount> — Coins bank me daalo
• /withdraw <amount> — Bank se coins nikalo

👊 Aᴄᴛɪᴏɴ Cᴏᴍᴍᴀɴᴅs:
• /kill (reply) — Target ko kill karo
• /rob (reply) — Kisi ke coins loot lo
• /protect — 24hr protection lo
• /revive (reply) — Dead user revive karo

✨ Gᴀᴍᴇs:
• /flip <amount> <h/t> — 🏀 Basketball flip
• /dice <amount> <1-6> — 🎲 Dice roll
• /roulette <amount> <0-36> — 🎰 Slot roulette
• /color <red/green/violet> <amount> — 🎯 Color prediction

🌟 Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ:
• /toprich — Top 10 richest players
• /taxpool — Total tax coins

😡 Max bet per game: $1,000,000
"""

    await update.message.reply_text(
        text,
        reply_to_message_id=update.message.id
    )

# =========================
# HELP
# =========================

@admin_required
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    text = """
👑 Cᴀsʜɪɴᴏ Gᴏᴅ ❤️‍🔥

🪙 Cᴏɪɴs
/daily /bal /give /taxpool

🏦 Bᴀɴᴋ
/deposit /withdraw /cashbal

🎮 Gᴀᴍᴇs
/flip <amount> <h/t>
/dice <amount> <1-6>
/roulette <amount> <0-36>
/color <red/green/violet> <amount>

⚔️ Aᴄᴛɪᴏɴ
/kill /rob /protect /revive

🏆 Rᴀɴᴋs
/top /toprich /topkill

😡 Max bet: $5,000,000 | Min bet: $100
"""

    await update.message.reply_text(text)


# =========================
# MENU
# =========================

@admin_required
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    kb = [

        [InlineKeyboardButton("🪙 Balance", callback_data="bal"),
         InlineKeyboardButton("🎁 Daily", callback_data="daily")],

        [InlineKeyboardButton("🎲 Dice", callback_data="dice"),
         InlineKeyboardButton("🎡 Roulette", callback_data="roulette")],

        [InlineKeyboardButton("🪙 Flip", callback_data="flip"),
         InlineKeyboardButton("🎨 Color", callback_data="color")],

        [InlineKeyboardButton("🏆 Leaderboard", callback_data="toprich")]

    ]

    await update.message.reply_text(
        "👑 GOD ECONOMY MENU",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    if q.data == "bal":
        u = get_user(user_id)

        protect_left = int(u["protected_until"] - time.time())

        if protect_left > 0:
            hours = protect_left // 3600
            minutes = (protect_left % 3600) // 60
            protect_text = f"🛡 Protection: {hours}h {minutes}m left"
        else:
            protect_text = "🛡 Protection: Not active"

        text = (
            f"👑 {q.from_user.first_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Coins: ${fmt(u['coins'])}\n"
            f"🏦 Bank: ${fmt(u['bank'])}\n"
            f"💀 Kills: {u['kills']}\n"
            f"{protect_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        await q.message.reply_text(text)

    else:
        await q.message.reply_text(f"Use command: /{q.data}")


# =========================
# ECONOMY
# =========================

@admin_required
async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    # 👇 check reply
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    else:
        target_user = update.effective_user

    uid = str(target_user.id)
    u = get_user(uid)

    coins = int(u.get("coins", 0))
    bank = int(u.get("bank", 0))
    kills = int(u.get("kills", 0))
    rank = get_user_rank(uid)

    name = f"<a href='tg://user?id={uid}'>{html.escape(target_user.first_name)}</a>"

    protect_left = int(float(u.get("protected_until", 0)) - time.time())
    protect_text = (
        f"{protect_left // 3600}h {(protect_left % 3600) // 60}m left"
        if protect_left > 0 else "Not active"
    )

    text = (
        f"👑 {name}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Coins: ${fmt(coins)}\n"
        f"🏦 Bank: ${fmt(bank)}\n"
        f"💀 Kills: {kills}\n"
        f"🏆 Rank: #{rank}\n"
        f"🛡 Protection: {protect_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


@admin_required
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)

    now = time.time()

    if now - float(u.get("last_daily", 0)) < 86400:
        remaining = 86400 - (now - float(u.get("last_daily", 0)))
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)

        return await update.message.reply_text(
            f"❌ Daily already claimed\n⏳ Come back in {hours}h {minutes}m",
            reply_to_message_id=update.message.id
        )

    u["coins"] = int(u.get("coins", 0)) + DAILY_REWARD
    u["last_daily"] = now

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        f"🎁 Daily Claimed! +${fmt(DAILY_REWARD)}",
        reply_to_message_id=update.message.id
    )

@admin_required
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tax_pool
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi user ke message par reply karke /give <amount> use karo",
            reply_to_message_id=update.message.id
        )

    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /give <amount>",
            reply_to_message_id=update.message.id
        )

    sender_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    if target_user.is_bot:
        return await update.message.reply_text("❌ Bot ko coins nahi de sakte")

    if target_user.id == sender_user.id:
        return await update.message.reply_text("❌ Khud ko coins nahi de sakte")

    amount = int(context.args[0])

    sender = get_user(sender_user.id)
    target = get_user(target_user.id)

    if sender["coins"] < amount:
        return await update.message.reply_text("❌ Not enough coins")

    tax = int(amount * GIVE_TAX)
    send_amount = amount - tax

    sender["coins"] -= amount
    target["coins"] += send_amount
    tax_pool += tax

    save_user(sender_user.id, sender)
    save_user(target_user.id, target)
    save()

    sender_name = html.escape(sender_user.first_name)
    target_name = html.escape(target_user.first_name)

    await update.message.reply_text(
        f"💸 Transfer Successful!\n\n"
        f"👤 From: <a href='tg://user?id={sender_user.id}'>{sender_name}</a>\n"
        f"👤 To: <a href='tg://user?id={target_user.id}'>{target_name}</a>\n"
        f"💰 Sent: ${fmt(send_amount)}\n"
        f"🏦 Tax: ${fmt(tax)}",
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )

# =========================
# BANK SETTINGS
# =========================

MAX_BANK = 1_000_000_000
BANK_TAX_RATE = 0.03
BANK_TAX_TIME = 86400  # 1 day

def apply_bank_tax(uid, user):
    now = time.time()
    next_tax_time = float(user.get("last_bank_tax", 0))

    # pehli baar set karo (agar nahi hai)
    if next_tax_time == 0:
        user["last_bank_tax"] = now + BANK_TAX_TIME
        save_user(uid, user)
        return

    # jab time aa jaye
    if now >= next_tax_time:
        tax = int(int(user.get("bank", 0)) * BANK_TAX_RATE)

        if tax > 0:
            user["bank"] = int(user.get("bank", 0)) - tax

        # next cycle set karo
        user["last_bank_tax"] = now + BANK_TAX_TIME
        save_user(uid, user)

# =========================
# BANK
# =========================

@admin_required
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /deposit <amount>",
            reply_to_message_id=update.message.id
        )

    uid = update.effective_user.id
    u = get_user(uid)

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount",
            reply_to_message_id=update.message.id
        )

    if amount <= 0:
        return await update.message.reply_text(
            "❌ Amount must be greater than 0",
            reply_to_message_id=update.message.id
        )

    if int(u.get("coins", 0)) < amount:
        return await update.message.reply_text(
            "❌ Not enough coins",
            reply_to_message_id=update.message.id
        )

    if int(u.get("bank", 0)) + amount > MAX_BANK:
        return await update.message.reply_text(
            f"❌ Bank limit reached! Max: ${fmt(MAX_BANK)}",
            reply_to_message_id=update.message.id
        )

    u["coins"] = int(u.get("coins", 0)) - amount
    u["bank"] = int(u.get("bank", 0)) + amount

    # tax timer deposit ke time se start hoga
    u["last_bank_tax"] = time.time() + BANK_TAX_TIME

    save_user(uid, u)
    save()

    await update.message.reply_text(
        f"🏦 Deposited ${fmt(amount)}",
        reply_to_message_id=update.message.id
    )

@admin_required
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /withdraw <amount>",
            reply_to_message_id=update.message.id
        )

    uid = update.effective_user.id
    u = get_user(uid)

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount",
            reply_to_message_id=update.message.id
        )

    if amount <= 0:
        return await update.message.reply_text(
            "❌ Amount must be greater than 0",
            reply_to_message_id=update.message.id
        )

    if int(u.get("bank", 0)) < amount:
        return await update.message.reply_text(
            "❌ Not enough bank balance",
            reply_to_message_id=update.message.id
        )

    u["bank"] = int(u.get("bank", 0)) - amount
    u["coins"] = int(u.get("coins", 0)) + amount

    save_user(uid, u)
    save()

    await update.message.reply_text(
        f"💰 Withdrawn ${fmt(amount)}",
        reply_to_message_id=update.message.id
    )


@admin_required
async def cashbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    uid = update.effective_user.id
    u = get_user(uid)

    apply_bank_tax(uid, u)

    # tax lagne ke baad fresh user dubara lo
    u = get_user(uid)

    coins = int(u.get("coins", 0))
    bank = int(u.get("bank", 0))

    next_tax_time = float(u.get("last_bank_tax", 0))
    remaining = int(next_tax_time - time.time())

    if remaining < 0:
        remaining = 0

    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    tax_text = f"⏳ Next tax in {hours}h {minutes}m"

    save_user(uid, u)

    await update.message.reply_text(
        f"💰 Wallet: ${fmt(coins)}\n"
        f"🏦 Bank: ${fmt(bank)}\n\n"
        f"📉 3% tax every 24h\n"
        f"{tax_text}",
        reply_to_message_id=update.message.id
    )


# =========================
# ACTIONS
# =========================

@admin_required
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi user ke message par reply karke /kill use karo.",
            reply_to_message_id=update.message.id
        )

    attacker_user = update.effective_user
    victim_user = update.message.reply_to_message.from_user

    if victim_user.is_bot:
        return await update.message.reply_text(
            "❌ Bot ko kill nahi kar sakte.",
            reply_to_message_id=update.message.id
        )

    if attacker_user.id == victim_user.id:
        return await update.message.reply_text(
            "❌ Khud ko kill nahi kar sakte.",
            reply_to_message_id=update.message.id
        )

    attacker = get_user(attacker_user.id)
    victim = get_user(victim_user.id)

    kill_left = int(KILL_COOLDOWN - (time.time() - float(attacker.get("last_kill", 0))))

    if kill_left > 0:
        return await update.message.reply_text(
            f"⏳ Kill cooldown active\nTry again in {kill_left}s",
            reply_to_message_id=update.message.id
        )

    protect_left = int(float(victim.get("protected_until", 0)) - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 <a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> protected hai\n"
            f"❌ Kill block ho gaya\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    victim["dead_until"] = time.time() + 43200
    attacker["coins"] = int(attacker.get("coins", 0)) + KILL_REWARD
    attacker["kills"] = int(attacker.get("kills", 0)) + 1
    attacker["last_kill"] = time.time()

    save_user(attacker_user.id, attacker)
    save_user(victim_user.id, victim)
    save()

    await update.message.reply_text(
        f"💀 KILL SUCCESS\n\n"
        f"⚔️ <a href='tg://user?id={attacker_user.id}'>{html.escape(attacker_user.first_name)}</a> ne "
        f"<a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> ko kill kar diya\n"
        f"💰 Reward: ${fmt(KILL_REWARD)}",
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )
        

@admin_required
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi user ke message par reply karke /rob use karo.",
            reply_to_message_id=update.message.id
        )

    robber_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    robber = get_user(robber_user.id)
    target = get_user(target_user.id)

    rob_left = int(ROB_COOLDOWN - (time.time() - float(robber.get("last_rob", 0))))

    if rob_left > 0:
        return await update.message.reply_text(
            f"⏳ Rob cooldown active\nTry again in {rob_left}s",
            reply_to_message_id=update.message.id
        )

    protect_left = int(float(target.get("protected_until", 0)) - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 {target_user.first_name} protected hai\n"
            f"❌ Rob block ho gaya\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me",
            reply_to_message_id=update.message.id
        )

    steal = int(int(target.get("coins", 0)) * ROB_PERCENT)

    if steal <= 0:
        return await update.message.reply_text(
            "❌ Target ke paas lootne layak coins nahi hain.",
            reply_to_message_id=update.message.id
        )

    target["coins"] = int(target.get("coins", 0)) - steal
    robber["coins"] = int(robber.get("coins", 0)) + steal
    robber["last_rob"] = time.time()

    save_user(robber_user.id, robber)
    save_user(target_user.id, target)
    save()

    await update.message.reply_text(
        f"💰 ROB SUCCESS\n\n"
        f"🕵️ {robber_user.first_name} ne {target_user.first_name} se ${fmt(steal)} loot liye",
        reply_to_message_id=update.message.id
    )

@admin_required
async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)

    now = time.time()
    protect_left = int(float(u.get("protected_until", 0)) - now)

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 Tum already protected ho\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me",
            reply_to_message_id=update.message.id
        )

    u["protected_until"] = now + 86400

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        "🛡 Protection activated for 24 hours",
        reply_to_message_id=update.message.id
    )

@admin_required
async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi dead user ke message par reply karke /revive use karo.",
            reply_to_message_id=update.message.id
        )

    target_user = update.message.reply_to_message.from_user
    user = get_user(target_user.id)

    if not is_dead(user):
        return await update.message.reply_text(
            "❌ Ye user dead nahi hai",
            reply_to_message_id=update.message.id
        )

    if int(user.get("coins", 0)) < REVIVE_COST:
        return await update.message.reply_text(
            "❌ Revive ke liye coins nahi hain",
            reply_to_message_id=update.message.id
        )

    user["coins"] = int(user.get("coins", 0)) - REVIVE_COST
    user["dead_until"] = 0

    save_user(target_user.id, user)
    save()

    await update.message.reply_text(
        f"❤️ {target_user.first_name} revive ho gaya",
        reply_to_message_id=update.message.id
    )
     
# =========================
# GAMES
# =========================

def win_message(user, emoji, result, pick, amount):
    return f"""
✨ {emoji} SAHI! YOU WON!
━━━━━━━━━━━━━━━━━━━━━
{emoji} Result: {result}
✅ Tera pick: {pick}

🪙 Jeet: +${fmt(amount)}

👑 Lucky ho <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 🔥
"""


def lose_message(user, emoji, result, pick, amount):
    return f"""
💀 {emoji} GALAT! HAARA!
━━━━━━━━━━━━━━━━━━━━━
{emoji} Result: {result}
❌ Tera pick: {pick}

😔 Nuksan: -${fmt(amount)}

👑 <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 💸
"""

@admin_required
async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /flip <amount> <h/t>",
            reply_to_message_id=update.message.id
        )

    uid = update.effective_user.id

    # Agar abhi flip chal raha hai to ignore
    if uid in flip_busy:
        return

    # 3 sec cooldown after previous completed flip
    now = time.time()
    last = flip_cooldown.get(uid, 0)
    if now - last < 3:
        return

    flip_busy.add(uid)

    try:
        u = get_user(uid)

        try:
            bet = int(context.args[0])
        except:
            return await update.message.reply_text(
                "❌ Invalid amount",
                reply_to_message_id=update.message.id
            )

        choice = context.args[1].lower()
        if choice not in ["h", "t"]:
            return await update.message.reply_text(
                "❌ Choose h or t",
                reply_to_message_id=update.message.id
            )

        user_name = html.escape(update.effective_user.first_name)
        choice_text = "Heads" if choice == "h" else "Tails"

        print(f"FLIP LOG | name={user_name} | bet=${fmt(bet)} | pick={choice_text}")

        error = check_bet(u, bet)
        if error:
            return await update.message.reply_text(
                error,
                reply_to_message_id=update.message.id
            )

        shot = await context.bot.send_dice(
            chat_id=update.effective_chat.id,
            emoji="🏀",
            reply_to_message_id=update.message.id
        )

        value = shot.dice.value
        await asyncio.sleep(1)

        if value >= 4:
            result_key = "h"
            result_text = "Heads"
        else:
            result_key = "t"
            result_text = "Tails"

        if result_key == choice:
            win = bet * 2
            u["coins"] = int(u.get("coins", 0)) + win
            text = win_message(update.effective_user, "🪙", result_text, choice_text, win)

            print(
                f"FLIP RESULT | name={user_name} | bet=${fmt(bet)} | pick={choice_text} | result={result_text} | status=WIN | payout=${fmt(win)}"
            )
        else:
            u["coins"] = int(u.get("coins", 0)) - bet
            text = lose_message(update.effective_user, "🪙", result_text, choice_text, bet)

            print(
                f"FLIP RESULT | name={user_name} | bet=${fmt(bet)} | pick={choice_text} | result={result_text} | status=LOSE | loss=${fmt(bet)}"
            )

        save_user(uid, u)
        save()

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    finally:
        # Cooldown END pe set hoga, start pe nahi
        flip_cooldown[uid] = time.time()
        flip_busy.discard(uid)

@admin_required
async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /dice <amount> <1-6>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)

    try:
        bet = int(context.args[0])
        guess = int(context.args[1])
    except:
        return await update.message.reply_text(
            "❌ Invalid input",
            reply_to_message_id=update.message.id
        )

    if guess < 1 or guess > 6:
        return await update.message.reply_text(
            "❌ Choose number 1 to 6",
            reply_to_message_id=update.message.id
        )

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(
            error,
            reply_to_message_id=update.message.id
        )

    dice_msg = await context.bot.send_dice(
        chat_id=update.effective_chat.id,
        emoji="🎲",
        reply_to_message_id=update.message.id
    )

    roll = dice_msg.dice.value
    await asyncio.sleep(1)

    if roll == guess:
        win = bet * 5
        u["coins"] += win
        text = win_message(update.effective_user, "🎲", str(roll), str(guess), win)
    else:
        u["coins"] -= bet
        text = lose_message(update.effective_user, "🎲", str(roll), str(guess), bet)

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


@admin_required
async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /slots <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)

    try:
        bet = int(context.args[0])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount",
            reply_to_message_id=update.message.id
        )

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(
            error,
            reply_to_message_id=update.message.id
        )

    slot_msg = await context.bot.send_dice(
        chat_id=update.effective_chat.id,
        emoji="🎰",
        reply_to_message_id=update.message.id
    )

    value = slot_msg.dice.value
    await asyncio.sleep(1)

    if value == 64:
        win = bet * 10
        u["coins"] += win
        result = "💎💎💎 JACKPOT"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    elif value in [1, 22, 43]:
        win = bet * 3
        u["coins"] += win
        result = "🔥 Double Match"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    elif value in [16, 32]:
        win = bet * 2
        u["coins"] += win
        result = "✨ Small Win"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    else:
        u["coins"] -= bet
        result = "❌ No Match"
        text = lose_message(update.effective_user, "🎰", result, "🎰", bet)

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


@admin_required
async def color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /color <red/green> <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)

    choice = context.args[0].lower()

    try:
        bet = int(context.args[1])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount",
            reply_to_message_id=update.message.id
        )

    if choice not in ["red", "green"]:
        return await update.message.reply_text(
            "❌ Choose red or green",
            reply_to_message_id=update.message.id
        )

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(
            error,
            reply_to_message_id=update.message.id
        )

    dart = await context.bot.send_dice(
        chat_id=update.effective_chat.id,
        emoji="🎯",
        reply_to_message_id=update.message.id
    )

    value = dart.dice.value
    await asyncio.sleep(1)

    if value in [1, 2, 3]:
        result = "red"
    else:
        result = "green"

    if result == choice:
        win = bet * 2
        u["coins"] += win
        text = win_message(update.effective_user, "🎨", result.upper(), choice.upper(), win)
    else:
        u["coins"] -= bet
        text = lose_message(update.effective_user, "🎨", result.upper(), choice.upper(), bet)

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
        )        

# =========================
# LEADERBOARD
# =========================

@admin_required
async def toprich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uid, name, coins
                FROM users
                ORDER BY coins DESC
                LIMIT 10
            """)
            rows = cur.fetchall()

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = "🏆 GOD WEALTH TOP 10\n━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, row in enumerate(rows):
        uid = row["uid"]
        name = html.escape(str(row.get("name", "User")))
        coins = int(row.get("coins", 0))
        text += f"{medals[i]} <a href='tg://user?id={uid}'>{name}</a> — ${fmt(coins)}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )

@admin_required
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toprich(update, context)


# =========================
# OWNER PREMIUM PANEL
# =========================

def is_owner(update: Update):
    return update.effective_user.id == OWNER_ID


def admin_search_users(query: str, limit: int = 10):
    query = query.strip()

    with get_conn() as conn:
        with conn.cursor() as cur:
            if query.isdigit():
                cur.execute("""
                    SELECT uid, name, coins, bank
                    FROM users
                    WHERE uid = %s
                    LIMIT %s
                """, (query, limit))
                rows = cur.fetchall()
                if rows:
                    return rows

            cur.execute("""
                SELECT uid, name, coins, bank
                FROM users
                WHERE name ILIKE %s
                ORDER BY coins DESC
                LIMIT %s
            """, (f"%{query}%", limit))
            return cur.fetchall()

@admin_required
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    keyboard = [
        [
            InlineKeyboardButton("Set Coins", callback_data="admin:setcoins"),
            InlineKeyboardButton("Add Coins", callback_data="admin:addcoins"),
        ],
        [
            InlineKeyboardButton("Set Bank", callback_data="admin:setbank"),
            InlineKeyboardButton("Add Bank", callback_data="admin:addbank"),
        ],
        [
            InlineKeyboardButton("Reset User", callback_data="admin:resetuser"),
            InlineKeyboardButton("User Info", callback_data="admin:userinfo"),
        ],
        [
            InlineKeyboardButton("Ban User", callback_data="admin:banuser"),
            InlineKeyboardButton("Unban User", callback_data="admin:unbanuser"),
        ],
        [
            InlineKeyboardButton("Reset All Coins", callback_data="admin:resetallcoins"),
        ],
        [
            InlineKeyboardButton("Close", callback_data="admin:close"),
        ]
    ]

    await update.message.reply_text(
        "👑 OWNER PANEL\n\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_ID:
        return await query.message.reply_text("❌ Owner only")

    data = query.data

    if data == "admin:close":
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_selected_uid", None)
        context.user_data.pop("admin_step", None)
        return await query.edit_message_text("❌ Panel closed")

    if data == "admin:resetallcoins":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET coins = 0")
            conn.commit()

        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_selected_uid", None)
        context.user_data.pop("admin_step", None)

        return await query.edit_message_text("✅ Sabke coins reset ho gaye")

    if data.startswith("admin:setcoins"):
        context.user_data["admin_action"] = "setcoins"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Set Coins")

    if data.startswith("admin:addcoins"):
        context.user_data["admin_action"] = "addcoins"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Add Coins")

    if data.startswith("admin:setbank"):
        context.user_data["admin_action"] = "setbank"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Set Bank")

    if data.startswith("admin:addbank"):
        context.user_data["admin_action"] = "addbank"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Add Bank")

    if data.startswith("admin:resetuser"):
        context.user_data["admin_action"] = "resetuser"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Reset User")

    if data.startswith("admin:userinfo"):
        context.user_data["admin_action"] = "userinfo"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for User Info")

    if data.startswith("admin:banuser"):
        context.user_data["admin_action"] = "banuser"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Ban User")

    if data.startswith("admin:unbanuser"):
        context.user_data["admin_action"] = "unbanuser"
        context.user_data["admin_step"] = "search_user"
        return await query.edit_message_text("Send user name or user id to search for Unban User")

    if data.startswith("admin:pick:"):
        uid = data.split(":", 2)[2]
        context.user_data["admin_selected_uid"] = uid
        action = context.user_data.get("admin_action")

        user = get_user(uid)
        name = html.escape(user.get("name", "User"))

        if action == "userinfo":
            protect_left = int(float(user.get("protected_until", 0)) - time.time())
            dead_left = int(float(user.get("dead_until", 0)) - time.time())

            protect_text = f"{protect_left//3600}h {(protect_left%3600)//60}m left" if protect_left > 0 else "Not active"
            dead_text = f"{dead_left//3600}h {(dead_left%3600)//60}m left" if dead_left > 0 else "Not dead"
            ban_text = "Yes" if user.get("is_banned", False) else "No"

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await query.edit_message_text(
                f"👤 {name}\n"
                f"🆔 {uid}\n"
                f"🪙 Coins: ${fmt(user['coins'])}\n"
                f"🏦 Bank: ${fmt(user['bank'])}\n"
                f"💀 Kills: {user['kills']}\n"
                f"🛡 Protection: {protect_text}\n"
                f"☠️ Dead: {dead_text}\n"
                f"🚫 Banned: {ban_text}"
            )

        if action == "resetuser":
            user["coins"] = 0
            user["bank"] = 0
            user["kills"] = 0
            user["last_daily"] = 0
            user["dead_until"] = 0
            user["protected_until"] = 0
            user["last_rob"] = 0
            user["last_kill"] = 0
            user["last_bank_tax"] = 0
            user["last_flip"] = 0

            save_user(uid, user)
            save()

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await query.edit_message_text(f"✅ Reset done for {name}")

        if action == "banuser":
            user["is_banned"] = True
            save_user(uid, user)
            save()

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await query.edit_message_text(f"🚫 {name} banned permanently")

        if action == "unbanuser":
            user["is_banned"] = False
            save_user(uid, user)
            save()

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await query.edit_message_text(f"✅ {name} unbanned")

        context.user_data["admin_step"] = "enter_amount"
        return await query.edit_message_text(
            f"Selected user: {name}\n"
            f"UID: {uid}\n\n"
            f"Now send amount"
        )


async def admin_panel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    if update.effective_chat.type != "private":
        return

    step = context.user_data.get("admin_step")
    action = context.user_data.get("admin_action")

    if not step or not action:
        return

    if step == "search_user":
        search = update.message.text.strip()
        rows = admin_search_users(search)

        if not rows:
            return await update.message.reply_text("❌ No user found")

        keyboard = []
        for row in rows:
            uid = str(row["uid"])
            name = html.escape(str(row.get("name", "User")))
            coins = int(row.get("coins", 0))
            bank = int(row.get("bank", 0))

            keyboard.append([
                InlineKeyboardButton(
                    f"{name} | ${fmt(coins)} | 🏦 ${fmt(bank)}",
                    callback_data=f"admin:pick:{uid}"
                )
            ])

        return await update.message.reply_text(
            "Select user:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if step == "enter_amount":
        uid = context.user_data.get("admin_selected_uid")
        if not uid:
            context.user_data.pop("admin_step", None)
            return await update.message.reply_text("❌ No user selected")

        try:
            amount = int(update.message.text.strip())
        except:
            return await update.message.reply_text("❌ Invalid amount")

        user = get_user(uid)
        name = html.escape(user.get("name", "User"))

        if action == "setcoins":
            user["coins"] = amount
            save_user(uid, user)
            save()
            msg = f"✅ Coins set to ${fmt(amount)} for {name}"

        elif action == "addcoins":
            user["coins"] = int(user.get("coins", 0)) + amount
            save_user(uid, user)
            save()
            msg = f"✅ Added ${fmt(amount)} coins to {name}"

        elif action == "setbank":
            user["bank"] = amount
            save_user(uid, user)
            save()
            msg = f"✅ Bank set to ${fmt(amount)} for {name}"

        elif action == "addbank":
            user["bank"] = int(user.get("bank", 0)) + amount
            save_user(uid, user)
            save()
            msg = f"✅ Added ${fmt(amount)} bank to {name}"

        else:
            msg = "❌ Unknown action"

        context.user_data.pop("admin_step", None)
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_selected_uid", None)

        return await update.message.reply_text(msg)


# =========================
# APP START
# =========================

print("TOKEN FOUND:", bool(TOKEN))

app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()

print("APP BUILT")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("menu", menu))

app.add_handler(CommandHandler("bal", bal))
app.add_handler(CommandHandler("daily", daily))
app.add_handler(CommandHandler("give", give))

app.add_handler(CommandHandler("deposit", deposit))
app.add_handler(CommandHandler("withdraw", withdraw))
app.add_handler(CommandHandler("cashbal", cashbal))

app.add_handler(CommandHandler("kill", kill))
app.add_handler(CommandHandler("rob", rob))
app.add_handler(CommandHandler("protect", protect))
app.add_handler(CommandHandler("revive", revive))

app.add_handler(CommandHandler("flip", flip))
app.add_handler(CommandHandler("dice", dice))
app.add_handler(CommandHandler("slots", slots))
app.add_handler(CommandHandler("color", color))

app.add_handler(CommandHandler("top", top))
app.add_handler(CommandHandler("toprich", toprich))

# NEW OWNER PANEL
app.add_handler(CommandHandler("panel", panel))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin:"))

# OLD NORMAL BUTTON CALLBACK
app.add_handler(CallbackQueryHandler(button))

# ALWAYS LAST
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_panel_text))

print("God Economy Bot started...")
keep_alive()

print("STARTING POLLING")

async def clear(app):
    await app.bot.delete_webhook(drop_pending_updates=True)

app.post_init = clear

# CRASH PROTECTION
while True:
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print("CRASH ERROR:", e)
        time.sleep(5)
