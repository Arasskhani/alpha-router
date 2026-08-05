# برنامهٔ بازنام‌گذاری سراسری Alpha Router

<div dir="rtl">

## وضعیت و قواعد اجرا

- نام نهایی محصول: **Alpha Router**
- وضعیت اجرا: مراحل ۱ تا ۸ در current tree پیاده‌سازی شده‌اند و هنوز commit نشده‌اند؛ مرحلهٔ ۹ و مراحل بعدی اجرا نشده‌اند.
- این سند فقط برنامه است و ایجاد آن مجوز اجرای هیچ مرحله‌ای نیست.
- پیش از شروع **هر مرحله**، تأیید مستقیم با عبارت «مرحلهٔ N تأیید است» گرفته می‌شود.
- پس از هر مرحله، تغییرات و نتایج تست گزارش می‌شوند و اجرا تا تأیید مرحلهٔ بعد متوقف می‌ماند.
- پیش‌فرض پروژه، حذف کامل PostgreSQL، Redis، SeaweedFS، حساب‌ها، نشست‌ها، API Keyها و تنظیمات فعلی است.
- مسیرهای استاندارد `/api` و `/v1` و قرارداد OpenAI-compatible تغییر نمی‌کنند.
- تاریخچهٔ Git نیز بازنویسی می‌شود؛ بنابراین تمام commit hashها تغییر خواهند کرد.

## ماتریس قطعی نام‌گذاری

- نام نمایشی: `Alpha Router`
- PascalCase: `AlphaRouter`
- snake_case: `alpha_router`
- kebab-case: `alpha-router`
- ثابت‌ها و prefixهای بزرگ: `ALPHA_ROUTER`
- API Key prefix: `alpha_router_`
- Gateway master key pattern: `sk-alpha-router-...`
- Cookieها: `alpha_router_session` و `alpha_router_csrf`
- PostgreSQL user/database: `alpha_router`
- S3 bucket: `alpha-router-media`
- Docker image/service slug: `alpha-router`

نام‌های متعلق به سرویس‌ها و استانداردهای خارجی، مانند OpenRouter، OpenAI، LiteLLM، PostgreSQL، Redis، SeaweedFS، SAML، OIDC و S3 تغییر نمی‌کنند.

---

## مرحلهٔ ۰ — ممیزی نهایی خط‌به‌خط

### اقدامات

۱. خواندن تمام فایل‌های first-party دارای tokenهای برند legacy و گونه‌های مرتبط.

۲. خواندن callerها، importerها و قراردادهای متصل، حتی اگر خود فایل نام قدیمی نداشته باشد.

۳. فهرست‌برداری از:

- متن‌های نمایشی
- symbolها و نام فایل‌ها
- Cookieها، Headerها و LocalStorage
- DB table، column، index، FK و enum-like valueها
- Chat markerها و Import/Export formatها
- Docker، Compose، image، volume، network و hostnameها
- اسکریپت‌ها، CI، مستندات و assetها
- branchها، tagها، remoteها و Git LFS

۴. تفکیک موارد واقعی برند از false positiveهایی مانند `alphabetical` یا alpha channel.

### معیار قبولی

- فهرست نهایی دامنه و گروه‌های اتمیک ارائه شده باشد.
- هیچ فایل مرتبطی بدون طبقه‌بندی باقی نمانده باشد.

### گیت

پس از ارائهٔ گزارش، اجرا برای دریافت تأیید مرحلهٔ ۱ متوقف می‌شود.

---

## مرحلهٔ ۱ — Baseline و تست‌های حفاظتی

### Baseline

۱. Python compile/import.

۲. تست‌های حساس Auth، Cookie، CSRF، Gateway، Budget، Chat marker و Export.

۳. اجرای کامل Backend test suite.

۴. اجرای Frontend Vitest.

۵. اجرای TypeScript و Vite production build.

۶. اجرای `docker compose config`.

۷. ثبت Health response و OpenAPI metadata فعلی.

### تست‌های جدید

- Branding constants
- Cookie و API key prefix
- Chat wire markerهای مشترک Frontend/Backend
- Chat Export/Import round-trip
- App attribution
- OpenRouter outbound headerها
- DB schema identifiers
- OpenAPI title، TOTP issuer و Health identity

### فایل‌های محوری

- [`backend/app/config.py`](../backend/app/config.py)
- [`backend/app/main.py`](../backend/app/main.py)
- [`frontend/src/lib/brand.ts`](../frontend/src/lib/brand.ts)

### معیار قبولی

- Baseline قابل تکرار باشد.
- شکست‌های از قبل موجود از شکست‌های ناشی از Rename تفکیک شده باشند.

