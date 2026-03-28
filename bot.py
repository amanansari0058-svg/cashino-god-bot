# =========================
# IMPORTS
# =========================

import json
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

pending_duels = {}
active_duels = {}
recent_duel_tasks = []
MAX_RECENT_DUEL_TASKS = 8

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6479017313

START_COINS = 0
DAILY_COOLDOWN = 86400
DAILY_REWARD = 5000

tax_pool = 0
jackpot_pool = 99922337203685477

KILL_REWARD = 500
REVIVE_COST = 500

GIVE_TAX = 0.1
ROB_PERCENT = 0.3

ROB_COOLDOWN = 300
KILL_COOLDOWN = 300

MIN_BET = 100
MAX_BET = 1000000

DUEL_TIMEOUT = 30
DUEL_ANSWER_TIMEOUT = 20
DUEL_START_DELAY = 2

# =========================
# SPAM SYSTEM
# =========================

spam_tracker = {}

SPAM_COOLDOWN = 5.0
SPAM_RESET_TIME = 5.0
SPAM_BASE_PENALTY = 500


#========== PROFILE CONSTANTS ==========#

CURRENT_SEASON = "2026-03"

LEVEL_BADGES = {
    5: "Beginner",
    10: "Rookie",
    20: "Skilled",
    30: "Pro",
    40: "Elite",
    50: "Master",
    75: "Legend",
    100: "King"
}


# =========================
# DATABASE
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def migrate_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS level BIGINT DEFAULT 1;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS xp BIGINT DEFAULT 0;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS badges TEXT DEFAULT '[]';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS season_id TEXT DEFAULT 'current';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS season TEXT DEFAULT '{}';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS all_time TEXT DEFAULT '{}';
            """)
        conn.commit()



def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid TEXT PRIMARY KEY,
                    name TEXT DEFAULT 'User',
                    username TEXT DEFAULT '',
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
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS username TEXT DEFAULT ''
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
                        last_rob, last_kill, last_bank_tax, last_flip,
                        level, xp, badges, season_id, season, all_time
                    )
                    VALUES (
                        %s, 'User', 0, 0, 0,
                        0, 0, 0, 0, 0, 0, 0,
                        1, 0, '[]', '2026-03', '{}', '{}'
                    )
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
    user["last_flip"] = float(user.get("last_flip", 0))
    user["is_banned"] = bool(user.get("is_banned", False))
    user["name"] = str(user.get("name", "User"))
    user["username"] = str(user.get("username", ""))

    user["level"] = int(user.get("level", 1))
    user["xp"] = int(user.get("xp", 0))
    user["season_id"] = str(user.get("season_id", CURRENT_SEASON))

    badges_raw = user.get("badges", "[]")
    try:
        user["badges"] = json.loads(badges_raw) if isinstance(badges_raw, str) else badges_raw
    except:
        user["badges"] = []

    season_raw = user.get("season", "{}")
    try:
        user["season"] = json.loads(season_raw) if isinstance(season_raw, str) else season_raw
    except:
        user["season"] = {}

    if not isinstance(user["season"], dict):
        user["season"] = {}

    user["season"].setdefault("coins", 0)
    user["season"].setdefault("kills", 0)
    user["season"].setdefault("rank", 0)

    all_time_raw = user.get("all_time", "{}")
    try:
        user["all_time"] = json.loads(all_time_raw) if isinstance(all_time_raw, str) else all_time_raw
    except:
        user["all_time"] = {}

    if not isinstance(user["all_time"], dict):
        user["all_time"] = {}

    user["all_time"].setdefault("duel_wins", 0)
    user["all_time"].setdefault("best_streak", 0)
    user["all_time"].setdefault("total_earned", 0)

    return user


#========== PROFILE HELPERS ==========#

def xp_needed_for_next_level(level: int) -> int:
    return 200 + (level * 70) + (level * level * 4)

def add_xp(user, amount: int):
    if amount <= 0:
        return False

    user["xp"] += amount
    leveled_up = False

    while user["xp"] >= xp_needed_for_next_level(user["level"]):
        need = xp_needed_for_next_level(user["level"])
        user["xp"] -= need
        user["level"] += 1
        leveled_up = True

    update_badges(user)
    return leveled_up

def update_badges(user):
    badges = set(user.get("badges", []))

    level = user.get("level", 1)
    kills = user.get("kills", 0)
    duel_wins = user.get("all_time", {}).get("duel_wins", 0)
    total_earned = user.get("all_time", {}).get("total_earned", 0)
    best_streak = user.get("all_time", {}).get("best_streak", 0)

    for lvl, badge_name in LEVEL_BADGES.items():
        if level >= lvl:
            badges.add(badge_name)

    if kills >= 10:
        badges.add("Killer")
    if duel_wins >= 10:
        badges.add("Duel Master")
    if total_earned >= 10000:
        badges.add("Rich")
    if best_streak >= 5:
        badges.add("On Fire")

    user["badges"] = list(badges)

def check_and_reset_season(user):
    if user["season_id"] != CURRENT_SEASON:
        user["season_id"] = CURRENT_SEASON
        user["season"] = {
            "coins": 0,
            "kills": 0,
            "rank": 0
        }

def get_status_text(user):
    now = int(time.time())
    if user.get("dead_until", 0) > now:
        return "Dead"
    return "Alive"

def get_display_badges(user, limit=2):
    badges = user.get("badges", [])
    if not badges:
        return "None"
    return ", ".join(badges[:limit])

def get_season_rank(uid):
    uid = str(uid)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT uid, season FROM users")
            rows = cur.fetchall()

    board = []

    for row in rows:
        season_raw = row.get("season", "{}")

        try:
            season_data = json.loads(season_raw) if isinstance(season_raw, str) else season_raw
        except:
            season_data = {}

        if not isinstance(season_data, dict):
            season_data = {}

        coins = int(season_data.get("coins", 0))
        board.append((str(row["uid"]), coins))

    board.sort(key=lambda x: x[1], reverse=True)

    for i, (row_uid, _) in enumerate(board, start=1):
        if row_uid == uid:
            return i

    return 0
    

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
                    is_banned=%s,
                    level=%s,
                    xp=%s,
                    badges=%s,
                    season_id=%s,
                    season=%s,
                    all_time=%s
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
                int(user.get("level", 1)),
                int(user.get("xp", 0)),
                json.dumps(user.get("badges", [])),
                str(user.get("season_id", CURRENT_SEASON)),
                json.dumps(user.get("season", {
                    "coins": 0,
                    "kills": 0,
                    "rank": 0
                })),
                json.dumps(user.get("all_time", {
                    "duel_wins": 0,
                    "best_streak": 0,
                    "total_earned": 0
                })),
                uid
            ))
        conn.commit()

    user_cache[str(uid)] = user

def get_user_rank(uid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uid
                FROM users
                ORDER BY (COALESCE(coins, 0) + COALESCE(bank, 0)) DESC
            """)
            rows = cur.fetchall()

    for i, row in enumerate(rows, start=1):
        if str(row["uid"]) == str(uid):
            return i
    return 0


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


