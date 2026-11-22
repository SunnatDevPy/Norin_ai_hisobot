# 🥩 Norin AI Hisobot — Ishlab Chiqaruvchi & Ulgurji Savdo Telegram Boti

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Gemini AI](https://img.shields.io/badge/Gemini-Multimodal%20AI-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/)

Norin ishlab chiqaruvchi sexlar va ulgurji go‘sht/oziq-ovqat yetkazib beruvchilar uchun **tarozi/nakladnoy rasmidan faqat kg va mahsulot turini o‘qib**, har bir mijozning **individual narxida** hisoblaydigan, mijozning Telegram guruhiga **tannarx va foydasiz** yuboradigan, **qarz daftari, kunlik sof foyda, kassa sverkasi, Excel hisobotlari va ko‘p filialli (Multi-Tenant) SaaS obuna boshqaruvi**ga ega Telegram bot.

---

## ✨ Asosiy Imkoniyatlar

### 1. 📸 AI Faqat Rasm & Ovoz Uchun (Matn & Hisobotlar — 0 Token)
- **Tarozi cheki / Nakladnoy rasmi (Gemini Vision):** Chekdagi do‘konning so‘m narxlarini e’tiborsiz qoldirib, faqat **kg vazni** va **mahsulot turini** (`Ot` / `Mol`) o‘qiydi. Bir nechta tarozi nakleykasi bitta rasmda bo‘lsa, barchasini jamlab beradi (`8.25 + 9.1 + 7.65 = 25 kg`).
- **Rasm tagidagi (Caption) Postavshik / Mijoz ustuvorligi:** Nakladnoyda postavshik nomi bo‘lmasa yoki xato bosilgan bo‘lsa, rasm tagiga mijoz/postavshik nomini yozib yuborish kifoya — bot chekdagi bosma nomni tashlab, rasm tagidagi nomni oladi (bazada bo‘lmasa 1 bosishda **yangi mijoz** qilib qo‘shish tugmasini chiqaradi).
- **Matn & Caption — 0 Token:** Shaxsiy chat va guruhdagi matnli buyurtmalar (`"Iftiqor ot 25 yarim kg"`), `"3 yarim million"`, `"yarim mln"` kabi iboralar hamda barcha hisobotlar AI chaqirmasdan mahalliy parser orqali qayta ishlanadi.
- **Ovozli xabarlar:** 90 soniyagacha bo‘lgan ovozli xabarlarni Gemini Audio orqali tushunadi; to‘lov/xarajat/kassa bosqichlarida yengil `extract_amount_from_audio` ishlatiladi.
- **Barqarorlik va Sarf Nazorati:** Yo‘q (`404`) modellar avtomatik 1 soatga keshlanadi (`gemini-flash-lite-latest` → `gemini-2.5-flash-lite` → `gemini-2.5-flash`), har bir rasm/ovoz so‘rovi `ai_usage_logs` jadvalida tokenlari bilan saqlanadi.

### 2. 🥩 Mahsulotlar, 🏪 Mijozlar & 🔗 Guruh Sinxronizatsiyasi
- **Mahsulot katalogi:** Har bir mahsulot uchun **tannarx**, **standart sotuv narxi**, **nom o‘zgartirish**, **o‘lchov birligi** (`kg` / `dona` / `porsiya` / `litr`) va **sinonimlar (alias)** sozlanadi.
- **Vozvrat (Qaytarilgan mahsulot):** Mijozdan qaytgan mahsulotni alohida `↩️ Vozvrat` sifatida kiritish — mijoz qarzini, kunlik/davriy sof foydani va Akt Sverkani avtomatik to‘g‘rilaydi (tannarx va foyda mijoz guruhiga chiqmaydi).
- **Mijozlar bazasi:** Telefon raqam, boshlang‘ich qarz, sinonimlar va mijozga xos **individual narx/kg** (masalan, A do‘kon — `112 000`, B do‘kon — `118 000`).
- **1-bosishda Guruh Ulash:** Admin Deep-Link orqali botni mijoz guruhiga qo‘shib bog‘lash; guruhga yuboriladigan caption va Akt Sverkada **tannarx, sof foyda va marja hech qachon chiqarilmaydi**.
- **Jonli Sinxronizatsiya:** Sotuvda kg, narx, mahsulot turi (`🥩 Tur`), mijoz almashtirilsa yoki sotuv/to‘lov o‘chirilsa — mijoz guruhidagi xabar va yangilangan qarz qoldig‘i avtomatik tahrirlanadi.
- **Tezkor To‘lov (`💵 Pulini oldim`):** Tasdiqlangan sotuv kartasining o‘zidan 1 bosishda `Naqd / Karta / Perechesleniye` to‘lovini yozish.

### 3. 💳 Qarz Daftari, Xarajatlar & Kun Yakuni (Sverka)
- **Pul oldi-berdi:** Mijozlardan **Naqd / Karta / Perechesleniye** to‘lovlari, sex xarajatlari **7 ta kategoriya** bo‘yicha (`Go'sht`, `Xamir`, `Ziravor`, `Ish haqi`, `Transport`, `Ijara`, `Boshqa`), asosiy pul kiritish va kassa qarzi hisobi.
- **Kechagi ochiq smena ogohlantirishi:** Oldingi kun yopilmagan bo‘lsa, Kunlik hisobot va Kunni yakunlash oynasida eslatma chiqadi.
- **🏁 Kunni yakunlash:** Qo‘ldagi naqd pulni sanab kassa bilan solishtirish (kamomad/ortiqcha) va qoldiqni keyingi kunga o‘tkazish.

### 4. 📊 Hisobotlar & Jonli Formulali `.xlsx` Excel Eksporti
- **Davriy analitika:** **Bugungi**, **7 kun**, **30 kun**, **Shu oy** va **O'tgan oy** hisobotlari (jami kg, tushum, tannarx, sof foyda, marja `%`, to‘lov turlari va xarajatlar).
- **Professional Excel fayllar (`OpenPyXL`):**
  - **Kunlik & Davriy 4 varaqli Excel:** Barcha jadvallarda jonli `=SUM(...)` (`JAMI`) va satr formulalari, raqamli `0.0%` marja, `Kirim (+)` / `Chiqim (-)` va xarajat `Kategoriya`si, hoshiyalar, zebra ranglar, muzlatilgan sarlavha, filtr va A4 chop etish sozlamalari.
  - **Cheklanmagan Akt Sverka:** 100 qator cheklovisiz to‘liq xronologik tarix, jonli qoldiq formulasi (`=H...+F...-G...`) — mijozga yuborish uchun tannarxsiz toza ko‘rinishda.

### 5. 🏢 Multi-Tenant SaaS, `/superadmin` & Super Admin `/menu`
- **Har bir mijozga alohida izolyatsiyalangan baza (`tenant_id`):** Har bir filial o‘z mahsulotlari, mijozlari, guruhlari, kassasi, obunasi va sozlamalariga ega. Super Admin `#1 Test Filial` da qoladi.
- **Telegramdan Odam Tanlash (`KeyboardButtonRequestUsers`):** Alohida ID aniqlovchi botsiz, **«👤 Telegramdan odam tanlash»** tugmasi orqali kontakt ro‘yxatidan odam tanlanadi — bot ID va profilini avto oladi (shuningdek forward va qo‘lda `ID Ism` kiritish ham ishlaydi).
- **Foydalanuvchi & Filial Boshqaruvi:** Rolni almashtirish (`owner` ↔ `staff`), xodimni boshqa filialga ko‘chirish, har bir filial uchun alohida tarif/grace/avto-tasdiq/yaxlitlash & **kunlik AI limit** (`ai_daily_limit`) sozlamalari (`sa:settings`), **Umumiy SaaS MRR & Analitika** (`sa:analytics`), 30 kunlik AI sarfini ko‘rish, barcha foydalanuvchilarga e’lon (`sa:broadcast`), tanlangan filialni tozalash (`/clear`) yoki o‘chirish.
- **Maxsus Komandalar Chegarasi:** `BotCommandScopeChat` orqali `/menu`, `/superadmin`, `/clear` faqat Super Admin menyusida chiqadi va boshqalar uchun yopiq bo‘ladi.
- **Barqaror DB FSM Xotira (`fsm_states`):** Barcha kiritish bosqichlari (FSM holatlari) PostgreSQL/SQLite da saqlanadi va konteyner qayta yonganda ham o‘chib ketmaydi.
- **Kunlik Avtomatik Zaxira (`norin-backup`):** Har 24 soatda PostgreSQL bazasidan gzip siqilgan `pg_dump` olib, 14 kunlik nusxalarni saqlaydi.

---

## 🤖 Buyruqlar Ro‘yxati

| Buyruq | Kimlar uchun | Vazifasi |
|---|---|---|
| `/start` | Barcha ruxsat etilganlar | Asosiy menyu va guruh bog‘lash (`startgroup`) |
| `/myid` | Barcha foydalanuvchilar | Telegram foydalanuvchi va chat ID sini ko‘rsatish |
| `/cancel` | Barcha foydalanuvchilar | Faol kiritish jarayonini (FSM) bekor qilish |
| `/menu` | **Faqat Super Admin** | Filiallar, foydalanuvchilar, obuna va hisobot uchun tezkor boshqaruv menyusi |
| `/superadmin` | **Faqat Super Admin** | Multi-Tenant SaaS boshqaruv paneli (`/supaeradmin` ham ishlaydi) |
| `/clear` | **Faqat Super Admin** | Tanlangan filial savdolarini yoki bazasini 0 dan tozalash |

---

## 🏗 Tizim Arxitekturasi

```mermaid
flowchart TD
    U["Telegram DM / Guruhlar"] --> MW["SubscriptionMiddleware (Tenant & Auth Tekshiruvi)"]
    MW --> R["Aiogram 3 Routerlari"]
    R --> CP["clients_products.py (Mijoz, Narx, Mahsulot, Qarz)"]
    R --> WR["wallet_reports.py (Hisobot, Xarajat, Kassa, Excel)"]
    R --> SN["sales_norin.py (Rasm/Ovoz/Matn Sotuv & Tahrir)"]
    R --> SA["superadmin.py (/menu, /superadmin, Tenant & Odamlar)"]
    SN --> AI["gemini_ai.py (Faqat Rasm/Ovoz AI + 0-Token Lokal Matn Parser)"]
    WR --> EX["excel_export.py (OpenPyXL Formulali Excel & Akt Sverka)"]
    CP & WR & SN & SA --> DB["crud.py + SQLAlchemy Async"]
    DB --> PG["PostgreSQL 16 (Multi-Tenant Baza)"]
    PG --> BK["norin-backup (Har 24 soatda pg_dump -> .sql.gz)"]
```

---

## 📁 Loyiha Tuzilmasi

```text
Norin_AI_hisobot/
├── main.py                       # Bot kirish nuqtasi, BotCommandScope, Middleware & Obuna kuzatuvchisi
├── config.py                     # Pydantic Settings (.env konfiguratsiyasi va ADMIN_IDS parseri)
├── requirements.txt              # Python kutubxonalari
├── Dockerfile                    # Production konteyner obrazi (Python 3.12-slim)
├── docker-compose.yml            # norin-postgres + norin-bot + norin-backup (kunlik pg_dump)
├── .env.example                  # Muhit o'zgaruvchilari namunasi
├── REJA.md                       # Dastlabki biznes va arxitektura rejasi
├── README.md                     # Loyiha hujjati
├── database/
│   ├── models.py                 # SQLAlchemy 2.0 ORM modellari (Tenant, Sale, ProductReturn, FSMStateRecord, AIUsageLog)
│   ├── session.py                # Async engine, idempotent PostgreSQL migratsiya & seed
│   ├── fsm_storage.py            # PostgreSQL/SQLite ga asoslangan doimiy FSM holatlar xotirasi
│   └── crud.py                   # Tenant-izolyatsiyali CRUD, qarz/vozvrat/sverka, SaaS MRR, AI limit & hisob-kitob
├── services/
│   ├── gemini_ai.py              # Rasm/Ovoz Gemini AI + 0-token Uzbek matn/caption parseri
│   └── excel_export.py           # Formulali 4 varaqli kunlik/davriy Excel & to'liq Akt Sverka
├── bot/
│   ├── states.py                 # Aiogram FSM holatlari
│   ├── middlewares.py            # Obuna va ruxsat tekshiruvi (DM, guruh va CallbackQuery)
│   ├── keyboards.py              # Reply/Inline tugmalar, Telegram user-picker & Deep-Link
│   ├── ui_helpers.py             # Tezkor parallel callback javoblari va yagona inline UI boshqaruvi
│   └── handlers/
│       ├── __init__.py           # Routerlarni ustuvorlik tartibida ulash
│       ├── superadmin.py         # /menu, /superadmin, /clear, /myid, tenant & odam boshqaruvi
│       ├── clients_products.py   # /start, mahsulotlar, mijozlar, narxlar, guruh ulash, qarzlar
│       ├── wallet_reports.py     # Kunlik/oylik hisobot, xarajat kategoriyasi, kassa, Excel
│       └── sales_norin.py        # AI rasm/ovoz/matn sotuv, caption postavshik, to'lov & tahrir
└── tests/
    └── test_all.py               # Avtomatik Pytest testlar to'plami (20 ta test)
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

### 2-usul: Docker Compose + PostgreSQL 16 + Avtomatik Backup (Production / VPS)

```bash
cp .env.example .env
# .env ichida quyidagicha PostgreSQL ulanishini belgilang:
# POSTGRES_USER=norin
# POSTGRES_PASSWORD=kuchli_parol
# POSTGRES_DB=norin_db
# DATABASE_URL=postgresql+asyncpg://norin:kuchli_parol@norin-postgres:5432/norin_db

docker compose up -d --build
docker compose ps
docker compose logs -f norin-bot
```

> Zaxira fayllari avtomatik ravishda `./data/backups/norin_YYYY-MM-DD_HHMM.sql.gz` ko‘rinishida saqlanadi va 14 kundan eskisi tozalanadi.

---

## ⚙️ Muhit O‘zgaruvchilari (`.env`)

| O‘zgaruvchi | Tavsif | Standart / Namuna |
|---|---|---|
| `BOT_TOKEN` | `@BotFather` dan olingan Telegram bot tokeni | Majburiy |
| `SUPER_ADMIN_IDS` | Loyiha egasi / Super Admin Telegram ID lari (vergul bilan) | `5649321700` |
| `ADMIN_IDS` | `#1` Test filial admin/xodimlari ID lari (ixtiyoriy `:Ism` bilan) | `5649321700:Asad` |
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

Loyihada barcha asosiy modullar (parserlar, 0-token matn rejimi, multi-tenant izolyatsiya, rasm tagidagi postavshik nomi, Excel formulalari, to‘liq Akt Sverka, Vozvrat hisob-kitobi, doimiy DB FSM xotira, kunlik AI limit, SaaS MRR analitika, SQL agregatlar & UI tugmalar xavfsizligi hamda Super Admin funksiyalari) bo‘yicha 23 ta avtomatik test mavjud:

```bash
python -m pytest tests/test_all.py -v
```
