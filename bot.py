# =========================
# IMPORTS
# =========================

import os
import asyncio
import random
import time
import html
import psycopg
from psycopg.rows import dict_row

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# CACHE
# =========================

user_cache = {}

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6479017313

START_COINS = 0
DAILY_COOLDOWN = 86400
DAILY_REWARD = 5000

tax_pool = 0
jackpot_pool = 922337203685477

KILL_REWARD = 500
REVIVE_COST = 500

GIVE_TAX = 0.1
ROB_PERCENT = 0.3

ROB_COOLDOWN = 300
KILL_COOLDOWN = 300

MIN_BET = 100
MAX_BET = 1000000

# =========================
# SPAM SYSTEM
# =========================

spam_tracker = {}

SPAM_COOLDOWN = 2.5
SPAM_RESET_TIME = 5.0
SPAM_BASE_PENALTY = 500

# =========================
# DATABASE
# =========================

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
            
            cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS username TEXT DEFAULT ''
""")

        conn.commit()


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

    # 🔥 TYPE FIX (important)
    user["coins"] = int(user.get("coins", 0))
    user["bank"] = int(user.get("bank", 0))
    user["kills"] = int(user.get("kills", 0))
    user["last_daily"] = float(user.get("last_daily", 0))
    user["dead_until"] = float(user.get("dead_until", 0))
    user["protected_until"] = float(user.get("protected_until", 0))
    user["last_rob"] = float(user.get("last_rob", 0))
    user["last_kill"] = float(user.get("last_kill", 0))
    user["last_bank_tax"] = float(user.get("last_bank_tax", 0))
    user["last_flip"] = float(user.get("last_flip", 0))
    user["is_banned"] = bool(user.get("is_banned", False))
    user["name"] = str(user.get("name", "User"))
    user["username"] = str(user.get("username", ""))

    return user


def get_user_fast(uid):
    uid = str(uid)

    if uid in user_cache:
        return user_cache[uid]

    user = get_user(uid)
    user_cache[uid] = user
    return user


async def load_user(uid):
    return await asyncio.to_thread(get_user_fast, str(uid))


async def save_user_async(uid, user):
    await asyncio.to_thread(save_user, str(uid), user)
    
def save_user(uid, user):
    uid = str(uid)

    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET name=%s,
                    username=%s,
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
                user.get("username", ""),
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

    user_cache[str(uid)] = user


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
    first_name = update.effective_user.first_name
    username = update.effective_user.username or ""

    if not first_name:
        return

    user = get_user_fast(uid)

    changed = False

    if user.get("name") != first_name:
        user["name"] = first_name
        changed = True

    if user.get("username", "") != username:
        user["username"] = username
        changed = True

    if changed:
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
        user_id = update.effective_user.id
        chat = update.effective_chat
        now = time.time()

        user = await load_user(user_id)

        # banned user block
        if user.get("is_banned", False):
            return await update.message.reply_text(
                "❌ You are banned from using this bot"
            )

        # DM me sirf owner allow
        if chat.type == "private":
            if user_id != OWNER_ID:
                return await update.message.reply_text(
                    "❌ Bot DM me sirf owner ke liye hai"
                )

        # OWNER pe anti-spam nahi lagega
        if user_id != OWNER_ID:
            # =========================
            # ANTI SPAM
            # =========================

            text = update.message.text.lower().strip() if update.message and update.message.text else ""

            # ✅ SAFE COMMANDS
            safe_commands = [
                "/start", "/help",
                "/top", "/toprich",
                "/bal", "/cashbal",
                "/daily", "/deposit", "/withdraw",
                "/protect", "/revive", "/give"
            ]

            # ✅ skip safe commands
            if any(text.startswith(cmd) for cmd in safe_commands):
                return await func(update, context)

            data = spam_tracker.get(user_id, {
                "last_time": 0,
                "level": 0
            })

            last_time = float(data.get("last_time", 0))
            level = int(data.get("level", 0))

            # reset after time
            if now - last_time > SPAM_RESET_TIME:
                level = 0

            # spam detect
            if now - last_time < SPAM_COOLDOWN:
                level += 1

                penalty = SPAM_BASE_PENALTY * (2 ** (level - 1))

                current_coins = int(user.get("coins", 0))
                deducted = min(current_coins, penalty)
                user["coins"] = current_coins - deducted

                spam_tracker[user_id] = {
                    "last_time": now,
                    "level": level
                }

                await save_user_async(user_id, user)
                await asyncio.to_thread(save)

                return await update.message.reply_text(
    f"🚨 <b>Spam detected bhai</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"💸 <b>Penalty:</b> -${fmt(deducted)}\n"
    f"⚠️ <b>Offence #{level}</b> Penalty Double Har Bar\n"
    f"🧘 Aaram se bhai spam nhi kro 🤡\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML"
                )

            # normal command allowed
            spam_tracker[user_id] = {
                "last_time": now,
                "level": level
            }

        return await func(update, context)

    return wrapper

def alive_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = get_user_fast(update.effective_user.id)

        dead_left = int(float(user.get("dead_until", 0)) - time.time())

        if dead_left > 0:
            hours = dead_left // 3600
            minutes = (dead_left % 3600) // 60

            return await update.message.reply_text(
    f"💀 <b>Tum dead ho bhai</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"❌ <b>Abhi ye command use nahi kar sakte</b>\n"
    f"⏳ Alive in {hours}h {minutes}m\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML"
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
👑 <b>Wᴇʟᴄᴏᴍᴇ ᴛᴏ Cᴀsɪɴᴏ Gᴏᴅ Eᴄᴏɴᴏᴍʏ ❤️‍🔥!</b>

Yaha coins kamao, loot maro, kill karo aur games jeeto!

🪙 <b>Cᴏɪɴ Cᴏᴍᴍᴀɴᴅs:</b>
• <b>/daily</b> — Roz free coins  
• <b>/bal</b> — Apna coins balance + rank  
• <b>/give</b> (reply) — Coins gift karo (10% tax)

💵 <b>Cᴀsʜ Cᴏᴍᴍᴀɴᴅs:</b>
• <b>/cashbal</b> — Wallet aur bank balance dekho  
• <b>/deposit</b> &lt;amount&gt; — Coins bank me daalo  
• <b>/withdraw</b> &lt;amount&gt; — Bank se coins nikalo  

👊 <b>Aᴄᴛɪᴏɴ Cᴏᴍᴍᴀɴᴅs:</b>
• <b>/kill</b> (reply) — Target ko kill karo  
• <b>/rob</b> (reply) — Kisi ke coins loot lo  
• <b>/protect</b> — 24hr protection lo  
• <b>/revive</b> (reply) — Dead user revive karo  

✨ <b>Gᴀᴍᴇs:</b>
• <b>/flip</b> &lt;amount&gt; &lt;h/t&gt; — 🏀 Basketball flip  
• <b>/dice</b> &lt;amount&gt; &lt;1-6&gt; — 🎲 Dice roll  
• <b>/slots</b> &lt;amount&gt; — 🎰 Play slots  
• <b>/color</b> &lt;red/green&gt; &lt;amount&gt; — 🎯 Color prediction  

🌟 <b>Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ:</b>
• <b>/top</b> — Leaderboard  
• <b>/toprich</b> — Top 10 richest players  

🏦 <b>Eᴄᴏɴᴏᴍʏ:</b>
• <b>/taxpool</b> — Total collected tax dekho  
• <b>/jackpot</b> — Global jackpot amount dekho  

😡 <b>Max bet per game:</b> $1,000,000
"""

    await update.message.reply_text(text, parse_mode="HTML")