def get_duel_key(chat_id):
    return str(chat_id)


def clear_duel(chat_id):
    key = get_duel_key(chat_id)
    pending_duels.pop(key, None)
    active_duels.pop(key, None)


def normalize_duel_answer(text: str) -> str:
    return text.strip().lower()


def generate_duel_task():
    global recent_duel_tasks

    task_pool = []

    # 1) Math add
    for _ in range(8):
        a = random.randint(10, 99)
        b = random.randint(10, 99)
        prompt = f"🧠 <b>Math Duel</b>\nSolve karo: <b>{a} + {b}</b>"
        answer = str(a + b)
        task_id = f"math_add_{a}_{b}"
        task_pool.append((task_id, prompt, answer))

    # 2) Subtract
    for _ in range(8):
        a = random.randint(50, 150)
        b = random.randint(10, 49)
        prompt = f"➖ <b>Math Duel</b>\nSolve karo: <b>{a} - {b}</b>"
        answer = str(a - b)
        task_id = f"math_sub_{a}_{b}"
        task_pool.append((task_id, prompt, answer))

    # 3) Multiply
    for _ in range(8):
        a = random.randint(2, 12)
        b = random.randint(2, 12)
        prompt = f"✖️ <b>Multiply Duel</b>\nSolve karo: <b>{a} × {b}</b>"
        answer = str(a * b)
        task_id = f"math_mul_{a}_{b}"
        task_pool.append((task_id, prompt, answer))

    # 4) Exact type
    words = [
        "shadow", "legend", "casino", "thunder", "rocket", "winner",
        "phoenix", "sniper", "blazer", "crimson", "monster", "diamond",
        "venom", "battle", "hunter", "future", "storm", "ghost"
    ]
    for word in words:
        prompt = f"⌨️ <b>Type Duel</b>\nYe word exactly type karo: <b>{word}</b>"
        answer = word
        task_id = f"type_{word}"
        task_pool.append((task_id, prompt, answer))

    # 5) Reverse
    rev_words = [
        "dragon", "silver", "combat", "ticket", "future", "vision",
        "empire", "danger", "target", "ranger", "meteor", "blaster"
    ]
    for word in rev_words:
        prompt = f"🔁 <b>Reverse Duel</b>\nIs word ko reverse karke bhejo: <b>{word}</b>"
        answer = word[::-1]
        task_id = f"reverse_{word}"
        task_pool.append((task_id, prompt, answer))

    # 6) Uppercase
    upper_words = [
        "strike", "system", "bonus", "galaxy", "falcon", "sniper",
        "trophy", "winner", "action", "danger", "matrix", "gamer"
    ]
    for word in upper_words:
        prompt = f"🔠 <b>Case Duel</b>\nIs word ko <b>UPPERCASE</b> me bhejo: <b>{word}</b>"
        answer = word.lower()
        task_id = f"upper_{word}"
        task_pool.append((task_id, prompt, answer))

    # 7) Lowercase
    lower_words = [
        "KING", "FIRE", "GHOST", "RAGE", "LUCK", "VENOM",
        "POWER", "BLAZE", "NINJA", "TIGER"
    ]
    for word in lower_words:
        prompt = f"🔡 <b>Case Duel</b>\nIs word ko <b>lowercase</b> me bhejo: <b>{word}</b>"
        answer = word.lower()
        task_id = f"lower_{word}"
        task_pool.append((task_id, prompt, answer))

    # 8) Number sort
    for _ in range(8):
        nums = random.sample(range(1, 10), 4)
        prompt = (
            f"🔢 <b>Sort Duel</b>\n"
            f"In numbers ko ascending order me bhejo: <b>{' '.join(map(str, nums))}</b>\n"
            f"Format: 1 2 3 4"
        )
        answer = " ".join(map(str, sorted(nums)))
        task_id = f"sort_{'_'.join(map(str, nums))}"
        task_pool.append((task_id, prompt, answer))

    # 9) Vowel count
    vowel_words = ["education", "operation", "aviation", "equation", "universe"]
    for word in vowel_words:
        count = sum(1 for ch in word.lower() if ch in "aeiou")
        prompt = f"🗣 <b>Vowel Duel</b>\nIs word me vowels kitne hain: <b>{word}</b>"
        answer = str(count)
        task_id = f"vowel_{word}"
        task_pool.append((task_id, prompt, answer))

    available_tasks = [task for task in task_pool if task[0] not in recent_duel_tasks]

    if not available_tasks:
        recent_duel_tasks = []
        available_tasks = task_pool[:]

    task_id, prompt, answer = random.choice(available_tasks)

    recent_duel_tasks.append(task_id)
    if len(recent_duel_tasks) > MAX_RECENT_DUEL_TASKS:
        recent_duel_tasks.pop(0)

    return prompt, answer


