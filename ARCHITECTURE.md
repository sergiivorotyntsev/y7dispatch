# ARCHITECTURE.md — Y7Dispatch (Vehicle Transport Automation)

> Полная архитектурная документация системы. Последнее обновление: 2026-02-25.

---

## 1. ОБЩЕЕ ОПИСАНИЕ СИСТЕМЫ

### Что это
**Y7Dispatch** — система автоматизации документооборота для диспетчеров автоперевозок. Обрабатывает аукционные документы (Copart, IAA, Manheim), извлекает структурированные данные из PDF, предоставляет UI для ревью, и экспортирует листинги в Central Dispatch API.

### Для кого
| Роль | Что делает в системе |
|------|---------------------|
| **Диспетчер (оператор)** | Проверяет извлечённые данные, корректирует, утверждает для экспорта |
| **Менеджер (PO)** | Контролирует загруженность, проверяет метрики, принимает решения |
| **Система (автоматически)** | Мониторит почту, извлекает данные из PDF, считает расстояния и цены |

### Полный pipeline обработки данных

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    ВХОД: EMAIL / РУЧНАЯ ЗАГРУЗКА                    │
  └─────────────┬──────────────────────────┬────────────────────────────┘
                │                          │
    ┌───────────▼───────────┐   ┌──────────▼──────────┐
    │   Email Worker        │   │  Manual Upload      │
    │   (IMAP/OAuth2)       │   │  (POST /upload)     │
    │                       │   │                     │
    │  1. Poll inbox        │   │  1. Upload PDF      │
    │  2. Filter by rules   │   │  2. SHA256 dedup    │
    │  3. Extract gate pass │   │  3. Classify auction│
    │  4. Classify PDFs     │   │                     │
    │  5. Pick best invoice │   │                     │
    └───────────┬───────────┘   └──────────┬──────────┘
                │                          │
                └──────────┬───────────────┘
                           │
              ┌────────────▼────────────┐
              │  Document + Extraction  │
              │  Run Created in DB      │
              │                         │
              │  documents table        │
              │  extraction_runs table  │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  HaikuExtractor         │
              │  (Claude Haiku API)     │
              │                         │
              │  1. pdfplumber → text   │
              │  2. Send to Claude API  │
              │  3. Parse JSON response │
              │  4. Post-process fields │
              │  5. Store outputs_json  │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  Enrichment             │
              │                         │
              │  • VIN from subject     │
              │  • Gate pass from body  │
              │  • Auction directory    │
              │    lookup (phone/addr)  │
              │  • Load ID generation   │
              │  • Distance calculation │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  REVIEW UI              │
              │  (status: needs_review) │
              │                         │
              │  Диспетчер проверяет:   │
              │  • VIN, Year/Make/Model │
              │  • Pickup location      │
              │  • Warehouse (delivery) │
              │  • Price, dates, terms  │
              │  • Approve / Correct    │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  Preflight Validation   │
              │                         │
              │  Blocking issues:       │
              │  • Missing VIN          │
              │  • Missing pickup city  │
              │  • No warehouse         │
              │  • No price             │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  EXPORT to Central      │
              │  Dispatch API V2        │
              │                         │
              │  1. Build CD payload    │
              │  2. OAuth2 token        │
              │  3. POST /listings      │
              │  4. ETag tracking       │
              │  5. Audit log entry     │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  ВЫХОД: CD Listing      │
              │  (status: exported)     │
              └─────────────────────────┘
