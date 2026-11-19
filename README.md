# 🥩 Norin AI Hisobot — Ishlab Chiqaruvchi & Ulgurji Savdo Telegram Boti

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Gemini AI](https://img.shields.io/badge/Gemini-Multimodal%20AI-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/)

Norin ishlab chiqaruvchilar va ulgurji go'sht/ovqat yetkazib beruvchilar uchun **tarozi cheki rasmidan faqat kg ni o'qib (chekdagi do'kon narxini e'tiborsiz qoldirib) mijozning individual narxida hisoblaydigan**, har bir mijozning alohida Telegram guruhiga izoh bilan yuboradigan, **qarz daftari, kunlik sof foyda, kassa sverkasi va oylik obuna (`/superadmin`)** tizimiga ega Telegram bot.

---

## ✨ Asosiy Imkoniyatlar

### 1. 📸 AI Chek / Ovoz / Matn orqali KG Sotuv Hisobi (`Gemini Flash`)
- **Faqat KG o'qish:** Chekdagi do'konning chakana narxlarini tashlab, faqat **kg miqdori** va **go'sht turini** (`Ot go'shtli` / `Mol go'shtli`) aniqlaydi. Bitta rasmda bir nechta nakleyka bo'lsa, hammasini jamlab chiqaradi (`8.25 + 9.1 + 7.65 = 25 kg`).
- **Ovoz va Matn:** *"Iftiqor 80 notin ot 25 kg"* yoki *"ot 12.5 kg mol 8 kg"* deb yuborish kifoya.
- **Guruhga Avto-Yuborish & Jonli Tahrirlash:** Tasdiqlangan sotuv mijozning guruhiga rasm tagidagi chiroyli izoh bilan yuboriladi. **Tannarx va foyda hech qachon mijoz guruhida ko'rsatilmaydi!** Keyinchalik kg/narx/mijoz tahrirlansa yoki o'chirilsa, guruhdagi xabar ham avtomatik yangilanadi.
- **Guruh ichida Avto-Hisob:** Admin mijoz guruhining o'ziga rasm yoki matn tashlasa, bot darhol javob (reply) qilib hisobni yozadi, adminning shaxsiy chatiga esa sof foyda va tahrir tugmalarini yuboradi.

### 2. 🥩 Mahsulotlar (Tannarx) & 🏪 Mijozlar (Individual Narx + Guruh)
- Har bir mahsulot uchun **tannarx** va **standart sotuv narxi** sozlanadi.
- Har bir mijoz uchun alohida kg narx (masalan: A do'kon — `112 000`, B do'kon — `118 000`) va alohida Telegram guruhi biriktiriladi (1-bosishda **Admin Deep-Link** orqali).

### 3. 💳 Qarz Daftari, Pul Oldi-Berdi & Akt Sverka
- Mijozlardan **Naqd / Karta (Click/Payme) / Perechesleniye** ko'rinishida pul qabul qilish.
- Har bir mijozning joriy qarz qoldig'i, yuklar tarixi va to'lovlar **Akt Sverkasi** (Telegram guruhga yuborish yoki tannarxsiz Mijoz Excel yuklab olish).

### 4. 📊 Kunlik Foyda, Xarajatlar, Sverka & Excel
- Kunlik va 30 kunlik hisobot: jami kg, tushum, tannarx, **sof foyda va marja (%)**, xarajatlar, kassa qarzi va qo'ldagi naqd pul.
- **🏁 Kunni yakunlash:** Qo'ldagi naqd pulni sanab sverka qilish, ertangi kunga qoldiq o'tkazish va **4 varaqli `.xlsx` Excel** yuklab olish.

### 5. 💎 Oylik SaaS Obuna va `/superadmin` Boshqaruvi
- Sinov/oylik muddat, 3 kunlik grace period, avtomatik eslatmalar va muddat tugaganda bloklash.
- Mijoz `"💳 To'lov qildim"` tugmasini bosganda Super Adminga (dasturchiga) **1 bosishda `+30 kun` tasdiqlash** xabari boradi.
- `/myid` — foydalanuvchi Telegram ID sini bilish buyrug'i.
- `/superadmin` — obunani uzaytirish, narx/kontakt o'zgartirish, ruxsat etilgan ID larni qo'shish/o'chirish va to'lovlar tarixi.

---

## 🏗 Loyiha Tuzilmasi

```text
Norin_AI_hisobot/
├── main.py                       # Bot kirish nuqtasi (Aiogram 3 + Middleware + Obuna kuzatuvchisi)
├── config.py                     # Pydantic Settings (.env konfiguratsiyasi)
├── requirements.txt              # Python kutubxonalari
├── Dockerfile                    # Production konteyner obrazi
├── docker-compose.yml            # Izolyatsiyalangan norin-postgres + norin-bot stack
├── REJA.md                       # Biznes tahlil, SaaS strategiyasi va texnik reja
├── database/
│   ├── models.py                 # SQLAlchemy 2.0 ORM modellari
│   ├── session.py                # Async engine, init_db, boshlang'ich mahsulotlar & obuna seed
│   └── crud.py                   # Mahsulot, mijoz, narx, sotuv, qarz, kassa va obuna CRUD
├── services/
│   ├── gemini_ai.py              # Gemini Vision (faqat KG OCR), ovoz/matn va kg parseri
│   └── excel_export.py           # OpenPyXL 4 varaqli kunlik va mijoz Akt Sverka Excel eksporti
├── bot/
│   ├── states.py                 # Aiogram FSM holatlari
│   ├── middlewares.py            # Oylik obuna tekshiruvchi middleware
│   ├── keyboards.py              # Reply va Inline tugmalar + Admin Deep-Link
│   └── handlers/
│       ├── __init__.py           # Routerlarni ulash
│       ├── superadmin.py         # /myid, /superadmin paneli, obunani 1-bosishda tasdiqlash
│       ├── clients_products.py   # /start, mahsulotlar, mijozlar, individual narx, guruh ulash, qarzlar
│       ├── wallet_reports.py     # Kunlik/30 kunlik foyda hisoboti, xarajat, kassa sverka, history, Excel
│       └── sales_norin.py        # AI rasm/ovoz/matn sotuv, mijoz to'lovi, tahrirlash & guruh avto-hisob
└── tests/
    └── test_all.py               # Avtomatik Pytest testlari
```

---

## 🚀 Ishga Tushirish

### 1-usul: Lokal Python muhiti

```bash
python -m venv .venv
.venv\Scripts\activate      # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # BOT_TOKEN, SUPER_ADMIN_IDS, GEMINI_API_KEY ni to'ldiring
python main.py
```

### 2-usul: Docker Compose + PostgreSQL 16 (VPS uchun)

```bash
cp .env.example .env
# .env ichida DATABASE_URL=postgresql+asyncpg://norin:parol@norin-postgres:5432/norin_db qilib sozlang
docker compose up -d --build
docker compose logs -f norin-bot
```

---

## ⚙️ Muhit O'zgaruvchilari (`.env`)

| O'zgaruvchi | Tavsif | Standart / Namuna |
|---|---|---|
| `BOT_TOKEN` | `@BotFather` dan olingan Telegram bot tokeni | Majburiy |
| `SUPER_ADMIN_IDS` | Dasturchi / loyiha egasi Telegram ID lari (vergul bilan) | `5649321700` |
| `ADMIN_IDS` | Buyurtmachi va ishchilar Telegram ID lari (vergul bilan) | `""` |
| `OWNER_CONTACT` | Obuna tugaganda ko'rsatiladigan bog'lanish manzili | `@SunnatDevPy` |
| `DEFAULT_MONTHLY_PRICE` | Standart oylik obuna narxi (so'm) | `400000` |
| `DEFAULT_TRIAL_DAYS` | Boshlang'ich sinov muddati (kun) | `30` |
| `DATABASE_URL` | SQLite (`aiosqlite`) yoki PostgreSQL (`asyncpg`) manzili | `sqlite+aiosqlite:///./data/norin_bot.db` |
| `GEMINI_API_KEY` | Google Gemini API kaliti (rasm va ovoz o'qish uchun) | Majburiy |
| `GEMINI_MODEL` | Asosiy Gemini modeli | `gemini-flash-lite-latest` |
| `TIMEZONE` | Mahalliy vaqt mintaqasi | `Asia/Tashkent` |

---

## 🧪 Avtomatik Testlar

```bash
python -m pytest tests/test_all.py -v
```
