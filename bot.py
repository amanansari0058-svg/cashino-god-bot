from flask import Flask
import threading
import os

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
import json
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

TOKEN = "8680703173:AAFi1UEezi8HGusXMjgUsnpWOI01SjqCrlU"
OWNER_ID = 6479017313
DB_FILE = "users.json"

START_COINS = 0
DAILY_REWARD = 5000

KILL_REWARD = 500
REVIVE_COST = 500

GIVE_TAX = 0.1
ROB_PERCENT = 0.3

ROB_COOLDOWN = 300
KILL_COOLDOWN = 300

MIN_BET = 100
MAX_BET = 5000000

# =========================
# DATABASE
# =========================

try:
    with open(DB_FILE, "r") as f:
        data = json.load(f)
except:
    data = {"users": {}, "tax_pool": 0}

users = data["users"]
tax_pool = data["tax_pool"]


def save():
    data["users"] = users
    data["tax_pool"] = tax_pool
    with open(DB_FILE, "w") as f:
        json.dump(data, f)


def get_user(uid):
    uid = str(uid)

    if uid not in users:
        users[uid] = {
            "coins": START_COINS,
            "bank": 0,
            "kills": 0,
            "last_daily": 0,
            "dead_until": 0,
            "protected_until": 0,
            "last_rob": 0,
            "last_kill": 0,
            "name": "User",
        }
        save()

    return users[uid]


def update_name_from_update(update: Update):
    uid = str(update.effective_user.id)
    user = get_user(uid)
    if update.effective_user.first_name:
        user["name"] = update.effective_user.first_name
        save()


def is_dead(user):
    return time.time() < user["dead_until"]


def is_protected(user):
    return time.time() < user["protected_until"]


def fmt(x):
    return f"{x:,}"


def check_bet(u, bet):
    if bet < MIN_BET:
        return f"❌ Minimum bet is ${fmt(MIN_BET)}"
    if bet > MAX_BET:
        return f"❌ Maximum bet is ${fmt(MAX_BET)}"
    if u["coins"] < bet:
        return "❌ Not enough coins"
    return None

# =========================
# GROUP CHECK HELPER
# =========================

async def ensure_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)

        if bot_member.status not in ["administrator", "creator"]:
            await update.message.reply_text(
                "⚠️ Pehle mujhe group me admin do.\n"
                "Tabhi main yahan work karunga."
            )
            return False

    return True

# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    ok = await ensure_group_admin(update, context)
    if not ok:
        return

    text = """
👑 GOD ECONOMY BOT

Welcome!

/menu
/help
/top
"""

    await update.message.reply_text(text)


# =========================
# HELP
# =========================

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


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)

    now = time.time()

    if now - u["last_daily"] < 86400:
        left = 86400 - int(now - u["last_daily"])
        hours = left // 3600
        minutes = (left % 3600) // 60
        return await update.message.reply_text(
            f"❌ Daily already claimed\n⏳ Come back in {hours}h {minutes}m"
        )

    u["coins"] += DAILY_REWARD
    u["last_daily"] = now

    save()

    await update.message.reply_text("🎁 Daily Claimed! +$5000")


async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tax_pool
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /give <user_id> <amount>")

    sender = get_user(update.effective_user.id)
    uid = context.args[0]
    amount = int(context.args[1])

    if sender["coins"] < amount:
        return await update.message.reply_text("❌ Not enough coins")

    tax = int(amount * GIVE_TAX)
    send = amount - tax

    target = get_user(uid)

    sender["coins"] -= amount
    target["coins"] += send
    tax_pool += tax
    save()

    await update.message.reply_text(
        f"✅ Sent ${fmt(send)}\n💰 Tax: ${fmt(tax)}"
    )


async def taxpool_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💰 TAX POOL: ${fmt(tax_pool)}")


# =========================
# BANK
# =========================

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /deposit <amount>")

    u = get_user(update.effective_user.id)
    amount = int(context.args[0])

    if u["coins"] < amount:
        return await update.message.reply_text("❌ Not enough coins")

    u["coins"] -= amount
    u["bank"] += amount
    save()

    await update.message.reply_text(f"🏦 Deposited ${fmt(amount)}")


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /withdraw <amount>")

    u = get_user(update.effective_user.id)
    amount = int(context.args[0])

    if u["bank"] < amount:
        return await update.message.reply_text("❌ Not enough bank balance")

    u["bank"] -= amount
    u["coins"] += amount
    save()

    await update.message.reply_text(f"💰 Withdrawn ${fmt(amount)}")


async def cashbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"💰 Wallet: ${fmt(u['coins'])}\n🏦 Bank: ${fmt(u['bank'])}"
    )


