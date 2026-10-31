import os
import sqlite3
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

log = logging.getLogger(__name__)
DB_PATH = os.getenv("MATCH_DB_PATH", "match_finder.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PLATFORMS = {"📱 Mobile": "mobile", "🎮 Console": "console"}
MODES = {"🤝 Do‘stona": "friendly", "🏆 Reytingli": "competitive"}
DIVISIONS = ["1-divizion", "2-divizion", "3-divizion", "4-divizion", "5-divizion"]
REGIONS = ["🇺🇿 O‘zbekiston", "🌍 Boshqa"]
PROFILE_NAME, PROFILE_PLATFORM, PROFILE_DIVISION, PROFILE_REGION, QUEUE_SCORE = range(5)

RULES = (
    "⚠️ UZ MATCH FINDER QOIDALARI\n\n"
    "• Soxta natija, ataylab yutqazish va reytingni kelishib oshirish taqiqlanadi.\n"
    "• Soxta akkauntlar va boshqa foydalanuvchini aldash taqiqlanadi.\n"
    "• Shubhali holatlarda ochkolar bekor qilinishi, vaqtinchalik cheklov yoki blok qo‘llanishi mumkin.\n"
    "• Natijani bir o‘yinchi kiritadi, ikkinchisi tasdiqlaydi.\n"
    "• O‘yin natijasi eFootball bilan avtomatik tekshirilmaydi; tasdiqlash foydalanuvchilar zimmasida.\n"
    "• Do‘stona o‘yin reytingga ta’sir qilmaydi.\n\n"
    "Davom etish orqali qoidalarga rozilik bildirasiz."
)

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_match_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mf_users(
            user_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '', division TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '', rating REAL NOT NULL DEFAULT 0,
            rules_ok INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mf_queue(
            user_id INTEGER PRIMARY KEY, mode TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mf_matches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1 INTEGER NOT NULL, player2 INTEGER NOT NULL,
            mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'invited',
            reporter INTEGER, p1_score INTEGER, p2_score INTEGER,
            created_at TEXT NOT NULL, confirmed_by INTEGER,
            UNIQUE(player1, player2, status)
        );
        CREATE TABLE IF NOT EXISTS mf_pair_history(
            user_low INTEGER NOT NULL, user_high INTEGER NOT NULL,
            last_played TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(user_low,user_high)
        );
        """)
        # Add columns safely for databases created by earlier prototype versions.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(mf_matches)")}
        if "reporter" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN reporter INTEGER")
        if "p1_score" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN p1_score INTEGER")
        if "p2_score" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN p2_score INTEGER")
        if "confirmed_by" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN confirmed_by INTEGER")
        if "host_id" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN host_id INTEGER")
        if "room_id" not in cols:
            c.execute("ALTER TABLE mf_matches ADD COLUMN room_id TEXT")

def user_row(uid):
    with conn() as c:
        return c.execute("SELECT * FROM mf_users WHERE user_id=?", (uid,)).fetchone()

def main_kb():
    return ReplyKeyboardMarkup(
        [["⚽ UZ MATCH FINDER"], ["💰 Akkauntni baholash"]],
        resize_keyboard=True
    )

def match_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Profilim", callback_data="mf:profile")],
        [InlineKeyboardButton("🔎 Raqib topish", callback_data="mf:find")],
        [InlineKeyboardButton("🏆 TOP 10", callback_data="mf:rating")],
        [InlineKeyboardButton("📖 Qoidalar", callback_data="mf:rules")],
    ])

async def open_match_finder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = user_row(uid)
    if not row or not row["rules_ok"]:
        await update.effective_message.reply_text(
            RULES,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Qabul qilaman", callback_data="mf:accept_rules")],
                [InlineKeyboardButton("❌ Chiqish", callback_data="mf:close")],
            ])
        )
        return
    await update.effective_message.reply_text("⚽ UZ MATCH FINDER", reply_markup=match_menu())

async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await open_match_finder(update, context)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

    if data == "mf:close":
        await q.edit_message_text("UZ MATCH FINDER yopildi.")
        return
    if data == "mf:accept_rules":
        with conn() as c:
            c.execute("INSERT INTO mf_users(user_id,display_name,rules_ok) VALUES(?,?,1) "
                      "ON CONFLICT(user_id) DO UPDATE SET rules_ok=1",
                      (uid, q.from_user.full_name or "Player"))
        await q.edit_message_text(
            "Qoidalar qabul qilindi. Avval profilingizni sozlang.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 Profil yaratish", callback_data="mf:profile")]])
        )
        return
    row = user_row(uid)
    if data == "mf:rules":
        await q.edit_message_text(RULES, reply_markup=match_menu())
    elif data == "mf:profile":
        if row and row["display_name"] and row["platform"]:
            await q.edit_message_text(
                f"👤 {row['display_name']}\nPlatforma: {row['platform']}\n"
                f"Divizion: {row['division']}\nHudud: {row['region']}\nReyting: {row['rating']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Profilni yangilash", callback_data="mf:edit_profile")],
                                                   [InlineKeyboardButton("⬅️ Menyu", callback_data="mf:menu")]])
            )
        else:
            context.user_data["mf_profile_step"] = "name"
            await q.edit_message_text("Profil uchun o‘yin ichidagi yoki ko‘rinadigan ismingizni yozing:")
    elif data == "mf:edit_profile":
        context.user_data["mf_profile_step"] = "name"
        await q.edit_message_text("Yangi ko‘rinadigan ismingizni yozing:")
    elif data == "mf:menu":
        await q.edit_message_text("⚽ UZ MATCH FINDER", reply_markup=match_menu())
    elif data == "mf:rating":
        with conn() as c:
            top = c.execute(
                "SELECT display_name, rating FROM mf_users "
                "WHERE display_name != '' AND rules_ok=1 "
                "ORDER BY rating DESC, display_name ASC LIMIT 10"
            ).fetchall()

        lines = ["🏆 UZ MATCH FINDER — TOP 10", ""]
        medals = ["🥇", "🥈", "🥉"]

        for i, player in enumerate(top, 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            lines.append(
                f"{medal} {player['display_name']} — {player['rating']:g} ochko"
            )

        if not top:
            lines.append("Hozircha reytingda o‘yinchilar yo‘q.")

        await q.edit_message_text(
            "\\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Yangilash", callback_data="mf:rating")],
                [InlineKeyboardButton("⬅️ Menyu", callback_data="mf:menu")]
            ])
        )

    elif data == "mf:find":
        if not row or not row["display_name"] or not row["platform"]:
            await q.edit_message_text("Avval profilingizni to‘ldiring.", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("👤 Profil yaratish", callback_data="mf:profile")]]))
            return
        await q.edit_message_text("O‘yin turini tanlang:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Do‘stona", callback_data="mf:mode:friendly")],
            [InlineKeyboardButton("🏆 Reytingli", callback_data="mf:mode:competitive")],
        ]))
    elif data.startswith("mf:mode:"):
        mode = data.split(":")[-1]
        with conn() as c:
            c.execute("INSERT OR REPLACE INTO mf_queue(user_id,mode,created_at) VALUES(?,?,?)",
                      (uid, mode, datetime.now(timezone.utc).isoformat()))
            me = c.execute("SELECT u.* FROM mf_queue q JOIN mf_users u ON u.user_id=q.user_id "
                           "WHERE q.mode=? AND q.user_id<>? ORDER BY q.created_at LIMIT 1",
                           (mode, uid)).fetchone()
            if me:
                c.execute("DELETE FROM mf_queue WHERE user_id IN (?,?)", (uid, me["user_id"]))
                p1, p2 = sorted((uid, me["user_id"]))
                # Repeated opponents are blocked for 24 hours in rated mode.
                hist = c.execute("SELECT last_played,count FROM mf_pair_history WHERE user_low=? AND user_high=?",
                                 (p1,p2)).fetchone()
                if mode == "competitive" and hist:
                    last = datetime.fromisoformat(hist["last_played"])
                    if datetime.now(timezone.utc)-last < timedelta(hours=24):
                        c.execute("INSERT OR REPLACE INTO mf_queue VALUES(?,?,?)",
                                  (uid, mode, datetime.now(timezone.utc).isoformat()))
                        await q.edit_message_text("Bu raqib bilan reytingli o‘yin uchun 24 soat kutish kerak. Navbatda qoldingiz.")
                        return
                cur = c.execute("INSERT INTO mf_matches(player1,player2,mode,status,created_at) VALUES(?,?,?,'invited',?)",
                                (p1,p2,mode,datetime.now(timezone.utc).isoformat()))
                mid = cur.lastrowid
                opponent = me["user_id"]
            else:
                mid = None
                opponent = None
        if opponent:
            context.application.create_task(context.bot.send_message(
                opponent, f"⚽ Sizga yangi raqib topildi! Match #{mid}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Qabul qilish", callback_data=f"mf:accept:{mid}")],
                    [InlineKeyboardButton("❌ Rad etish", callback_data=f"mf:reject:{mid}")],
                ])
            ))
            await q.edit_message_text(f"Raqib topildi! Match #{mid}. Raqib javobi kutilmoqda.")
        else:
            await q.edit_message_text("🔎 Navbatga qo‘shildingiz. Raqib topilganda xabar beramiz.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Navbatdan chiqish", callback_data="mf:leave")]]))
    elif data == "mf:leave":
        with conn() as c:
            c.execute("DELETE FROM mf_queue WHERE user_id=?", (uid,))
        await q.edit_message_text("Navbatdan chiqarildingiz.", reply_markup=match_menu())
    elif data.startswith("mf:accept:") or data.startswith("mf:reject:"):
        mid = int(data.split(":")[-1])
        accept = data.startswith("mf:accept:")
        with conn() as c:
            m = c.execute("SELECT * FROM mf_matches WHERE id=?", (mid,)).fetchone()
            if not m or uid not in (m["player1"],m["player2"]) or m["status"] != "invited":
                await q.edit_message_text("Bu taklif faol emas.")
                return
            if accept:
                c.execute("UPDATE mf_matches SET status='active' WHERE id=?", (mid,))
            else:
                c.execute("UPDATE mf_matches SET status='rejected' WHERE id=?", (mid,))
        if accept:
            for player in (m["player1"],m["player2"]):
                context.application.create_task(context.bot.send_message(
                    player, f"Match #{mid} boshlandi. O‘yin tugagach, natijani kiriting:\n"
                    f"/mfresult {mid} SIZNING_GOL RAQIB_GOL"
                ))
            await q.edit_message_text("Taklif qabul qilindi.")
        else:
            await q.edit_message_text("Taklif rad etildi.")
            other = m["player1"] if uid == m["player2"] else m["player2"]
            context.application.create_task(context.bot.send_message(other, f"Match #{mid} rad etildi."))
    elif data.startswith("mf:confirm:") or data.startswith("mf:dispute:"):
        _, action, mid_s = data.split(":")
        mid = int(mid_s)
        with conn() as c:
            m = c.execute("SELECT * FROM mf_matches WHERE id=?", (mid,)).fetchone()
            if not m or m["status"] != "reported" or uid not in (m["player1"],m["player2"]):
                await q.edit_message_text("Natija tasdiqlash uchun mavjud emas.")
                return
            if uid == m["reporter"]:
                await q.edit_message_text("Natijani kiritgan o‘yinchi o‘zi tasdiqlay olmaydi.")
                return
            if action == "dispute":
                c.execute("UPDATE mf_matches SET status='disputed' WHERE id=?", (mid,))
                await q.edit_message_text("Natija bahsli deb belgilandi. Administrator ko‘rib chiqadi.")
                if ADMIN_ID:
                    context.application.create_task(context.bot.send_message(ADMIN_ID, f"⚠️ Match #{mid} bo‘yicha nizo."))
                return
            c.execute("UPDATE mf_matches SET status='confirmed',confirmed_by=? WHERE id=?", (uid,mid))
            if m["mode"] == "competitive":
                winner = m["player1"] if m["p1_score"] > m["p2_score"] else m["player2"] if m["p2_score"] > m["p1_score"] else None
                if winner:
                    loser = m["player2"] if winner == m["player1"] else m["player1"]
                    c.execute("UPDATE mf_users SET rating=rating+1 WHERE user_id=?", (winner,))
                    c.execute("UPDATE mf_users SET rating=CASE WHEN rating>0 THEN MAX(0,rating-0.5) ELSE 0 END WHERE user_id=?", (loser,))
                lo, hi = sorted((m["player1"],m["player2"]))
                now = datetime.now(timezone.utc).isoformat()
                c.execute("INSERT INTO mf_pair_history(user_low,user_high,last_played,count) VALUES(?,?,?,1) "
                          "ON CONFLICT(user_low,user_high) DO UPDATE SET last_played=excluded.last_played,count=count+1",
                          (lo,hi,now))
        await q.edit_message_text("✅ Natija tasdiqlandi. " + ("Reyting yangilandi." if m["mode"]=="competitive" else "Do‘stona o‘yin reytingga ta’sir qilmadi."))

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("mf_profile_step")
    if not step:
        return
    uid = update.effective_user.id
    value = (update.message.text or "").strip()
    if step == "name":
        if len(value) < 2 or len(value) > 24:
            await update.message.reply_text("Ism 2–24 belgi bo‘lsin. Qayta kiriting:")
            return
        context.user_data["mf_name"] = value
        context.user_data["mf_profile_step"] = "platform"
        await update.message.reply_text("Platformani tanlang:", reply_markup=ReplyKeyboardMarkup(
            [["📱 Mobile", "🎮 Console"]], resize_keyboard=True, one_time_keyboard=True))
    elif step == "platform":
        if value not in PLATFORMS:
            await update.message.reply_text("📱 Mobile yoki 🎮 Console tanlang.")
            return
        context.user_data["mf_platform"] = PLATFORMS[value]
        context.user_data["mf_profile_step"] = "division"
        await update.message.reply_text("Divizionni tanlang:", reply_markup=ReplyKeyboardMarkup(
            [[x] for x in DIVISIONS], resize_keyboard=True, one_time_keyboard=True))
    elif step == "division":
        if value not in DIVISIONS:
            await update.message.reply_text("Ro‘yxatdan divizion tanlang.")
            return
        context.user_data["mf_division"] = value
        context.user_data["mf_profile_step"] = "region"
        await update.message.reply_text("Hududingizni tanlang:", reply_markup=ReplyKeyboardMarkup(
            [["🇺🇿 O‘zbekiston", "🌍 Boshqa"]], resize_keyboard=True, one_time_keyboard=True))
    elif step == "region":
        if value not in REGIONS:
            await update.message.reply_text("Hududni ro‘yxatdan tanlang.")
            return
        with conn() as c:
            c.execute("INSERT INTO mf_users(user_id,display_name,platform,division,region,rules_ok) "
                      "VALUES(?,?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET "
                      "display_name=excluded.display_name,platform=excluded.platform,"
                      "division=excluded.division,region=excluded.region",
                      (uid, context.user_data["mf_name"], context.user_data["mf_platform"],
                       context.user_data["mf_division"], value))
        context.user_data.pop("mf_profile_step", None)
        await update.message.reply_text("✅ Profil saqlandi.", reply_markup=main_kb())
        await update.message.reply_text("UZ MATCH FINDER menyusi:", reply_markup=match_menu())

async def result_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        await update.message.reply_text("Format: /mfresult MATCH_ID SIZNING_GOL RAQIB_GOL")
        return
    try:
        mid, mine, theirs = map(int, context.args)
        if min(mine,theirs) < 0 or max(mine,theirs) > 99:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Hisobni to‘g‘ri kiriting. Masalan: /mfresult 12 3 1")
        return
    uid = update.effective_user.id
    with conn() as c:
        m = c.execute("SELECT * FROM mf_matches WHERE id=?", (mid,)).fetchone()
        if not m or m["status"] != "active" or uid not in (m["player1"],m["player2"]):
            await update.message.reply_text("Match topilmadi yoki natija kiritish mumkin emas.")
            return
        if m["reporter"] is not None:
            await update.message.reply_text("Natija allaqachon kiritilgan. Raqib tasdiqlashi yoki nizo ochishi kerak.")
            return
        p1s,p2s = (mine,theirs) if uid == m["player1"] else (theirs,mine)
        c.execute("UPDATE mf_matches SET status='reported',reporter=?,p1_score=?,p2_score=? WHERE id=?",
                  (uid,p1s,p2s,mid))
        other = m["player2"] if uid == m["player1"] else m["player1"]
    await update.message.reply_text("Natija raqibga tasdiqlash uchun yuborildi.")
    context.application.create_task(context.bot.send_message(
        other, f"Match #{mid} natijasi: {p1s}:{p2s}. Tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"mf:confirm:{mid}")],
            [InlineKeyboardButton("⚠️ Nizo ochish", callback_data=f"mf:dispute:{mid}")],
        ])
    ))

def register_match_finder(app: Application):
    """Call from main() after init_db(); does not replace existing bot handlers."""
    init_match_db()
    app.add_handler(CommandHandler("match", open_match_finder))
    app.add_handler(CommandHandler("mfresult", result_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^⚽ UZ MATCH FINDER$"), menu_button))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^mf:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler), group=1)

# ===== UZ MATCH FINDER: ROOM & RESULT PATCH =====
import random
import re

_mf_old_callback = callback
_mf_old_text_handler = text_handler

async def callback(update, context):
    q = update.callback_query
    data = q.data or ""
    uid = q.from_user.id

    if data.startswith("mf:accept:"):
        await q.answer()
        mid = int(data.split(":")[-1])

        with conn() as c:
            m = c.execute(
                "SELECT * FROM mf_matches WHERE id=?", (mid,)
            ).fetchone()

            if not m or uid not in (m["player1"], m["player2"]) or m["status"] != "invited":
                await q.edit_message_text("Bu taklif faol emas.")
                return

            host = random.choice((m["player1"], m["player2"]))
            c.execute(
                "UPDATE mf_matches SET status='room_wait',host_id=? WHERE id=?",
                (host, mid)
            )

        opponent = m["player2"] if host == m["player1"] else m["player1"]

        await context.bot.send_message(
            host,
            f"🎲 Qura natijasi: SIZ xona yaratuvchisiz!\n\n"
            f"Match #{mid}\n"
            "eFootball'da xona yarating va xona ID kodini shu botga yuboring."
        )

        await context.bot.send_message(
            opponent,
            f"🎲 Qura natijasi: raqib xona yaratadi.\n"
            f"Match #{mid}\nXona ID kodini kuting."
        )

        await q.edit_message_text("✅ Taklif qabul qilindi. Qura tashlandi!")
        return

    await _mf_old_callback(update, context)

async def text_handler(update, context):
    uid = update.effective_user.id
    value = (update.message.text or "").strip()

    # Xona kodini qabul qilish
    with conn() as c:
        m = c.execute(
            "SELECT * FROM mf_matches WHERE host_id=? AND status='room_wait' ORDER BY id DESC LIMIT 1",
            (uid,)
        ).fetchone()

    if m:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", value):
            await update.message.reply_text("Xona ID kodini to'g'ri yuboring.")
            return

        with conn() as c:
            c.execute(
                "UPDATE mf_matches SET room_id=?,status='active' WHERE id=? AND status='room_wait'",
                (value, m["id"])
            )

        opponent = m["player2"] if uid == m["player1"] else m["player1"]

        msg = (
            f"🏟 MATCH #{m['id']} XONASI TAYYOR!\n\n"
            f"🔑 Xona ID: {value}\n\n"
            "O'yinni boshlashingiz mumkin.\n"
            f"Tugagach hisobni yuboring: {m['id']} 2:1"
        )

        await update.message.reply_text("✅ Xona kodi saqlandi va raqibga yuborildi.")
        await context.bot.send_message(opponent, msg)
        return

    # Hisob: MATCH_ID 2:1
    score = re.fullmatch(r"(\d+)\s+(\d{1,2})\s*:\s*(\d{1,2})", value)

    if score:
        mid, mine, theirs = map(int, score.groups())
        await submit_result(update, context, mid, mine, theirs)
        return

    await _mf_old_text_handler(update, context)

async def submit_result(update, context, mid, mine, theirs):
    if not (0 <= mine <= 99 and 0 <= theirs <= 99):
        await update.message.reply_text("Hisob 0–99 oralig'ida bo'lishi kerak.")
        return

    uid = update.effective_user.id

    with conn() as c:
        m = c.execute(
            "SELECT * FROM mf_matches WHERE id=?", (mid,)
        ).fetchone()

        if not m or m["status"] != "active" or uid not in (m["player1"], m["player2"]):
            await update.message.reply_text("Match topilmadi yoki faol emas.")
            return

        if m["reporter"] is not None:
            await update.message.reply_text("Natija allaqachon yuborilgan.")
            return

        p1, p2 = (mine, theirs) if uid == m["player1"] else (theirs, mine)

        c.execute(
            "UPDATE mf_matches SET status='reported',reporter=?,p1_score=?,p2_score=? WHERE id=?",
            (uid, p1, p2, mid)
        )

        opponent = m["player2"] if uid == m["player1"] else m["player1"]

    await update.message.reply_text("✅ Natija raqibga yuborildi. Tasdiq kutilmoqda.")

    await context.bot.send_message(
        opponent,
        f"⚽ Match #{mid}\nHisob: {p1}:{p2}\n\nNatijani tasdiqlang:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"mf:confirm:{mid}")],
            [InlineKeyboardButton("⚠️ Nizo ochish", callback_data=f"mf:dispute:{mid}")]
        ])
    )

async def result_cmd(update, context):
    if len(context.args) != 3:
        await update.message.reply_text(
            "Format: /mfresult MATCH_ID SIZNING_GOL RAQIB_GOL"
        )
        return

    try:
        mid, mine, theirs = map(int, context.args)
    except ValueError:
        await update.message.reply_text("Hisob formatini tekshiring.")
        return

    await submit_result(update, context, mid, mine, theirs)

print("UZ MATCH FINDER PATCH LOADED")
# ===== END PATCH =====

