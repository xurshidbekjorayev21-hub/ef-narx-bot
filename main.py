import os
import sqlite3
import logging
from statistics import median
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Optional; SQLite used in this starter if not configured.

# Conversation states
PLATFORM, EPIC, BIGTIME, SHOWTIME, GOOGLE_PLAY, GAME_CENTER, KONAMI_ID, MINUS_COINS, COINS, PHOTOS = range(10)

DB_PATH = os.getenv("SQLITE_PATH", "ef_narx.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                epic INTEGER NOT NULL,
                bigtime INTEGER NOT NULL,
                showtime INTEGER NOT NULL,
                google_play TEXT NOT NULL,
                game_center TEXT NOT NULL,
                konami_id TEXT NOT NULL,
                minus_coins TEXT NOT NULL,
                coins INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                epic INTEGER NOT NULL,
                bigtime INTEGER NOT NULL,
                showtime INTEGER NOT NULL,
                price_uzs INTEGER NOT NULL,
                source TEXT DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def kb(options):
    return ReplyKeyboardMarkup([[x] for x in options], resize_keyboard=True, one_time_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Assalomu alaykum! Bu — eF Narx Bot.\n\n"
        "Akkauntingizni dastlabki baholash uchun /bahola buyrug‘ini bosing.\n"
        "Bot hozir sinov versiyasida: bozor narxlari bazasi yetarli bo‘lmasa, aniq summa to‘qib chiqarmaydi.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Buyruqlar:\n"
        "/start — botni boshlash\n"
        "/bahola — akkauntni baholash\n"
        "/cancel — baholashni bekor qilish\n"
        "/narx — narxlar bazasi haqida\n\n"
        "Administrator uchun:\n"
        "/addsale platform epic bigtime showtime narx_so'm\n"
        "Misol: /addsale android 10 2 3 250000\n\n"
        "Faqat haqiqiy sotuv narxlarini kiriting; e'lon narxlarini haqiqiy sotuv deb belgilamang."
    )


async def narx_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM comps").fetchone()[0]
    await update.message.reply_text(
        f"📊 Narxlar bazasida hozir {count} ta taqqoslash yozuvi bor.\n"
        "Yetarli va o‘xshash akkauntlar ma’lumoti bo‘lmasa, bot narxni taxmin qilib yozmaydi."
    )


async def bahola(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "1/9. Akkaunt qaysi platformada?",
        reply_markup=kb(["Android", "iPhone"]),
    )
    return PLATFORM


async def platform_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip().lower()
    if v not in ("android", "iphone"):
        await update.message.reply_text("Iltimos, Android yoki iPhone ni tanlang.", reply_markup=kb(["Android", "iPhone"]))
        return PLATFORM
    context.user_data["platform"] = v
    await update.message.reply_text("2/9. Nechta Epic futbolchi bor? Faqat son yozing.", reply_markup=ReplyKeyboardRemove())
    return EPIC


async def int_step(update: Update, context: ContextTypes.DEFAULT_TYPE, key, next_state, prompt, minimum=0, maximum=10000):
    try:
        n = int(update.message.text.strip().replace(" ", ""))
        if not minimum <= n <= maximum:
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"Iltimos, {minimum}–{maximum} oralig‘idagi butun sonni kiriting.")
        return next_state
    context.user_data[key] = n
    await update.message.reply_text(prompt)
    return next_state


async def epic_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 0 <= n <= 1000: raise ValueError
    except ValueError:
        await update.message.reply_text("Epic sonini 0–1000 oralig‘ida butun son bilan kiriting.")
        return EPIC
    context.user_data["epic"] = n
    await update.message.reply_text("3/9. Nechta Big Time futbolchi bor? Son kiriting.")
    return BIGTIME


async def bigtime_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 0 <= n <= 1000: raise ValueError
    except ValueError:
        await update.message.reply_text("Big Time sonini 0–1000 oralig‘ida kiriting.")
        return BIGTIME
    context.user_data["bigtime"] = n
    await update.message.reply_text("4/9. Nechta Show Time futbolchi bor? Son kiriting.")
    return SHOWTIME