# =========================
# HELP
# =========================

@admin_required
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎰 <b>Casino God Help</b>\n\n"

        "💰 <b>Economy</b>\n"
        "• <b>/bal</b> - Check balance\n"
        "• <b>/daily</b> - Claim daily reward\n"
        "• <b>/give</b> (reply) - Give coins\n"
        "• <b>/deposit</b> &lt;amount&gt; - Deposit to bank\n"
        "• <b>/withdraw</b> &lt;amount&gt; - Withdraw from bank\n"
        "• <b>/cashbal</b> - Check wallet and bank\n"
        "• <b>/taxpool</b> - Show total tax pool\n"
        "• <b>/jackpot</b> - Show jackpot amount\n\n"

        "🎮 <b>Games</b>\n"
        "• <b>/flip</b> &lt;amount&gt; - Coin flip game\n"
        "• <b>/dice</b> &lt;amount&gt; - Dice game\n"
        "• <b>/slots</b> &lt;amount&gt; - Slot machine\n"
        "• <b>/color</b> &lt;red/green&gt; &lt;amount&gt; - Color game\n\n"

        "⚔️ <b>Actions</b>\n"
        "• <b>/kill</b> (reply) - Kill user\n"
        "• <b>/rob</b> (reply) - Rob user\n"
        "• <b>/protect</b> - Activate protection\n"
        "• <b>/revive</b> (reply) - Revive user\n\n"

        "🏆 <b>Ranks</b>\n"
        "• <b>/top</b> - Leaderboard\n"
        "• <b>/toprich</b> - Richest users\n"
    )

    await update.message.reply_text(text, parse_mode="HTML")