---

## مرحلهٔ ۲ — هویت مرکزی Backend

### تغییرات

- `app_name` و OpenAPI title
- Health service به `alpha-router`
- logger namespaceها به `alpha_router.*`
- ایمیل‌های داخلی به دامنهٔ `alpha-router.local`
- User-Agent به `AlphaRouter/...`
- `X-Title` به `Alpha Router`
- TOTP issuer
- App attribution و نام‌های Activity/Logs
- نام Sandbox Broker
- نام فایل‌ها و prefixهای موقت Code Interpreter

### تست‌ها

- Python compile/import
- Health و OpenAPI
- TOTP
- Attribution و outbound headerها
- Production guard
- اسکن نام قدیمی در Backend metadata

---

## مرحلهٔ ۳ — بازنام‌گذاری Database و مدل دامنه

### نگاشت به قرارداد canonical

- مدل‌ها، tableها، columnها، FKها و sourceها از ماتریس قطعی نام‌گذاری پیروی می‌کنند.
- Report IDها، functionها، raw SQLها، indexها و DB monitor labelها هم‌نام شده‌اند.
- migrationهای branding و سایر migrationهای تاریخی در پاک‌سازی Greenfield حذف شده‌اند.

### فایل‌های محوری

- [`backend/app/models/api_key.py`](../backend/app/models/api_key.py)
- [`backend/app/models/logging.py`](../backend/app/models/logging.py)
- [`backend/app/db_migrate.py`](../backend/app/db_migrate.py)
- [`backend/app/services/budget_reservation_service.py`](../backend/app/services/budget_reservation_service.py)

### تست‌ها

- ساخت schema در DB تازه
- ORM و raw SQL
- Billing و Budget Reservation
- Reports، Logs و Activity
- اسکن نبود table، column و source قدیمی

---

## مرحلهٔ ۴ — Auth، Cookie و API Keys

### قرارداد canonical

- Cookieهای Session و CSRF فقط نام‌های ماتریس قطعی را تولید و مصرف می‌کنند.
- نام‌های تاریخی Cookie فقط در denylist متمرکزِ تنظیمات Production باقی می‌مانند.
- OIDC state cookie
- Connector OAuth state cookie
- API key prefix به `alpha_router_`
- Gateway master key pattern
- custom Headerهای متعلق به پروژه
- API JSON fieldهای اختصاصی دارای prefix قطعی `alpha_router`
- Frontend CSRF cookie reader
- Production insecure-default detection

مسیرهای `/api` و `/v1` و Headerهای استاندارد مانند `Authorization`، `X-CSRF-Token` و `X-OpenRouter-Title` تغییر نمی‌کنند.

### تست‌ها

- Login و Logout
- CSRF
- JWT revocation
- OIDC/SAML state
- Connector OAuth state
- Gateway authentication
- رد شدن Cookie و API Key قدیمی

---

## مرحلهٔ ۵ — Chat، Media و فرمت‌های ذخیره‌سازی

### قرارداد canonical

- تمام markerهای Image، Pending، Attachment و Audio فقط prefix نهایی را دارند.
- parserهای branding تاریخی حذف شده‌اند.
- فرمت Export فقط slug نهایی را می‌پذیرد.
- نام فایل‌های Export و Download
- media URL helperها
- `client_app` و image analytics filters
- IndexedDB، BroadcastChannel، Web Lock و CustomEventها

### تست‌ها

- round-trip تمام markerها
- Chat Export/Import
- Import فرمت‌های ChatGPT و Open WebUI
- Image، Audio و Attachment
- Code Interpreter
- Media authorization و URL parsing
- هماهنگی parserهای Frontend و Backend

---

## مرحلهٔ ۶ — Frontend و UI/UX

### تغییرات

- `PRODUCT_NAME = "Alpha Router"`
- Logo component و asset آن فقط نام canonical دارند.
- تمام CSS classها و CSS variableهای اختصاصی پروژه
- Login، Topbar، browser title و disclaimer
- متن خطاها و Confirm dialogها
- LocalStorage و sessionStorage keyها
- IndexedDB و Private Mode
- package name به `alpha-router-ui`
- Vite plugin و Persian font familyها
- Download filenameها
- regeneration کامل generated files و `dist`

### فایل‌های محوری

- [`frontend/src/lib/brand.ts`](../frontend/src/lib/brand.ts)
- [`frontend/src/components/AlphaRouterLogo.tsx`](../frontend/src/components/AlphaRouterLogo.tsx)
- [`frontend/src/styles.css`](../frontend/src/styles.css)
- [`frontend/src/components/ChatPanel.tsx`](../frontend/src/components/ChatPanel.tsx)

