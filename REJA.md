# 🥩 Norin AI Hisobot — Loyiha Tahlili, Biznes Modeli va Texnik Reja (`REJA.md`)

Ushbu hujjat **Norin ishlab chiqaruvchi / ulgurji yetkazib beruvchi (postavshik)** uchun mo'ljallangan **Norin AI Hisobot** Telegram botining arxitektura qarori, biznes tahlili, **oyma-oy daromad (SaaS obuna)** modeli va to'liq texnik rejasini o'z ichiga oladi.

---

## 🧭 1. Asosiy Savol: Alohida loyiha qilgan yaxshimi yoki `Hisobchi AI` ga qo'shganmi?

**Qat'iy tavsiya: ALOHIDA loyiha (`Norin_AI_hisobot`) qilish eng to'g'ri qaror.**

| Taqqoslash mezoni | `Hisobchi AI` (Do'kon / Retail) | `Norin AI Hisobot` (Sex / Postavshik) |
|---|---|---|
| **Biznes roli** | **Xaridor (Do'kon):** Ta'minotchilarga pul to'laydi | **Sotuvchi (Ishlab chiqaruvchi):** Do'konlarga kg da norin sotadi |
| **Asosiy o'lchov** | Nakladnoy summasi (so'm) va YesPOS prixod (`ITOG 👑`) | **Kg miqdori** (chekdagi do'kon narxini e'tiborsiz qoldirib, o'z narxida hisoblash) |
| **Narx siyosati** | Bitta ta'minotchi summasi | Mahsulot **tannarxi**, **standart narxi** va **har bir mijoz uchun individual kg narxi** |
| **Guruhlar tuzilmasi** | 3 ta ichki guruh (`Nakladnoy`, `Prixod`, `Kassa`) | **Har bir mijoz uchun alohida Telegram guruhi** + rahbariyat hisobot guruhi |
| **Maxfiylik (Xavfsizlik)** | Ichki xarajat guruhi | **Mijoz guruhida tannarx va sof foyda mutlaqo ko'rinmasligi shart!** |
| **Tijoratlashtirish (SaaS)** | Bitta do'konga moslangan | **Boshqa sexlarga (norin, shashlik, kolbasa, go'sht) oyma-oy obunaga sotish juda oson** |

**Texnik sabablar:**
1. **Ma'lumotlar bazasi va izolyatsiya:** Do'kon kassasidagi nakladnoy xarajatlari bilan Norin sexining kg savdosi, tannarx/marjasi va mijoz qarz daftari bitta bazada aralashib ketsa, menyu og'irlashadi va xatolik ehtimoli oshadi.
2. **Alohida Docker konteyner:** Bitta VPS serverda ham `hisobchi-bot`, ham `norin-bot` (`norin-postgres` + `norin-bot`) bir-biriga umuman xalaqit bermasdan parallel ishlaydi.
3. **Mustaqil obuna nazorati:** Buyurtmachi oylik to'lovni kechiktirsa, faqat Norin botini `/superadmin` orqali to'xtatish yoki uzaytirish mumkin.

---

## 💡 2. Biznes Bahosi: Bu Qanday Loyiha?

Siz mijozga **haqiqiy og'riqni yechadigan** kuchli taklif bergansiz:
- **Oldingi holat:** Buyurtmachi guruhga tarozi cheki rasmini tashlaydi, chekda do'konning ustama narxi chiqib turadi (lekin ulgurji narx boshqacha), odam qo'lda kalkulyatorda `kg × mijoz_narxi` qilib hisoblaydi, daftarga qarz yozadi, oqshom foydani hisoblashga soatlab vaqt ketadi.
- **Yangi holat (`Norin AI`):**
  1. Chek rasmi, ovoz (`"Iftiqor norin ot 25 kg"`) yoki matn yuboriladi $\rightarrow$ **AI faqat kg va go'sht turini oladi** (chekdagi do'kon narxini e'tiborsiz qoldiradi!).
  2. Mijozning individual narxiga ko'paytirib, **mijoz guruhiga rasm tagida toza hisob va yangilangan qarzni** tashlaydi.
  3. Mijoz ko'rmaydigan shaxsiy menyuda esa **tannarx, sof foyda, marja (%), barcha qarzlar va kunlik kassa sverkasi** avtomatik yuritiladi.

Bu tayyor **B2B Micro-SaaS** mahsulot: bitta Norin sexidan tashqari **shashlik marinad, yarim tayyor mahsulotlar, kolbasa, tovuq/go'sht ulgurji tarqatuvchilar**ning hammasiga oylik obunaga sotish mumkin.

---

## 🟢 1-BOSQICH: Tayyor Ishga Tushirilgan Tizim

### 1-Bo'lim: 🥩 Mahsulotlar Katalogi va Tannarx
- Standart seeded mahsulotlar:
  - `Norin (Ot go'shtli)` — sinonimlar: `OT`, `OT GO'SHTI`, `OTLI`, `NORIN OT`, `NOTIN OT`, `КОНИНА` (tannarx + standart sotuv narxi sozlanadi).
  - `Norin (Mol go'shtli)` — sinonimlar: `MOL`, `MOL GO'SHTI`, `MOLLI`, `NORIN MOL`, `NOTIN MOL`, `ГОВЯДИНА`.
- Bot menyusidan cheksiz yangi mahsulot qo'shish (masalan: *Qazi*, *Hasip*, *Xamir*), tannarx va sotuv narxini istalgan payt o'zgartirish.
- **Narx tarixi xavfsizligi (Snapshot):** Bugun mahsulot tannarxi o'zgarsa ham, kechagi sotuvlarning foyda hisobi buzilmaydi.

### 2-Bo'lim: 🏪 Mijozlar, Individual Narxlar va Guruhlar
- Har bir mijoz (masalan: `Iftiqor 80`, `Chorsu Do'kon`, `Makro`) uchun:
  - **Individual sotuv narxi:** Masalan, A mijozga Ot norin `112 000 so'm/kg`, B mijozga `118 000 so'm/kg`, C mijozga standart narx (`115 000 so'm/kg`).
  - **Alohida Telegram guruhi:** 1 bosishda **Admin Deep-Link** (`startgroup=bind_client_<id>`) yoki guruh ichida `/bind_group` orqali mijoz guruhiga bog'lash.
  - **Boshlang'ich qarz:** Tizimga o'tish paytidagi eski qarz qoldig'ini kiritish.

### 3-Bo'lim: 📸 AI Chek / Ovoz / Matn Sotuv Hisobi (`Gemini Flash`)
1. **Rasm OCR (Faqat KG o'qish):**
   - Gemini Vision tarozi cheki yoki nakladnoy rasmidan **chekdagi so'm narxlarini tashlab**, faqat **mahsulot turi (Ot/Mol)** va **kg miqdorini** ajratadi.
   - Agar bitta rasmda bir nechta tarozi nakleykasi bo'lsa (`8.25 + 9.1 + 7.65`), barchasini jamlab `25 kg` qilib chiqaradi va izohda qismlarini ko'rsatadi.
2. **Ovoz va Matn:**
   - *"Iftiqor 80 notin ot 25 kg"* yoki *"ot 12.5 kg mol 8 kg"* (ovozda ham, matnda ham, shaxsiy chatda ham, mijoz guruhining o'zida ham ishlaydi).
3. **Mijoz Guruhiga Xavfsiz Yuborish & Jonli Tahrirlash:**
   - Guruhda **faqat** `kg`, `mijoz narxi`, `jami summa` va `hozirgi qarz qoldig'i` ko'rinadi (**tannarx va foyda hech qachon guruhga chiqmaydi**).
   - Admin shaxsiy chatda kg/narx/mijozni tahrirlasa yoki o'chirsa, mijoz guruhidagi rasm tagidagi matn ham **`✏️ [TAHRIRLANDI]`** / **`❌ [BEKOR QILINDI]`** deb avtomatik yangilanadi.
4. **Guruh ichida Avto-Hisob:**
   - Admin mijoz guruhining o'ziga rasm yoki `"norin ot 25 kg"` deb yozsa, bot o'sha guruh qaysi mijozga ulanganini bilib, darhol rasmga reply qilib hisoblab beradi, admin shaxsiy chatiga esa sof foyda hisobini tashlaydi. (Begona gaplarga tegmaydi!)

### 4-Bo'lim: 💳 Qarz Daftari, Pul Oldi-Berdi va Akt Sverka
- **Mijozdan pul olish (`💵 Pul oldim (Mijoz)`):**
  - Naqd 💵 / Karta-Click 💳 / Perechesleniye 🏦 usullari bilan qabul qilish (ovoz/matnda ham: *"Iftiqordan 2 mln karta oldim"*).
  - Naqd pul kassa qoldig'iga qo'shiladi; karta/perechesleniye esa mijoz qarzini kamaytiradi, lekin qo'ldagi naqd pulga aralashmaydi.
  - Mijoz guruhiga to'lov kvitansiyasi yuborish.
- **Akt Sverka:**
  - Istalgan mijoz bo'yicha oxirgi yuklar, to'lovlar va qarz qoldig'ini guruhga yuborish yoki **Mijoz Excel** (tannarxsiz!) fayl qilib chiqarish.

### 5-Bo'lim: 📊 Kunlik Foyda, Xarajatlar, Sverka va Excel
- **Kunlik hisobot:** Bugungi jami kg (mahsulot kesimida), savdo summasi, tannarx, **sof foyda va marja (%)**, tushgan naqd/karta pullar, xarajatlar (go'sht, xamir, yo'l kira), kassa qarzi va qo'lda qolishi kerak bo'lgan aniq naqd pul.
- **🏁 Kunni yakunlash:** Qo'ldagi naqd pulni sanab kiritish $\rightarrow$ Kamomad/Ortiqcha farqni ko'rish $\rightarrow$ Arxivga saqlash va Rahbariyat hisobot guruhiga yuborish $\rightarrow$ Sanalgan pul ertangi kunga qoldiq bo'lib o'tadi.
- **📥 4 varaqli Excel (`.xlsx`):** `Kunlik Hisobot`, `Sotuvlar (Kg)`, `Mijozlar Qarzi`, `Pul Oldi-Berdi`.

---

## 💎 6-Bo'lim: Oyma-Oy Daromad (SaaS Obuna) va `/superadmin` Tizimi

### Nega mijoz sizga oyma-oy to'laydi? (Sotuv argumenti)
Mijozga buni **"bitta yozilgan skript"** emas, **"doimiy ishlab turadigan AI xizmat"** sifatida soting:
1. **Sun'iy Intellekt (Gemini API) xarajati:** Har bir chek rasmi va ovozli xabar pullik AI API orqali ishlaydi.
2. **24/7 Cloud Server va Avto-Backup:** Bot va ma'lumotlar bazasi kecha-kunduz serverda o'chmasdan turadi, har kuni bazadan nusxa olinadi.
3. **Texnik yordam va yangilanishlar:** Telegram API yoki chek shakli o'zgarsa tezkor moslab berish.

**Tavsiya etilgan tariflar:**
- **Boshlang'ich (14–30 kun):** Bepul sinov (mijoz botga o'rganib, barcha qarzlarni kiritib oladi — keyin boshqa tizimga o'tmaydi).
- **Standart oylik obuna:** `300 000 – 500 000 so'm / oy` (kuniga bor-yo'g'i 10–15 ming so'm — yarim kilo norin narxidan arzon).
- **Yillik (2 oy bepul):** `3 000 000 – 4 000 000 so'm / yil`.

### Texnik mexanizm (Bot ichiga qurilgan)
1. **`SubscriptionMiddleware`:** Har bir buyruq va tugmada obuna muddatini tekshiradi.
   - `active` / `expiring` (3 kun qolganda ogohlantirish) $\rightarrow$ to'liq ishlaydi.
   - `grace` (muddat tugagandan keyin 3 kun imtiyoz davri) $\rightarrow$ ishlaydi, lekin eslatma beradi.
   - `expired` / `suspended` $\rightarrow$ bot hisob-kitob funksiyalarini to'xtatib, muloyimlik bilan to'lov eslatmasini va **`💳 To'lov qildim (Tasdiqlash so'rash)`** tugmasini chiqaradi (mavjud Excel arxivini yuklab olish esa ochiq qoladi).
2. **`/superadmin` paneli (faqat sizning ID `5649321700` uchun):**
   - `+7 kun` / `+30 kun` / `+90 kun` / maxsus kun qo'shish;
   - Oylik narx va kontakt (`@username` / telefon) ni o'zgartirish;
   - Mijoz xodimlarini (`ADMIN_IDS` + bazadagi `AuthorizedUser`) ID bo'yicha qo'shish/o'chirish;
   - Mijoz `"💳 To'lov qildim"` tugmasini bossa, **sizning Telegramingizga** darhol xabar va **`✅ +30 kun tasdiqlash`** tugmasi keladi — 1 bosishda obuna uzayadi va to'lov tarixiga yoziladi!

---

## 🟡 2-BOSQICH: Kelajakdagi Kengaytirish
- **Multi-tenant SaaS:** Bitta bot serverida 10–50 ta turli Norin / Shashlik sexlariga alohida kabinet ochish.
- **Click / Payme integratsiyasi:** Oylik obunani avtomatik kartadan yechish.
- **Xom-ashyo ombori:** Kunlik sotib olingan ot/mol go'shti va xamirdan qancha kg tayyor norin chiqishini (chiqim koeffitsiyentini) nazorat qilish.

---

## 🛠 Texnik Arxitektura
- **Til va Framework:** Python 3.11+, Aiogram 3.x (Asinxron Telegram Bot)
- **Ma'lumotlar bazasi:** PostgreSQL 16 (`asyncpg` + `SQLAlchemy 2.0 Async`) — lokal test uchun SQLite (`aiosqlite`)
- **AI:** Google Gemini Flash Multimodal API (rasmdan faqat KG ajratish + o'zbekcha ovoz/matn tushunish)
- **Eksport:** OpenPyXL (`.xlsx` — ichki foyda hisoboti va mijozlar uchun tannarxsiz Akt Sverka)
