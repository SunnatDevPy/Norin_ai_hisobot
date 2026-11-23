# 📊 Sotuv AI — Savdo, Qarz, Kassa va AI Hisobot Tizimi

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flutter](https://img.shields.io/badge/Flutter-Material%203-02569B?logo=flutter&logoColor=white)](https://flutter.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Gemini AI](https://img.shields.io/badge/Gemini-Multimodal%20AI-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/)

**Sotuv AI** — uyda ishlab chiqaruvchilar, kichik savdogarlar, do‘konlar va ulgurji yetkazib beruvchilar uchun mo‘ljallangan **aqlli savdo, qarz daftari, kassa nazorati va AI chek o‘qish tizimi**. Tizim **Android mobil ilova (Flutter)**, **FastAPI backend** hamda **ixcham Telegram bot**ni bitta PostgreSQL bazasi orqali birlashtiradi.

---

## ✨ Asosiy Imkoniyatlar

### 1. 📱 Android Mobil Ilova (`mobile_app/` — Sotuv AI)
- **Cosmic Purple UI (`Oq` va `Qora` tema):** Zamonaviy yorug‘ va qorong‘i rejimlarda to‘liq moslashuvchi kartalar, `fl_chart` interaktiv grafiklari hamda chetdan-chetga (edge-to-edge) toza ekranlar.
- **Tezkor va Xavfsiz Kirish:**
  - Telegram botga 1-bosishda o‘tib **`START`** orqali avtomatik ulanish (`telegram-ticket` / `telegram-poll`);
  - Telegram ID kiritmasdan botdagi 6 xonali `/apk` kodi bilan kirish;
  - **Barmoq izi (Otpechatka)** va **4 xonali PIN-kod** bilan ilova qulfi hamda faol qurilmalarni boshqarish.
- **Markaziy ✨ AI Sotuv Tugmasi:** Pastki panel markazidan 1 bosishda:
  - Nakladnoy yoki tarozi cheki rasmini **Gemini Vision** orqali o‘qish;
  - Matnli buyurtmadan 0-token mahalliy parser bilan hisoblash;
  - Bir nechta mahsulotni qo‘lda tezkor kiritish va tasdiqlash.
- **Mijozlar & Akt Sverka:** Qarzlar reytingi, shaxsiy narxlar, tezkor to‘lov (`Naqd` / `Karta` / `O'tkazma`), `Vozvrat`, Telegram guruhga tannarxsiz xabar va xronologik balans tarixi.
- **Kassa & Kun Yakuni:** Real vaqt kassa balansi, 7+ kategoriyali xarajatlar, jonli `Sverka farqi` bilan kunni yopish, smenalar tarixi va **Excel (`.xlsx`)** ochish/ulashish.
- **OTA APK Avto-Yangilash:** Ilova ichidan serverdagi yangi versiyani (`/api/v1/apk/version`) tekshirish va o‘rnatish.

### 2. 🤖 Ixcham Telegram Bot (`bot/`)
Bot foydalanuvchilar uchun atigi **4 ta asosiy bo‘lim** bilan soddalashtirilgan:
1. **📲 APK** (`/apk`) — eng so‘nggi Android APK faylini yuklash va 6 xonali bir martalik kirish kodini olish.
2. **📊 Dashboardlar** (`/dashboard`) — Bugungi, 7 kunlik, 30 kunlik, Shu oy va O‘tgan oy hisobotlari hamda jonli formulali `.xlsx` Excel eksporti.
3. **👥 Guruh sozlash** (`/groups`) — Hisobot guruhini va mijoz guruhlarini 1-bosishda Telegram Deep-Link orqali bog‘lash (mijoz guruhlariga tannarx va foyda hech qachon chiqarilmaydi).
4. **🛡 Status** (`/status`) — joriy hisob, obuna muddati va AI limit holatini ko‘rish.

*(Mijoz guruhlariga yuborilgan rasm/cheklar ham AI va guruh avto-hisobi orqali avtomatik qayta ishlanadi.)*

### 3. 🚀 Multi-Tenant FastAPI Backend (`api/`) & PostgreSQL 16
- **Izolyatsiyalangan ma’lumotlar (`tenant_id`):** Har bir do‘kon/foydalanuvchi o‘z mahsulotlari, mijozlari, kassasi va hisobotlariga ega.
- **JWT + Refresh Token:** `30` daqiqalik access token, aylanuvchi refresh tokenlar (`api_sessions`) va `audit_logs` nazorati.
- **AI Resurs & Barqarorlik:** Rasm va ovozli xabarlar uchun Gemini fallback (`gemini-flash-lite-latest` → `gemini-2.5-flash-lite` → `gemini-2.5-flash`), 0-token matn/hisobot parseri va har 24 soatda avtomatik `norin-backup` (`pg_dump`).

---

## 🤖 Bot Buyruqlari Ro‘yxati

| Buyruq | Kimlar uchun | Vazifasi |
|---|---|---|
| `/start` | Barcha ruxsat etilganlar | Asosiy menyu va Deep-Link ulanish (`apk_...`, `bind_...`) |
| `/apk` | Barcha ruxsat etilganlar | Android APK faylini yuklab olish va 6 xonali kirish kodi |
| `/dashboard` | Barcha ruxsat etilganlar | Kunlik va davriy dashboardlar + Excel eksport |
| `/groups` | Barcha ruxsat etilganlar | Mijoz va hisobot guruhlarini sozlash |
| `/status` | Barcha ruxsat etilganlar | Obuna va hisob holatini ko‘rish |
| `/myid` | Barcha foydalanuvchilar | Telegram ID ni ko‘rish |
| `/cancel` | Barcha foydalanuvchilar | Faol kiritish bosqichini bekor qilish |
| `/superadmin`, `/menu`, `/clear` | **Faqat Super Admin** | SaaS boshqaruvi, foydalanuvchilar va xizmat ko‘rsatish |

---

## 🏗 Tizim Arxitekturasi

```mermaid
flowchart TD
    APP["Sotuv AI Android APK (Flutter / Material 3)"] -->|HTTPS + JWT| API["FastAPI REST API (norin-api :8000)"]
    TG["Telegram Bot (Aiogram 3)"] --> MW["SubscriptionMiddleware"]
    MW --> R["4 ta Asosiy Bo'lim (APK / Dashboard / Guruhlar / Status)"]
    R & API --> SVC["gemini_ai.py / group_notify.py / excel_export.py"]
    SVC --> DB["database/crud.py + SQLAlchemy Async"]
    DB --> PG["PostgreSQL 16 (Multi-Tenant Baza)"]
    PG --> BK["norin-backup (Har 24 soatda pg_dump -> .sql.gz)"]
```

---

## 📁 Loyiha Tuzilmasi

```text
Norin_AI_hisobot/
├── main.py                       # Bot kirish nuqtasi, BotCommandScope & obuna kuzatuvchisi
├── config.py                     # Pydantic Settings (.env va JWT/OTP sozlamalari)
├── requirements.txt              # Python kutubxonalari
├── Dockerfile                    # Production konteyner obrazi (Python 3.12-slim)
├── docker-compose.yml            # norin-postgres + norin-api (:8000) + norin-bot + norin-backup
├── build_apk.ps1                 # Flutter APK versiya oshirish, test, release build & deploy
├── .env.example                  # Muhit o'zgaruvchilari namunasi
├── README.md                     # Loyiha hujjati
├── api/                          # FastAPI REST API (norin-api)
│   ├── main.py                   # App, CORS, lifespan & OTA APK version/download endpointlari
│   ├── deps.py                   # JWT auth va tenant konteksti
│   ├── security.py               # OTP/Refresh hash, JWT & rate limiter
│   ├── serializers.py            # JSON javob modellari
│   └── routers/                  # auth.py, read.py, write.py, admin.py
├── database/
│   ├── models.py                 # SQLAlchemy 2.0 ORM modellari
│   ├── session.py                # Async engine, migratsiya & boshlang'ich seed
│   ├── fsm_storage.py            # DB ga asoslangan doimiy FSM holatlar xotirasi
│   └── crud.py                   # Tenant-izolyatsiyali CRUD, qarz/vozvrat/sverka & hisobotlar
├── services/
│   ├── gemini_ai.py              # Rasm/Ovoz Gemini AI + 0-token matn parseri
│   ├── group_notify.py           # Mijoz guruhlariga tannarxsiz xabar yuborish
│   └── excel_export.py           # Jonli formulali kunlik/davriy Excel & Akt Sverka
├── bot/
│   ├── keyboards.py              # 4 tugmali soddalashtirilgan menyu va inline klaviaturalar
│   ├── middlewares.py            # Obuna va ruxsat tekshiruvi
│   ├── states.py                 # FSM holatlari
│   ├── ui_helpers.py             # Jadval, formatlash va karta yordamchilari
│   └── handlers/                 # apk_link, clients_products, sales_norin, wallet_reports, superadmin
├── mobile_app/                   # Flutter Material 3 Android APK loyihasi (Sotuv AI)
│   ├── pubspec.yaml              # Riverpod, Dio, fl_chart, image_picker, local_auth, flutter_secure_storage
│   └── lib/
│       ├── main.dart             # Edge-to-edge ilova kirish nuqtasi & Splash
│       ├── core/                 # API client, biometrik/PIN qulf, Dark/Light tema, widgetlar, OTA updater
│       └── features/             # Auth, Dashboard, AI/Qo'lda sotuv, Mijozlar, Kassa, Sozlamalar, Admin
└── tests/
    ├── test_all.py               # Bot, DB, Excel va Super Admin pytest testlari
    └── test_api.py               # FastAPI auth, read, write va admin pytest testlari
```

---

## 🚀 Ishga Tushirish

### 1-usul: Lokal Python muhiti (SQLite bilan tezkor test)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # BOT_TOKEN, SUPER_ADMIN_IDS, GEMINI_API_KEY ni kiriting
python main.py
```

### 2-usul: Docker Compose + PostgreSQL 16 + Avtomatik Backup (VPS / Production)

```bash
cp .env.example .env
# .env ichida PostgreSQL ulanishini belgilang:
# POSTGRES_USER=norin
# POSTGRES_PASSWORD=kuchli_parol
# POSTGRES_DB=norin_db
# DATABASE_URL=postgresql+asyncpg://norin:kuchli_parol@norin-postgres:5432/norin_db

docker compose up -d --build
docker compose ps
docker compose logs -f norin-bot
```

> Zaxira fayllari avtomatik ravishda `./data/backups/norin_YYYY-MM-DD_HHMM.sql.gz` ko‘rinishida saqlanadi va 14 kundan eskisi tozalanadi.

### 3-usul: Android APK (`mobile_app/`) Yig‘ish va Serverga Yuklash

```powershell
# Versiyani avtomatik oshirish, analyze, test, release APK va serverga yuklash:
.\build_apk.ps1 -Deploy
# Yoki faqat lokal APK yig'ish:
.\build_apk.ps1
```

> Tayyor fayl `dist/norin_ai.apk` va `dist/apk_version.json` ko‘rinishida yig‘iladi.

---

## ⚙️ Muhit O‘zgaruvchilari (`.env`)

| O‘zgaruvchi | Tavsif | Standart / Namuna |
|---|---|---|
| `BOT_TOKEN` | `@BotFather` dan olingan Telegram bot tokeni | Majburiy |
| `SUPER_ADMIN_IDS` | Loyiha egasi / Super Admin Telegram ID lari (vergul bilan) | `123456789` |
| `ADMIN_IDS` | Asosiy hisob xodimlari ID lari (ixtiyoriy `:Ism` bilan) | `123456789:Asad` |
| `API_JWT_SECRET` | FastAPI JWT/OTP imzo siri (bo‘sh bo‘lsa `BOT_TOKEN` dan olinadi) | Ixtiyoriy |
| `API_PUBLIC_URL` | Tashqi HTTPS API & APK yuklab olish manzili | `https://your-domain.example.com` |
| `OWNER_CONTACT` | Obuna eslatmalarida ko‘rsatiladigan aloqa | `@your_username` |
| `DEFAULT_MONTHLY_PRICE` | Standart oylik obuna narxi (so‘m) | `400000` |
| `DEFAULT_TRIAL_DAYS` | Boshlang‘ich sinov muddati (kun) | `30` |
| `DATABASE_URL` | SQLite (`aiosqlite`) yoki PostgreSQL (`asyncpg`) ulanish satri | `sqlite+aiosqlite:///./data/norin_bot.db` |
| `POSTGRES_USER` | Docker PostgreSQL foydalanuvchisi | `norin` |
| `POSTGRES_PASSWORD` | Docker PostgreSQL paroli | `change_me_strong_password` |
| `POSTGRES_DB` | Docker PostgreSQL baza nomi | `norin_db` |
| `GEMINI_API_KEY` | Google Gemini API kaliti (rasm va ovoz o‘qish uchun) | Majburiy |
| `GEMINI_MODEL` | Asosiy Gemini modeli | `gemini-flash-lite-latest` |
| `TIMEZONE` | Mahalliy vaqt mintaqasi (kunlik smena va hisobotlar uchun) | `Asia/Tashkent` |

---

## 🧪 Avtomatik Testlar

```bash
# Backend + API testlari
python -m pytest tests/test_all.py tests/test_api.py -v

# Flutter static analyze va widget testlari
cd mobile_app && flutter analyze && flutter test
```