### تست‌ها

- Vitest
- TypeScript build
- Vite production build
- اسکن bundle
- بررسی asset referenceها

---

## مرحلهٔ ۷ — مستندات Admin و User (تکمیل‌شده، بدون commit)

### تغییرات

- Admin Guide
- User Manual
- نمودار معماری
- Security Operations Runbook
- Security Auditها با نام‌های canonical:
  - `ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT.md`
  - `ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT.html`
  - `ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT_FA.html`
  - `ALPHA_ROUTER_SECURITY_AUDIT_FINAL_REPORT.html`
- `CLAUDE.md` و `AGENTS.md`
- مثال‌های Curl و متغیرهایی مانند `$ALPHA_ROUTER_BASE`
- Cookie، API Key، DB و Docker topology
- anchorهایی مانند `why-alpha-router`
- title، accessibility label و metadata

### فایل‌های محوری

- [`frontend/src/pages/admin/docs/sections.tsx`](../frontend/src/pages/admin/docs/sections.tsx)
- [`frontend/src/pages/user/docs/sections.tsx`](../frontend/src/pages/user/docs/sections.tsx)
- [`frontend/src/components/docs/AdminArchitectureDiagram.tsx`](../frontend/src/components/docs/AdminArchitectureDiagram.tsx)
- [`docs/SECURITY_OPERATIONS_RUNBOOK.md`](SECURITY_OPERATIONS_RUNBOOK.md)
- [`docs/ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT.md`](ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT.md)
- [`docs/ALPHA_ROUTER_SECURITY_AUDIT_FINAL_REPORT.html`](ALPHA_ROUTER_SECURITY_AUDIT_FINAL_REPORT.html)
- [`CLAUDE.md`](../CLAUDE.md)
- [`AGENTS.md`](../AGENTS.md)

### تست‌ها

- اسکن متن مستندات
- Frontend build
- کنترل anchorها و لینک‌های داخلی
- بازبینی دستی Admin Guide و User Manual

---

## مرحلهٔ ۸ — Docker، PostgreSQL، SeaweedFS و عملیات (تکمیل‌شده، بدون commit)

### تغییرات

- Compose project: `alpha-router`
- App service/image: `alpha-router`
- Sandbox imageها و container prefixها
- Volumeهای `alpha_router_pg`، `alpha_router_redis` و `alpha_router_seaweedfs`
- PostgreSQL user/database: `alpha_router`
- S3 bucket: `alpha-router-media`
- Unix user/home: `alpha_router`
- Networkهای اختصاصی
- `.env.example` و `.env` محلی بدون افشای Secretها
- Dockerfileها، healthcheckها و PgBouncer
- تمام PowerShell و shell scriptها
- Backup و object-storage security scripts

### فایل‌های محوری

- [`docker-compose.yml`](../docker-compose.yml)
- [`Dockerfile`](../Dockerfile)
- [`backend/app/sandbox_broker.py`](../backend/app/sandbox_broker.py)
- [`deploy/seaweedfs/entrypoint.sh`](../deploy/seaweedfs/entrypoint.sh)
- [`.env.example`](../.env.example)

### تست‌ها

- `docker compose config`
- Build هر سه image
- بررسی dependencyها و hostnameها
- بررسی healthcheckها
- اسکن نام‌های قدیمی در فایل‌های استقرار

---

## مرحلهٔ ۹ — پاک‌سازی سراسری Current Tree

### اقدامات

۱. Rename تمام فایل‌ها و مسیرهای دارای نام قدیمی.

۲. حذف compatibility codeهای سه هویت تاریخی که با Greenfield reset دیگر کاربرد ندارند.

۳. جست‌وجوی case-insensitive در کل repository.

۴. بررسی دستی هر match برای جلوگیری از تغییر dependencyها و مفاهیم عمومی.

۵. بازسازی lockfile، generated assets و Frontend bundle.

### معیار قبولی

- هیچ استفادهٔ متعلق به برند قدیمی در current tree باقی نمانده باشد.
- false positiveهای باقی‌مانده در allowlist مستند شده باشند.

---

## مرحلهٔ ۱۰ — تست خودکار کامل پیش از حذف داده

ترتیب تست:

۱. تست‌های Rename-sensitive

۲. Python compile/import

۳. کل Backend test suite

۴. PostgreSQL reservation canary در صورت دسترسی

۵. Frontend Vitest

۶. TypeScript و Vite build

۷. Docker Compose config

۸. ساخت کامل imageها

۹. اسکن نهایی نام‌ها، فایل‌ها و generated output