async def expire_pending_duel(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await asyncio.sleep(DUEL_TIMEOUT)

    key = get_duel_key(chat_id)
    duel = pending_duels.get(key)

    if not duel:
        return

    clear_duel(chat_id)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚔️ <b>Duel request expire ho gaya</b>\n"
                "Kisi ne time pe accept nahi kiya"
            ),
            parse_mode="HTML"
        )
    except:
        pass


async def expire_active_duel(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    global jackpot_pool

    await asyncio.sleep(DUEL_ANSWER_TIMEOUT)

    key = get_duel_key(chat_id)
    duel = active_duels.get(key)

    if not duel:
        return

    challenger = await load_user(duel["challenger_id"])
    accepter = await load_user(duel["acceptor_id"])

    amount = duel["amount"]

    challenger["coins"] = int(challenger.get("coins", 0)) + amount
    accepter["coins"] = int(accepter.get("coins", 0)) + amount

    jackpot_pool += duel["jackpot_bonus"]

    await asyncio.gather(
        save_user_async(duel["challenger_id"], challenger),
        save_user_async(duel["acceptor_id"], accepter)
    )
    await asyncio.to_thread(save)

    clear_duel(chat_id)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⌛ <b>Duel timeout ho gaya</b>\n"
                f"💰 Dono players ko <b>${fmt(amount)}</b> refund kar diye gaye\n"
                f"🎰 Jackpot bonus <b>${fmt(duel['jackpot_bonus'])}</b> pool me wapas chala gaya"
            ),
            parse_mode="HTML"
        )
    except:
        pass


