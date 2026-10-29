"""
eF Narx Bot: yig‘uvchi (faqat oxirgi 30 kun).
Telegram foydalanuvchi API orqali @efootball_shop tarixini o‘qiydi.
Natija: listings.jsonl — har bir topilgan e’lon bitta JSON qatorida.
Bu skript botga avtomatik narx kiritmaydi; natijalarni avval tekshirish kerak.
"""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

CHANNELS = [
    os.getenv("CHANNEL", "efootball_shop"),
    "efootballpageshop",
    "zicoshopkanal",
]
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION = os.getenv("TG_SESSION_B64", "")
OUT = Path(os.getenv("OUTPUT_FILE", "listings.jsonl"))

PRICE_RE = re.compile(
    r"(?:narx|цена)\s*[:：\-]?\s*([^\r\n]*)",
    re.IGNORECASE
)
COIN_RE = re.compile(r"(\d[\d\s]*)\s*coins?\b", re.IGNORECASE)
STRENGTH_RE = re.compile(r"(?:collective\s*strength|jamoa\s*kuchi|max\s*sila|sila|team\s*strength|AK)\s*[:\-]?\s*(\d{3,4})", re.I)

def parse_post(message):
    text = (message.message or "").strip()
    price = None
    match = PRICE_RE.search(text)
    if match:
        price_text = match.group(1)
        currency_match = re.search(
            r"^(.+?)\s*(?:so['’`ʻ]?m|sum|сум|uzs)\b",
            price_text,
            re.IGNORECASE
        )
        if currency_match:
            price_text = currency_match.group(1).strip()
            groups = re.findall(r"\d+", price_text)

            # Faqat bitta aniq narx: 1350000, 19 000 yoki 1 350 000.
            valid_grouping = (
                len(groups) == 1
                or (
                    len(groups) == 2
                    and 1 <= len(groups[0]) <= 3
                    and len(groups[1]) == 3
                )
                or (
                    len(groups) == 3
                    and 1 <= len(groups[0]) <= 3
                    and len(groups[1]) == 3
                    and len(groups[2]) == 3
                )
            )

            if valid_grouping:
                value = int("".join(groups))
                if 10000 <= value <= 10000000:
                    price = value

    coins = None
    coin_match = COIN_RE.search(text)
    if coin_match:
        digits = re.sub(r"\D", "", coin_match.group(1))
        if digits:
            coins = int(digits)

    strength = None
    strength_match = STRENGTH_RE.search(text)
    if strength_match:
        strength = int(strength_match.group(1))

    low = text.lower()
    obmen = "bor" if re.search(r"obmen.{0,20}(?:bor|ha|ko['’`ʻ]?r)", low) else (
        "yo‘q" if re.search(r"obmen.{0,20}(?:yo['’`ʻ]?q|нет)", low) else None
    )
    linked = None
    if "google" in low or "game center" in low:
        if "toza" in low:
            linked = "toza"
        elif "ulangan" in low:
            linked = "ulangan"

    return {
        "message_id": message.id,
        "date": message.date.astimezone(timezone.utc).isoformat() if message.date else None,
        "channel": getattr(message, "_source_channel", CHANNELS[0]),
        "url": f"https://t.me/{getattr(message, '_source_channel', CHANNELS[0])}/{message.id}",
        "text": text,
        "price_uzs": price,
        "coins": coins,
        "collective_strength": strength,
        "obmen": obmen,
        "google_gamecenter_note": linked,
        "has_photo": bool(message.photo),
        "price_needs_review": price is None,
    }

async def main():
    if not API_ID or not API_HASH:
        raise SystemExit(
            "TG_API_ID va TG_API_HASH sozlanmagan. Ularni my.telegram.org saytidan oling; "
            "hech kimga yubormang."
        )
    try:
        api_id = int(API_ID)
    except ValueError:
        raise SystemExit("TG_API_ID raqam bo‘lishi kerak.")

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    client = TelegramClient(StringSession(SESSION), api_id, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram sessiyasi yaroqsiz yoki tizimga kiritilmagan.")

    found = []
    seen = set()

    for channel_name in CHANNELS:
        try:
            entity = await client.get_entity(channel_name)
            async for msg in client.iter_messages(entity):
                if not msg.date:
                    continue
                if msg.date.astimezone(timezone.utc) < cutoff:
                    break

                key = (channel_name.lower(), msg.id)
                if key in seen:
                    continue
                seen.add(key)

                # Har bir e'lon manbasini saqlash.
                msg._source_channel = channel_name.lstrip("@")
                row = parse_post(msg)

                if row["price_uzs"] is not None or re.search(
                    r"akkaunt|akk\\b|narx\\s*:", row["text"], re.I
                ):
                    found.append(row)

            print(f"{channel_name}: yig‘ildi")
        except Exception as e:
            print(f"{channel_name}: XATO — {e}")

    # Har ishga tushirishda natijani yangilaydi; postlar sanasi bo‘yicha tartiblaydi.
    with OUT.open("w", encoding="utf-8") as f:
        for row in sorted(found, key=lambda x: x["date"] or ""):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with_price = sum(1 for x in found if x["price_uzs"] is not None)
    print(f"Tugadi: {len(found)} ta e’lon saqlandi; {with_price} tasida narx matndan topildi.")
    print(f"Fayl: {OUT.resolve()}")
    print("Eslatma: rasmdagi jamoa kuchi avtomatik o‘qilmaydi; topilgan narxlarni tekshiring.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
