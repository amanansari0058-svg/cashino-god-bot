from flask import Flask
import threading
import os
import psycopg
from psycopg.rows import dict_row

web = Flask(__name__)

@web.route("/")
def home():
    return "Bot is alive"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)

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
    ContextTypes,
)

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("TOKEN")
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

conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    global tax_pool

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
                last_kill DOUBLE PRECISION DEFAULT 0
            )
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
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM bot_meta WHERE key = 'tax_pool'")
        row = cur.fetchone()
        return int(row["value"]) if row else 0


def set_tax_pool(value):
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

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE uid = %s", (uid,))
        user = cur.fetchone()

        if not user:
            cur.execute("""
                INSERT INTO users (
                    uid, name, coins, bank, kills,
                    last_daily, dead_until, protected_until,
                    last_rob, last_kill
                )
                VALUES (%s, 'User', 0, 0, 0, 0, 0, 0, 0, 0)
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
    user["name"] = str(user.get("name", "User"))

    return user


def save_user(uid, user):
    uid = str(uid)

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
                last_kill=%s
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
            uid
        ))
        conn.commit()


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

def admin_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):

        chat = update.effective_chat

        if chat.type in ["group", "supergroup"]:
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)

            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    "⚠️ Pehle mujhe group me admin do.\n"
                    "Tabhi main yahan work karunga.",
                    reply_to_message_id=update.message.id
                )
                return

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

    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        u = get_user(target.id)
        name = target.first_name
        uid = str(target.id)
    else:
        target = update.effective_user
        u = get_user(target.id)
        name = target.first_name
        uid = str(target.id)

    protect_left = int(u["protected_until"] - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60
        protect_text = f"🛡 Protection: Active ({hours}h {minutes}m left)"
    else:
        protect_text = "🛡 Protection: Not active"

    sorted_users = sorted(users.items(), key=lambda x: x[1]["coins"], reverse=True)
    rank = next((i+1 for i,(user_id,_) in enumerate(sorted_users) if user_id == uid), "N/A")

    txt = (
        f"👑 {name}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Coins: ${fmt(u['coins'])}\n"
        f"🏦 Bank: ${fmt(u['bank'])}\n"
        f"💀 Kills: {u['kills']}\n"
        f"🌍 Global Rank: #{rank}\n"
        f"{protect_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(txt)


@admin_required
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)

    now = time.time()

    if now - u.get("last_daily", 0) < 86400:
        remaining = 86400 - (now - u["last_daily"])
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)

        return await update.message.reply_text(
            f"❌ Daily already claimed\n⏳ Come back in {hours}h {minutes}m",
            reply_to_message_id=update.message.id
        )

    u["coins"] += 5000
    u["last_daily"] = now

    save()

    await update.message.reply_text(
        "🎁 Daily Claimed! +$5000",
        reply_to_message_id=update.message.id
    )


@admin_required
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tax_pool
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /give <user_id> <amount>",
            reply_to_message_id=update.message.id
        )

    sender = get_user(update.effective_user.id)
    uid = context.args[0]
    amount = int(context.args[1])

    if sender["coins"] < amount:
        return await update.message.reply_text(
            "❌ Not enough coins",
            reply_to_message_id=update.message.id
        )

    tax = int(amount * GIVE_TAX)
    send = amount - tax

    target = get_user(uid)

    sender["coins"] -= amount
    target["coins"] += send
    tax_pool += tax

    save_user(update.effective_user.id, sender)
    save_user(uid, target)
    save()

    await update.message.reply_text(
        f"✅ Sent ${fmt(send)}\n💰 Tax: ${fmt(tax)}",
        reply_to_message_id=update.message.id
    )


async def taxpool_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💰 TAX POOL: ${fmt(tax_pool)}",
        reply_to_message_id=update.message.id
    )

# =========================
# BANK
# =========================

@admin_required
@admin_required
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /deposit <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)
    amount = int(context.args[0])

    if u["coins"] < amount:
        return await update.message.reply_text(
            "❌ Not enough coins",
            reply_to_message_id=update.message.id
        )

    u["coins"] -= amount
    u["bank"] += amount

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

    u = get_user(update.effective_user.id)
    amount = int(context.args[0])

    if u["bank"] < amount:
        return await update.message.reply_text(
            "❌ Not enough bank balance",
            reply_to_message_id=update.message.id
        )

    u["bank"] -= amount
    u["coins"] += amount

    save()

    await update.message.reply_text(
        f"💰 Withdrawn ${fmt(amount)}",
        reply_to_message_id=update.message.id
    )


@admin_required
async def cashbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    u = get_user(update.effective_user.id)

    coins = int(u.get("coins", 0))
    bank = int(u.get("bank", 0))

    await update.message.reply_text(
        f"💰 Cash: ${fmt(coins)}\n🏦 Bank: ${fmt(bank)}",
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
            "❌ Kisi user ke message par reply karke /kill use karo."
        )

    attacker_user = update.effective_user
    victim_user = update.message.reply_to_message.from_user

    if victim_user.is_bot:
        return await update.message.reply_text("❌ Bot ko kill nahi kar sakte.")

    if attacker_user.id == victim_user.id:
        return await update.message.reply_text("❌ Khud ko kill nahi kar sakte.")

    attacker = get_user(attacker_user.id)
    victim = get_user(victim_user.id)

    kill_left = int(KILL_COOLDOWN - (time.time() - attacker["last_kill"]))

    if kill_left > 0:
        return await update.message.reply_text(
            f"⏳ Kill cooldown active\nTry again in {kill_left}s"
        )

    protect_left = int(victim["protected_until"] - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 <a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> protected hai\n"
            f"❌ Kill block ho gaya\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me",
            parse_mode="HTML"
        )

    victim["dead_until"] = time.time() + 86400

    attacker["coins"] += KILL_REWARD
    attacker["kills"] += 1
    attacker["last_kill"] = time.time()

    save_user(attacker_user.id, attacker)
    save_user(victim_user.id, victim)
    save()

    await update.message.reply_text(
        f"💀 KILL SUCCESS\n\n"
        f"⚔️ <a href='tg://user?id={attacker_user.id}'>{html.escape(attacker_user.first_name)}</a> ne "
        f"<a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> ko kill kar diya\n"
        f"💰 Reward: ${fmt(KILL_REWARD)}",
        parse_mode="HTML"
    )


@admin_required
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi user ke message par reply karke /rob use karo."
        )

    robber_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    robber = get_user(robber_user.id)
    target = get_user(target_user.id)

    rob_left = int(ROB_COOLDOWN - (time.time() - robber["last_rob"]))

    if rob_left > 0:
        return await update.message.reply_text(
            f"⏳ Rob cooldown active\nTry again in {rob_left}s"
        )

    protect_left = int(target["protected_until"] - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 {target_user.first_name} protected hai\n"
            f"❌ Rob block ho gaya\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me"
        )

    steal = int(target["coins"] * ROB_PERCENT)

    if steal <= 0:
        return await update.message.reply_text(
            "❌ Target ke paas lootne layak coins nahi hain."
        )

    target["coins"] -= steal
    robber["coins"] += steal
    robber["last_rob"] = time.time()

    save_user(update.effective_user.id, u)
save()

    await update.message.reply_text(
        f"💰 ROB SUCCESS\n\n"
        f"🕵️ {robber_user.first_name} ne {target_user.first_name} se ${fmt(steal)} loot liye"
    )


@admin_required
async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)

    now = time.time()
    protect_left = int(u["protected_until"] - now)

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"🛡 Tum already protected ho\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me"
        )

    u["protected_until"] = now + 86400
    save_user(update.effective_user.id, u)
save()

    await update.message.reply_text(
        "🛡 Protection activated for 24 hours"
    )


@admin_required
async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ Kisi dead user ke message par reply karke /revive use karo."
        )

    target_user = update.message.reply_to_message.from_user
    user = get_user(target_user.id)

    if not is_dead(user):
        return await update.message.reply_text("❌ Ye user dead nahi hai")

    if user["coins"] < REVIVE_COST:
        return await update.message.reply_text("❌ Revive ke liye coins nahi hain")

    user["coins"] -= REVIVE_COST
    user["dead_until"] = 0

    save_user(update.effective_user.id, u)
save()

    await update.message.reply_text(
        f"❤️ {target_user.first_name} revive ho gaya"
    )
     
# =========================
# GAMES
# =========================

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


def win_message(user, emoji, result, pick, amount, multi=1):
    return f"""
✨ {emoji} SAHI! YOU WON!
━━━━━━━━━━━━━━━━━━━━━
{emoji} Result: {result}
✅ Tera pick: {pick}

🪙 Jeet: +${fmt(amount)} ({multi}x)

👑 Lucky ho <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 🔥
"""


def lose_message(user, emoji, result, pick, amount):
    return f"""
💀 {emoji} GALAT! HAARA!
━━━━━━━━━━━━━━━━━━━━━
{emoji} Result: {result}
❌ Tera pick: {pick}

😔 Nuksan: -${fmt(amount)} coins

Agli baar sahi lagana
👑 <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 💸
"""


async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /flip <amount> <h/t>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)
    u["coins"] = int(u.get("coins", 0))

    try:
        bet = abs(int(context.args[0]))
    except:
        return await update.message.reply_text(
            "❌ Invalid bet amount",
            reply_to_message_id=update.message.id
        )

    choice = context.args[1].lower()

    if choice not in ["h", "t"]:
        return await update.message.reply_text(
            "❌ Choose h or t",
            reply_to_message_id=update.message.id
        )

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
    await asyncio.sleep(3)

    if value >= 4:
        result_key = "h"
        result_text = "Heads"
    else:
        result_key = "t"
        result_text = "Tails"

    pick_text = "Heads" if choice == "h" else "Tails"

    if result_key == choice:
        u["coins"] += bet
        text = win_message(update.effective_user, "🪙", result_text, pick_text, bet, 2)
    else:
        u["coins"] -= bet
        text = lose_message(update.effective_user, "🪙", result_text, pick_text, bet)

    save_user(update.effective_user.id, u)
save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /dice <amount> <1-6>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)
    u["coins"] = int(u.get("coins", 0))

    try:
        bet = abs(int(context.args[0]))
        guess = int(context.args[1])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount or number",
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
    await asyncio.sleep(3)

    if roll == guess:
        win = bet * 5
        u["coins"] += win
        text = win_message(update.effective_user, "🎲", str(roll), str(guess), win, 5)
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


async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /roulette <amount> <0-36>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)
    u["coins"] = int(u.get("coins", 0))

    try:
        bet = abs(int(context.args[0]))
        guess = int(context.args[1])
    except:
        return await update.message.reply_text(
            "❌ Invalid amount or number",
            reply_to_message_id=update.message.id
        )

    if guess < 0 or guess > 36:
        return await update.message.reply_text(
            "❌ Choose number 0 to 36",
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
    await asyncio.sleep(3)

    result = value % 37

    if result == guess:
        win = bet * 35
        u["coins"] += win
        text = win_message(update.effective_user, "🎡", str(result), str(guess), win, 35)
    else:
        u["coins"] -= bet
        text = lose_message(update.effective_user, "🎡", str(result), str(guess), bet)

    save_user(update.effective_user.id, u)
save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


async def color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /color <red/green/violet> <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user(update.effective_user.id)
    u["coins"] = int(u.get("coins", 0))

    choice = context.args[0].lower()

    try:
        bet = abs(int(context.args[1]))
    except:
        return await update.message.reply_text(
            "❌ Invalid bet amount",
            reply_to_message_id=update.message.id
        )

    if choice not in ["red", "green", "violet"]:
        return await update.message.reply_text(
            "❌ Choose red, green or violet",
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
    await asyncio.sleep(3)

    if value in [1, 2]:
        result = "red"
    elif value in [3, 4]:
        result = "green"
    else:
        result = "violet"

    if result == choice:
        if result == "violet":
            win = bet * 3
            multi = 3
        else:
            win = bet * 2
            multi = 2

        u["coins"] += win
        text = win_message(update.effective_user, "🎨", result, choice, win, multi)
    else:
        u["coins"] -= bet
        text = lose_message(update.effective_user, "🎨", result, choice, bet)

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

async def toprich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_users = sorted(
        users.items(),
        key=lambda x: x[1]["coins"],
        reverse=True
    )[:10]

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    text = "🏆 GOD WEALTH TOP 10\n━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, (uid, data) in enumerate(sorted_users):
        try:
            chat = await context.bot.get_chat(uid)
            name = html.escape(chat.first_name or data.get("name", "User"))
        except:
            name = html.escape(data.get("name", "User"))

        text += f"{medals[i]} <a href='tg://user?id={uid}'>{name}</a> — ${fmt(data['coins'])}\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toprich(update, context)

# =========================
# ADMIN
# =========================

def is_owner(update: Update):
    return update.effective_user.id == OWNER_ID


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    text = """
👑 ADMIN PANEL

/setcoins <user_id> <amount>
/addcoins <user_id> <amount>
/resetuser <user_id>
/setbank <user_id> <amount>
/addbank <user_id> <amount>
/userinfo <user_id>
"""

    await update.message.reply_text(text)


async def setcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /setcoins <user_id> <amount>")

    uid = context.args[0]
    amount = int(context.args[1])

    user = get_user(uid)
    user["coins"] = amount
    save()

    await update.message.reply_text(f"✅ Coins set to ${fmt(amount)}")


async def addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /addcoins <user_id> <amount>")

    uid = context.args[0]
    amount = int(context.args[1])

    user = get_user(uid)
    user["coins"] += amount
    save()

    await update.message.reply_text(f"✅ Added ${fmt(amount)} coins")


async def resetuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /resetuser <user_id>")

    uid = context.args[0]
    user = get_user(uid)

    user["coins"] = 0
    user["bank"] = 0
    user["kills"] = 0
    user["last_daily"] = 0
    user["dead_until"] = 0
    user["protected_until"] = 0
    user["last_rob"] = 0
    user["last_kill"] = 0

    save()

    await update.message.reply_text("✅ User reset successful")


async def setbank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /setbank <user_id> <amount>")

    uid = context.args[0]
    amount = int(context.args[1])

    user = get_user(uid)
    user["bank"] = amount
    save()

    await update.message.reply_text(f"✅ Bank set to ${fmt(amount)}")


async def addbank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /addbank <user_id> <amount>")

    uid = context.args[0]
    amount = int(context.args[1])

    user = get_user(uid)
    user["bank"] += amount
    save()

    await update.message.reply_text(f"✅ Added ${fmt(amount)} to bank")


async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Owner only command")

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /userinfo <user_id>")

    uid = context.args[0]
    user = get_user(uid)

    protect_left = int(user["protected_until"] - time.time())
    dead_left = int(user["dead_until"] - time.time())

    if protect_left > 0:
        protect_text = f"{protect_left//3600}h {(protect_left%3600)//60}m left"
    else:
        protect_text = "Not active"

    if dead_left > 0:
        dead_text = f"{dead_left//3600}h {(dead_left%3600)//60}m left"
    else:
        dead_text = "Not dead"

    text = (
        f"👤 User ID: {uid}\n"
        f"🪙 Coins: ${fmt(user['coins'])}\n"
        f"🏦 Bank: ${fmt(user['bank'])}\n"
        f"💀 Kills: {user['kills']}\n"
        f"🛡 Protection: {protect_text}\n"
        f"☠️ Dead: {dead_text}"
    )

    await update.message.reply_text(text)

# =========================
# APP START
# =========================

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("menu", menu))

app.add_handler(CommandHandler("bal", bal))
app.add_handler(CommandHandler("daily", daily))
app.add_handler(CommandHandler("give", give))
app.add_handler(CommandHandler("taxpool", taxpool_cmd))

app.add_handler(CommandHandler("deposit", deposit))
app.add_handler(CommandHandler("withdraw", withdraw))
app.add_handler(CommandHandler("cashbal", cashbal))

app.add_handler(CommandHandler("kill", kill))
app.add_handler(CommandHandler("rob", rob))
app.add_handler(CommandHandler("protect", protect))
app.add_handler(CommandHandler("revive", revive))

app.add_handler(CommandHandler("flip", flip))
app.add_handler(CommandHandler("dice", dice))
app.add_handler(CommandHandler("roulette", roulette))
app.add_handler(CommandHandler("color", color))

app.add_handler(CommandHandler("top", top))
app.add_handler(CommandHandler("toprich", toprich))

app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("setcoins", setcoins))
app.add_handler(CommandHandler("addcoins", addcoins))
app.add_handler(CommandHandler("resetuser", resetuser))
app.add_handler(CommandHandler("setbank", setbank))
app.add_handler(CommandHandler("addbank", addbank))
app.add_handler(CommandHandler("userinfo", userinfo))

app.add_handler(CallbackQueryHandler(button))

print("God Economy Bot started...")
keep_alive()
app.run_polling()
