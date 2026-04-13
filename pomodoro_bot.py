
"""
Pomodoro Tracker Bot
====================
Setup:
1. Create a bot via @BotFather and copy the token
2. Link a Discussion Group to your channel (Channel Settings > Discussion)
3. Add the bot to the discussion group as an ADMIN
4. pip install python-telegram-bot apscheduler
5. Set BOT_TOKEN and CHANNEL_ID below, then run: python pomodoro_bot.py

How it works:
- Members comment on channel posts with tomato emojis to log pomodoros
- Bot counts them automatically
- Daily summary auto-posts at 23:00 every day
- Weekly summary auto-posts every Sunday at 23:30
"""

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# CONFIG

BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"       # from @BotFather
CHANNEL_ID = "@your_channel_username"    # e.g. "@myproductivitychannel"
SUMMARY_HOUR   = 23   # auto-post daily summary at 23:00
SUMMARY_MINUTE = 0
DATA_FILE = "pomodoro_data.json"

# LOGGING────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# DATA HELPERS───────────────────────────────────────────────────────────

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"daily": {}, "users": {}}   # users: {id: display_name}

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def week_keys() -> list[str]:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

def count_tomatoes(text: str) -> int:
    return text.count("🍅")

def current_hour_key() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H")

def build_leaderboard(day_data: dict, users: dict, title: str) -> str:
    if not day_data:
        return f"{title}\n\nNo tomatoes recorded yet 😴"

    sorted_users = sorted(day_data.items(), key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = [title, ""]

    for i, (uid, tomatoes) in enumerate(sorted_users):
        name = users.get(uid, f"User {uid}")
        medal = medals[i] if i < 3 else f"{i+1}."
        bar = "🍅" * min(tomatoes, 20)   # cap bar display at 20 for readability
        extra = f"+{tomatoes - 20}" if tomatoes > 20 else ""
        lines.append(f"{medal} {name} — {tomatoes} 🍅\n    {bar}{extra}")

    total = sum(day_data.values())
    lines += ["", f"━━━━━━━━━━━━━━━━━━━━", f"Group total: {total} 🍅 ({total * 25} min of focus 🔥)"]
    return "\n".join(lines)

# MESSAGE HANDLER────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    tomatoes = count_tomatoes(msg.text)
    if tomatoes == 0:
        return

    data = load_data()
    uid  = str(msg.from_user.id)
    name = msg.from_user.full_name or msg.from_user.username or f"User {uid}"
    key  = today_key()
    hour_key = current_hour_key()

    # ── Hourly cooldown check ──────────────────────────────────────────────
    last_submission = data.get("last_submission", {}).get(uid)
    if last_submission == hour_key:
        next_hour = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0)
        wait_min  = int((next_hour - datetime.now()).seconds / 60)
        await msg.reply_text(
            f"⏳ {name}, you already logged this hour!\n"
            f"Next submission available in ~{wait_min} min 🕐"
        )
        return
    # ──────────────────────────────────────────────────────────────────────

    # Store user display name
    data["users"][uid] = name

    # Add to today's count
    if key not in data["daily"]:
        data["daily"][key] = {}
    data["daily"][key][uid] = data["daily"][key].get(uid, 0) + tomatoes

    # Record this hour as used
    if "last_submission" not in data:
        data["last_submission"] = {}
    data["last_submission"][uid] = hour_key

    save_data(data)

    total_today = data["daily"][key][uid]
    await msg.reply_text(
        f"Got it {name}! +{tomatoes} 🍅 logged\n"
        f"Your total today: {total_today} 🍅 = {total_today * 25} min of focus 💪"
    )

# COMMANDS───────────────────────────────────────────────────────────────

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    key  = today_key()
    day_data = data["daily"].get(key, {})
    text = build_leaderboard(day_data, data["users"], f"📊 Today's Pomodoros — {key}")
    await update.message.reply_text(text)

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data    = load_data()
    keys    = week_keys()
    totals  = defaultdict(int)

    for k in keys:
        for uid, count in data["daily"].get(k, {}).items():
            totals[uid] += count

    week_start = keys[0]
    text = build_leaderboard(dict(totals), data["users"], f"📅 Weekly Summary — w/o {week_start}")
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍅 *Pomodoro Tracker Bot*\n\n"
        "Just send 🍅 emojis in the comments to log your sessions!\n\n"
        "*Commands:*\n"
        "/today — today's leaderboard\n"
        "/weekly — this week's totals\n"
        "/help — show this message",
        parse_mode="Markdown"
    )

# SCHEDULED POSTS────────────────────────────────────────────────────────

async def post_daily_summary(bot: Bot):
    data     = load_data()
    key      = today_key()
    day_data = data["daily"].get(key, {})
    text     = build_leaderboard(day_data, data["users"], f"🌙 Daily Summary — {key}")
    await bot.send_message(chat_id=CHANNEL_ID, text=text)
    log.info(f"Daily summary posted for {key}")

async def post_weekly_summary(bot: Bot):
    data   = load_data()
    keys   = week_keys()
    totals = defaultdict(int)

    for k in keys:
        for uid, count in data["daily"].get(k, {}).items():
            totals[uid] += count

    text = build_leaderboard(dict(totals), data["users"], f"🏆 Weekly Champion — w/o {keys[0]}")
    await bot.send_message(chat_id=CHANNEL_ID, text=text)
    log.info("Weekly summary posted")

# MAIN───────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("help",   cmd_help))

    async def post_init(application):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            post_daily_summary,
            trigger="cron",
            hour=SUMMARY_HOUR,
            minute=SUMMARY_MINUTE,
            args=[application.bot]
        )
        scheduler.add_job(
            post_weekly_summary,
            trigger="cron",
            day_of_week="sun",
            hour=23,
            minute=30,
            args=[application.bot]
        )
        scheduler.start()
        log.info("Pomodoro bot is running...")

    app.post_init = post_init
    app.run_polling()

if __name__ == "__main__":
    main()