هر failure گزارش می‌شود و اصلاح آن فقط پس از تأیید مستقیم انجام خواهد شد.

---

## مرحلهٔ ۱۱ — حذف غیرقابل‌بازگشت داده و Fresh Stack

### هشدار

این مرحله PostgreSQL، Redis، SeaweedFS، کاربران، API Keyها، نشست‌ها، Media و تنظیمات فعلی را غیرقابل‌بازگشت حذف می‌کند؛ مگر اینکه پیش‌تر backup گرفته شده باشد.

### اقدامات

- توقف Stack
- `docker compose down -v --remove-orphans`
- حذف Volumeها و Imageهای قدیمی
- ساخت `.env` جدید با نام‌ها و Secretهای تازه
- Build و Boot Stack جدید
- ساخت DB schema تازه
- ساخت S3 bucket تازه
- Bootstrap حساب Admin جدید

### تست‌ها

- سلامت تمام Containerها
- PostgreSQL و PgBouncer
- schema جدید
- Redis
- SeaweedFS/S3 upload-download-delete
- Production guard
- Health و Login page

برای اجرای این مرحله یک تأیید مخرب مستقل گرفته می‌شود.

---

## مرحلهٔ ۱۲ — تست دستی توسط مالک پروژه

موارد زیر باید توسط کاربر یا با دسترسی مستقیم او آزمایش شوند:

۱. نمایش Alpha Router در Login، Topbar و browser title.

۲. Responsive بودن لوگو در Desktop و Mobile.

۳. Login، Logout و Cookieهای جدید.

۴. CSRF روی عملیات POST.

۵. Theme و تنظیمات پس از Refresh.

۶. Private Mode و IndexedDB.

۷. هماهنگی Chat در دو Tab.

۸. Chat streaming، Stop و queue.

۹. Image generation.

۱۰. Attachment، Audio و Code Interpreter.

۱۱. Media upload/view/download.

۱۲. Chat Export و Import مجدد.

۱۳. Admin Guide، User Manual و anchorها.

۱۴. Activity، API Logs و Reports.

۱۵. ساخت API Key جدید و تست `/v1/models`.

۱۶. Chat Completion و Embeddings از Client خارجی.

۱۷. LDAP، SAML، OIDC، TOTP و Connector OAuth در صورت استفاده.

عامل برای هر مورد دستور دقیق ارائه می‌کند و منتظر نتیجهٔ کاربر می‌ماند.

---

## مرحلهٔ ۱۳ — Commit و بازنویسی تاریخچهٔ Git

### اقدامات

- ساخت backup کامل با `git bundle`
- ایجاد clone آزمایشی جداگانه
- Commit تغییرات با Conventional Commit
- بازنویسی تمام branchها و tagها با `git filter-repo`
- تغییر pathها و محتوای متنی در تاریخچه
- اجرای `git fsck`
- اسکن تمام commitها برای نام قدیمی
- مقایسهٔ current tree بازنویسی‌شده با نسخهٔ تأییدشده

### هشدار

تمام commit hashها تغییر می‌کنند و تمام cloneهای قدیمی باید حذف و دوباره Clone شوند.

Commit و history rewrite هر کدام تأیید مستقل می‌گیرند.

---

## مرحلهٔ ۱۴ — Rename کردن Repository و Force Push

Remote فعلی GitHub هنوز از نام تاریخی repository استفاده می‌کند.

### اقدامات

- Rename repository به `alpha-router`
- به‌روزرسانی Remote URL
- Force-push تمام branchها و tagها
- بررسی branch protection، Actions/CI، Secrets و Webhookها
- تغییر پوشهٔ محلی به `C:\APPS\alpha-router`
- بازکردن Workspace جدید در Cursor
- Clone آزمایشی از صفر
- اجرای Smoke test روی Clone تازه

### هشدار

Force-push شاخهٔ اصلی عملیات بسیار پرریسکی است و فقط با تأیید صریح همان مرحله اجرا می‌شود.

---

## معیار نهایی موفقیت

- Current tree فاقد نام قدیمی محصول باشد.
- تمام تاریخچهٔ Git بازنویسی و بررسی شده باشد.
- تمام شناسه‌های پروژه از Naming Matrix جدید پیروی کنند.
- DB، Storage، Cookie، API Key، Docker و UI فقط هویت جدید داشته باشند.
- `/api`، `/v1` و قراردادهای استاندارد خارجی سالم بمانند.
- تمام تست‌های Backend، Frontend و Docker سبز باشند.
- تست دستی مالک پروژه کامل شده باشد.
- Clone تازه از repository جدید بتواند Stack را از صفر اجرا کند.

</div>
