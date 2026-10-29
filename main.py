import os
import json
import base64
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from statistics import median

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, CallbackQueryHandler,
    ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("SQLITE_PATH", "ef_narx.db")
LISTINGS_PATH = os.getenv("LISTINGS_PATH", "listings.jsonl")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
VISION_MODEL = os.getenv("VISION_MODEL", "deepseek-flash")

# States: photo first, then the account questions.
PHOTO, PLATFORM, EPIC, BIGTIME, SHOWTIME, GOOGLE_PLAY, GAME_CENTER, KONAMI_ID, MINUS_COINS, COINS = range(10)


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
                team_strength INTEGER,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_cooldowns (
                user_id INTEGER PRIMARY KEY,
                last_valuation_at TEXT,
                last_rejoined_at TEXT
            )
        """)
        # Upgrade an older database without losing existing records.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(valuations)").fetchall()}
        if "team_strength" not in cols:
            conn.execute("ALTER TABLE valuations ADD COLUMN team_strength INTEGER")


def kb(options):
    return ReplyKeyboardMarkup([[x] for x in options], resize_keyboard=True, one_time_keyboard=True)


def classify_ef_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Send an eFootball screenshot to DeepSeek Vision using Python's built-in HTTP client."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY sozlanmagan")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    prompt = (
        "You are a strict image gate for an eFootball account valuation Telegram bot. "
        "Decide whether the image clearly shows the eFootball (Konami football game) in-game UI, "
        "preferably a team/squad/player list/account screen. Do not accept real-world football photos, "
        "other games, memes, pets, selfies, logos alone, or unrelated screenshots. If uncertain, set "
        "is_efootball=false. Read visible team/collective strength and coin count only if legible; "
        "do not guess. Return ONLY valid JSON with keys: is_efootball (boolean), confidence (number 0-1), "
        "team_strength (integer or null), coins (integer or null), epic_count (integer or null), "
        "bigtime_count (integer or null), showtime_count (integer or null), reason (short Uzbek sentence)."
    )
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "max_tokens": 350,
        "thinking": {"type": "disabled"},
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + DEEPSEEK_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {details}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"DeepSeek API ulanish xatosi: {exc}") from None

    choices = result.get("choices") or []
    if not choices:
        raise ValueError("DeepSeek javobida choices topilmadi")
    raw = choices[0].get("message", {}).get("content") or ""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(raw)
    if not isinstance(data, dict) or "is_efootball" not in data:
        raise ValueError("Vision javobi noto‘g‘ri formatda")
    return data


def load_recent_listings(days=30):
    """Read JSONL and dynamically keep only rows from the last N days."""
    path = LISTINGS_PATH
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    if not os.path.isfile(path):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    raw_date = row.get("date")
                    if not raw_date:
                        continue
                    dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt.astimezone(timezone.utc) < cutoff:
                        continue
                    price = row.get("price_uzs")
                    if (
                        isinstance(price, (int, float))
                        and not isinstance(price, bool)
                        and 10000 <= price <= 10000000
                        and row.get("price_needs_review") is False
                    ):
                        rows.append(row)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
    except OSError:
        log.exception("E’lonlar faylini o‘qib bo‘lmadi")
    return rows


def estimate_from_recent_listings(team_strength, coins):
    """Approximate from asking prices in the rolling 30-day window, not confirmed sale prices."""
    rows = load_recent_listings(30)
    # Team strength is the strongest usable shared feature currently parsed from the channel posts.
    if team_strength is None:
        return None, len(rows), 0
    ranked = []
    for row in rows:
        strength = row.get("collective_strength")
        if not isinstance(strength, (int, float)):
            continue
        diff = abs(int(strength) - int(team_strength))
        if diff > 80:
            continue
        score = diff / 40.0
        listing_coins = row.get("coins")
        if isinstance(listing_coins, (int, float)) and coins is not None:
            # Coins are useful but may be missing or inconsistently described in posts.
            denominator = max(100, int(coins), int(listing_coins))
            coin_diff = abs(int(listing_coins) - int(coins)) / denominator
            if coin_diff > 0.75:
                continue
            score += coin_diff
        ranked.append((score, int(row["price_uzs"])))
    ranked.sort(key=lambda x: x[0])
    selected = [price for _, price in ranked[:15]]
    if len(selected) < 3:
        return None, len(rows), len(selected)
    mid = int(median(selected))
    return (int(mid * 0.8), mid, int(mid * 1.2)), len(rows), len(selected)




REQUIRED_CHATS = [
    ("@Retro_eFootball", "https://t.me/Retro_eFootball", "📢 Retro eFootball"),
    ("@eFretro_group", "https://t.me/eFretro_group", "👥 eFretro guruhi"),
    ("@Retro_eFshop", "https://t.me/Retro_eFshop", "🛒 Retro eFshop"),
]

async def subscription_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return False

    missing = []
    for chat, url, title in REQUIRED_CHATS:
        try:
            member = await context.bot.get_chat_member(chat, user.id)
            if member.status not in ("member", "administrator", "creator"):
                missing.append((url, title))
        except Exception as e:
            print(f"Obuna tekshiruvi xatosi ({chat}): {e}")
            missing.append((url, title))

    if not missing:
        return True

    keyboard = [
        [InlineKeyboardButton(title, url=url)]
        for url, title in missing
    ]
    keyboard.append([
        InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")
    ])

    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Botdan foydalanish uchun quyidagi uchala kanal/guruhga ham a’zo bo‘ling. "
            "Bittasidan chiqsangiz, foydalanish cheklanadi.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return False

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await subscription_check(update, context):
        await query.message.reply_text(
            "✅ Uchala obuna ham tasdiqlandi! Endi botdan foydalanishingiz mumkin."
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await subscription_check(update, context):
        return
    await update.message.reply_text(
        "⚽ Assalomu alaykum! Bu — eF Narx Bot.\n\n"
        "Akkauntni baholash uchun /bahola buyrug‘ini bosing. Avval eFootball jamoangizning "
        "o‘yin ichidagi skrinshotini yuborish so‘raladi. Boshqa rasmlar qabul qilinmaydi.\n\n"
        "Narx faqat yetarli o‘xshash ma’lumot bo‘lsa ko‘rsatiladi; bu kafolatlangan sotuv narxi emas.",
        reply_markup=kb(["💰 Akkauntni baholash"]),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Buyruqlar:\n/start — botni boshlash\n/bahola — akkauntni baholash\n"
        "/cancel — bekor qilish\n/narx — mavjud narxlar ma’lumoti\n\n"
        "Administrator uchun: /addsale platform epic bigtime showtime narx_so'm\n"
        "Misol: /addsale android 10 2 3 250000\n"
        "E’lon narxlari haqiqiy sotuv narxi degani emas."
    )


async def narx_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recent = load_recent_listings(30)
    with db() as conn:
        manual_count = conn.execute("SELECT COUNT(*) FROM comps").fetchone()[0]
    priced = sum(1 for r in recent if r.get("price_uzs"))
    await update.message.reply_text(
        "📊 Narx tahlili holati\n"
        f"• Oxirgi 30 kun ichidagi narxli e’lonlar: {priced} ta\n"
        f"• Qo‘lda kiritilgan taqqoslashlar: {manual_count} ta\n"
        "Bot eski e’lonlarni har bir hisoblash paytida avtomatik chiqarib tashlaydi."
    )


async def bahola(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = datetime.now(timezone.utc)

    with db() as conn:
        row = conn.execute(
            "SELECT last_valuation_at FROM user_cooldowns WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row and row["last_valuation_at"]:
        last = datetime.fromisoformat(row["last_valuation_at"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        remaining = 10800 - (now - last).total_seconds()
        if remaining > 0:
            minutes = int(remaining // 60) + 1
            await update.effective_message.reply_text(
                f"⏳ Akkauntingiz yaqinda baholangan. "
                f"Qayta baholash uchun yana {minutes} daqiqa kuting."
            )
            return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "📸 Avval eFootball o‘yinidagi jamoangiz/akkauntingiz ekranining skrinshotini yuboring.\n\n"
        "Boshqa o‘yin, oddiy surat yoki tushunarsiz rasm qabul qilinmaydi. Rasm tekshiruvi uchun "
        "bir necha soniya ketishi mumkin."
    )
    return PHOTO


async def photo_text_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Iltimos, matn emas, eFootball o‘yinidan olingan skrinshotni rasm sifatida yuboring.")
    return PHOTO


async def photo_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not DEEPSEEK_API_KEY:
        await update.message.reply_text(
            "⚠️ Rasm tekshiruvi hali sozlanmagan: bot egasi DEEPSEEK_API_KEY ni server muhitiga kiritishi kerak."
        )
        return ConversationHandler.END
    await update.message.reply_text("🔎 Rasmni tekshiryapman, biroz kuting…")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await tg_file.download_as_bytearray())
        result = classify_ef_image(image_bytes, "image/jpeg")
    except Exception as exc:
        log.exception("Rasm tekshirishda xato")
        if "DEEPSEEK_API_KEY" in str(exc):
            msg = "⚠️ Rasm tekshiruvi sozlanmagan. Bot administratori API kalitini sozlashi kerak."
        else:
            msg = "⚠️ Rasmni tekshira olmadim. Iltimos, qayta urinib ko‘ring yoki aniqroq skrinshot yuboring."
        await update.message.reply_text(msg)
        return PHOTO

    is_valid = bool(result.get("is_efootball")) and float(result.get("confidence", 0)) >= 0.75
    if not is_valid:
        await update.message.reply_text(
            "❌ Bu eFootball jamoasi ekrani ekanini ishonchli aniqlay olmadim.\n"
            "Iltimos, eFootball o‘yinini ochib, jamoa yoki futbolchilar ro‘yxati ko‘rinadigan ekranining "
            "aniq skrinshotini yuboring."
        )
        return PHOTO

    context.user_data["team_strength"] = result.get("team_strength")
    if result.get("coins") is not None:
        context.user_data["coins"] = result.get("coins")
    for k in ("epic_count", "bigtime_count", "showtime_count"):
        if result.get(k) is not None:
            context.user_data[k] = result[k]

    strength_text = f"\n📈 Rasmda jamoa kuchi: {result['team_strength']}" if result.get("team_strength") else ""
    await update.message.reply_text(
        "✅ Rasm eFootball o‘yiniga tegishli ko‘rinadi. Endi akkaunt ma’lumotlarini aniqlashtiramiz."
        + strength_text + "\n\n1/9. Akkaunt qaysi platformada?",
        reply_markup=kb(["Android", "iPhone"]),
    )
    return PLATFORM


async def platform_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.text.strip().lower()
    if v not in ("android", "iphone"):
        await update.message.reply_text("Iltimos, Android yoki iPhone ni tanlang.", reply_markup=kb(["Android", "iPhone"]))
        return PLATFORM
    context.user_data["platform"] = v
    prompt = "2/9. Nechta Epic futbolchi bor? Faqat son yozing."
    if context.user_data.get("epic_count") is not None:
        prompt += f" (Rasm tahlilida taxminan {context.user_data['epic_count']} ta deb ko‘rindi; xohlasangiz shu sonni kiriting.)"
    await update.message.reply_text(prompt, reply_markup=ReplyKeyboardRemove())
    return EPIC


async def epic_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 0 <= n <= 1000: raise ValueError
    except ValueError:
        await update.message.reply_text("Epic sonini 0–1000 oralig‘ida kiriting.")
        return EPIC
    context.user_data["epic"] = n
    prompt = "3/9. Nechta Big Time futbolchi bor? Son kiriting."
    if context.user_data.get("bigtime_count") is not None:
        prompt += f" (Rasm tahlilida taxminan {context.user_data['bigtime_count']} ta deb ko‘rindi.)"
    await update.message.reply_text(prompt)
    return BIGTIME


async def bigtime_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 0 <= n <= 1000: raise ValueError
    except ValueError:
        await update.message.reply_text("Big Time sonini 0–1000 oralig‘ida kiriting.")
        return BIGTIME
    context.user_data["bigtime"] = n
    prompt = "4/9. Nechta Show Time futbolchi bor? Son kiriting."
    if context.user_data.get("showtime_count") is not None:
        prompt += f" (Rasm tahlilida taxminan {context.user_data['showtime_count']} ta deb ko‘rindi.)"
    await update.message.reply_text(prompt)
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
    if context.user_data.get("coins") is not None:
        await update.message.reply_text(
            f"9/9. Rasmda taxminan {context.user_data['coins']} Coin ko‘rindi. To‘g‘ri bo‘lsa shu sonni, aks holda to‘g‘ri sonni kiriting.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text("9/9. Akkauntda nechta Coin bor? Son kiriting. Bilmasangiz 0 yozing.", reply_markup=ReplyKeyboardRemove())
    return COINS


async def estimate_manual(platform, epic, bigtime, showtime):
    with db() as conn:
        rows = conn.execute("SELECT * FROM comps WHERE platform = ?", (platform,)).fetchall()
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
        if not 0 <= n <= 1000000: raise ValueError
    except ValueError:
        await update.message.reply_text("Coin sonini 0–1 000 000 oralig‘ida kiriting.")
        return COINS
    d = context.user_data
    d["coins"] = n
    with db() as conn:
        conn.execute("""
            INSERT INTO valuations
            (user_id, platform, epic, bigtime, showtime, google_play, game_center, konami_id, minus_coins, coins, team_strength)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            update.effective_user.id, d["platform"], d["epic"], d["bigtime"], d["showtime"],
            d["google_play"], d["game_center"], d["konami_id"], d["minus_coins"], d["coins"], d.get("team_strength")
        ))

    prices, recent_total, comparable_count = estimate_from_recent_listings(d.get("team_strength"), d["coins"])
    if not prices:
        prices, manual_count = await estimate_manual(d["platform"], d["epic"], d["bigtime"], d["showtime"])

    text = ""
    if prices:
        low, mid, high = prices
        text += (
            "💵 TAXMINIY NARX ORALIG‘I (UZS):\n"
            f"🔴 Tez sotish: {low:,} so‘m\n"
            f"🟡 O‘rtacha: {mid:,} so‘m\n"
            f"🟢 Yuqoriroq: {high:,} so‘m\n\n"
            "🇺🇿 Bot O‘zbekiston eFootball akkauntlari bozorini tahlil qilgan holda narx belgilaydi. Narxlar o‘ylab topilmaydi!"
        ).replace(",", " ")
    else:
        text += (
            "⚠️ Hozircha ishonchli narx chiqarish uchun o‘xshash ma’lumot yetarli emas.\n"
            "Rasmda jamoa kuchi aniq ko‘rinmasa yoki o‘xshash e’lonlar kam bo‘lsa, bot narxni to‘qib chiqarmaydi."
        )
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO user_cooldowns (user_id, last_valuation_at)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_valuation_at = excluded.last_valuation_at
            """,
            (update.effective_user.id, datetime.now(timezone.utc).isoformat()),
        )

    await update.message.reply_text(
        "💰 Akkauntni baholash",
        reply_markup=kb(["💰 Akkauntni baholash"]),
    )
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
        await update.message.reply_text("Format: /addsale platform epic bigtime showtime narx_so'm\nMisol: /addsale android 10 2 3 250000")
        return
    with db() as conn:
        conn.execute(
            "INSERT INTO comps(platform, epic, bigtime, showtime, price_uzs) VALUES (?, ?, ?, ?, ?)",
            (platform, epic, bigtime, showtime, price),
        )
    await update.message.reply_text("✅ Taqqoslash yozuvi qo‘shildi. Haqiqiy sotuv narxi ekanini tekshiring.")


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
        entry_points=[CommandHandler("bahola", bahola), MessageHandler(filters.Regex("^💰 Akkauntni baholash$"), bahola)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO, photo_step), MessageHandler(filters.TEXT & ~filters.COMMAND, photo_text_step)],
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
    app.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("narx", narx_cmd))
    app.add_handler(CommandHandler("addsale", addsale))
    app.add_handler(conv)
    log.info("eF Narx Bot ishga tushmoqda.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