# =========================
# ACTIONS
# =========================

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

    save()

    await update.message.reply_text(
        f"💀 KILL SUCCESS\n\n"
        f"⚔️ <a href='tg://user?id={attacker_user.id}'>{html.escape(attacker_user.first_name)}</a> ne "
        f"<a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> ko kill kar diya\n"
        f"💰 Reward: ${fmt(KILL_REWARD)}",
        parse_mode="HTML"
    )


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

    save()

    await update.message.reply_text(
        f"💰 ROB SUCCESS\n\n"
        f"🕵️ {robber_user.first_name} ne {target_user.first_name} se ${fmt(steal)} loot liye"
    )


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
    save()

    await update.message.reply_text(
        "🛡 Protection activated for 24 hours"
    )


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

    save()

    await update.message.reply_text(
        f"❤️ {target_user.first_name} revive ho gaya"
    )


# =========================
# GAMES
# =========================

async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /flip <amount> <h/t>")

    u = get_user(update.effective_user.id)

    bet = int(context.args[0])
    choice = context.args[1].lower()

    if choice not in ["h", "t"]:
        return await update.message.reply_text("❌ Choose h or t")

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(error)

    result = random.choice(["h", "t"])

    msg = await update.message.reply_text("🪙 Flipping coin...")

    if result == "h":
        frames = ["🪙 T", "🪙 H", "🪙 T", "🪙 H"]
    else:
        frames = ["🪙 H", "🪙 T", "🪙 H", "🪙 T"]

    for frame in frames:
        await asyncio.sleep(0.35)
        try:
            await msg.edit_text(frame)
        except:
            pass

    if result == choice:
        u["coins"] += bet
        text = f"🪙 Result: {result.upper()}\n🎉 Won ${fmt(bet)}"
    else:
        u["coins"] -= bet
        text = f"🪙 Result: {result.upper()}\n💸 Lost ${fmt(bet)}"

    save()
    await msg.edit_text(text)


async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /dice <amount> <1-6>")

    u = get_user(update.effective_user.id)

    bet = int(context.args[0])
    guess = int(context.args[1])

    if guess < 1 or guess > 6:
        return await update.message.reply_text("❌ Choose number 1 to 6")

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(error)

    roll = random.randint(1, 6)

    msg = await update.message.reply_text("🎲 Rolling dice...")

    frames = [1, 3, 5, 2, 6, roll]
    for num in frames:
        await asyncio.sleep(0.35)
        try:
            await msg.edit_text(f"🎲 {num}")
        except:
            pass

    if roll == guess:
        win = bet * 5
        u["coins"] += win
        text = f"🎲 Dice: {roll}\n🎉 Won ${fmt(win)}"
    else:
        u["coins"] -= bet
        text = f"🎲 Dice: {roll}\n💸 Lost ${fmt(bet)}"

    save()
    await msg.edit_text(text)


async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /roulette <amount> <0-36>")

    u = get_user(update.effective_user.id)

    bet = int(context.args[0])
    guess = int(context.args[1])

    if guess < 0 or guess > 36:
        return await update.message.reply_text("❌ Choose number 0 to 36")

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(error)

    result = random.randint(0, 36)

    msg = await update.message.reply_text("🎡 Spinning roulette...")

    frames = [
        random.randint(0, 36),
        random.randint(0, 36),
        random.randint(0, 36),
        random.randint(0, 36),
        result
    ]

    for num in frames:
        await asyncio.sleep(0.4)
        try:
            await msg.edit_text(f"🎡 {num}")
        except:
            pass

    if result == guess:
        win = bet * 35
        u["coins"] += win
        text = f"🎡 Result: {result}\n🎉 Won ${fmt(win)}"
    else:
        u["coins"] -= bet
        text = f"🎡 Result: {result}\n💸 Lost ${fmt(bet)}"

    save()
    await msg.edit_text(text)


async def color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_name_from_update(update)

    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /color <red/green/violet> <amount>")

    u = get_user(update.effective_user.id)

    choice = context.args[0].lower()
    bet = int(context.args[1])

    if choice not in ["red", "green", "violet"]:
        return await update.message.reply_text("❌ Choose red, green or violet")

    error = check_bet(u, bet)
    if error:
        return await update.message.reply_text(error)

    result = random.choice(["red", "green", "violet"])

    msg = await update.message.reply_text("🎨 Spinning colors...")

    if result == "red":
        frames = ["🟢 GREEN", "🟣 VIOLET", "🔴 RED"]
    elif result == "green":
        frames = ["🟣 VIOLET", "🔴 RED", "🟢 GREEN"]
    else:
        frames = ["🔴 RED", "🟢 GREEN", "🟣 VIOLET"]

    for frame in frames:
        await asyncio.sleep(0.4)
        try:
            await msg.edit_text(frame)
        except:
            pass

    if result == choice:
        if result == "violet":
            win = bet * 3
        else:
            win = bet * 2

        u["coins"] += win
        text = f"🎨 Result: {result}\n🎉 Won ${fmt(win)}"
    else:
        u["coins"] -= bet
        text = f"🎨 Result: {result}\n💸 Lost ${fmt(bet)}"

    save()
    await msg.edit_text(text)


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
