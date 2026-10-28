# eF Narx Bot

eFootball akkauntlarini dastlabki baholash uchun Telegram botning boshlang‘ich versiyasi.

## Hozirgi imkoniyatlar
- Platforma, Epic, Big Time, Show Time, Google Play, Game Center, KONAMI ID, minus Coin va Coin haqida savollar.
- Javoblarni SQLite bazasida saqlash.
- Administrator kiritgan taqqoslash narxlari asosida ehtiyotkor narx diapazoni chiqarish.
- Ma’lumot yetarli bo‘lmasa, narxni to‘qib chiqarmaslik.

## Hozircha yo‘q
- Kanal tarixini avtomatik yig‘ish.
- Rasmdagi futbolchilarni AI orqali aniqlash.
- Haqiqiy sotuvlarni avtomatik tasdiqlash.
- PostgreSQL ulanishi. Render'da SQLite ma'lumotlari qayta deploy yoki servis qayta yaratilganda yo‘qolishi mumkin; uzoq muddatli ishlash uchun persistent disk yoki PostgreSQL qo‘shish kerak.

## Ishga tushirish
1. Python 3.11+ o‘rnating.
2. `pip install -r requirements.txt`
3. `BOT_TOKEN` muhit o‘zgaruvchisiga BotFather tokenini qo‘ying.
4. `ADMIN_ID` ga o‘z Telegram numeric user ID'ingizni kiriting.
5. `python main.py`

## Administrator narx qo‘shishi
`/addsale android 10 2 3 250000`

Tartib: platforma, Epic soni, Big Time soni, Show Time soni, narx (so‘m).
Faqat ishonchli va imkon qadar haqiqiy sotuv narxlarini kiriting. E’lon narxlarini sotilgan narx sifatida ko‘rsatmaslik kerak.

## Render
`render.yaml` worker yaratish uchun namunaviy sozlama. `BOT_TOKEN` va `ADMIN_ID` ni Render Environment Variables bo‘limida maxfiy kiriting. Tokenni GitHub kodiga yozmang.