init_db()
tax_pool = get_tax_pool()

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
                "/top", "/toprich", "/taxpool",
                "/bal", "/cashbal", "/jackpot",
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

⚔️ <b>Dᴜᴇʟ Cᴏᴍᴍᴀɴᴅ:</b>
• <b>/duel</b> &lt;amount&gt; — Skill based duel challenge khelo ⚡

🌟 <b>Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ:</b>
• <b>/top</b> — Leaderboard  
• <b>/toprich</b> — Top 10 richest players  

🏦 <b>Eᴄᴏɴᴏᴍʏ:</b>
• <b>/profile</b> — Apni profile dekho
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
        "• <b>/profile</b> - Your profile\n"
        "• <b>/bal</b> - Check balance\n"
        "• <b>/daily</b> - Claim daily reward\n"
        "• <b>/give</b> (reply) - Give coins\n"
        "• <b>/deposit</b> &lt;amount&gt; - Deposit to bank\n"
        "• <b>/withdraw</b> &lt;amount&gt; - Withdraw from bank\n"
        "• <b>/cashbal</b> - Check wallet and bank\n"
        "• <b>/taxpool</b> - Show total tax pool\n"
        "• <b>/jackpot</b> - Show jackpot amount\n\n"

        "🎮 <b>Games</b>\n"
"• <b>/flip</b> &lt;amount&gt; - Coin flip\n"
"• <b>/dice</b> &lt;amount&gt; - Dice game\n"
"• <b>/slots</b> &lt;amount&gt; - Slots\n"
"• <b>/color</b> &lt;red/green&gt; &lt;amount&gt; - Color game\n\n"
"• <b>/duel</b> &lt;amount&gt; - Skill duel \n\n"

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

    u.setdefault("all_time", {})
    u["all_time"].setdefault("total_earned", 0)

    u.setdefault("season", {})
    u["season"].setdefault("coins", 0)
    u["season"].setdefault("kills", 0)
    u["season"].setdefault("rank", 0)

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

    u["all_time"]["total_earned"] += DAILY_REWARD
    u["season"]["coins"] += DAILY_REWARD
    add_xp(u, 3)

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

    sender, target = await asyncio.gather(
        load_user(sender_user.id),
        load_user(target_user.id)
    )

    sender.setdefault("all_time", {})
    sender["all_time"].setdefault("total_earned", 0)

    sender.setdefault("season", {})
    sender["season"].setdefault("coins", 0)
    sender["season"].setdefault("kills", 0)
    sender["season"].setdefault("rank", 0)

    target.setdefault("all_time", {})
    target["all_time"].setdefault("total_earned", 0)

    target.setdefault("season", {})
    target["season"].setdefault("coins", 0)
    target["season"].setdefault("kills", 0)
    target["season"].setdefault("rank", 0)

    if sender["coins"] < amount:
        return await update.message.reply_text("❌ Not enough coins")

    tax = int(amount * GIVE_TAX)
    send_amount = amount - tax

    sender["coins"] -= amount
    target["coins"] += send_amount
    tax_pool += tax

    # 🔥 PROFILE + XP
    target["all_time"]["total_earned"] += send_amount
    target["season"]["coins"] += send_amount

    add_xp(sender, 1)
    add_xp(target, 1)

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
        f"🧾 <b>Tax:</b> ${fmt(tax)}\n"
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


#========== /PROFILE COMMAND ==========#