# =========================
# ECONOMY
# =========================

@admin_required
async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    else:
        target_user = update.effective_user

    uid = target_user.id

    # 🔥 parallel load (fast)
    u, rank = await asyncio.gather(
        load_user(uid),
        asyncio.to_thread(get_user_rank, str(uid))
    )

    coins = int(u.get("coins", 0))
    bank = int(u.get("bank", 0))
    kills = int(u.get("kills", 0))

    protect_left = int(float(u.get("protected_until", 0)) - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60
        protect_text = f"{hours}h {minutes}m left"
    else:
        protect_text = "Not active"

    text = (
        f"👑 <b><a href='tg://user?id={uid}'>{html.escape(target_user.first_name)}</a></b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Coins:</b> ${fmt(coins)}\n"
        f"🏦 <b>Bank:</b> ${fmt(bank)}\n"
        f"💀 <b>Kills:</b> {kills}\n"
        f"🏆 <b>Rank:</b> #{rank}\n"
        f"🛡 <b>Protection:</b> {protect_text}\n"
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

    uid = update.effective_user.id
    u = await load_user(uid)

    now = time.time()
    last = float(u.get("last_daily", 0))

    if now - last < DAILY_COOLDOWN:
        remaining = int(DAILY_COOLDOWN - (now - last))
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        return await update.message.reply_text(
            f"⏳ Daily already claimed\nTry again in {hours}h {minutes}m"
        )

    u["coins"] = int(u.get("coins", 0)) + DAILY_REWARD
    u["last_daily"] = now

    await save_user_async(uid, u)
    await asyncio.to_thread(save)

    await update.message.reply_text(
        f"🎁 Daily reward claimed!\n💰 +${fmt(DAILY_REWARD)} coins"
    )


@alive_required
@admin_required
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tax_pool
    update_name_from_update(update)

    if not update.message.reply_to_message:
        return await update.message.reply_text("❌ Reply karke /give <amount> use karo")

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /give <amount>")

    sender_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    if target_user.is_bot:
        return await update.message.reply_text("❌ Bot ko coins nahi de sakte")

    if target_user.id == sender_user.id:
        return await update.message.reply_text("❌ Khud ko coins nahi de sakte")

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("❌ Invalid amount")

    if amount <= 0:
        return await update.message.reply_text("❌ Amount > 0 hona chahiye")

    # 🔥 PARALLEL LOAD (FASTER)
    sender, target = await asyncio.gather(
        load_user(sender_user.id),
        load_user(target_user.id)
    )

    if sender["coins"] < amount:
        return await update.message.reply_text("❌ Not enough coins")

    tax = int(amount * GIVE_TAX)
    send_amount = amount - tax

    sender["coins"] -= amount
    target["coins"] += send_amount
    tax_pool += tax

    # 🔥 PARALLEL SAVE (FASTER)
    await asyncio.gather(
        save_user_async(sender_user.id, sender),
        save_user_async(target_user.id, target)
    )

    await asyncio.to_thread(save)

    sender_name = html.escape(sender_user.first_name)
    target_name = html.escape(target_user.first_name)

    await update.message.reply_text(
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"💸 <b>{sender_name}</b> sent <b>${fmt(send_amount)}</b> to <b>{target_name}</b>\n"
    f"🧾 <b>Tax:</b> ${fmt(tax)}",
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )

@admin_required
async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global jackpot_pool

    await update.message.reply_text(
    f"🎰 <b>GLOBAL JACKPOT</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"💎 <b>Jackpot:</b> ${fmt(jackpot_pool)}\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"🌍 Yeh jackpot sab players ke liye open hai\n"
    f"⚔️ Khelte raho, mauka kabhi bhi mil sakta hai\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )

# =========================
# BANK SETTINGS
# =========================

MAX_BANK = 5_000_000_000
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

@alive_required
@admin_required
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /deposit <amount>")

    uid = update.effective_user.id
    u = await load_user(uid)

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("❌ Invalid amount")

    if amount <= 0:
        return await update.message.reply_text("❌ Amount must be greater than 0")

    if int(u.get("coins", 0)) < amount:
        return await update.message.reply_text("❌ Not enough coins")

    if int(u.get("bank", 0)) + amount > MAX_BANK:
        return await update.message.reply_text(
            f"❌ Bank limit reached! Max: ${fmt(MAX_BANK)}"
        )

    u["coins"] = int(u.get("coins", 0)) - amount
    u["bank"] = int(u.get("bank", 0)) + amount

    # tax timer deposit ke time se start hoga
    u["last_bank_tax"] = time.time() + BANK_TAX_TIME

    await save_user_async(uid, u)
    await asyncio.to_thread(save)

    await update.message.reply_text(
    f"🏦 <b>DEPOSIT SUCCESS</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"💰 <b>Amount Deposited:</b> ${fmt(amount)}\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"📊 Bank funds time ke sath adjust hote rahenge\n"
    f"⏳ Long term hold me difference dekhne ko milega\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )


@alive_required
@admin_required
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /withdraw <amount>")

    uid = update.effective_user.id
    u = await load_user(uid)

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("❌ Invalid amount")

    if amount <= 0:
        return await update.message.reply_text("❌ Amount must be greater than 0")

    if int(u.get("bank", 0)) < amount:
        return await update.message.reply_text("❌ Not enough bank balance")

    u["bank"] = int(u.get("bank", 0)) - amount
    u["coins"] = int(u.get("coins", 0)) + amount

    await save_user_async(uid, u)
    await asyncio.to_thread(save)

    await update.message.reply_text(f"💰 Withdrawn ${fmt(amount)}")



@admin_required
async def cashbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    uid = update.effective_user.id
    u = await load_user(uid)

    # apply_bank_tax sync hai, isliye thread me chalao
    await asyncio.to_thread(apply_bank_tax, uid, u)

    # tax lagne ke baad fresh user dubara lo
    u = await load_user(uid)

    coins = int(u.get("coins", 0))
    bank = int(u.get("bank", 0))

    next_tax_time = float(u.get("last_bank_tax", 0))
    remaining = int(next_tax_time - time.time())

    if remaining < 0:
        remaining = 0

    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    tax_text = f"⏳ Next tax in {hours}h {minutes}m"

    await update.message.reply_text(
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"💰 <b>Wallet:</b> ${fmt(coins)}\n"
    f"🏦 <b>Bank:</b> ${fmt(bank)}\n\n"
    f"📉 <b>Bank balance par daily adjustment apply hota hai</b>\n"
    f"{tax_text}",
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )

@admin_required
async def taxpool_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tax_pool

    await update.message.reply_text(
    f"💰 <b>GLOBAL TAX POOL</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"🏦 <b>Pool:</b> ${fmt(tax_pool)}\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )

# =========================
# ACTIONS
# =========================

@alive_required
@admin_required
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    attacker, victim = await asyncio.gather(
        load_user(attacker_user.id),
        load_user(victim_user.id)
    )

    kill_left = int(KILL_COOLDOWN - (time.time() - float(attacker.get("last_kill", 0))))

    if kill_left > 0:
        return await update.message.reply_text(
            f"⏳ Kill cooldown active\nTry again in {kill_left}s"
        )

    protect_left = int(float(victim.get("protected_until", 0)) - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> protected hai\n"
            f"❌ Kill block ho gaya\n"
            f"⏳ Protection khatam hogi {hours}h {minutes}m me",
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )

    victim["dead_until"] = time.time() + 43200
    attacker["coins"] = int(attacker.get("coins", 0)) + KILL_REWARD
    attacker["kills"] = int(attacker.get("kills", 0)) + 1
    attacker["last_kill"] = time.time()

    await asyncio.gather(
        save_user_async(attacker_user.id, attacker),
        save_user_async(victim_user.id, victim)
    )
    await asyncio.to_thread(save)

    await update.message.reply_text(
    f"💀 <b>KILL SUCCESS</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━\n"
    f"⚔️ <b><a href='tg://user?id={attacker_user.id}'>{html.escape(attacker_user.first_name)}</a></b> ne "
    f"<b><a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a></b> ko kill kar diya\n"
    f"💰 <b>Reward:</b> ${fmt(KILL_REWARD)}\n"
    f"━━━━━━━━━━━━━━━━━━━━",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )


@alive_required
@admin_required
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text(
    "❌ <b>Kisi user ke message par reply karke /kill use karo.</b>",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
        )

    robber_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    robber, target = await asyncio.gather(
        load_user(robber_user.id),
        load_user(target_user.id)
    )

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
    f"🛡 <b>{html.escape(target_user.first_name)} protected hai</b>\n"
    f"❌ <b>Rob block ho gaya</b>\n"
    f"⏳ <b>Protection khatam hogi</b> {hours}h {minutes}m me",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
        )

    steal = int(int(target.get("coins", 0)) * ROB_PERCENT)

    if steal <= 0:
        return await update.message.reply_text(
    "❌ <b>Target ke paas lootne layak coins nahi hain.</b>",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
        )

    target["coins"] = int(target.get("coins", 0)) - steal
    robber["coins"] = int(robber.get("coins", 0)) + steal
    robber["last_rob"] = time.time()

    await asyncio.gather(
        save_user_async(robber_user.id, robber),
        save_user_async(target_user.id, target)
    )
    await asyncio.to_thread(save)

    await update.message.reply_text(
    f"💰 <b>ROB SUCCESS</b>\n\n"
    f"🕵️ <b>{html.escape(robber_user.first_name)}</b> ne <b>{html.escape(target_user.first_name)}</b> se <b>${fmt(steal)}</b> loot liye",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )


@alive_required
@admin_required
async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = await load_user(uid)

    now = time.time()
    protect_left = int(float(u.get("protected_until", 0)) - now)

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <b>Tum already protected ho</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ <b>Protection khatam hogi:</b> {hours}h {minutes}m\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    u["protected_until"] = now + 86400

    await save_user_async(uid, u)
    await asyncio.to_thread(save)

    await update.message.reply_text(
        f"🛡 <b>Protection activated</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Duration:</b> 24 hours\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


@admin_required
async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ <b>Reply karke hi /revive use kar sakte ho</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    target_user = update.message.reply_to_message.from_user
    user = await load_user(target_user.id)

    if not is_dead(user):
        return await update.message.reply_text(
            "❌ <b>Ye user dead nahi hai</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    if int(user.get("coins", 0)) < REVIVE_COST:
        return await update.message.reply_text(
            "❌ <b>Revive ke liye enough coins nahi hai</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    user["coins"] = int(user.get("coins", 0)) - REVIVE_COST
    user["dead_until"] = 0

    await save_user_async(target_user.id, user)
    await asyncio.to_thread(save)

    await update.message.reply_text(
        f"❤️ <b>{html.escape(target_user.first_name)} revive ho gaya</b>\n"
        f"💸 <b>Cost:</b> ${fmt(REVIVE_COST)}",
        parse_mode="HTML",
        reply_to_message_id=update.message.id
        )

    await update.message.reply_text(
    f"❤️ <b>{html.escape(target_user.first_name)} revive ho gaya</b>",
    parse_mode="HTML",
    reply_to_message_id=update.message.id
    )
     
# =========================
# GAMES
# =========================

def win_message(user, emoji, result, pick, amount):
    return f"""
✨ {emoji} <b>SAHI! YOU WON!</b>
━━━━━━━━━━━━━━━━━━━━━
{emoji} <b>Result:</b> {result}
✅ <b>Tera pick:</b> {pick}

🪙 <b>Jeet:</b> +${fmt(amount)}

👑 Lucky ho <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 🔥
"""


def lose_message(user, emoji, result, pick, amount):
    return f"""
💀 {emoji} <b>GALAT! HAARA!</b>
━━━━━━━━━━━━━━━━━━━━━
{emoji} <b>Result:</b> {result}
❌ <b>Tera pick:</b> {pick}

😔 <b>Nuksan:</b> -${fmt(amount)}

👑 <a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a> 💸
"""

@alive_required
@admin_required
async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /flip <amount> <h/t>",
            reply_to_message_id=update.message.id
        )

    uid = update.effective_user.id
    u = get_user_fast(uid)

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


@alive_required
@admin_required
async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /dice <amount> <1-6>",
            reply_to_message_id=update.message.id
        )

    u = get_user_fast(update.effective_user.id)

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


@alive_required
@admin_required
async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        return await update.message.reply_text(
            "Usage: /slots <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user_fast(update.effective_user.id)

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


@alive_required
@admin_required
async def color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Usage: /color <red/green> <amount>",
            reply_to_message_id=update.message.id
        )

    u = get_user_fast(update.effective_user.id)

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
    rows = await asyncio.to_thread(get_top_users)

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = "🏆 GOD WEALTH TOP 10\n━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, row in enumerate(rows):
        uid = row["uid"]
        name = html.escape(str(row.get("name", "User")))
        coins = int(row.get("coins", 0))

        text += f"{medals[i]} <a href='tg://user?id={uid}'>{name}</a> — ${fmt(coins)}\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


def get_top_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uid, name, coins
                FROM users
                ORDER BY coins DESC
                LIMIT 10
            """)
            return cur.fetchall()


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
            # direct id search
            if query.isdigit():
                cur.execute("""
                    SELECT uid, name, username, coins, bank
                    FROM users
                    WHERE uid = %s
                    LIMIT %s
                """, (query, limit))
                rows = cur.fetchall()
                if rows:
                    return rows

            q = query.lower().lstrip("@")

            # name + username search
            cur.execute("""
                SELECT uid, name, username, coins, bank
                FROM users
                WHERE LOWER(name) LIKE %s
                   OR LOWER(COALESCE(username, '')) LIKE %s
                ORDER BY coins DESC
                LIMIT %s
            """, (f"%{q}%", f"%{q}%", limit))

            return cur.fetchall()


# =========================
# BANNED USERS HELPERS
# =========================

def admin_get_banned_users(limit: int = 10):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uid, name, username, coins, bank
                FROM users
                WHERE is_banned = TRUE
                ORDER BY name ASC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()


def admin_search_banned_users(query: str, limit: int = 10):
    query = query.strip()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # direct id search
            if query.isdigit():
                cur.execute("""
                    SELECT uid, name, username, coins, bank
                    FROM users
                    WHERE is_banned = TRUE AND uid = %s
                    LIMIT %s
                """, (query, limit))
                rows = cur.fetchall()
                if rows:
                    return rows

            q = query.lower().lstrip("@")

            # name + username search (only banned)
            cur.execute("""
                SELECT uid, name, username, coins, bank
                FROM users
                WHERE is_banned = TRUE
                  AND (
                      LOWER(name) LIKE %s
                      OR LOWER(COALESCE(username, '')) LIKE %s
                  )
                ORDER BY name ASC
                LIMIT %s
            """, (f"%{q}%", f"%{q}%", limit))

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

        rows = admin_get_banned_users()

        if not rows:
            return await query.edit_message_text(
                "✅ Abhi koi banned user nahi hai\n\nSend user name, username ya user id agar search karna hai"
            )

        keyboard = []
        for row in rows:
            uid = str(row["uid"])
            name = html.escape(str(row.get("name", "User")))
            username = str(row.get("username", "") or "")
            coins = int(row.get("coins", 0))
            bank = int(row.get("bank", 0))

            label = f"{name}"
            if username:
                label += f" (@{username})"
            label += f" | ${fmt(coins)} | 🏦 ${fmt(bank)}"

            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"admin:pick:{uid}")
            ])

        return await query.edit_message_text(
            "🚫 Banned users list\n\nNeeche se select karo ya name/username/id bhej ke search karo",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    if data.startswith("admin:pick:"):
        uid = data.split(":", 2)[2]
        context.user_data["admin_selected_uid"] = uid
        action = context.user_data.get("admin_action")

        user = get_user_fast(uid)
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

    if not update.message or not update.message.text:
        return

    step = context.user_data.get("admin_step")
    action = context.user_data.get("admin_action")

    if not step or not action:
        return

    # =========================
    # SEARCH USER STEP
    # =========================
    if step == "search_user":
        search = update.message.text.strip()

        if action == "unbanuser":
            rows = admin_search_banned_users(search)
        else:
            rows = admin_search_users(search)

        if not rows:
            return await update.message.reply_text("❌ User not found")

        keyboard = []
        for row in rows:
            uid = str(row["uid"])
            name = html.escape(str(row.get("name", "User")))
            username = str(row.get("username", "") or "")
            coins = int(row.get("coins", 0))
            bank = int(row.get("bank", 0))

            label = f"{name}"
            if username:
                label += f" (@{username})"
            label += f" | ${fmt(coins)} | 🏦 ${fmt(bank)}"

            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"admin:pick:{uid}")
            ])

        return await update.message.reply_text(
            "Select user:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # ENTER AMOUNT STEP
    # =========================
    if step == "enter_amount":
        uid = context.user_data.get("admin_selected_uid")

        if not uid:
            context.user_data.pop("admin_step", None)
            return await update.message.reply_text("❌ No user selected")

        try:
            amount = int(update.message.text.strip())
        except:
            return await update.message.reply_text("❌ Invalid amount")

        user = get_user_fast(uid)
        name = html.escape(user.get("name", "User"))

        if action == "setcoins":
            user["coins"] = amount
            save_user(uid, user)
            await asyncio.to_thread(save)

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await update.message.reply_text(
                f"✅ {name} coins set to ${fmt(amount)}"
            )

        if action == "addcoins":
            user["coins"] = int(user.get("coins", 0)) + amount
            save_user(uid, user)
            await asyncio.to_thread(save)

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await update.message.reply_text(
                f"✅ Added ${fmt(amount)} coins to {name}"
            )

        if action == "addbank":
            user["bank"] = int(user.get("bank", 0)) + amount
            save_user(uid, user)
            await asyncio.to_thread(save)

            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_selected_uid", None)

            return await update.message.reply_text(
                f"✅ Added ${fmt(amount)} bank balance to {name}"
            )

        return await update.message.reply_text("❌ Invalid admin action")


# =========================
# APP START
# =========================

print("TOKEN FOUND:", bool(TOKEN))

app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()

print("APP BUILT")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))

app.add_handler(CommandHandler("bal", bal))
app.add_handler(CommandHandler("daily", daily))
app.add_handler(CommandHandler("give", give))

app.add_handler(CommandHandler("deposit", deposit))
app.add_handler(CommandHandler("withdraw", withdraw))
app.add_handler(CommandHandler("cashbal", cashbal))

app.add_handler(CommandHandler("taxpool", taxpool_cmd))
app.add_handler(CommandHandler("jackpot", jackpot_cmd))

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

# ALWAYS LAST
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_panel_text))

print("God Economy Bot started...")
print("STARTING POLLING")

async def clear(app):
    await app.bot.delete_webhook(drop_pending_updates=True)

app.post_init = clear

app.run_polling(drop_pending_updates=True)