async def showtime_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 0 <= n <= 1000: raise ValueError
    except ValueError:
        await update.message.reply_text("Show Time sonini 0–1000 oralig‘ida kiriting.")
        return SHOWTIME
    context.user_data["showtime"] = n
    await update.message.reply_text("5/9. Google Play akkauntga ulanganmi?", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
    return GOOGLE_PLAY


async def google_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    if v not in ("Ha", "Yo‘q", "Bilmayman"):
        await update.message.reply_text("Ha, Yo‘q yoki Bilmayman variantidan tanlang.", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
        return GOOGLE_PLAY
    context.user_data["google_play"] = v
    await update.message.reply_text("6/9. Game Center ulanganmi?", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
    return GAME_CENTER


async def gamecenter_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    if v not in ("Ha", "Yo‘q", "Bilmayman"):
        await update.message.reply_text("Ha, Yo‘q yoki Bilmayman variantidan tanlang.", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
        return GAME_CENTER
    context.user_data["game_center"] = v
    await update.message.reply_text("7/9. KONAMI ID ulanganmi?", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
    return KONAMI_ID


async def konami_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    if v not in ("Ha", "Yo‘q", "Bilmayman"):
        await update.message.reply_text("Ha, Yo‘q yoki Bilmayman variantidan tanlang.", reply_markup=kb(["Ha", "Yo‘q", "Bilmayman"]))
        return KONAMI_ID
    context.user_data["konami_id"] = v
    await update.message.reply_text("8/9. Akkauntda minus Coin bormi?", reply_markup=kb(["Bor", "Yo‘q", "Bilmayman"]))
    return MINUS_COINS


async def minus_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip()
    if v not in ("Bor", "Yo‘q", "Bilmayman"):
        await update.message.reply_text("Bor, Yo‘q yoki Bilmayman variantidan tanlang.", reply_markup=kb(["Bor", "Yo‘q", "Bilmayman"]))
        return MINUS_COINS
    context.user_data["minus_coins"] = v
    await update.message.reply_text("9/9. Akkauntda nechta Coin bor? Son kiriting. Bilmasangiz 0 yozing.", reply_markup=ReplyKeyboardRemove())
    return COINS


async def estimate(platform, epic, bigtime, showtime):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM comps WHERE platform = ?",
            (platform,),
        ).fetchall()
    # Use nearest comps with weighted distance. Only estimate when at least 3 reasonably similar records exist.
    ranked = []
    for r in rows:
        distance = abs(r["epic"] - epic) + 2 * abs(r["bigtime"] - bigtime) + abs(r["showtime"] - showtime)
        ranked.append((distance, r["price_uzs"]))
    ranked.sort(key=lambda x: x[0])
    close = [price for distance, price in ranked[:7] if distance <= max(5, int((epic + bigtime + showtime + 1) * 0.35))]
    if len(close) < 3:
        return None, len(rows)
    base = int(median(close))
    return (int(base * 0.8), base, int(base * 1.2)), len(rows)


async def coins_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip().replace(" ", ""))
        if not 0 <= n <= 1000000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Coin sonini 0–1 000 000 oralig‘ida kiriting.")
        return COINS

    d = context.user_data
    d["coins"] = n
    with db() as conn:
        conn.execute("""
            INSERT INTO valuations
            (user_id, platform, epic, bigtime, showtime, google_play, game_center, konami_id, minus_coins, coins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            update.effective_user.id, d["platform"], d["epic"], d["bigtime"], d["showtime"],
            d["google_play"], d["game_center"], d["konami_id"], d["minus_coins"], d["coins"]
        ))

    prices, count = await estimate(d["platform"], d["epic"], d["bigtime"], d["showtime"])
    text = (
        "⚽ eF NARX BOT — BAHOLASH HISOBOTI\n\n"
        f"📱 Platforma: {d['platform'].title()}\n"
        f"💎 Epic: {d['epic']} ta\n"
        f"🔥 Big Time: {d['bigtime']} ta\n"
        f"⭐ Show Time: {d['showtime']} ta\n"
        f"🎮 Google Play: {d['google_play']}\n"
        f"🍎 Game Center: {d['game_center']}\n"
        f"🆔 KONAMI ID: {d['konami_id']}\n"
        f"🪙 Minus Coin: {d['minus_coins']}\n"
        f"💰 Coin: {d['coins']}\n\n"
    )
    if prices:
        low, mid, high = prices
        text += (
            "💵 TAQQOSIY NARXLAR (UZS):\n"
            f"🔴 Tez sotish: {low:,} so‘m\n"
            f"🟡 Tavsiya etiladigan: {mid:,} so‘m\n"
            f"🟢 Yuqori narx: {high:,} so‘m\n\n"
            "Narx o‘xshash akkauntlar bo‘yicha avtomatik taqqoslandi; bu kafolatlangan sotuv narxi emas."
        ).replace(",", " ")
    else:
        text += (
            "⚠️ Hozircha ishonchli narx chiqarish uchun ma’lumot yetarli emas.\n"
            f"Bu platforma bo‘yicha bazada {count} ta taqqoslash yozuvi bor.\n"
            "Bozor bazasi to‘ldirilgach, bot narx chiqaradi. Hozircha soxta narx ko‘rsatmaymiz."
        )
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Yana baholash uchun /bahola buyrug‘ini bosing.")
    return ConversationHandler.END


async def addsale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bu buyruq faqat bot administratori uchun.")
        return
    try:
        platform = context.args[0].lower()
        epic, bigtime, showtime, price = map(int, context.args[1:5])
        if platform not in ("android", "iphone") or min(epic, bigtime, showtime) < 0 or price <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Format: /addsale platform epic bigtime showtime narx_so'm\n"
            "Misol: /addsale android 10 2 3 250000"
        )
        return
    with db() as conn:
        conn.execute(
            "INSERT INTO comps(platform, epic, bigtime, showtime, price_uzs) VALUES (?, ?, ?, ?, ?)",
            (platform, epic, bigtime, showtime, price),
        )
    await update.message.reply_text("✅ Taqqoslash narxi bazaga qo‘shildi. Bu haqiqiy sotuv narxi ekanini tekshiring.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Baholash bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable sozlanmagan.")
    init_db()
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("bahola", bahola)],
        states={
            PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, platform_step)],
            EPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, epic_step)],
            BIGTIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bigtime_step)],
            SHOWTIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, showtime_step)],
            GOOGLE_PLAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, google_step)],
            GAME_CENTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gamecenter_step)],
            KONAMI_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, konami_step)],
            MINUS_COINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, minus_step)],
            COINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, coins_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("narx", narx_cmd))
    app.add_handler(CommandHandler("addsale", addsale))
    app.add_handler(conv)
    log.info("eF Narx Bot ishga tushmoqda.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