@admin_required
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = get_user_fast(tg_user.id)
    user["name"] = tg_user.first_name or "Unknown"
    user["username"] = tg_user.username or ""

    check_and_reset_season(user)
    update_badges(user)

    current_rank = get_user_rank(tg_user.id)
    user["season"]["rank"] = current_rank

    level = user["level"]
    xp = user["xp"]
    xp_needed = xp_needed_for_next_level(level)

    season_coins = user["season"]["coins"]
    season_kills = user["season"]["kills"]

    duel_wins = user["all_time"]["duel_wins"]
    best_streak = user["all_time"]["best_streak"]
    total_earned = user["all_time"]["total_earned"]

    safe_name = html.escape(user["name"])

    text = (
        "<b>╔═══ 👤 PLAYER PROFILE ═══╗</b>\n\n"
        f'👤 <b>Name:</b> <a href="tg://user?id={tg_user.id}">{safe_name}</a>\n'
        f"⭐ <b>Level:</b> {level}  |  ✨ <b>XP:</b> {xp}/{xp_needed}\n\n"
        "<b>📅 Current Season</b>\n"
        f"💰 <b>Coins:</b> {season_coins:,}   💀 <b>Kills:</b> {season_kills}   👑 <b>Rank:</b> #{current_rank}\n\n"
        "<b>📜 All Time</b>\n"
        f"⚔️ <b>Duel Wins:</b> {duel_wins}   🔥 <b>Best Streak:</b> {best_streak}\n"
        f"💸 <b>Total Earned:</b> {total_earned:,}\n\n"
        f"🏅 <b>Badges:</b> {get_display_badges(user, 2)}\n"
        f"❤️ <b>Status:</b> {get_status_text(user)}\n\n"
        "<b>╚═══════════════════╝</b>"
    )

    save_user(tg_user.id, user)

    await update.message.reply_text(
        text,
        parse_mode="HTML"
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

    u["last_bank_tax"] = time.time() + BANK_TAX_TIME

    # 🔥 XP (safe, no farming)
    add_xp(u, 1)

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

    # 🔥 XP (safe, no farming)
    add_xp(u, 1)

    await save_user_async(uid, u)
    await asyncio.to_thread(save)

    await update.message.reply_text(
        f"💰 Withdrawn ${fmt(amount)}"
    )



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
    f"{tax_text}\n"
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
            "❌ <b>Kisi user ke message par reply karke /kill use karo.</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    attacker_user = update.effective_user
    victim_user = update.message.reply_to_message.from_user

    if victim_user.is_bot:
        return await update.message.reply_text(
            "❌ <b>Bot ko kill nahi kar sakte.</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    if attacker_user.id == victim_user.id:
        return await update.message.reply_text(
            "❌ <b>Khud ko kill nahi kar sakte.</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    attacker, victim = await asyncio.gather(
        load_user(attacker_user.id),
        load_user(victim_user.id)
    )

    attacker.setdefault("all_time", {})
    attacker["all_time"].setdefault("duel_wins", 0)
    attacker["all_time"].setdefault("best_streak", 0)
    attacker["all_time"].setdefault("total_earned", 0)

    attacker.setdefault("season", {})
    attacker["season"].setdefault("coins", 0)
    attacker["season"].setdefault("kills", 0)
    attacker["season"].setdefault("rank", 0)

    kill_left = int(KILL_COOLDOWN - (time.time() - float(attacker.get("last_kill", 0))))

    if kill_left > 0:
        return await update.message.reply_text(
            f"⏳ <b>Kill cooldown active</b>\n"
            f"Try again in {kill_left}s",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    protect_left = int(float(victim.get("protected_until", 0)) - time.time())

    if protect_left > 0:
        hours = protect_left // 3600
        minutes = (protect_left % 3600) // 60

        return await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <b><a href='tg://user?id={victim_user.id}'>{html.escape(victim_user.first_name)}</a> protected hai</b>\n"
            f"❌ <b>Kill block ho gaya</b>\n"
            f"⏳ <b>Protection khatam hogi</b> {hours}h {minutes}m me\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    victim["dead_until"] = time.time() + 43200
    attacker["coins"] = int(attacker.get("coins", 0)) + KILL_REWARD
    attacker["kills"] = int(attacker.get("kills", 0)) + 1
    attacker["last_kill"] = time.time()

    attacker["all_time"]["total_earned"] += KILL_REWARD
    attacker["season"]["coins"] += KILL_REWARD
    attacker["season"]["kills"] += 1
    add_xp(attacker, 8)

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

    robber.setdefault("all_time", {})
    robber["all_time"].setdefault("duel_wins", 0)
    robber["all_time"].setdefault("best_streak", 0)
    robber["all_time"].setdefault("total_earned", 0)

    robber.setdefault("season", {})
    robber["season"].setdefault("coins", 0)
    robber["season"].setdefault("kills", 0)
    robber["season"].setdefault("rank", 0)

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

    robber["all_time"]["total_earned"] += steal
    robber["season"]["coins"] += steal
    add_xp(robber, 6)

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
    add_xp(u, 2)

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


@alive_required
@admin_required
async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "❌ <b>Reply karke hi /revive use kar sakte ho</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    reviver_user = update.effective_user
    target_user = update.message.reply_to_message.from_user

    target = await load_user(target_user.id)
    reviver = await load_user(reviver_user.id)

    reviver.setdefault("all_time", {})
    reviver["all_time"].setdefault("duel_wins", 0)
    reviver["all_time"].setdefault("best_streak", 0)
    reviver["all_time"].setdefault("total_earned", 0)

    reviver.setdefault("season", {})
    reviver["season"].setdefault("coins", 0)
    reviver["season"].setdefault("kills", 0)
    reviver["season"].setdefault("rank", 0)

    if not is_dead(target):
        return await update.message.reply_text(
            "❌ <b>Ye user dead nahi hai</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    if int(reviver.get("coins", 0)) < REVIVE_COST:
        return await update.message.reply_text(
            "❌ <b>Revive ke liye enough coins nahi hai</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    reviver["coins"] = int(reviver.get("coins", 0)) - REVIVE_COST
    target["dead_until"] = 0

    add_xp(reviver, 4)

    await asyncio.gather(
        save_user_async(reviver_user.id, reviver),
        save_user_async(target_user.id, target)
    )
    await asyncio.to_thread(save)

    await update.message.reply_text(
        f"❤️ <b>{html.escape(target_user.first_name)} revive ho gaya</b>\n"
        f"💸 <b>Cost:</b> ${fmt(REVIVE_COST)}",
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

    u.setdefault("all_time", {})
    u["all_time"].setdefault("total_earned", 0)

    u.setdefault("season", {})
    u["season"].setdefault("coins", 0)
    u["season"].setdefault("kills", 0)
    u["season"].setdefault("rank", 0)

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
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        text = win_message(update.effective_user, "🪙", result_text, choice_text, win)

        print(
            f"FLIP RESULT | name={user_name} | bet=${fmt(bet)} | pick={choice_text} | result={result_text} | status=WIN | payout=${fmt(win)}"
        )
    else:
        u["coins"] = int(u.get("coins", 0)) - bet
        add_xp(u, 2)
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

    u.setdefault("all_time", {})
    u["all_time"].setdefault("total_earned", 0)

    u.setdefault("season", {})
    u["season"].setdefault("coins", 0)
    u["season"].setdefault("kills", 0)
    u["season"].setdefault("rank", 0)

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
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        text = win_message(update.effective_user, "🎲", str(roll), str(guess), win)
    else:
        u["coins"] -= bet
        add_xp(u, 2)
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

    u.setdefault("all_time", {})
    u["all_time"].setdefault("total_earned", 0)

    u.setdefault("season", {})
    u["season"].setdefault("coins", 0)
    u["season"].setdefault("kills", 0)
    u["season"].setdefault("rank", 0)

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
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        result = "💎💎💎 JACKPOT"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    elif value in [1, 22, 43]:
        win = bet * 3
        u["coins"] += win
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        result = "🔥 Double Match"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    elif value in [16, 32]:
        win = bet * 2
        u["coins"] += win
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        result = "✨ Small Win"
        text = win_message(update.effective_user, "🎰", result, "🎰", win)

    else:
        u["coins"] -= bet
        add_xp(u, 2)
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

    u.setdefault("all_time", {})
    u["all_time"].setdefault("total_earned", 0)

    u.setdefault("season", {})
    u["season"].setdefault("coins", 0)
    u["season"].setdefault("kills", 0)
    u["season"].setdefault("rank", 0)

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
        u["all_time"]["total_earned"] += win
        u["season"]["coins"] += win
        add_xp(u, 4)
        text = win_message(update.effective_user, "🎨", result.upper(), choice.upper(), win)
    else:
        u["coins"] -= bet
        add_xp(u, 2)
        text = lose_message(update.effective_user, "🎨", result.upper(), choice.upper(), bet)

    save_user(update.effective_user.id, u)
    save()

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_to_message_id=update.message.id
    )


@alive_required
@admin_required
async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        return await update.message.reply_text(
            "❌ <b>Usage:</b> /duel &lt;amount&gt;",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    challenger_user = update.effective_user
    chat_id = update.effective_chat.id
    key = get_duel_key(chat_id)

    if key in pending_duels or key in active_duels:
        return await update.message.reply_text(
            "❌ <b>Is chat me already ek duel chal raha hai</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text(
            "❌ <b>Invalid amount</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    if amount <= 0:
        return await update.message.reply_text(
            "❌ <b>Amount 0 se bada hona chahiye</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    if amount > MAX_BET:
        return await update.message.reply_text(
            f"❌ <b>Max duel bet:</b> ${fmt(MAX_BET)}",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    challenger = await load_user(challenger_user.id)

    if int(challenger.get("coins", 0)) < amount:
        return await update.message.reply_text(
            "❌ <b>Not enough coins</b>",
            parse_mode="HTML",
            reply_to_message_id=update.message.id
        )

    pending_duels[key] = {
        "challenger_id": challenger_user.id,
        "challenger_name": challenger_user.first_name,
        "amount": amount
    }

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Accept Duel", callback_data=f"duel_accept:{chat_id}")
    ]])

    await update.message.reply_text(
        f"⚔️ <b>SKILL DUEL CHALLENGE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{html.escape(challenger_user.first_name)}</b> ne <b>${fmt(amount)}</b> ka duel khola hai\n"
        f"🎯 Accept karte hi random skill task aayega\n"
        f"⏳ {DUEL_TIMEOUT} sec ke andar accept karo\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=update.message.id
    )

    asyncio.create_task(expire_pending_duel(context, chat_id))


# =========================
# DUEL HANDLER
# =========================

async def duel_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global jackpot_pool

    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("duel_accept:"):
        return

    chat_id = int(data.split(":")[1])
    key = get_duel_key(chat_id)

    if key not in pending_duels:
        return await query.edit_message_text(
            "❌ <b>Ye duel ab active nahi hai</b>",
            parse_mode="HTML"
        )

    duel = pending_duels[key]
    accepter_user = query.from_user

    if accepter_user.id == duel["challenger_id"]:
        return await query.answer("Apna hi duel accept nahi kar sakte", show_alert=True)

    challenger, accepter = await asyncio.gather(
        load_user(duel["challenger_id"]),
        load_user(accepter_user.id)
    )

    amount = duel["amount"]

    if int(challenger.get("coins", 0)) < amount:
        clear_duel(chat_id)
        return await query.edit_message_text(
            "❌ <b>Challenger ke paas enough coins nahi bache</b>",
            parse_mode="HTML"
        )

    if int(accepter.get("coins", 0)) < amount:
        return await query.answer("Tumhare paas enough coins nahi hain", show_alert=True)

    challenger["coins"] = int(challenger.get("coins", 0)) - amount
    accepter["coins"] = int(accepter.get("coins", 0)) - amount

    pot = amount * 2
    jackpot_bonus = min(jackpot_pool, pot)
    jackpot_pool -= jackpot_bonus
    total_prize = pot + jackpot_bonus

    await asyncio.gather(
        save_user_async(duel["challenger_id"], challenger),
        save_user_async(accepter_user.id, accepter)
    )
    await asyncio.to_thread(save)

    prompt, answer = generate_duel_task()

    pending_duels.pop(key, None)

    active_duels[key] = {
        "challenger_id": duel["challenger_id"],
        "challenger_name": duel["challenger_name"],
        "acceptor_id": accepter_user.id,
        "acceptor_name": accepter_user.first_name,
        "amount": amount,
        "pot": pot,
        "jackpot_bonus": jackpot_bonus,
        "total_prize": total_prize,
        "answer": normalize_duel_answer(answer)
    }

    await query.edit_message_text(
        f"⚔️ <b>DUEL ACCEPTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{html.escape(duel['challenger_name'])}</b> vs <b>{html.escape(accepter_user.first_name)}</b>\n"
        f"💰 <b>Base Prize:</b> ${fmt(pot)}\n"
        f"🎰 <b>Jackpot Boost:</b> ${fmt(jackpot_bonus)}\n"
        f"🏆 <b>Total Prize:</b> ${fmt(total_prize)}\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

    await asyncio.sleep(DUEL_START_DELAY)

    if key not in active_duels:
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🧠 <b>SKILL TASK</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{prompt}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ Jo sabse pehle <b>normal text</b> me sahi jawab bhejega wahi jeetega"
        ),
        parse_mode="HTML"
    )

    asyncio.create_task(expire_active_duel(context, chat_id))


async def duel_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    key = get_duel_key(chat_id)

    if key not in active_duels:
        return

    duel = active_duels[key]
    user_id = update.effective_user.id

    if user_id not in [duel["challenger_id"], duel["acceptor_id"]]:
        return

    user_answer = normalize_duel_answer(update.message.text)

    if user_answer != duel["answer"]:
        return

    winner = await load_user(user_id)
    loser_id = duel["acceptor_id"] if user_id == duel["challenger_id"] else duel["challenger_id"]
    loser = await load_user(loser_id)

    winner.setdefault("all_time", {})
    winner["all_time"].setdefault("duel_wins", 0)
    winner["all_time"].setdefault("best_streak", 0)
    winner["all_time"].setdefault("total_earned", 0)

    winner.setdefault("season", {})
    winner["season"].setdefault("coins", 0)
    winner["season"].setdefault("kills", 0)
    winner["season"].setdefault("rank", 0)

    loser.setdefault("all_time", {})
    loser["all_time"].setdefault("duel_wins", 0)
    loser["all_time"].setdefault("best_streak", 0)
    loser["all_time"].setdefault("total_earned", 0)

    loser.setdefault("season", {})
    loser["season"].setdefault("coins", 0)
    loser["season"].setdefault("kills", 0)
    loser["season"].setdefault("rank", 0)

    winner["coins"] = int(winner.get("coins", 0)) + duel["total_prize"]
    winner["duel_wins"] = int(winner.get("duel_wins", 0)) + 1
    winner["all_time"]["duel_wins"] += 1
    winner["all_time"]["total_earned"] += duel["total_prize"]
    winner["season"]["coins"] += duel["total_prize"]

    add_xp(winner, 10)
    add_xp(loser, 4)

    await asyncio.gather(
        save_user_async(user_id, winner),
        save_user_async(loser_id, loser)
    )
    await asyncio.to_thread(save)

    winner_name = html.escape(update.effective_user.first_name)

    clear_duel(chat_id)

    await update.message.reply_text(
        f"🏆 <b>DUEL WINNER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>{winner_name}</b> ne sabse pehle sahi jawab diya\n"
        f"💰 <b>Prize Won:</b> ${fmt(duel['total_prize'])}\n"
        f"🎰 <b>Jackpot Bonus Included:</b> ${fmt(duel['jackpot_bonus'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━",
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
                cur.execute("""
                    UPDATE users
                    SET 
                        coins = 0,
                        bank = 0,
                        kills = 0,
                        dead_until = 0,
                        protected_until = 0,
                        last_daily = 0,
                        last_rob = 0,
                        last_kill = 0,
                        last_bank_tax = 0,
                        season = %s
                """, (
                    json.dumps({
                        "coins": 0,
                        "kills": 0,
                        "rank": 0
                    }),
                ))
            conn.commit()

        user_cache.clear()

        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_selected_uid", None)
        context.user_data.pop("admin_step", None)

        return await query.edit_message_text(
            "⚙️ <b>PLAYER RESET SUCCESSFUL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ Wallet: Reset\n"
            "❌ Bank: Reset\n"
            "❌ Kills: Reset\n"
            "❌ Protection/Cooldowns: Reset\n"
            "❌ Current Season: Reset\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Level/XP/Badges: Safe\n"
            "✅ All Time: Safe\n"
            "✅ Jackpot: Safe\n"
            "━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )

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

    if step == "enter_amount":
        uid = context.user_data.get("admin_selected_uid")

        if not uid:
            context.user_data.pop("admin_step", None)
            context.user_data.pop("admin_action", None)
            return await update.message.reply_text("❌ No user selected")

        try:
            amount = int(update.message.text.strip())
        except:
            return await update.message.reply_text("❌ Invalid amount")

        user = get_user_fast(uid)
        name = html.escape(user.get("name", "User"))

        if action == "setcoins":
            user["coins"] = amount

        elif action == "addcoins":
            user["coins"] = int(user.get("coins", 0)) + amount

        elif action == "setbank":
            user["bank"] = amount

        elif action == "addbank":
            user["bank"] = int(user.get("bank", 0)) + amount

        else:
            return await update.message.reply_text("❌ Invalid admin action")

        save_user(uid, user)
        await asyncio.to_thread(save)

        context.user_data.pop("admin_step", None)
        context.user_data.pop("admin_selected_uid", None)
        context.user_data.pop("admin_action", None)

        return await update.message.reply_text(
            f"✅ Done\n👤 {name}\n💰 Amount: ${fmt(amount)}"
            )


# =========================
# APP START
# =========================

print("TOKEN FOUND:", bool(TOKEN))

migrate_db()

app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()

print("APP BUILT")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))

app.add_handler(CommandHandler("profile", profile_command))
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

# 🔥 DUEL SYSTEM
app.add_handler(CommandHandler("duel", duel))
app.add_handler(CallbackQueryHandler(duel_accept_callback, pattern=r"^duel_accept:"))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), duel_answer_handler), group=0)

# NEW OWNER PANEL
app.add_handler(CommandHandler("panel", panel))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin:"))

# ALWAYS LAST
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_panel_text), group=1)

print("God Economy Bot started...")
print("STARTING POLLING")

async def clear(app):
    await app.bot.delete_webhook(drop_pending_updates=True)

app.post_init = clear

app.run_polling(drop_pending_updates=True)