```

---

## 2. АРХИТЕКТУРА И СТРУКТУРА ПРОЕКТА

### Паттерн архитектуры
**Модульный монолит** — один процесс FastAPI, разделённый на слои:
- **API Layer** (`api/routes/`) — REST endpoints
- **Service Layer** (`services/`) — бизнес-логика
- **Extraction Layer** (`extractors/`) — парсинг PDF
- **Data Layer** (`api/models.py`, `api/database.py`) — ORM и SQLite
- **Frontend** (`web/src/`) — React SPA, обслуживается тем же сервером

### Дерево файлов с описанием

```
y7dispatch/
│
├── api/                              # ═══ BACKEND (FastAPI) ═══
│   ├── main.py                       # Entry point: app init, middleware, email polling, routes
│   ├── auth.py                       # JWT auth: login, logout, middleware (httpOnly cookies)
│   ├── database.py                   # SQLite connection (get_connection context manager)
│   ├── models.py                     # ORM: 30+ tables, Repository classes, schema init
│   ├── audit_log.py                  # Audit trail: export events, ETag tracking, redaction
│   ├── batch_jobs.py                 # Async batch CD export with semaphore rate limiting
│   ├── batch_queue.py                # Thread-based batch queue (ThreadPoolExecutor)
│   ├── cd_client.py                  # Central Dispatch API V2: OAuth2, ETag, retry
│   ├── mi_client.py                  # CD Market Intelligence pricing API client
│   ├── dlq.py                        # Dead Letter Queue: failed email retry/resolution
│   ├── listing_fields.py             # Field registry: CD field definitions, validation
│   │
│   ├── routes/                       # ═══ REST ENDPOINTS ═══
│   │   ├── documents.py              # Upload, list, get, hold, archive, classify
│   │   ├── extractions.py            # Run extraction, OCR, needs-review list
│   │   ├── reviews.py                # Review items, submit corrections, approve
│   │   ├── exports.py                # CD export: preview, send, batch, preflight
│   │   ├── listings.py               # Load ID generation and tracking
│   │   ├── batch.py                  # Batch approve/hold/archive (max 50)
│   │   ├── warehouses.py             # Warehouse CRUD, YAML sync
│   │   ├── pricing.py                # Price recommendation endpoint
│   │   ├── metrics.py                # Extraction/quality/drift metrics
│   │   ├── health.py                 # Health/ready/live probes
│   │   ├── training.py               # Submit corrections, rules, stats
│   │   ├── credentials.py            # Credential CRUD with test connection
│   │   ├── dlq.py                    # DLQ summary, list, retry, resolve
│   │   ├── attachments.py            # PDF attachment management
│   │   └── integrations/             # External service routes
│   │       ├── email.py              # Email log, scan, process
│   │       ├── email_log.py          # Email history and stats
│   │       ├── cd.py                 # CD integration settings
│   │       ├── oauth.py              # OAuth callback handlers
│   │       ├── sheets.py             # Google Sheets integration
│   │       ├── csv_export.py         # CSV export
│   │       └── utils.py              # Fernet encryption helpers
│   │
│   └── workers/
│       └── email_worker.py           # IMAP polling, attachment classification, PDF processing
│
├── services/                         # ═══ БИЗНЕС-ЛОГИКА ═══
│   ├── haiku_extractor.py            # PRIMARY: Claude Haiku API extraction with prompt caching
│   ├── credential_store.py           # Fernet-encrypted credential storage in SQLite
│   ├── pricing_engine.py             # Transport pricing: MI API + floor/ceiling + urgency
│   ├── distance_service.py           # Distance: Google Maps → OSRM → Haversine fallback
│   ├── auction_directory.py          # 100+ Copart/IAA/Manheim locations (phone, address)
│   ├── cd_exporter.py                # CD payload builder, validator, field mapper
│   ├── central_dispatch.py           # Legacy CD API client (OAuth2)
│   ├── orchestrator.py               # Email → extraction pipeline (legacy)
│   ├── warehouse.py                  # Legacy warehouse router (NJ, GA, CA, TX)
│   ├── idempotency.py                # SHA256-based deduplication
│   ├── correction_rules_service.py   # Learning extraction rules from corrections
│   ├── weather_service.py            # Route weather alerts
│   ├── sheets.py                     # Google Sheets read/write
│   ├── sheets_exporter.py            # Export results to Sheets
│   └── backup_service.py             # Database backup
│
├── extractors/                       # ═══ PDF EXTRACTION PIPELINE ═══
│   ├── base.py                       # BaseExtractor ABC: scoring, VIN/phone/address helpers
│   ├── copart.py                     # Copart Sales Receipt extraction
│   ├── iaa.py                        # IAA Buyer Receipt extraction
│   ├── manheim.py                    # Manheim Bill of Sale + Vehicle Release
│   ├── block_extractor.py            # Layout-aware block-based extraction
│   ├── spatial_parser.py             # Spatial coordinate parsing
│   ├── field_resolver.py             # 5-level field precedence resolution
│   ├── address_parser.py             # US address normalization (50 states)
│   ├── ocr_strategy.py               # OCR fallback (pytesseract + pdf2image)
│   ├── gate_pass.py                  # Gate pass PIN extraction from email body
│   ├── location_classifier.py        # Document region classification
│   ├── location_lookup.py            # Location name disambiguation
│   └── zone_extractor.py             # Zone/region fallback extraction
│
├── web/                              # ═══ FRONTEND (React + Vite) ═══
│   └── src/
│       ├── App.jsx                   # Root: auth check, sidebar, routes
│       ├── api.js                    # API client (100+ endpoints, dedup, 401 handler)
│       ├── pages/
│       │   ├── Documents.jsx         # Production workflow: list, batch ops, export
│       │   ├── Review.jsx            # Field review: 9 sections, approve, export
│       │   ├── EmailLog.jsx          # 2-step email scan: scan → select → process
│       │   ├── Settings.jsx          # 5 tabs: Credentials, Warehouses, CD, Email, Audit
│       │   ├── TestLab.jsx           # Training documents, zone templates
│       │   └── Login.jsx             # JWT authentication form
│       ├── components/
│       │   ├── review/               # 9 review section components
│       │   │   ├── VehicleSection.jsx
│       │   │   ├── PickupSection.jsx
│       │   │   ├── DeliverySection.jsx
│       │   │   ├── DatesSection.jsx
│       │   │   ├── PricingPaymentSection.jsx
│       │   │   ├── AdditionalInfoSection.jsx
│       │   │   ├── ExtractionInfoBar.jsx
│       │   │   ├── ExportActions.jsx
│       │   │   └── EmailContextPanel.jsx
│       │   ├── documents/            # Documents table, filters, modals, batch bar
│       │   ├── settings/             # Settings tabs + SettingsContext
│       │   ├── PreflightBanner.jsx   # Validation: blocking/warning issues
│       │   ├── ExportPreviewModal.jsx # CD payload preview
│       │   └── WeatherIndicator.jsx  # Route weather
│       ├── hooks/
│       │   └── useDocuments.js       # All Documents page state and logic
│       └── utils/
│           └── date.js               # Date parsing (SQLite UTC + RFC 2822)
│
├── tests/                            # ═══ ТЕСТЫ (54 файла, 1286 тестов) ═══
│   ├── conftest.py                   # Fixtures: test DB, TestClient, sample PDFs
│   ├── test_*.py                     # 25 unit/integration test files
│   ├── e2e/                          # 29 E2E test files
│   └── evaluation/                   # Extraction accuracy metrics
│
├── docs/                             # ═══ ДОКУМЕНТАЦИЯ (17 файлов) ═══
│   ├── DEVELOPMENT_JOURNAL.md        # Дневник разработки
│   ├── DEVELOPER_GUIDE.md            # Онбординг разработчика
│   ├── ALGORITHM_SPECIFICATION.md    # Спецификация алгоритмов
│   ├── TECHNICAL_SPEC_V2.md          # CD v2 интеграция
│   └── ...                           # Ещё 13 файлов по доменам
│
├── scripts/                          # Утилиты: диагностика, нагрузочное тестирование
├── data/                             # SQLite базы + uploads + attachments
│   ├── control_panel.db              # Основная БД (815 KB)
│   ├── training.db                   # Данные для обучения (61 KB)
│   └── uploads/                      # Загруженные PDF файлы
│
├── config/
│   └── poll_settings.json            # Настройки email polling
│
├── CLAUDE.md                         # AI context + team rules
├── .env.example                      # Шаблон переменных окружения
├── warehouses.yaml                   # Константы складов (delivery)
├── cd_field_mapping_v2.yaml          # Маппинг полей → CD API
├── cd_defaults.yaml                  # Дефолтные значения для CD
├── Dockerfile                        # Docker контейнер
├── docker-compose.yml                # Локальная разработка
├── pyproject.toml                    # Python 0.2.0, зависимости
└── requirements.txt                  # Пиннованные версии
```

### Диаграмма зависимостей между модулями

```
                    ┌──────────────┐
                    │  api/main.py │  ◄── Entry Point
                    └──────┬───────┘
                           │ registers
          ┌────────────────┼────────────────────┐
          │                │                    │
  ┌───────▼──────┐  ┌─────▼──────┐  ┌──────────▼────────┐
  │ api/routes/* │  │ api/auth   │  │ workers/email_wkr  │
  └───────┬──────┘  └────────────┘  └──────────┬─────────┘
          │                                    │
          │ uses                               │ uses
          │                                    │
  ┌───────▼──────────────────────┐   ┌─────────▼──────────┐
  │  api/models.py (Repository)  │   │ services/           │
  │  api/database.py (SQLite)    │   │  haiku_extractor    │
  │  api/audit_log.py            │   │  credential_store   │
  │  api/listing_fields.py       │   │  distance_service   │
  └───────┬──────────────────────┘   │  pricing_engine     │
          │                          │  auction_directory   │
          │                          └─────────┬───────────┘
          │                                    │
          │              ┌─────────────────────┤
          │              │                     │
  ┌───────▼──────┐  ┌───▼──────────┐  ┌───────▼──────┐
  │  SQLite DB   │  │  extractors/ │  │ External APIs│
  │  (control_   │  │  copart.py   │  │  Claude API  │
  │   panel.db)  │  │  iaa.py      │  │  CD API V2   │
  └──────────────┘  │  manheim.py  │  │  Google Maps │
                    │  base.py     │  │  OSRM        │
                    └──────────────┘  └──────────────┘
```

---

## 3. ТЕХНОЛОГИЧЕСКИЙ СТЕК

### Backend
| Технология | Версия | Назначение |
|-----------|--------|-----------|
| Python | >=3.9 (prod: 3.11-3.12) | Язык backend |
| FastAPI | >=0.100.0 | Web framework (async) |
| Uvicorn | >=0.23.0 | ASGI сервер |
| SQLModel | >=0.0.14 | ORM поверх SQLite |
| Pydantic | >=2.0.0 | Валидация данных |
| pdfplumber | >=0.10.0 | Извлечение текста из PDF |
| anthropic | (latest) | Claude Haiku API клиент |
| httpx | >=0.24.0 | Async HTTP клиент |
| cryptography (Fernet) | (latest) | Шифрование credentials |
| tenacity | >=8.0.0 | Retry логика |
| PyYAML | >=6.0.0 | Парсинг конфигов |
| PyJWT | (latest) | JWT токены |
| bcrypt | (latest) | Хеширование паролей |
| msal | (latest) | Microsoft OAuth2 |

### Frontend
| Технология | Версия | Назначение |
|-----------|--------|-----------|
| React | 18 | UI framework |
| Vite | 5.x | Сборка и dev-сервер |
| Tailwind CSS | 3.x | Стилизация |
| React Router | 6.x | Навигация |

### Внешние API и сервисы
| Сервис | Протокол | Назначение |
|--------|---------|-----------|
| Claude Haiku API | REST (HTTPS) | Извлечение данных из PDF (PRIMARY) |
| Central Dispatch API V2 | REST + OAuth2 | Создание листингов перевозок |
| CD Market Intelligence | REST | Рекомендованные цены перевозки |
| Google Distance Matrix | REST (API key) | Расстояния между точками |
| OSRM (project-osrm.org) | REST (free) | Fallback расстояния (без ключа) |
| Microsoft Graph / IMAP | IMAP + OAuth2 | Получение email с вложениями |
| Google Sheets API | REST + OAuth2 | Опциональный экспорт (legacy) |

### База данных
- **SQLite** (`data/control_panel.db`) — основная, 30+ таблиц
- **SQLite** (`data/training.db`) — данные для обучения
- WAL mode для concurrent reads

---

## 4. КЛЮЧЕВЫЕ АЛГОРИТМЫ И ЛОГИКА

### 4.1 Извлечение данных из PDF (HaikuExtractor)

**Файл:** `services/haiku_extractor.py`
**Модель:** `claude-haiku-4-5-20251001`

```
АЛГОРИТМ:
1. pdfplumber → извлечь текст из каждой страницы PDF
2. Объединить с маркерами "--- Page N ---"
3. Обрезать до MAX_TEXT_LENGTH = 50000 символов
4. Отправить в Claude Haiku API:
   - system prompt (кешируется → 90% экономия)
   - user prompt с текстом документа
5. Получить JSON с 30+ полями
6. Post-processing:
   - IAA lot: убрать "000-" префикс
   - Copart pickup_name: "COPART - {city}"
   - IAA pickup_name: полное имя ветки (напр. "332 - East Bay")
   - Manheim release_date: YYYY-MM-DD / AVAILABLE_NOW / NO_RELEASE_DOCUMENT
7. Retry: 3 попытки с backoff [1s, 3s, 10s]
```

**Prompt caching (Phase 1.6):**
```python
# System prompt кешируется через cache_control
messages = [{
    "role": "user",
    "content": [
        {"type": "text", "text": system_prompt,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": user_prompt}
    ]
}]
# Результат: cache_read_tokens → 90% дешевле
```

### 4.2 Классификация аукциона

**Файл:** `extractors/base.py` → `score(text)`

```
АЛГОРИТМ (Weighted Indicator Scoring):
1. Для каждого аукциона (Copart/IAA/Manheim) — набор индикаторов с весами:
   - Copart: "SOLD THROUGH COPART" (5.0), "copart.com" (4.0), "Copart" (3.0)
   - IAA: "Insurance Auto Auctions" (5.0), "IAAI" (3.0), "Buyer Receipt" (2.0)
   - Manheim: "Manheim" (3.0), "OFFSITE VEHICLE RELEASE" (2.0)
2. score = sum(matched_weights) / sum(all_weights)
3. Порог: SCORE_THRESHOLD = 0.6
4. Приоритет: text content → email subject → filename patterns
```

### 4.3 Приоритет разрешения полей (Field Resolution)

**Файл:** `extractors/field_resolver.py`

```
ПРИОРИТЕТ (от высшего к низшему):
1. USER_OVERRIDE      — ручные правки оператора в Review UI
2. WAREHOUSE_CONST    — константы склада (адрес доставки)
3. AUCTION_CONST      — дефолты аукциона
4. EXTRACTED          — извлечённые из документа значения
5. DEFAULT            — fallback из cd_defaults.yaml

Для каждого поля:
- Строим кандидатов со всех уровней
- Выбираем кандидата с наивысшим приоритетом
- Отслеживаем альтернативы для аудита
```

### 4.4 Расчёт расстояний

**Файл:** `services/distance_service.py`

```
ПРИОРИТЕТ ИСТОЧНИКОВ:
1. Google Distance Matrix (если есть API ключ)
   → POST maps.googleapis.com/maps/api/distancematrix/json
   → Возвращает distance_miles, duration_minutes

2. OSRM (бесплатный, без ключа)
   → GET router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}
   → Нужна ZIP → coordinates конверсия

3. Haversine (fallback)
   → Great-circle distance × 1.3 (road factor)
   → _ZIP3_COORDS: 1000+ ZIP-кодов → (lat, lon)

КЕШИРОВАНИЕ:
- distance_cache таблица в SQLite
- TTL: 7 дней для расстояний
- TTL: 24 часа для цен
```

### 4.5 Расчёт цены перевозки

**Файл:** `services/pricing_engine.py`

```
ФОРМУЛА:
  base_price = avg_dispatch_price + (spread × 0.5)
  adjusted   = base_price × urgency_multiplier
  final      = max(floor, min(ceiling, adjusted))

FLOOR (максимум из):
  - $150 (абсолютный минимум)
  - distance × $0.40/mile
  - avg_dispatch × 0.85

CEILING (минимум из):
  - avg_dispatch × 1.50
  - distance × $2.00/mile (OPEN) или $3.00/mile (ENCLOSED)

МНОЖИТЕЛИ СРОЧНОСТИ:
  STANDARD = 1.00x
  PRIORITY = 1.12x
  URGENT   = 1.25x
```

### 4.6 Дедупликация email

**Файл:** `api/workers/email_worker.py`

```
АЛГОРИТМ:
1. email_log.message_id — UNIQUE constraint → дубли отсекаются на INSERT
2. Thread replies без PDF → skip (In-Reply-To / References headers)
3. Non-vehicle emails → skip (subject filter, если нет VIN)
4. SHA256 хеш PDF файла → documents.sha256 UNIQUE → дубли файлов
```

### 4.7 Классификация вложений email

**Файл:** `api/workers/email_worker.py` → `_classify_and_rank_attachments()`

```
АЛГОРИТМ:
1. Классифицировать каждый PDF по имени файла:
   - "invoice" / "ShowReport" → invoice (для извлечения)
   - Auction listing page → listing_page (сохраняется как вложение)
   - Condition report → condition_report
   - Vehicle release → vehicle_release
   - Banking → banking

2. Если нет явного invoice, а есть unknown PDF:
   - 1 unknown → это invoice
   - Несколько unknowns → САМЫЙ МАЛЕНЬКИЙ по размеру = invoice
     (текстовые PDF ~100-200 KB, фото-листинги ~300-600 KB)

3. Если всё ещё нет invoice → promote listing_page → invoice

4. Content-aware disambiguation:
   - Если несколько invoices → выбрать 1-страничный Buyer Receipt
   - Если invoice 3+ стр. и listing_page 1 стр. → SWAP

Результат: ОДИН extraction run на email
```

### 4.8 Генерация Load ID

**Файл:** `api/routes/listings.py`

```
ФОРМАТ: MDD + first3Make + first2Model + sequence

Примеры:
  M=02, D=25, Make=TOYOTA, Model=PRIUS → 225TOYPR
  Если уже есть → 225TOYPR2, 225TOYPR3, ...
```

### 4.9 Валидация Gate Pass

**Файл:** `extractors/gate_pass.py`, `api/workers/email_worker.py`

```
REGEX паттерны:
  "Gate Pass PIN:\s*(\d{4,8})"
  "Gate Pass Code:\s*([A-Z0-9]{4,12})"
  "PIN:\s*(\d{4,8})"

Источники:
  1. Email body text
  2. PDF document text
  3. Предыдущие extraction runs (inherited)
```

---

## 5. ИЗВЛЕКАЕМЫЕ ДАННЫЕ

### Общие поля (все аукционы)

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|----------|
| `vehicle_vin` | string(17) | **ДА** | VIN номер (ISO 3779, нет I/O/Q) |
| `vehicle_year` | int | **ДА** | Год выпуска (19XX-20XX) |
| `vehicle_make` | string | **ДА** | Производитель (TOYOTA, BMW, ...) |
| `vehicle_model` | string | **ДА** | Модель (PRIUS, X5, ...) |
| `vehicle_lot` | string | нет | Номер лота аукциона |
| `vehicle_color` | string | нет | Цвет |
| `vehicle_type` | enum | нет | SEDAN/SUV/TRUCK/VAN/COUPE/WAGON |
| `vehicle_is_inoperable` | bool | нет | Неподвижное ТС (default: false) |
| `pickup_name` | string | **ДА** | Название точки забора |
| `pickup_address` | string | нет | Адрес |
| `pickup_city` | string | **ДА** | Город |
| `pickup_state` | string(2) | **ДА** | Штат (2 буквы) |
| `pickup_zip` | string(5) | нет | ZIP код |
| `pickup_phone` | string | нет | Телефон аукциона |
| `total_amount` | float | нет | Цена покупки на аукционе |
| `buyer_name` | string | нет | Имя покупателя |
| `seller_name` | string | нет | Имя продавца |
| `gate_pass` | string | нет | PIN для выдачи ТС |

### Специфичные поля Manheim

| Поле | Описание |
|------|----------|
| `manheim_release_date` | YYYY-MM-DD / AVAILABLE_NOW / NO_RELEASE_DOCUMENT |
| `manheim_offsite` | true если ТС не на территории Manheim |
| `offsite_pickup_address/city/state/zip` | Адрес забора если offsite |

### Обработка отсутствующих полей
- Обязательные: **блокируют экспорт** (Preflight validation → blocking issue)
- Необязательные: **warning** в UI, экспорт разрешён
- Default values: из `cd_defaults.yaml` (например trailer_type=OPEN)

---

## 6. ИНТЕГРАЦИИ

### 6.1 Claude Haiku API (Anthropic)
| Параметр | Значение |
|----------|---------|
| Endpoint | `https://api.anthropic.com/v1/messages` |
| Model | `claude-haiku-4-5-20251001` |
| Auth | Header: `x-api-key: {ANTHROPIC_API_KEY}` |
| Credentials var | `ANTHROPIC_API_KEY` или credential_store.anthropic |
| При недоступности | Extraction fails → status=failed, DLQ entry |

### 6.2 Central Dispatch API V2
| Параметр | Значение |
|----------|---------|
| Token URL | `https://id.centraldispatch.com/connect/token` |
| API Base | `https://marketplace-api.centraldispatch.com` |
| Auth | OAuth2 client_credentials (client_id + client_secret) |
| Key endpoints | POST /listings, PUT /listings/id/{id}, GET /listings |
| Credentials vars | `CD_CLIENT_ID`, `CD_CLIENT_SECRET`, `CD_MARKETPLACE_ID` |
| Rate limit | Semaphore (3 concurrent), exponential backoff on 429 |
| ETag | Optimistic concurrency: If-Match header, refresh on 412 |
| При недоступности | Export fails → retry up to 3x → audit_log entry |

### 6.3 Google Distance Matrix
| Параметр | Значение |
|----------|---------|
| Endpoint | `https://maps.googleapis.com/maps/api/distancematrix/json` |
| Auth | API key (query param) |
| Credentials var | `GOOGLE_MAPS_API_KEY` или credential_store.google_maps |
| При недоступности | Fallback → OSRM → Haversine estimate |

### 6.4 OSRM (Open Source Routing Machine)
| Параметр | Значение |
|----------|---------|
| Endpoint | `http://router.project-osrm.org/route/v1/driving/` |
| Auth | Без аутентификации (публичный) |
| При недоступности | Fallback → Haversine × 1.3 |

### 6.5 Microsoft 365 Email (IMAP + OAuth2)
| Параметр | Значение |
|----------|---------|
| Protocol | IMAP over SSL (port 993) |
| Auth | OAuth2 client_credentials (MSAL) |
| Credentials vars | `EMAIL_TENANT_ID`, `EMAIL_CLIENT_ID`, `EMAIL_CLIENT_SECRET` |
| Mode | **READ-ONLY** — не перемещает и не удаляет письма |
| При недоступности | Poll fails → retry on next interval |

### 6.6 Google Sheets (опционально, legacy)
| Параметр | Значение |
|----------|---------|
| Auth | Service Account (credentials.json) |
| Credentials var | `SHEETS_SPREADSHEET_ID`, `SHEETS_CREDENTIALS_FILE` |
| При недоступности | Sheets export skipped, main flow continues |

---

## 7. ОБРАБОТКА ОШИБОК И НАДЁЖНОСТЬ

### Типы ошибок

| Тип | Обработка | Файл |
|-----|-----------|------|
| Corrupted PDF | DLQ entry + status=failed | email_worker.py |
| Extraction failed | Retry 3x, then DLQ | haiku_extractor.py |
| CD API 429 | Exponential backoff, Retry-After header | cd_client.py |
| CD API 409 | Find existing listing by partnerReferenceId | cd_client.py |
| CD API 412 | Refresh ETag, retry | cd_client.py |
| OAuth2 token expired | Auto-refresh, retry request | cd_client.py |
| Duplicate email | UNIQUE constraint → skip (idempotent) | email_worker.py |
| Scanned PDF (no text) | OCR via pytesseract + pdf2image | ocr_strategy.py |
| Non-vehicle email | Subject filter → skip | email_worker.py |

### Retry логика
```python
# HaikuExtractor: 3 попытки
RETRY_DELAYS = [1, 3, 10]  # секунды

# CD API: 3 попытки
CD_RETRY_ATTEMPTS = 3
CD_BACKOFF_BASE = 2.0
CD_BACKOFF_MAX = 30.0

# Email polling: каждые N минут (настраивается)
```

### Idempotency
- `email_log.message_id` — UNIQUE → duplicate emails rejected
- `documents.sha256` — UNIQUE → duplicate PDFs rejected
- CD API: `idempotency_key` header → prevents double-posting
- `partnerReferenceId` → stable ref per doc+run (CD-{doc_id}-{run_id}-{hash[:8]})

### Логи
- Python logging → stdout
- `LOG_LEVEL` env var (default: INFO)
- `email_activity_log` table — email processing history
- `integration_audit_log` table — export event audit trail
- Each API request gets unique `request_id` (ContextVar)

### При падении системы
- **Данные не теряются** — SQLite WAL mode, all writes committed
- **Email inbox не изменяется** — READ-ONLY mode
- **Restart safe** — idempotency keys prevent re-processing
- **DLQ** — failed items queued for manual resolution

---

## 8. КОНФИГУРАЦИЯ И ДЕПЛОЙ

### Переменные окружения (.env)

```bash
# === ОБЯЗАТЕЛЬНЫЕ ===
DATABASE_PATH=data/control_panel.db     # Путь к SQLite
ANTHROPIC_API_KEY=sk-ant-...            # Claude API ключ
AUTH_USERNAME=sergii                     # Логин
AUTH_PASSWORD_HASH=$2b$12$...           # bcrypt хеш пароля
JWT_SECRET=64-char-hex-string           # Секрет для JWT токенов
JWT_EXPIRE_HOURS=24                     # Время жизни сессии

# === РЕКОМЕНДУЕМЫЕ ===
CORS_ORIGINS=http://localhost:3000      # Разрешённые origins
COOKIE_SECURE=true                      # HTTPS only cookies (false для dev)

# === CD EXPORT (если нужен экспорт) ===
CD_CLIENT_ID=your-cd-client-id
CD_CLIENT_SECRET=your-cd-client-secret
CD_MARKETPLACE_ID=10000

# === ОПЦИОНАЛЬНЫЕ ===
GOOGLE_MAPS_API_KEY=...                 # Для точных расстояний (fallback: OSRM)
SHEETS_ENABLED=false                    # Google Sheets интеграция
LOG_LEVEL=INFO                          # DEBUG/INFO/WARNING/ERROR
TEMP_DIR=/tmp/dispatch                  # Временные файлы
```

### Запуск с нуля

```bash
# 1. Установка Python зависимостей
pip install -e ".[dev]"

# 2. Настройка аутентификации
python scripts/setup_auth.py

# 3. Создание .env файла
cp .env.example .env
# Заполнить ANTHROPIC_API_KEY, JWT_SECRET, AUTH_PASSWORD_HASH

# 4. Запуск backend
uvicorn api.main:app --reload --port 8000
# При первом старте автоматически создаются все таблицы и seed данные

# 5. Запуск frontend (в другом терминале)
cd web && npm install && npm run dev

# 6. Проверка
curl http://localhost:8000/health
# → {"status": "healthy", "checks": {...}}
```

### Docker

```bash
# Сборка и запуск
docker compose up -d

# Проверка
docker compose logs app
curl http://localhost:8000/health
```

### Предварительные условия
- Python >=3.9 (рекомендуется 3.11+)
- Node.js >=18 (для frontend)
- Для OCR (опционально): Tesseract OCR + Poppler

---

## 9. ОПТИМИЗАЦИИ В КОДЕ

### Реализованные оптимизации

| Оптимизация | Файл | Эффект |
|------------|------|--------|
| **Prompt caching** | haiku_extractor.py | 90% снижение стоимости Claude API |
| **Distance cache (7d)** | distance_service.py | Минимизация Google Maps вызовов |
| **Price cache (24h)** | pricing_engine.py | Минимизация MI API вызовов |
| **Email dedup** | email_worker.py | message_id + SHA256 → нет повторной обработки |
| **JOIN вместо N+1** | documents.py (list) | Один SQL запрос с LEFT JOIN вместо N запросов |
| **Singleton extractors** | haiku_extractor.py | get_haiku_extractor() → ленивая инициализация |
| **In-flight request dedup** | web/src/api.js | GET запросы к тому же URL → одна Promise |
| **Session storage cache** | useDocuments.js | Кеш документов в sessionStorage |
| **Attachment classification** | email_worker.py | 1 extraction run на email вместо N |
| **Background email polling** | main.py | asyncio task, не блокирует API |

### Нагрузка 10-20 запросов в день
Текущая архитектура **более чем достаточна**:
- SQLite справляется с тысячами записей
- Claude Haiku API: ~2-5 сек на документ
- Bottleneck: Claude API latency (не параллелится в текущей реализации)

### Для масштабирования до 20-30+ запросов
Ничего менять не нужно. Текущие лимиты:
- SQLite: до ~1000 concurrent reads (WAL mode)
- Claude API: batch mode можно включить
- CD API: semaphore уже ограничен на 3 concurrent

### Узкие места (bottlenecks)
1. **Claude API latency** (2-5 сек) — можно параллелить batch extraction
2. **Single-threaded email polling** — не проблема при 20-30 emails/day
3. **SQLite write lock** — не проблема при текущих объёмах

---

## 10. НЮАНСЫ И EDGE CASES

### Различия форматов аукционов

| Аукцион | Формат документа | Особенности |
|---------|-----------------|-------------|
| **Copart** | Sales Receipt / Bill of Sale | LOT#: XXXXXXXX, "SOLD THROUGH COPART", pickup_name = "COPART - {city}" |
| **IAA** | Buyer Receipt | StockNo с "000-" префиксом (убирается), pickup = полное имя ветки |
| **Manheim** | Bill of Sale + Vehicle Release | release_date, offsite pickup, "AVAILABLE_NOW" vs дата |

### Обработка email thread replies
- `In-Reply-To` / `References` headers → определение reply
- Reply без нового PDF → skip (status=skipped, reason="Thread reply without PDF")
- Reply с новым PDF → обрабатывается нормально

### Повреждённые PDF
- pdfplumber не может открыть → `extract_text_from_pdf` возвращает `("", 0)` → extraction fails → DLQ entry
- Слишком мало текста:
  - `< 50 chars` (haiku_extractor.py) → short-circuit, API не вызывается, `result.error = "Insufficient text extracted from document"`
  - `< 100 chars` (extractors/base.py `MIN_TEXT_LENGTH`) → `score()` возвращает 0.0, `needs_ocr = True`
- Текст длиннее `MAX_TEXT_LENGTH = 50000` символов → молчаливо обрезается с `logger.warning`
- JSON ответ от Claude не парсится → 3-уровневый fallback:
  1. Убрать markdown code fences (` ```json ``` `), затем `json.loads()`
  2. Найти первый `{` и последний `}`, попробовать `json.loads()` на подстроке
  3. Вернуть `None` → extraction fails

### Scanned PDFs и OCR fallback

**Файл:** `extractors/ocr_strategy.py`

OCR решение принимается через оценку качества извлечённого текста:

| Параметр | Значение |
|----------|---------|
| `MIN_CHARS_GOOD` | 200 символов |
| `MIN_CHARS_USABLE` | 50 символов |
| `MIN_WORDS_GOOD` | 30 слов |
| `MIN_ALPHA_RATIO` | 0.5 (50% текста — буквы) |
| `MAX_GARBLED_RATIO` | 0.1 (10% нечитаемых символов) |

**Уровни качества и действия:**

| Качество | Условие | Действие |
|----------|---------|----------|
| `UNUSABLE` | `< 50 chars` ИЛИ `garbled > 20%` | → OCR (pytesseract + pdf2image) |
| `POOR` | `< 200 chars` ИЛИ `alpha_ratio < 0.5` | → HYBRID (OCR + native) если нет VIN и дат; иначе OCR |
| `GOOD` | `>= 30 слов` И `garbled < 10%` | → NATIVE (без OCR) |
| `EXCELLENT` | VIN найден И даты найдены И `>= 30 слов` И `garbled < 10%` | → NATIVE |

**Garbled detection:** regex `[^\x00-\x7F]|[\x00-\x08\x0B\x0C\x0E-\x1F]` — non-ASCII + control characters.

**Зависимости OCR:** Tesseract OCR + Poppler (pdf2image) — опциональные, без них OCR fallback недоступен.

### VIN валидация (ISO 3779)

**Regex:** `\b[A-HJ-NPR-Z0-9]{17}\b` (используется одинаково в 3 модулях)

| Правило | Реализация |
|---------|-----------|
| Ровно 17 символов | `{17}` в regex |
| Нет I, O, Q | Диапазоны `A-H`, `J-N`, `P-R`, `S-Z` исключают эти буквы |
| Word boundaries | `\b` предотвращает частичные совпадения внутри строк |
| Регистр | Subject email приводится к UPPER перед поиском |

**Источники VIN (по приоритету):**
1. Извлечение из PDF через Claude Haiku API
2. Email subject line (fallback) — записывается в `outputs_json` с `vin_source = "email_subject"` только если VIN из PDF отсутствует

**Ограничения:** Валидация только структурная (17 символов, допустимый алфавит). Check digit (позиция 9) не проверяется. Невалидный VIN с правильным форматом пройдёт валидацию.

### Множественные документы в одном email

**Файл:** `api/workers/email_worker.py` → `_classify_and_rank_attachments()`

**7-шаговый каскад выбора invoice для extraction:**

```
Шаг 1: Классификация по имени файла
  ├── banking (wire/ach/bank/payment) → НИКОГДА не извлекается
  ├── invoice (invoice.pdf, bill_of_sale.pdf, ShowReport*) → кандидат
  ├── listing_page (run and drive, for auction, enhanced vehicle) → вложение
  ├── condition_report (condition, inspection) → вложение
  ├── vehicle_release (release, onsite) → вложение
  └── unknown → решается на шаге 2

Шаг 2: Resolve unknowns
  ├── 1 unknown + нет invoice → unknown = invoice
  └── N unknowns + нет invoice → САМЫЙ МАЛЕНЬКИЙ по bytes = invoice, остальные = listing_page
      (текстовые PDF ~100-200 KB, фото-листинги ~300-600 KB)

Шаг 3: Промоция если invoice всё ещё нет
  └── listing_page → invoice → condition_report → invoice

Шаг 4: Если несколько invoices → _pick_best_invoice()
  ├── Подсчёт страниц: regex scan "/Type /Page" минус "/Type /Pages" в raw bytes
  ├── Предпочтение: 1-страничный PDF (IAA Buyer Receipt ~145-170 KB)
  └── Остальные invoices → listing_page

Шаг 5: Swap check
  └── Если invoice ≥ 3 страницы И есть listing_page = 1 страница → SWAP

Шаг 6: Inoperable detection по имени файла
  ├── "run_and_drive" / "runs_and_drives" → operable
  └── "inop" / "non_run" / "does_not_run" → inoperable

Шаг 7: Сохранение attachment-ов (не invoice) в attachments таблицу
```

**Результат:** ОДИН extraction run на email, остальные PDF сохраняются как вложения.

### Форматы gate pass кодов

**Файл:** `extractors/gate_pass.py`, `api/workers/email_worker.py`

**Извлечение из email body** (email_worker.py, 4 паттерна, case-insensitive):

| Приоритет | Паттерн | Пример |
|-----------|---------|--------|
| 1 | `gate\s*pass\s*(?:pin\|code\|#\|number)\s*[:\-]?\s*([A-Z0-9]{2,10})` | "Gate Pass Pin: D164" |
| 2 | `gate\s*pass\s*[:\-]\s*([A-Z0-9]{2,10})` | "Gate Pass: D164" |
| 3 | `gate\s*pass\s*(?:is)\s+([A-Z0-9]{2,10})` | "Gate Pass is D164" |
| 4 | `\bpin\s*[:\-]\s*([A-Z0-9]{2,10})` | "PIN: D164" |

**Извлечение из PDF** (gate_pass.py, по специфичности):

| Источник | Паттерн |
|----------|---------|
| IAA | `IAA Gate Pass #: XXXX` (требует слово "IAA"/"IAAI" перед "Gate Pass") |
| Copart | `Copart Release Code: XXXX`, `Lot Pin: XXXX` |
| Manheim | `Release ID: XXXX`, `Pickup Code: XXXX` |
| Generic | `Gate Pass: XXXX`, `Release Code: XXXX`, `Access PIN: XXXX`, `Auth Code: XXXX`, `Pass Code: XXXX` |

**Валидация кода:**
- Длина: 2-10 символов (email body) или 4-20 символов (gate_pass.py)
- Допустимые символы: `[A-Z0-9]` (email body) или `[A-Z0-9-]` (gate_pass.py, дефис разрешён)
- Стоп-слова (email body): `{'pin', 'pass', 'gate', 'the', 'is', 'see'}`
- Стоп-слова (gate_pass.py): `{'CODE', 'PASS', 'GATE', 'PIN', 'NONE', 'NULL', 'TEST'}`

**Источники gate pass (по приоритету):**
1. Email body → `email_log.gate_pass` + `outputs_json.gate_pass`
2. PDF text → через gate_pass.py при extraction
3. Предыдущие extraction runs → inherited через `email_log` при re-extraction

### Аукционная локация не найдена в directory

**Файл:** `services/auction_directory.py`

Справочник содержит 100+ локаций Copart/IAA/Manheim с адресами и телефонами.

**Lookup:** `lookup_auction_location(name)` → нормализация имени (lowercase, дефисы → пробелы) → точное совпадение по `_LOOKUP_INDEX`.

**Что происходит при неудаче:**
- Функция возвращает `None` молча, без логирования
- Телефон и адрес аукциона НЕ заполняются автоматически
- Извлечённые из PDF pickup_city/state/zip всё ещё используются
- Экспорт в CD разрешён если pickup_city и pickup_state есть из PDF

**Что НЕ поддерживается:**
- Частичное совпадение ("Copart Clearw*") — нет fuzzy matching
- Скобочные суффиксы: "Copart Clearwater (FL)" → не найдёт "Copart Clearwater"
- Запятые: "Copart, Clearwater" → не найдёт "Copart Clearwater"
- Аббревиатуры: "Cpt Clearwater" → не найдёт

### ZIP код не распознан для расстояния

**Файл:** `services/distance_service.py`

**`_zip_to_coords` — каскад разрешения:**
1. ZIP `None` или `< 3` символов → возвращает `None`
2. Первые 3 цифры → поиск в `_ZIP3_COORDS` (550+ записей, покрытие не полное)
3. Не найдено → Google Geocoding API с `"{zip}, USA"` суффиксом
4. Google успешен → **кеширует координаты в runtime** `_ZIP3_COORDS[prefix]` (не персистентно)
5. Google недоступен → возвращает `None`

**Что происходит при `None` координатах:**
- OSRM fallback → `ValueError` (не может построить маршрут)
- Haversine fallback → `DistanceResult(source="unknown", distance_miles=None)`
- Pricing engine → floor = $150 (абсолютный минимум, без per-mile компонента)
- Warehouse options → `float("inf")` distance → склад последний в списке сортировки

**Известные баги в `_ZIP3_COORDS`:**
- `"716"` (Arkansas/Louisiana) → записаны координаты Аляски `(71.3, -156.8)` — расстояние будет радикально неверным
- `"280"`, `"281"`, `"282"` — дублируются в словаре: SC координаты перезаписаны NC координатами

**Обязательный суффикс `, USA`:** Без него Google может интерпретировать US ZIP как почтовый код другой страны.

### Manheim offsite vs onsite pickup различия

**Файлы:** `extractors/manheim.py`, `services/haiku_extractor.py`, `api/routes/extractions.py`

**Определение типа:**
- OFFSITE: текст содержит `"OFFSITE VEHICLE RELEASE"` или `"not located at a Manheim facility"`
- ONSITE: всё остальное (default)

**Поля в зависимости от типа:**

| Поле | ONSITE | OFFSITE |
|------|--------|---------|
| `pickup_name` | Имя объекта Manheim (напр. "Manheim Portland") | Имя продавца / бизнеса |
| `pickup_address/city/state/zip` | Адрес объекта Manheim | Адрес продавца (из offsite полей) |
| `pickup_location_type` | `"AUCTION"` | `"BUSINESS"` (принудительно) |
| `manheim_release_date` | Конкретная дата ИЛИ `"AVAILABLE_NOW"` | Обычно `"AVAILABLE_NOW"` |
| `release_notes` | Нет | `"OFFSITE VEHICLE RELEASE \| Vehicle is not located..."` |

**Propagation offsite полей** (extractions.py):
Когда `manheim_offsite = true`, offsite поля перезаписывают основные pickup поля:
- `pickup_address` ← `offsite_pickup_address`
- `pickup_city` ← `offsite_pickup_city`
- `pickup_state` ← `offsite_pickup_state` (если есть)
- `pickup_zip` ← `offsite_pickup_zip` (если есть)
- Минимальное условие: `offsite_addr` И `offsite_city` должны быть непустыми

**`manheim_release_date` → `available_date` propagation:**

| Значение `manheim_release_date` | Действие |
|--------------------------------|----------|
| `"2026-02-03"` (ISO дата) | `available_date = "2026-02-03"`, confidence 0.95 |
| `"AVAILABLE_NOW"` | `available_date = today`, confidence 0.9 |
| `"NO_RELEASE_DOCUMENT"` | `available_date` НЕ устанавливается, warning: `"No release document found — set available date manually"` |
| `null` | Молча пропускается, `available_date` не устанавливается |

**Если `available_date` не установлен:** В `build_cd_payload` fallback = сегодняшняя дата. Expiration = available_date + 30 дней.

### Edge cases при экспорте в Central Dispatch

**Файлы:** `api/routes/exports.py`, `api/cd_client.py`, `api/batch_jobs.py`

#### Preflight validation (blocking issues)

Перед экспортом `get_blocking_issues()` проверяет обязательные поля:

| Blocking issue | Условие |
|---------------|---------|
| Missing VIN | `vehicle_vin` пустой или null |
| Missing pickup city | `pickup_city` пустой |
| Missing pickup state | `pickup_state` пустой |
| No warehouse | ни `warehouse_id`, ни `delivery_address` |
| No price | `price_total` = 0 или null |

Если хотя бы один blocking issue → batch export пропускает run со статусом `BLOCKED`.

#### 409 Conflict (duplicate listing)

**Два разных обработчика с разным поведением:**

| Обработчик | Файл | Поведение |
|-----------|------|-----------|
| `CDClient.create_listing()` | cd_client.py | На 409 → `_find_existing_listing(ref_id)` → GET по `partnerReferenceId` → возвращает найденный листинг |
| `send_to_cd()` | exports.py | 409 НЕ входит в retryable коды `(429, 500, 502, 503, 504)` → **не ретраится**, возвращает ошибку с raw body |

**Результат:** При прямом вызове `CDClient` — 409 обрабатывается gracefully (восстанавливается существующий листинг). При вызове через `send_to_cd` route — 409 = жёсткая ошибка без retry.

#### 412 Precondition Failed (ETag mismatch)

- Происходит когда листинг был изменён другим пользователем/системой между чтением и обновлением
- `send_to_cd_with_retry` (exports.py): обновляет ETag inline и ретраит (до 3 раз)
- `CDClient.update_listing` (cd_client.py): одна попытка refresh ETag → если GET fails → сразу failure, без оставшихся retries

#### Idempotency на границе часов

`idempotency_key` = `MD5(partnerReferenceId + str(int(time.time() / 3600)))`. Если request начался в 12:59:59 и ретрай произошёл в 13:00:01 — ключ изменится, и CD может создать дубликат.

#### Batch export особенности

| Аспект | Поведение |
|--------|-----------|
| Статус job после failures | Всегда `COMPLETED` (нет `PARTIAL`) — failures видны только в `results_json` |
| Параллелизм | Последовательная обработка items (не параллельная), несмотря на semaphore в send_to_cd |
| Already-exported runs | `/batch-post` route проверяет и пропускает; `BatchJobProcessor` — **НЕ проверяет**, может повторно POST/PUT |
| Test documents | Пропускаются со статусом `SKIPPED` |
| Максимум items | 50 per batch (валидация на route уровне) |

### Известные ограничения системы

#### Архитектурные ограничения
| Ограничение | Причина | Влияние |
|-------------|--------|---------|
| SQLite (single-writer) | Монолитная архитектура | Один процесс записи, WAL mode для concurrent reads |
| Single-threaded email polling | `asyncio` task в main event loop | Не проблема при 20-30 emails/day |
| Нет параллельного extraction | Один PDF за раз через Claude API | Bottleneck 2-5 сек на документ |
| Нет WebSocket/SSE | Frontend polling | Review UI не обновляется в реальном времени |

#### Extraction ограничения
| Ограничение | Детали |
|-------------|--------|
| Только английский текст | Claude Haiku prompt на английском, regex для US адресов |
| Max 50,000 символов на PDF | Молчаливое обрезание, потеря данных в конце длинных документов |
| VIN — только структурная валидация | Check digit (позиция 9) не проверяется |
| OCR зависит от Tesseract + Poppler | Без этих зависимостей scanned PDF не обрабатываются |
| `vehicle_year` fallback = 2020 | Если год не извлечён, в CD payload попадает 2020 без предупреждения |
| Шаблон release notes: literal `{placeholder}` | Если ключ шаблона отсутствует, `{gate_pass}` попадает в payload как текст |

#### Distance/Pricing ограничения
| Ограничение | Детали |
|-------------|--------|
| `_ZIP3_COORDS` — неполное покрытие | ~550 из ~900 возможных ZIP3 префиксов |
| Баг ZIP `"716"` | Координаты Аляски вместо Arkansas — расстояние будет ~4000 миль вместо ~500 |
| Haversine × 1.3 — грубая оценка | Road factor не учитывает горы, реки, отсутствие дорог |
| Enclosed trailer ceiling не пересчитывается | При смене urgency cached результат использует `is_enclosed=False` |
| MI API недоступен → `price=None` | Требуется ручное назначение цены |

#### CD API ограничения
| Ограничение | Детали |
|-------------|--------|
| Idempotency key = hourly | Дубликаты возможны на границе часов |
| 409 в send_to_cd route | Не ретраится (в отличие от CDClient) |
| `partnerReferenceId` max 50 chars | Обрезание без учёта hash суффикса → потеря уникальности |
| Нет jitter в backoff | Concurrent retries не распределяются во времени |
| `Retry-After` как HTTP-date | Не парсится корректно, fallback 5 сек |
| ETag refresh failure → instant break | Одна неудачная попытка refresh → update прекращается |

#### Auction directory ограничения
| Ограничение | Детали |
|-------------|--------|
| Только exact match | Нет fuzzy/partial matching |
| ~100 локаций | Новые локации требуют ручного добавления |
| Нет автообновления | Справочник статичный, в коде |

#### Frontend ограничения
| Ограничение | Детали |
|-------------|--------|
| Tailwind NOT available | Несмотря на наличие в зависимостях, стилизация через inline styles / CSS modules |
| Нет React Context для single-page state | Props-down паттерн: Review.jsx передаёт всё через props |
| sessionStorage cache | Кеш документов не синхронизирован между вкладками |

---

## 11. ИНСТРУКЦИЯ ДЛЯ МЕНЕДЖЕРОВ И ДИСПЕТЧЕРОВ

> Эта секция написана простым языком для сотрудников, которые работают с системой ежедневно, но не являются программистами.

---

### 11.1 Что делает программа (простыми словами)

Y7Dispatch — это программа-помощник для диспетчеров автоперевозок. Когда покупается машина на аукционе (Copart, IAA, Manheim), продавец присылает на почту PDF-документ — чек, счёт или акт продажи. Раньше диспетчер вручную открывал каждый PDF, переписывал оттуда VIN, марку, модель, адрес аукциона, номер лота, и вбивал всё это в Central Dispatch. На один автомобиль уходило 10-15 минут ручной работы.

Теперь программа делает это автоматически: она сама проверяет почту, находит письма с PDF-документами, читает документ с помощью искусственного интеллекта, вытаскивает все нужные данные, рассчитывает расстояние до склада и рекомендует цену перевозки. Диспетчеру остаётся только проверить данные на экране, исправить если что-то не так, и нажать кнопку «Экспорт в Central Dispatch». Вместо 10-15 минут — 1-2 минуты на машину.

---

### 11.2 Что программа делает АВТОМАТИЧЕСКИ

| # | Действие | Раньше (вручную) | Сейчас (автоматически) |
|---|----------|-----------------|----------------------|
| 1 | **Проверка почты** | Диспетчер вручную открывал почту, искал письма с документами среди спама и переписки | Система каждые 5 минут сама проверяет почтовый ящик и находит новые письма с PDF-вложениями |
| 2 | **Скачивание PDF** | Открыть письмо → скачать вложение → сохранить в папку | Система сама скачивает PDF и сохраняет его в базу данных |
| 3 | **Определение аукциона** | Диспетчер по виду документа определял — это Copart, IAA или Manheim | Система автоматически распознаёт тип аукциона по содержимому PDF |
| 4 | **Чтение документа** | Диспетчер читал PDF глазами, искал VIN, марку, модель, адрес | Искусственный интеллект (Claude) читает документ и извлекает 30+ полей данных |
| 5 | **Извлечение VIN** | Вручную копировал 17-значный номер из PDF | Система находит VIN в документе, а если не нашла — ищет в теме письма |
| 6 | **Извлечение Gate Pass** | Вручную искал PIN-код в тексте письма или в документе | Система ищет gate pass в теле письма и в PDF по нескольким шаблонам |
| 7 | **Определение адреса забора** | Вручную искал адрес аукциона, иногда гуглил | Система определяет pickup-адрес из документа + справочник 100+ аукционных локаций с телефонами |
| 8 | **Расчёт расстояния** | Открывал Google Maps, вбивал адреса, записывал мили | Система автоматически считает расстояние через Google Maps (или бесплатный OSRM) |
| 9 | **Рекомендация цены** | Диспетчер по опыту назначал цену или звонил коллегам | Система запрашивает рыночные данные из Central Dispatch Market Intelligence и рекомендует цену |
| 10 | **Генерация Load ID** | Вручную придумывал номер загрузки | Система генерирует уникальный Load ID по формату: месяц + день + марка + модель (напр. 225TOYPR) |
| 11 | **Фильтрация спама** | Диспетчер сам пропускал нерелевантные письма | Система отфильтровывает не-автомобильные письма (обновления аккаунта, подписки, маркетинг) |
| 12 | **Защита от дублей** | Диспетчер мог случайно обработать одно письмо дважды | Система проверяет ID письма и хеш PDF — дубли автоматически отклоняются |
| 13 | **Выбор правильного PDF** | Если в письме несколько вложений — диспетчер вручную выбирал нужный | Система классифицирует все вложения (invoice, listing page, condition report) и выбирает правильный |
| 14 | **Формирование CD-листинга** | Вручную заполнял 30+ полей в Central Dispatch | Система собирает полный payload для CD API из извлечённых данных + дефолтов + данных склада |
| 15 | **Определение даты доступности (Manheim)** | Вручную читал Vehicle Release и определял дату | Система распознаёт release date из документа Manheim и ставит правильную available date |

---

### 11.3 Что программа НЕ делает (ручная работа)

| # | Действие | Почему нельзя автоматизировать |
|---|----------|-------------------------------|
| 1 | **Проверка правильности данных** | ИИ извлекает данные с точностью ~85-95%, но ошибки возможны. Человек должен подтвердить, что VIN, марка, адрес — верные. Ответственность за данные на диспетчере. |
| 2 | **Назначение склада доставки** | Решение о том, на какой склад везти машину — бизнес-решение. Зависит от клиента, загруженности, логистики. Система показывает расстояния и цены для каждого склада, но выбирает человек. |
| 3 | **Утверждение цены перевозки** | Система рекомендует цену на основе рыночных данных, но финальная цена — решение диспетчера. Может зависеть от срочности, отношений с перевозчиком, сезона. |
| 4 | **Работа со сканированными PDF** | Если документ — скан (фото, а не текст), нужен OCR. Качество OCR зависит от качества скана. Иногда нужно вручную ввести данные. |
| 5 | **Обработка нестандартных документов** | Если документ не от Copart/IAA/Manheim или в нестандартном формате — система может не распознать. Нужен ручной ввод. |
| 6 | **Связь с перевозчиками** | Система создаёт листинг в Central Dispatch, но переговоры с перевозчиками ведёт человек. |
| 7 | **Решение проблем с экспортом** | Если Central Dispatch возвращает ошибку (409 дубликат, невалидные данные) — диспетчер должен разобраться и исправить. |
| 8 | **Отслеживание gate pass для Manheim offsite** | Если машина не на территории Manheim — нужен gate pass от продавца. Система не может его запросить сама. |
| 9 | **Проверка после экспорта в CD** | После отправки листинга нужно убедиться, что он появился в CD и данные корректны. Система не проверяет CD-сторону. |
| 10 | **Управление Hold/Pending статусами** | Решение о постановке документа на hold (ожидание gate pass, оплаты, титула) — решение диспетчера. |

---

### 11.4 Ежедневный рабочий процесс диспетчера

#### 1. Утро — что проверить первым делом

1. Откройте программу в браузере и войдите (логин/пароль).
2. Перейдите на страницу **Documents** (первая в боковом меню).
3. Посмотрите на карточки вверху:
   - **Needs Review** (жёлтая) — сколько новых документов ждут проверки. Это ваша основная работа.
   - **Ready to Export** (синяя) — документы, проверенные вчера но не экспортированные.
   - **Failed** (красная, в фильтре статусов) — есть ли ошибки обработки.
4. Если карточка **Needs Review** показывает 0, а вы ожидали документы — перейдите в **Email Log** и проверьте, приходили ли письма (см. секцию 11.7).

#### 2. Обработка новых документов — на что смотреть

1. В таблице документов отфильтруйте статус **Needs Review**.
2. Документы сгруппированы по дате. Начните с самых старых.
3. Для каждого документа в строке таблицы вы видите основные данные: VIN, марку/модель, аукцион, город забора.
4. **Быстрый визуальный контроль прямо в таблице:**
   - VIN заполнен? Если пусто — нажмите **Review** и проверьте вручную.
   - Аукцион определён (синий/зелёный/фиолетовый бейдж)? Если серый "UNKNOWN" — нужно проверить.
   - Город забора есть? Если пусто — данные из документа не извлеклись.
5. Нажмите **Review** (синяя ссылка в колонке Actions) чтобы открыть страницу проверки.

#### 3. Review — какие поля проверять обязательно, какие можно пропустить

**ОБЯЗАТЕЛЬНО проверьте (ошибки здесь = проблемы в Central Dispatch):**
- **VIN** — должен быть 17 символов. Система подсвечивает зелёной галочкой если уверена. Если нет галочки — проверьте по PDF.
- **Year / Make / Model** — должны совпадать с тем, что в документе.
- **Pickup City / State** — откуда забирать. Если город не тот — перевозчик поедет не туда.
- **Warehouse** (склад доставки) — выберите правильный склад. Без склада экспорт невозможен.
- **Price** (цена перевозки) — проверьте, что сумма разумная. Система показывает $/mile рядом.

**ЖЕЛАТЕЛЬНО проверьте (но не критично):**
- **Pickup Name** — название аукционной локации. Если неверное, перевозчик может запутаться.
- **Gate Pass** — PIN-код для забора. Если есть в письме, система уже его подставила.
- **Trailer Type** — OPEN по умолчанию. Для дорогих машин может потребоваться ENCLOSED.
- **Inoperable** — по умолчанию OPERABLE. Если машина не на ходу — переключите.

**МОЖНО пропустить (заполняются автоматически):**
- **Load ID** — генерируется автоматически.
- **Delivery Address** — подтягивается из выбранного склада.
- **Dates** — Available Date заполняется автоматически (сегодня или из release date).
- **Payment Terms** — дефолтные значения из настроек.

#### 4. Экспорт в Central Dispatch — как убедиться что всё правильно

1. После проверки всех полей нажмите кнопку **Approve for Export** (зелёная, внизу страницы Review).
   - Если кнопка неактивна (серая) — выберите склад доставки.
2. Проверьте **Preflight Banner** вверху секции экспорта:
   - **Зелёный** "Ready for Export" — всё в порядке, можно экспортировать.
   - **Красный** — есть блокирующие проблемы. Их нужно исправить (см. секцию 11.9).
   - **Жёлтый** — предупреждения. Экспорт возможен, но стоит проверить.
3. Нажмите **Export to CD** (зелёная кнопка).
4. Откроется модальное окно **Export Preview** — последняя проверка перед отправкой:
   - Просмотрите таблицу всех полей. Красным подсвечены пустые обязательные поля.
   - Каждое поле показывает **источник** (откуда взято): Extracted (из PDF), Warehouse (из склада), Default (дефолт), User Input (ваш ввод).
   - Нажмите **Dry Run** (жёлтая кнопка) — система проверит payload без реальной отправки.
   - Если Dry Run успешен — нажмите **Export to CD** (зелёная кнопка).
5. После успешного экспорта:
   - Статус документа сменится на **Exported** (синий бейдж).
   - Появится CD Listing ID.

**Массовый экспорт:** На странице Documents отметьте чекбоксами нужные документы и нажмите **Export (N)** в синей панели вверху.

#### 5. Конец дня — что проверить перед уходом

1. Отфильтруйте **Needs Review** — в идеале должно быть 0.
2. Проверьте фильтр **Failed** — если есть неудачные обработки, разберитесь с ними (переоткрыть, перезапустить или отметить на hold).
3. Проверьте фильтр **On Hold** — напомните себе, какие документы ждут gate pass или оплаты.
4. Проверьте **Email Log** — убедитесь, что автоматический опрос почты работает (синяя мигающая точка = polling активен).

---

### 11.5 Как понять что система работает правильно

**Признаки нормальной работы:**

| Что проверить | Где смотреть | Нормальное значение |
|--------------|-------------|-------------------|
| Почта опрашивается | **Email Log** → статус-бар внизу панели Scan | Синяя мигающая точка, "Auto-poll: ON", время последнего опроса < 10 минут назад |
| Письма обрабатываются | **Email Log** → таблица | Новые письма появляются со статусом "Processed" (зелёный) |
| Документы извлекаются | **Documents** → карточка Needs Review | Число растёт по мере поступления писем |
| ИИ работает | **Settings** → Credentials → Anthropic | Зелёная точка, статус "OK" |
| Расстояния считаются | **Review** → секция Delivery Warehouse | Расстояние показывается в милях рядом с каждым складом |
| CD подключен | **Settings** → Central Dispatch | Зелёный бейдж "Connected" |
| Здоровье системы | Адрес `/health` в браузере | `"status": "healthy"`, все checks = "ok" |

**Типичные цифры за рабочий день (при 10-20 машинах/день):**
- Email Log: 10-20 писем со статусом "Processed"
- Documents: 10-20 документов в Needs Review утром
- Extraction accuracy: ~85-95% полей заполнены правильно без коррекции
- Время обработки одного письма: 5-15 секунд

---

### 11.6 Как понять что что-то пошло не так

**Типичные симптомы проблем:**

| Что вижу | Что это значит | Что делать |
|----------|---------------|-----------|
| Утром 0 документов в Needs Review, хотя письма должны были прийти | Автоматический опрос почты не работает | Перейти в Email Log → проверить статус auto-poll. Если серая точка — polling отключён. Если красная ошибка — проблема с подключением к почте. Нажать "Poll Now" вручную. |
| Документ в статусе **OCR Required** (оранжевый) | PDF — скан (фотография), а не текстовый документ | Открыть Review → нажать "Try Vision Extract". Если не помогло — ввести данные вручную. |
| Документ в статусе **Failed** (красный) | Ошибка при обработке: повреждённый PDF, ИИ не ответил, или сбой сети | Открыть Review → нажать "Re-run" (перезапустить). Если снова Failed — документ повреждён или нестандартный, ввести данные вручную. |
| VIN пустой в извлечённых данных | ИИ не нашёл VIN в документе | Открыть PDF глазами, найти VIN, ввести вручную в поле VIN на странице Review. |
| Неправильный город забора | ИИ ошибся в определении адреса аукциона | Исправить вручную поля City, State, ZIP в секции Pick-Up Location. |
| Аукцион определён как "UNKNOWN" | Документ не распознан как Copart/IAA/Manheim | Не критично для экспорта. Проверьте pickup данные вручную. |
| Preflight показывает красные ошибки | Не все обязательные поля заполнены | Прочитать описание каждой ошибки, заполнить недостающие поля (см. секцию 11.9). |
| Экспорт в CD вернул ошибку | Проблема на стороне Central Dispatch или невалидные данные | Прочитать текст ошибки. Типичные: "duplicate listing" (уже есть), невалидная дата, VIN уже в системе. |
| Цена перевозки = 0 или пустая | Market Intelligence не вернул данные или маршрут не распознан | Нажать "Get Price from Central Dispatch" в секции Pricing. Если не помогло — ввести цену вручную. |
| Расстояние до склада не показывается | Google Maps API не настроен или ZIP-код не распознан | Проверить Settings → Credentials → Google Maps. Если не настроен — система использует приблизительные расстояния. |
| Письмо в Email Log со статусом "Skipped" | Система сочла письмо нерелевантным (нет PDF, thread reply, не-автомобильное) | Раскрыть строку в Email Log, прочитать "Skip reason". Если письмо нужное — нажать "Process" вручную. |
| Много документов с одинаковым VIN | Повторная обработка одного и того же автомобиля | Система предупредит о дублировании VIN. Проверьте, не обработан ли этот VIN ранее. |

---

### 11.7 Что делать если система не обрабатывает письма

**Пошаговая инструкция:**

**Шаг 1. Проверьте статус автоопроса:**
- Перейдите в **Email Log** (второй пункт в боковом меню).
- Посмотрите на панель статуса под секцией "Scan Emails":
  - Синяя мигающая точка + "Auto-poll: ON" → опрос работает. Проверьте "Last: X minutes ago" — если давно, нажмите **"Poll Now"**.
  - Серая точка + "Auto-poll: OFF" → опрос выключен. Включите его: **Settings** → вкладка **Email** → переключатель Auto-poll → ON.
  - Красный текст ошибки → проблема с подключением (см. шаг 2).

**Шаг 2. Проверьте подключение к почте:**
- Перейдите в **Settings** → вкладка **Email**.
- Убедитесь, что все поля заполнены (Email Address, Tenant ID / IMAP сервер, Client ID/Secret или пароль).
- Нажмите кнопку **"Test Connection"**.
  - Если зелёное сообщение "Connected" → подключение работает. Проблема в другом (см. шаг 3).
  - Если красное сообщение с ошибкой → учётные данные неверны или почтовый сервер недоступен. Проверьте правильность данных. Для Microsoft OAuth2 — проверьте Tenant ID, Client ID, Client Secret в Azure Portal.

**Шаг 3. Проверьте входящие вручную:**
- На странице **Email Log** нажмите **"Scan Inbox"** (синяя кнопка).
- Установите диапазон дат (например, последние 7 дней).
- Посмотрите результаты:
  - Если писем 0 → в почтовом ящике нет новых писем с PDF за этот период.
  - Если письма есть со статусом "NEW" → отметьте их и нажмите **"Process Selected"**.
  - Если письма есть со статусом "Processed" → они уже обработаны, проверьте страницу Documents.
  - Если статус "DUP VIN" → этот VIN уже есть в системе.

**Шаг 4. Проверьте фильтры отправителей:**
- **Settings** → вкладка **Email** → секция "Sender Filter".
- Если список не пустой — только письма от этих отправителей будут обработаны. Убедитесь, что нужный отправитель в списке, или очистите список для приёма всех.

**Шаг 5. Когда звонить разработчику:**
- Если **Test Connection** возвращает ошибку, а учётные данные 100% правильные — возможно, истёк OAuth2 токен или сервер заблокировал IP.
- Если письма сканируются, но не обрабатываются (все "Failed") — возможна проблема с ИИ API (проверьте Settings → Credentials → Anthropic).
- Если при нажатии "Poll Now" ничего не происходит в течение 2+ минут — возможен сбой сервера, нужна перезагрузка.

---

### 11.8 Review UI — как работать с интерфейсом проверки

Страница Review открывается по нажатию **Review** или **View** в таблице документов. Состоит из 9 секций. Слева — PDF документа для сверки, справа — извлечённые данные.

#### Секция 1: Extraction Info Bar (информационная панель)

**Что за данные:** Общая информация об обработке документа.
**Что показывает:**
- Имя файла PDF
- Тип аукциона — цветной бейдж: COPART (синий), IAA (зелёный), MANHEIM (фиолетовый), UNKNOWN (серый)
- Метод извлечения — "Claude Haiku" (основной), "Zone Fallback" (запасной), "Pattern Only" (только regex)
- Стоимость обработки — сколько стоил вызов ИИ (обычно $0.001-0.005)
- Уверенность — процент уверенности системы в извлечённых данных

**Действия:** Нет, только информация.
**Типичные проблемы:** Если уверенность < 60% — проверяйте данные особенно внимательно.

#### Секция 2: Vehicle Information (данные о транспортном средстве)

**Что за данные:** VIN, год, марка, модель, цвет, номер лота, тип кузова, тип прицепа, подвижность.
**Что ОБЯЗАТЕЛЬНО проверить:**
- **VIN** — ровно 17 символов. Зелёная галочка = система уверена. Если нет галочки — сверьте с PDF.
- **Year / Make / Model** — должны точно совпадать с документом. Поля с оранжевым фоном = система не уверена, проверьте.

**Что можно исправить:** Все поля редактируемые. Кликните в поле и измените значение.
**На что обратить внимание:**
- Система может перепутать Model и Make (например, "Prius" как марку вместо модели).
- Если Make/Model написаны в верхнем регистре (TOYOTA) — это нормально.
- **Inoperable** — кнопка-переключатель. Зелёный "OPERABLE" = машина на ходу, красный "INOPERABLE" = машина не едет. По умолчанию OPERABLE.
- **Trailer Type** — для обычных машин OPEN. Для дорогих/коллекционных — ENCLOSED.

#### Секция 3: Pick-Up Location (место забора)

**Что за данные:** Откуда забирать автомобиль — название аукционной локации, адрес, город, штат, ZIP, телефон.
**Что ОБЯЗАТЕЛЬНО проверить:**
- **City и State** — если ошибка здесь, перевозчик поедет не туда.
- **ZIP** — нужен для расчёта расстояния. Если пустой — расстояние и цена не рассчитаются.

**Что можно исправить:** Все поля редактируемые.
**На что обратить внимание:**
- Если телефон пустой — нажмите кнопку **"Lookup"** рядом с полем. Система найдёт телефон аукциона в справочнике.
- Если "Lookup" показывает "Not found" — аукционная локация не в справочнике, введите телефон вручную.
- **Location Type** — обычно AUCTION. Для Manheim offsite может быть BUSINESS.
- Для Manheim: если машина offsite (не на территории Manheim), адрес забора будет адресом продавца, а не Manheim.

#### Секция 4: Delivery Warehouse (склад доставки)

**Что за данные:** Куда доставить автомобиль. Выбирается из списка настроенных складов.
**Что ОБЯЗАТЕЛЬНО проверить:**
- **Выбран ли склад** — без склада экспорт невозможен. Если не выбран — жёлтое предупреждение.

**Как выбрать склад:**
- Система показывает карточки-варианты с расстоянием, временем в пути и ценой.
- **"BEST VALUE"** (янтарный бейдж) — рекомендованный вариант по соотношению цена/расстояние.
- **"Default"** (зелёный бейдж) — склад по умолчанию из настроек.
- Нажмите на карточку нужного склада.

**На что обратить внимание:**
- Если расстояние помечено "~ straight-line est." (серый текст) — это приблизительная оценка по прямой. Реальное расстояние по дорогам может быть на 20-30% больше. Настройте Google Maps API в Settings для точных расстояний.
- Ссылка **"Enter address manually"** позволяет указать произвольный адрес доставки вместо склада.

#### Секция 4b: Route Weather (погода на маршруте)

**Что за данные:** Погодные предупреждения на маршруте от аукциона до склада.
**Как пользоваться:**
- Секция свёрнута по умолчанию. В заголовке — бейдж статуса: "Clear" (зелёный) = всё хорошо, "X alerts" (красный) = есть предупреждения.
- Разверните секцию если бейдж красный — прочитайте AI-сводку и рекомендации.
- **HIGH RISK** (красный) — серьёзная непогода, стоит перенести забор.
- **MEDIUM RISK** (жёлтый) — есть риски, но перевозка возможна.
- **LOW RISK** (зелёный) — всё в порядке.

#### Секция 5: Dates (даты)

**Что за данные:** Дата доступности для забора, дата истечения, желаемая дата доставки.
**Что ОБЯЗАТЕЛЬНО проверить:**
- **Date Available to Ship** — когда машину можно забрать. По умолчанию сегодня. Для Manheim — дата из release document (если есть).

**На что обратить внимание:**
- **Expiration Date** — считается автоматически (available + 30 дней), нередактируемое.
- Для Manheim: если жёлтое предупреждение "No Onsite Vehicle Release" — нужно связаться с продавцом для получения release document.
- Дата в прошлом = блокирующая ошибка при экспорте. Дата дальше 30 дней = тоже ошибка.

#### Секция 6: Pricing and Payment (цена и оплата)

**Что за данные:** Цена перевозки, условия оплаты.
**Что ОБЯЗАТЕЛЬНО проверить:**
- **Amount to Pay Carrier** — главная сумма. Система показывает $/mile рядом (нормально $1.00-$2.50/mile для open trailer).

**Как получить рекомендацию цены:**
1. Убедитесь, что выбран pickup и склад.
2. Нажмите **"Get Price from Central Dispatch"** (широкая кнопка).
3. Система покажет рыночные данные: средняя цена диспетчеров, средняя цена листингов, спред.
4. Нажмите **"Use This Price"** чтобы перенести рекомендованную цену в поле Amount.
5. Скорректируйте вручную если нужно.

**На что обратить внимание:**
- Если кнопка неактивна — сначала выберите pickup location и warehouse.
- Если жёлтое сообщение "No market data available" — для этого маршрута нет рыночных данных, введите цену вручную.
- **COD** (Cash on Delivery) — обычно 0. Если нужна оплата при забора/доставке — заполните.

#### Секция 7: Additional Info (дополнительная информация)

**Что за данные:** Load ID, gate pass, заметки для перевозчика, условия загрузки.
**Что можно исправить:**
- **Gate Pass** — PIN-код для забора с аукциона. Если система нашла в письме — уже заполнен.
- **Additional Vehicle Information** — заметки, видимые перевозчику после назначения. Сюда автоматически добавляется gate pass.
- **Load-Specific Terms** — шаблон с контактной информацией и условиями оплаты.
- **Transport Special Instructions** — часы работы склада, требования к записи.

**На что обратить внимание:**
- **Load ID** — генерируется автоматически, можно изменить до экспорта. После экспорта — заблокирован.
- **Request carrier use CD App** — флажок, по умолчанию включён. Означает, что перевозчик должен использовать приложение CD для фото-осмотра.

#### Секция 8: Document Details (детали документа)

**Что за данные:** Внутренняя информация, НЕ отправляется в Central Dispatch.
Секция свёрнута по умолчанию.

**Что показывает при развороте:**
- Кто отправил email, тема, дата
- Buyer ID, Buyer Name, Seller Name, Sale Date, Purchase Amount
- Manheim Release Date, Manheim Offsite
- Сырые данные извлечения (для отладки)

**Действия:** Нет. Только для справки.

#### Секция 9: Export Actions (действия экспорта)

**Что за данные:** Preflight-проверка + кнопки действий.
**Элементы:**
- **Preflight Banner** — зелёный/жёлтый/красный индикатор готовности (подробнее в секции 11.9).
- Счётчик полей: "N correct" (зелёный), "N corrected" (синий), "N need review" (оранжевый).
- **Save Changes** (синяя обводка) — сохранить изменения без утверждения.
- **Approve for Export** (зелёная) — утвердить для экспорта. Требует выбранного склада.
- **Export to CD** (зелёная) — открывает модальное окно предпросмотра и отправки.

---

### 11.9 Preflight — что означают предупреждения

Баннер Preflight показывается в секции Export Actions и визуально сигнализирует о готовности документа к экспорту.

#### Blocking Issues (красный баннер) — НЕЛЬЗЯ экспортировать, пока не исправлено

| Сообщение | Что значит | Как исправить |
|-----------|-----------|--------------|
| "Missing required field: VIN" | VIN не заполнен | Найдите VIN в PDF и введите вручную (17 символов) |
| "VIN must be exactly 17 characters (got N)" | VIN неправильной длины | Проверьте VIN — возможно лишний/пропущенный символ |
| "Missing required field: City" (pickup) | Город забора не заполнен | Введите город в секции Pick-Up Location |
| "Missing required field: State" (pickup) | Штат забора не заполнен | Введите 2-буквенный код штата (напр. TX, CA, NJ) |
| "Warehouse not selected (delivery address incomplete)" | Не выбран склад доставки | Выберите склад в секции Delivery Warehouse |
| "At least 1 vehicle required. VIN is missing." | Нет данных о транспортном средстве | Заполните секцию Vehicle Information |
| "Pickup stop incomplete. Missing: city, state" | Неполный адрес забора | Заполните недостающие поля в Pick-Up Location |
| "Delivery stop incomplete. Please select a warehouse." | Нет адреса доставки | Выберите склад или введите адрес вручную |
| "Available date cannot be in the past" | Дата доступности в прошлом | Измените Date Available to Ship на сегодня или позже |
| "Available date cannot be more than 30 days in the future" | Дата слишком далеко в будущем | CD не принимает даты дальше 30 дней. Установите ближе. |
| "Expiration date cannot be in the past" | Дата истечения в прошлом | Обычно auto-calculated. Измените available date. |
| "Desired delivery date must be on or after available date" | Желаемая доставка раньше даты забора | Установите delivery date >= available date |
| "External ID must be 50 characters or less" | Load ID слишком длинный | Сократите Load ID (обычно auto-generated, не должно случаться) |
| "[Field] format is invalid" | Неверный формат (ZIP, State, VIN) | Проверьте формат: ZIP = 5 цифр, State = 2 буквы, VIN = 17 символов |

#### Warnings (жёлтый баннер) — можно экспортировать, но стоит обратить внимание

Предупреждения появляются для необязательных полей, которые пустые или подозрительные. Экспорт НЕ блокируется.

| Типичные предупреждения | Можно ли игнорировать |
|------------------------|---------------------|
| Пустое поле Color | Да — CD не требует цвет |
| Пустой Phone у pickup | Да — но перевозчику будет сложнее связаться с аукционом |
| Пустой Lot Number | Да — но полезно для идентификации |
| Пустой Gate Pass | Зависит от ситуации — без gate pass перевозчик может не забрать машину |
| Пустой Contact Name | Да — необязательное поле |

**Правило:** Красное — исправьте обязательно. Жёлтое — исправьте если можете, но экспорт возможен и без этого.

---

### 11.10 Central Dispatch — что создаётся автоматически

При нажатии **Export to CD** система формирует полный листинг перевозки в Central Dispatch. Вот что попадает в листинг:

#### Данные автомобиля
- VIN, Year, Make, Model, Color
- Vehicle Type (CD определяет автоматически из VIN, но мы тоже отправляем)
- Operable / Inoperable
- Lot Number (если есть)
- Additional Vehicle Info (заметки + gate pass)

#### Маршрут (2 остановки)
- **Stop 1 — Pickup:** название локации, адрес, город, штат, ZIP, телефон, контакт, тип (Auction/Business)
- **Stop 2 — Delivery:** все данные склада из настроек — название, адрес, город, штат, ZIP, телефон, контакт

#### Цена и условия
- Total price (сумма перевозчику)
- COD amount и метод (если есть)
- Balance amount (total - COD), метод, сроки оплаты
- Payment terms begin on (обычно "Receiving Signed BOL")

#### Даты
- Available Date (когда забирать)
- Expiration Date (available + 30 дней)
- Desired Delivery Date (если указано)

#### Прочее
- Trailer Type (OPEN / ENCLOSED)
- External ID (Load ID)
- Notes, Special Instructions
- Marketplace ID (из настроек CD)
- Requires Inspection (по умолчанию: да)

#### Что ОБЯЗАТЕЛЬНО проверить после экспорта

1. **CD Listing ID** — появляется на странице Review после успешного экспорта. Запишите.
2. **Проверьте листинг в Central Dispatch** — войдите в CD и убедитесь, что данные корректны.
3. **Адрес забора** — ошибка здесь = перевозчик поедет не туда.
4. **Цена** — убедитесь, что сумма разумная.

#### Типичные проблемы после экспорта и решения

| Проблема | Причина | Решение |
|----------|--------|---------|
| "Duplicate listing" (409) | Листинг с таким VIN или Reference ID уже есть в CD | Найдите существующий листинг в CD. Если нужно обновить — система поддерживает PUT (обновление). |
| "Rate limited" (429) | Слишком много запросов к CD за короткое время | Подождите 1-2 минуты и повторите. При массовом экспорте система автоматически замедляется. |
| "Invalid date" | Дата в прошлом или дальше 30 дней | Исправьте даты на странице Review и повторите экспорт. |
| "Invalid VIN" | VIN не прошёл валидацию CD | Проверьте VIN: ровно 17 символов, без букв I, O, Q. |
| Листинг создан, но данные неполные | Необязательные поля были пустые | Обновите через CD интерфейс или исправьте в системе и экспортируйте заново (PUT). |

---

### 11.11 Часто задаваемые вопросы (FAQ)

**1. Пришло письмо, но документ не появился в системе — почему?**

Возможные причины:
- Автоопрос выключен (проверьте Email Log → статус polling).
- Письмо без PDF-вложения (проверьте в Email Log, колонка "Attach").
- Письмо отфильтровано как нерелевантное (тема содержит "update profile", "subscription" и т.п.). Если в теме есть VIN — письмо всегда обрабатывается.
- Отправитель не в списке разрешённых (Settings → Email → Sender Filter).
- Письмо — ответ в цепочке (reply) без нового PDF → система пропускает его.
- Письмо уже обработано ранее (проверьте в Email Log по теме/отправителю).

**2. Система показывает неправильный адрес забора — что делать?**

Откройте страницу Review → секция Pick-Up Location → исправьте City, State, ZIP вручную. Если аукционная локация неизвестна системе (кнопка "Lookup" → "Not found"), введите адрес из документа руками.

**3. Как обработать документ, который система не распознала?**

Если статус "OCR Required" → нажмите "Try Vision Extract" на странице Review. Если статус "Failed" → нажмите "Re-run" в таблице Documents. Если всё равно не работает → откройте PDF глазами и введите все данные вручную в секции Review.

**4. Можно ли изменить данные после экспорта в Central Dispatch?**

Да, но через повторный экспорт (система отправит PUT-запрос на обновление). Измените данные на странице Review и нажмите "Export to CD" повторно. Система обновит существующий листинг, а не создаст новый.

**5. Что означает "BEST VALUE" на карточке склада?**

Система рассчитала, что этот склад оптимален по соотношению расстояние/цена перевозки. Это рекомендация, а не обязательный выбор. Вы можете выбрать любой другой склад.

**6. Почему цена перевозки пустая?**

Цена рассчитывается из рыночных данных Central Dispatch Market Intelligence. Если данных нет (редкий маршрут) или подписка MI не активна, система не может дать рекомендацию. Нажмите "Get Price from Central Dispatch" или введите цену вручную.

**7. Что такое Gate Pass и где его взять?**

Gate Pass (PIN-код) — это код для забора машины с аукциона. Обычно присылается в теме или теле письма от аукциона. Система автоматически извлекает его из текста email. Если не нашла — проверьте письмо вручную и введите в поле Gate Pass.

**8. Как добавить новый склад?**

Settings → вкладка Warehouses → кнопка "Add Warehouse". Заполните: код, название, штат, город, адрес, ZIP, телефон, контакт. Отметьте "Default Warehouse" если это основной склад.

**9. Что делать если на странице Review жёлтое предупреждение "No Onsite Vehicle Release" (Manheim)?**

Это значит что в документе Manheim не найдена дата release. Свяжитесь с продавцом и запросите Onsite Vehicle Release document. Пока его нет, доступная дата будет "сегодня" (по умолчанию).

**10. Можно ли обработать несколько документов за раз?**

Да. На странице Documents отметьте чекбоксами нужные документы. Появится синяя панель с кнопками массовых действий: Approve, Export, Hold, Archive. Лимит — 50 документов за раз.

**11. Что означает статус "On Hold"?**

Документ поставлен на ожидание. Причины: ожидание gate pass, оплаты, титула, vehicle release. Видно по красному бейджу "HOLD" в таблице. Чтобы снять — нажмите "Unhold" или "Release Hold" на странице Review.

**12. Как узнать, обработалось ли письмо?**

Перейдите в Email Log. Найдите письмо по отправителю или теме. Статус "Processed" (зелёный) = обработано, есть ссылка на документ. Раскройте строку — в правой панели "Linked Documents" будут ссылки "Open in Review".

**13. Почему два документа показывают одинаковый VIN?**

Если по одному VIN пришло два разных письма (например, invoice и потом обновлённый invoice). Система предупредит о дублировании при загрузке. Проверьте оба документа — возможно второй содержит обновлённые данные.

**14. Что делать если система работает медленно?**

Обработка одного PDF занимает 5-15 секунд (вызов ИИ). Это нормально. Если страница не загружается или зависает — обновите браузер (F5). Если проблема сохраняется — обратитесь к разработчику.

**15. Как переключить документ из Test Lab в Production?**

Документы загруженные через Test Lab предназначены для тестирования и обучения системы. Чтобы обработать реальный документ — загрузите его через кнопку "Upload Document" на странице Documents (не через Test Lab).

---

## 12. МЕТРИКИ И МОНИТОРИНГ

---

### 12.1 Ключевые метрики

**Endpoint:** `GET /api/metrics/summary`

Сводка за последние N дней (по умолчанию 7).

#### Основные показатели

| Метрика | Описание | Нормальное значение | Тревога |
|---------|---------|-------------------|---------|
| `total_runs` | Общее число обработок за период | 10-100 (зависит от объёма) | 0 за рабочий день = почта не работает |
| `exported` | Число экспортированных в CD | Близко к total_runs | Если << total_runs — большой backlog |
| `needs_review` | Число ожидающих проверки | Растёт утром, падает к концу дня | > 50 = backlog, нужно больше ресурсов |
| `failed` | Число неудачных обработок | 0-2 за день | > 5 за день = проблема с ИИ или форматом документов |
| `success_rate` | % экспортированных от общего | > 80% | < 50% = системная проблема |
| `avg_extraction_score` | Средняя уверенность извлечения | 0.80-0.95 | < 0.70 = качество документов упало или ИИ модель деградирует |

#### Метрики извлечения (по аукционам)

**Endpoint:** `GET /api/metrics/extractions?group_by=auction`

| Метрика | Описание | Нормальное значение |
|---------|---------|-------------------|
| `avg_raw_text_length` | Средняя длина текста из PDF | 2000-8000 символов |
| `avg_words_count` | Среднее число слов | 300-1000 |
| `ocr_applied_rate` | % документов, потребовавших OCR | < 10% |
| `avg_evidence_coverage` | Покрытие полей доказательствами | > 0.80 |
| `avg_extraction_score` | Средняя оценка извлечения | > 0.85 |

**Когда бить тревогу по extraction metrics:**
- `ocr_applied_rate > 30%` — аукцион стал присылать сканы вместо текстовых PDF. Warning.
- `ocr_applied_rate > 50%` — критично, формат документов изменился. Critical.
- `avg_extraction_score < 0.70` — качество извлечения упало, возможно изменился формат документов.

#### Метрики качества

**Endpoint:** `GET /api/metrics/quality?group_by=auction`

| Метрика | Описание | Нормальное значение | Тревога |
|---------|---------|-------------------|---------|
| `fill_rate` | % заполненных полей от всех | > 85% | < 70% warning, < 50% critical |
| `required_fill_rate` | % заполненных обязательных полей | > 90% | < 80% warning, < 60% critical |
| `pickup_parse_success_rate` | % документов с распознанным адресом забора | > 90% | < 70% = проблема с pickup extraction |
| `classification_confidence_avg` | Средняя уверенность классификации аукциона | > 0.60 | < 0.30 warning, < 0.20 critical |
| `blocking_issues_count` | Число документов с блокирующими проблемами | 0 | > 10 = системная проблема |

#### Алерты дрейфа качества

**Endpoint:** `GET /api/metrics/drift/alerts`

Система автоматически детектирует деградацию качества по аукционам. Алерты генерируются когда метрика ниже порога в течение нескольких дней подряд (по умолчанию 3 дня). Минимум 5 обработок в день для генерации алерта.

| Алерт | Уровень | Порог |
|-------|---------|-------|
| `fill_rate_warning` | Warning | required_fill_rate < 80% |
| `fill_rate_critical` | Critical | required_fill_rate < 60% |
| `ocr_rate_critical` | Critical | OCR rate > 50% |
| `classification_critical` | Critical | Уверенность классификации < 0.20 |

**Формат ответа:**
```json
{
  "alerts": [{
    "alert_type": "fill_rate_critical",
    "severity": "critical",
    "auction_code": "IAA",
    "message": "Required fill rate critically low for IAA",
    "current_value": 45.0,
    "threshold": 60,
    "days_below": 3
  }],
  "alert_count": 1,
  "critical_count": 1,
  "warning_count": 0
}
```

**Что делать при получении алерта:**
- **fill_rate critical** — проверить последние документы этого аукциона. Возможно изменился формат PDF.
- **ocr_rate critical** — аукцион стал присылать сканы. Проверить, установлен ли Tesseract OCR.
- **classification critical** — система не может определить тип аукциона. Проверить документы вручную.

---

### 12.2 Аудит экспорта

**Файл:** `api/audit_log.py`
**Таблица:** `audit_events`
**UI:** Settings → вкладка Audit Log

Аудит записывает каждое действие при экспорте в Central Dispatch для полной прослеживаемости.

#### Типы событий

| Тип события | Что записывает |
|------------|---------------|
| `UPLOAD` | Загрузка нового документа |
| `EXTRACT` | Запуск извлечения данных из PDF |
| `OCR` | Применение OCR к сканированному PDF |
| `POST_CREATE` | Успешное создание нового листинга в CD (HTTP POST) |
| `POST_UPDATE` | Успешное обновление существующего листинга в CD (HTTP PUT) |
| `POST_FAIL` | Неудачная попытка отправки в CD |
| `POST_RETRY` | Повторная попытка после неудачи |
| `POST_DUPLICATE` | Обнаружен дубликат листинга |
| `ETAG_REFRESH` | Обновление ETag после конфликта версий |
| `ETAG_CONFLICT` | Листинг был изменён другим пользователем (412 Precondition Failed) |
| `BATCH_START` | Начало массового экспорта |
| `BATCH_END` | Завершение массового экспорта |
| `CORRECTION` | Ручная коррекция поля оператором |

#### Что содержит каждая запись

| Поле | Описание |
|------|---------|
| `event_type` | Тип события (из таблицы выше) |
| `entity_type` | Тип объекта: "document", "run", "listing" |
| `run_id` | ID extraction run |
| `document_id` | ID документа |
| `cd_listing_id` | ID листинга в Central Dispatch |
| `request_id` | Уникальный ID запроса (12 символов) |
| `payload_hash` | Хеш отправленных данных (SHA-256, первые 16 символов) — для проверки что именно отправлялось |
| `response_status` | HTTP-код ответа (200 = успех, 409 = дубликат, 412 = конфликт версий, 429 = rate limit) |
| `response_snippet` | Первые 500 символов ответа от CD API |
| `etag_before` / `etag_after` | Версии ETag (для отслеживания конкурентных изменений) |
| `metadata_json` | Дополнительные данные (число автомобилей, external ID, ошибки) |
| `created_at` | Время события |

#### Как читать аудит

**В UI:** Settings → Audit Log → фильтр по интеграции → таблица с колонками Time, Integration, Action, Status, Details.

**Через API:**
- `GET /api/audit/run/{run_id}` — все события для одного extraction run
- `GET /api/audit/listing/{cd_listing_id}` — все события для одного CD листинга
- `GET /api/audit/recent?event_type=POST_FAIL&limit=20` — последние 20 неудачных попыток

**Безопасность:** Секретные данные (токены, пароли, API ключи) автоматически заменяются на "[REDACTED]" в metadata_json.

**Типичный аудит-trail успешного экспорта:**
```
1. EXTRACT      → extraction started (run_id=88)
2. RESOLVE      → fields resolved from 5 sources
3. VALIDATE     → payload valid
4. POST_CREATE  → HTTP 201, cd_listing_id=CD-12345, etag="abc..."
```

**Типичный аудит-trail неудачного экспорта:**
```
1. POST_FAIL    → HTTP 409, error="Duplicate listing"
2. POST_RETRY   → retry attempt 1
3. POST_FAIL    → HTTP 409, same error
```

---

### 12.3 Health checks

**Endpoint:** `GET /health`

Проверка здоровья системы. Возвращает общий статус и детали по каждому компоненту.

#### Формат ответа

```json
{
  "status": "healthy",
  "version": "1.1.0",
  "git_sha": "6721b21",
  "git_branch": "main",
  "build_time": "2026-02-25T10:00:00Z",
  "checks": {
    "database": {"status": "ok", "path": "data/control_panel.db"},
    "dir_data": "ok",
    "dir_datasets": "ok",
    "dir_datasets_runs": "ok",
    "dir_config": "ok",
    "config_local_settings": true,
    "config_env_file": true,
    "config_sheets_credentials": false,
    "anthropic_api": true,
    "email_config": true,
    "cd_api": true,
    "data_counts": {
      "documents": 245,
      "extraction_runs": 312,
      "email_log": 520
    }
  }
}
```

#### Как интерпретировать результаты

| Проверка | Что проверяет | "ok" / true | Что делать если "not ok" / false |
|----------|-------------|------------|--------------------------------|
| `status` | Общий статус | "healthy" | "unhealthy" = база данных недоступна, нужна перезагрузка |
| `database` | Файл БД существует | "ok" | "not_initialized" = БД не создана, перезапустите сервер |
| `dir_data` | Папка `data/` доступна для записи | "ok" | Проверьте права доступа на папку |
| `anthropic_api` | API ключ Claude настроен | true | false = ИИ не работает, проверьте Settings → Credentials → Anthropic |
| `email_config` | Почта настроена | true | false = email polling не работает, проверьте Settings → Email |
| `cd_api` | CD API настроен | true | false = экспорт невозможен, проверьте Settings → Central Dispatch |
| `config_sheets_credentials` | Google Sheets настроен | true/false | false = не критично, Sheets — опциональная интеграция |
| `data_counts.documents` | Число документов в БД | > 0 | 0 = система пустая (нормально при первом запуске) |
| `data_counts.extraction_runs` | Число обработок | > 0 | 0 = ни один документ не обработан |
| `data_counts.email_log` | Число записей в email лог | > 0 | 0 = почта ни разу не проверялась |

#### Дополнительные probes

| Endpoint | Назначение | Ответ |
|----------|-----------|-------|
| `GET /ready` | Readiness probe (для Docker/k8s) | `{"ready": true}` |
| `GET /live` | Liveness probe (для Docker/k8s) | `{"alive": true}` |

**Для мониторинга:** Рекомендуется проверять `/health` каждые 5 минут. Если `status != "healthy"` — оповестить разработчика.

---