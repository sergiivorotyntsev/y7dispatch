# Y7Dispatch: Согласованный План Действий v3.1

> **Дата**: 2026-02-11
> **Статус**: СОГЛАСОВАНО — Готово к исполнению
> **Базовый документ**: DIRECTIVE_V3_ACTION_PLAN.md + ревью Senior Full-Stack
> **Принцип**: Все решения приняты. Нет открытых вопросов. Можно начинать.

---

## 0. Принятые Решения (закрытые вопросы)

| # | Вопрос | Решение | Обоснование |
|---|--------|---------|-------------|
| 1 | `training_service.py` | **Вариант C** — переименовать в `correction_rules_service.py`, удалить ML/PEFT код, оставить correction→rule логику | При масштабировании (100+ docs/day) accumulated rules дают +3-5% accuracy бесплатно. Но ML-инфраструктура сейчас мертвый вес |
| 2 | `oauth.py` | **Не трогать** | Это service-level auth для Gmail/Sheets/CD API, а не user-facing RBAC. Удаление сломает все интеграции |
| 3 | `VisualZoneEditor.jsx` | **Проверить содержимое**: если drag-to-create → в `_archive/`; если read-only overlay → оставить | Template Builder запрещён, Evidence Viewer нужен. Архивировать, не удалять — пригодится при 2+ операторах |
| 4 | CD API Sandbox | **Mock в CI** + ручной smoke test через sandbox (если есть) раз в неделю | CI не должен зависеть от внешнего sandbox. Mock + OpenAPI schema validation надёжнее |
| 5 | Webhook override в v3 | **Проверить, если нет — реализовать в Week 1** | Блокирует Gate 1. Apps Script onEdit → POST /api/sheets/override |
| 6 | Reconciliation job | **Добавить если отсутствует** | 15 строк кода. Fallback для пропущенных webhooks. Cron каждые 5 мин |
| 7 | DLQ alerts | **Slack webhook** (primary) + email fallback | `send_alert(message, severity)` — HIGH=immediate, LOW=daily digest |

---

## 1. Production Gates (неизменные)

```
[ ] GATE 1: Email → DB row < 60 sec (Copart, IAA, Manheim)
[ ] GATE 2: VIN extraction accuracy ≥ 99% on golden set
[ ] GATE 3: Address extraction accuracy ≥ 95% on golden set
[ ] GATE 4: CD export success ≥ 98% on 20 real listings
[ ] GATE 5: Zero silent failures (every error → DLQ or alert)
[ ] GATE 6: Market Intelligence pricing works with manual fallback
```

---

## 2. Track A: Backend — Конкретные Действия

### A1. Dead Code Removal (День 1)

#### Удалить без обсуждения:

```bash
# Sheets exporters v1/v2
DELETE  services/sheets_exporter_v1.py
DELETE  services/sheets_exporter_v2.py
RENAME  services/sheets_exporter_v3.py → services/sheets_exporter.py
UPDATE  все imports во всех файлах, ссылающихся на v1/v2/v3

# ClickUp
DELETE  services/clickup.py
DELETE  api/routes/integrations/clickup.py
UPDATE  удалить imports и route registrations
```

#### training_service.py — рефакторинг:

```bash
# Шаг 1: Создать новый файл
CREATE  services/correction_rules_service.py

# Шаг 2: Перенести ТОЛЬКО:
#   - CorrectionRule model/schema
#   - apply_corrections() — логика "user fix → rule"
#   - get_rules_for_field() — поиск подходящих правил
#   Всё что содержит: PEFT, LoRA, model, training, weights,
#   epochs, batch_size, fine-tune — НЕ переносить

# Шаг 3: Удалить оригинал
DELETE  services/training_service.py

# Шаг 4: Удалить TODO
#   services/training_service.py:334 → файл удалён
#   api/routes/extractions.py:704 → удалить TODO, 
#     заменить на: raise NotImplementedError("ML extraction disabled")
#     или убрать route полностью если он не используется
```

**Критерий**: если после переноса `correction_rules_service.py` содержит < 50 строк — перенести логику в `field_resolver.py` и удалить файл.

#### Endpoint Audit:

```
ПРАВИЛО: endpoint остаётся если он обслуживает хотя бы 1 из:
  - Email ingestion pipeline
  - PDF extraction + review
  - Google Sheets sync
  - CD export + pricing
  - System health/settings
  - DLQ management

ПРАВИЛО: endpoint удаляется/отключается если он обслуживает:
  - ML training
  - ClickUp
  - Template builder CRUD (не путать с template config read)
  - Любой stub/placeholder

ДЕЙСТВИЕ: 
  1. Пройти по всем route files
  2. Для каждого endpoint — пометить KEEP/DISABLE
  3. DISABLE = закомментировать route registration (не удалять код)
  4. Логировать: "Disabled {N} endpoints, kept {M}"
```

**Почему DISABLE, а не DELETE**: при масштабировании часть endpoints понадобится (template management когда появится второй оператор). Закомментированный код с датой и причиной — дешевле чем переписывать с нуля.

```python
# DISABLED 2026-02-11: Template builder UI not needed for single operator
# Re-enable when: second operator onboarded OR template count > 10
# @router.post("/templates")
# async def create_template(template: TemplateCreate):
#     ...
```

#### Финал дня 1:

```bash
git add -A
git commit -m "chore: dead code removal — sheets v1/v2, clickup, ML stubs

- Deleted sheets_exporter_v1.py, v2.py
- Renamed v3 → sheets_exporter.py  
- Deleted clickup.py + route
- Refactored training_service → correction_rules_service (ML removed)
- Disabled {N} unused endpoints
- All tests passing"

# Запустить полный test suite ПЕРЕД коммитом
pytest tests/ -v --tb=short
```

---

### A2. E2E Tests (Дни 2–4)

#### Структура:

```
tests/
├── e2e/
│   ├── conftest.py          # Shared fixtures, test DB, mock CD API
│   ├── fixtures/
│   │   ├── copart_sample.pdf
│   │   ├── copart_ground_truth.json
│   │   ├── iaa_sample.pdf
│   │   ├── iaa_ground_truth.json
│   │   ├── manheim_sample.pdf
│   │   ├── manheim_ground_truth.json
│   │   └── corrupted.pdf
│   ├── test_copart_pipeline.py
│   ├── test_iaa_pipeline.py
│   ├── test_manheim_pipeline.py
│   ├── test_cd_export.py
│   └── test_error_handling.py
```

#### Test 1-3: Auction Pipelines (шаблон одинаковый)

```python
# tests/e2e/test_copart_pipeline.py

import pytest
from pathlib import Path

class TestCopartPipeline:
    """
    Full pipeline: PDF file → extraction → DB row → field validation
    Uses real Copart PDF from golden dataset.
    """

    @pytest.fixture
    def sample_pdf(self):
        return Path("tests/e2e/fixtures/copart_sample.pdf").read_bytes()

    @pytest.fixture
    def ground_truth(self):
        return json.loads(
            Path("tests/e2e/fixtures/copart_ground_truth.json").read_text()
        )

    async def test_extraction_creates_db_row(self, sample_pdf, ground_truth):
        """PDF → extraction → DB row exists with correct status"""
        result = await pipeline.process_document(sample_pdf, source="copart")
        
        assert result.dispatch_id is not None
        assert result.row_status == "NEW"
        assert result.auction_type == "COPART"

    async def test_vin_accuracy(self, sample_pdf, ground_truth):
        """VIN matches ground truth exactly"""
        result = await pipeline.process_document(sample_pdf, source="copart")
        assert result.fields["vehicle_vin"].value == ground_truth["vehicle_vin"]

    async def test_address_extraction(self, sample_pdf, ground_truth):
        """Pickup address components match ground truth"""
        result = await pipeline.process_document(sample_pdf, source="copart")
        
        assert result.fields["pickup_city"].value == ground_truth["pickup_city"]
        assert result.fields["pickup_state"].value == ground_truth["pickup_state"]
        assert result.fields["pickup_zip"].value == ground_truth["pickup_zip"]

    async def test_gate_pass_from_email_body(self, ground_truth):
        """Gate pass extracted from email body (not PDF)"""
        email_body = "Your Gate Pass PIN is: ABC1234. Lot #98765432"
        result = await pipeline.process_email_body(email_body, source="copart")
        
        assert result.fields["gate_pass"].value == "ABC1234"

    async def test_confidence_scores_present(self, sample_pdf):
        """Every extracted field has confidence score"""
        result = await pipeline.process_document(sample_pdf, source="copart")
        
        for field_name, field in result.fields.items():
            assert 0.0 <= field.confidence <= 1.0, \
                f"{field_name} missing confidence score"
```

#### Test 4: CD Export

```python
# tests/e2e/test_cd_export.py

class TestCDExport:
    """
    DB row → preflight → price → export → status update
    CD API is MOCKED — validates payload schema.
    """

    @pytest.fixture
    def mock_cd_api(self, mocker):
        """Mock CD API that validates payload against OpenAPI schema"""
        mock = mocker.patch("services.cd_client.CDClient.create_listing")
        mock.return_value = CDResponse(
            listing_id="CD-2026-TEST-001",
            status="ACTIVE",
            etag="abc123"
        )
        return mock

    @pytest.fixture
    def mock_market_intel(self, mocker):
        """Mock Market Intelligence API"""
        mock = mocker.patch("services.cd_client.CDClient.get_listing_prices")
        mock.return_value = [
            ListingPrice(
                listing_price=550.0,
                dispatch_price=485.0,
                listing_price_per_mile=0.55,
                dispatch_distance=1000
            )
        ]
        return mock

    async def test_preflight_passes_for_complete_row(self, complete_db_row):
        """All required fields present → preflight green"""
        result = await exporter.preflight_check(complete_db_row.dispatch_id)
        assert result.ready is True
        assert len(result.errors) == 0

    async def test_preflight_fails_for_missing_vin(self, incomplete_db_row):
        """Missing VIN → preflight red with actionable error"""
        result = await exporter.preflight_check(incomplete_db_row.dispatch_id)
        assert result.ready is False
        assert any("VIN" in e.message for e in result.errors)

    async def test_pricing_engine_calculates(self, mock_market_intel):
        """PricingEngine returns valid recommendation"""
        price = await pricing_engine.calculate_recommended_price(
            origin=Address(city="Dallas", state="TX", zip="75201"),
            destination=Address(city="Chicago", state="IL", zip="60601"),
            vehicle=Vehicle(vin="1HGCM82633A004352", year=2003, make="Honda")
        )
        assert price.price is not None
        assert price.floor <= price.price <= price.ceiling
        assert price.source == PriceSource.CD_MARKET_INTELLIGENCE

    async def test_export_creates_listing(self, mock_cd_api, complete_db_row):
        """Export → CD API called → status updated"""
        result = await exporter.export_listing(complete_db_row.dispatch_id)
        
        assert result.success is True
        assert result.cd_listing_id == "CD-2026-TEST-001"
        
        # Verify DB updated
        row = await db.get(complete_db_row.dispatch_id)
        assert row.row_status == "EXPORTED"
        assert row.cd_listing_id == "CD-2026-TEST-001"

    async def test_export_payload_matches_cd_schema(self, mock_cd_api, complete_db_row):
        """Payload sent to CD API matches V2 schema requirements"""
        await exporter.export_listing(complete_db_row.dispatch_id)
        
        payload = mock_cd_api.call_args[1]["payload"]
        
        # Required fields per CD API V2
        assert "externalId" in payload
        assert "trailerType" in payload
        assert len(payload["stops"]) == 2
        assert payload["stops"][0]["stopNumber"] == 1
        assert len(payload["vehicles"]) >= 1
        assert len(payload["vehicles"][0]["vin"]) == 17
        assert "price" in payload
        assert payload["price"]["total"] > 0
```

#### Test 5: Error Handling

```python
# tests/e2e/test_error_handling.py

class TestErrorHandling:
    """
    Failure scenarios → DLQ + alerts, no silent failures
    """

    async def test_corrupted_pdf_to_dlq(self):
        """Corrupted PDF → DLQ entry created, not stuck"""
        corrupted = b"%PDF-1.4 CORRUPTED DATA"
        result = await pipeline.process_document(corrupted, source="copart")
        
        assert result.status == "FAILED"
        dlq_entry = await dlq.get_latest()
        assert dlq_entry is not None
        assert "corrupted" in dlq_entry.error.lower() or "parse" in dlq_entry.error.lower()

    async def test_duplicate_email_deduplicated(self):
        """Same email processed twice → only one DB row"""
        email_id = "MSG-12345"
        await pipeline.process_email(email_id, pdf_bytes=sample_pdf)
        await pipeline.process_email(email_id, pdf_bytes=sample_pdf)
        
        rows = await db.find_by_email_id(email_id)
        assert len(rows) == 1  # Deduplicated

    async def test_unknown_auction_flags_manual_review(self):
        """PDF from unknown auction → row created with MANUAL_REVIEW status"""
        unknown_pdf = Path("tests/e2e/fixtures/unknown_auction.pdf").read_bytes()
        result = await pipeline.process_document(unknown_pdf, source="unknown")
        
        assert result.row_status == "MANUAL_REVIEW"

    async def test_cd_api_failure_does_not_lose_data(self, mocker):
        """CD API 500 → export fails gracefully, data preserved"""
        mocker.patch(
            "services.cd_client.CDClient.create_listing",
            side_effect=CDAPIError("500 Internal Server Error")
        )
        
        result = await exporter.export_listing("D-TEST-001")
        assert result.success is False
        assert result.error is not None
        
        # Data still in DB, not corrupted
        row = await db.get("D-TEST-001")
        assert row.row_status == "READY"  # Not stuck in EXPORTING
        assert row.cd_listing_id is None

    async def test_market_intel_unavailable_fallback(self, mocker):
        """CD Market Intelligence down → MANUAL_REQUIRED, not crash"""
        mocker.patch(
            "services.cd_client.CDClient.get_listing_prices",
            side_effect=CDAPIError("503 Service Unavailable")
        )
        
        price = await pricing_engine.calculate_recommended_price(
            origin=Address(city="Dallas", state="TX", zip="75201"),
            destination=Address(city="Chicago", state="IL", zip="60601"),
            vehicle=Vehicle(vin="1HGCM82633A004352")
        )
        
        assert price.price is None
        assert price.source == PriceSource.MANUAL_REQUIRED
```

---

### A3. Sheets Consolidation (День 4)

```bash
# После удаления v1/v2 (в A1):

# 1. Проверить webhook override
grep -r "sheets/override" api/routes/
# Если endpoint НЕ существует → создать:
#   POST /api/sheets/override
#   Принимает: { dispatch_id, field, new_value, edited_by }
#   Действие: обновить override_{field} в DB

# 2. Проверить reconciliation job
grep -r "reconcil" services/ workers/
# Если НЕ существует → добавить в workers/sync_worker.py:
#   Каждые 5 мин: SELECT count(*) FROM dispatches WHERE updated_at > last_sheets_sync
#   Если diff > 0 → force sync, log warning

# 3. Тест
python -c "
from services.sheets_exporter import SheetsExporter
exporter = SheetsExporter()
exporter.sync_row('TEST-001')  # Should not crash
print('Sheets sync OK')
"
```

---

### A4. PricingEngine (Дни 6–7)

#### Аудит существующего кода:

```bash
# Прочитать текущую реализацию
cat services/pricing_engine.py

# Проверить по чеклисту:
```

| Требование | Код | Статус |
|-----------|-----|--------|
| `avg_dispatch_price` из CD API response | `statistics.mean(dispatch_prices)` | ☐ |
| `spread = avg_listing - avg_dispatch` | Вычисление | ☐ |
| `base = avg_dispatch + (spread × 0.5)` | Формула | ☐ |
| STANDARD ×1.0, PRIORITY ×1.12, URGENT ×1.25 | Модификаторы | ☐ |
| Floor: `max($150, $0.40/mile, avg_dispatch × 0.85)` | Ограничение | ☐ |
| Ceiling: `min($2.00/mile, avg_dispatch × 1.50)` | Ограничение | ☐ |
| Warnings: <90% = "Below market", >130% = "Above market" | Предупреждения | ☐ |
| Fallback: API down → `MANUAL_REQUIRED` | Обработка ошибок | ☐ |
| Cache: 24h TTL для одинаковых маршрутов | Кеширование | ☐ |

**Если GAP найден** → исправить. Не переписывать, а дополнить.

#### Sheets columns для pricing:

```python
# Добавить в sheets_exporter.py schema:

PRICING_COLUMNS = [
    {"name": "suggested_price", "class": "SYSTEM"},      # Auto from PricingEngine
    {"name": "price_source", "class": "SYSTEM"},          # CD_MARKET_INTEL | MANUAL_REQUIRED
    {"name": "price_low", "class": "SYSTEM"},             # CD avg_dispatch
    {"name": "price_high", "class": "SYSTEM"},            # CD avg_listing  
    {"name": "price_warnings", "class": "SYSTEM"},        # Below/Above market
    {"name": "price_floor", "class": "SYSTEM"},           # Calculated floor
    {"name": "price_ceiling", "class": "SYSTEM"},         # Calculated ceiling
    {"name": "price_data_points", "class": "SYSTEM"},     # How many CD records
    {"name": "final_price", "class": "OVERRIDE"},         # User override
    {"name": "urgency", "class": "OVERRIDE"},             # STANDARD/PRIORITY/URGENT
]

# Export logic:
# if final_price → use final_price
# elif suggested_price → use suggested_price  
# else → BLOCK export, error "Price required"
```

---

## 3. Track B: Frontend — Конкретные Действия

### B1. Evidence Overlay (День 5)

```javascript
// Проверить в PdfZoneViewer.jsx (или аналогичном компоненте):

// ТРЕБУЕМАЯ формула:
const transformCoordinates = (pdfBbox, pageHeight, scale) => {
  return {
    x: pdfBbox.x0 * scale,
    y: (pageHeight - pdfBbox.y1) * scale,  // Flip Y axis
    width: (pdfBbox.x1 - pdfBbox.x0) * scale,
    height: (pdfBbox.y1 - pdfBbox.y0) * scale,
  };
};

// ТЕСТ: Проверить с 5 документами (по 1-2 от каждого аукциона)
// Если работает для 80%+ полей — DONE
// Если edge cases (rotated pages, multi-column) — 
//   скрыть overlay для этих документов, показать text-only evidence
//   НЕ тратить больше 2 дней
```

**Правило 2 дней**: если за 2 дня overlay не работает стабильно — показывать text evidence (`source_text` из Citation) вместо visual bbox. Это работает, пользователь видит откуда данные, можно вернуться к overlay позже.

### B2. Page Stabilization (Дни 5–8)

#### Documents Page — чеклист:

```
[ ] Таблица с колонками: dispatch_id, auction_type, vehicle (year make model), 
    row_status, created_at
[ ] Status badge: NEW=blue, READY=green, EXPORTED=purple, ERROR=red, 
    MANUAL_REVIEW=yellow
[ ] Фильтр по auction_type (dropdown: ALL/COPART/IAA/MANHEIM)
[ ] Сортировка по дате (newest first по умолчанию)
[ ] Клик на строку → переход на Review page
[ ] Upload button → TestLab page (не новый endpoint)
```

#### Review Page — чеклист:

```
[ ] Левая панель: PDF viewer (уже есть, работает)
[ ] Правая панель: список extracted fields
[ ] Каждое поле показывает:
    - Field name (human readable)
    - Value
    - Confidence: цветная полоска (green ≥0.9, yellow 0.7-0.9, red <0.7)
    - Source text (evidence) — кликабельный, подсвечивает в PDF
    - Edit button → inline edit → POST /api/fields/{id}/override
[ ] Pricing section (B3 — подключить после A4):
    - Suggested price, source, warnings
    - Final price input
    - Urgency dropdown
[ ] Preflight banner (уже есть PreflightBanner.jsx):
    - Green: "Ready to export"  
    - Red: список ошибок
    - Yellow: список warnings
[ ] Export button → ExportPreviewModal (уже есть)
```

#### TestLab Page — чеклист:

```
[ ] Drag-and-drop PDF upload
[ ] Dropdown: auction type (COPART/IAA/MANHEIM/AUTO-DETECT)
[ ] "Extract" button → calls extraction API
[ ] Results table: field name, value, confidence, source
[ ] "Save to DB" button (optional — creates real dispatch row)
[ ] Время выполнения extraction (показать секунды)
```

#### Settings Page — чеклист:

```
[ ] Connection indicators (green dot / red dot):
    - Email (IMAP): last successful poll timestamp
    - Google Sheets: last sync timestamp
    - Central Dispatch API: last successful call timestamp
    - Claude API: last successful extraction timestamp
[ ] Cost summary: total spend today, this week, this month
[ ] System info: version, uptime, DB size
```

### B3. Pricing UI (Дни 8–9)

**Добавить в Review page, секция между fields и export:**

```
Wireframe:
┌─────────────────────────────────────────────────┐
│ 💰 PRICING                                      │
│                                                  │
│ Source: CD Market Intelligence (3 data points)   │
│                                                  │
│ Market Range:                                    │
│ ├── Avg Dispatch (carriers got paid): $485       │
│ ├── Avg Listing (brokers listed at):  $550       │
│ └── Spread: $65                                  │
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ $425    [$485]     ★ $517      [$727]       │ │
│ │ floor    market    recommended  ceiling      │ │
│ └─────────────────────────────────────────────┘ │
│                                                  │
│ Urgency: [STANDARD ▼]                           │
│ Recommended: $517                                │
│                                                  │
│ Final Price: [________]                          │
│ (leave empty to use recommended $517)            │
│                                                  │
│ ⚠️ Warnings: None                                │
└─────────────────────────────────────────────────┘
```

**Если backend A4 не готов**: показать секцию с mock данными и badge "Pricing API connecting...". UI не должен ждать backend.

### B4. Export Flow (Дни 9–10)

```
Flow:
1. User clicks "Check Export" → POST /api/exports/preflight/{id}
   → PreflightBanner updates (green/red/yellow)

2. If green → "Export" button enabled
   → Click → ExportPreviewModal opens:
     "Export to Central Dispatch?
      Vehicle: 2024 Toyota Camry (VIN: 1HGCM...)
      Route: Dallas, TX → Chicago, IL  
      Price: $517
      [Cancel] [Confirm Export]"

3. Confirm → POST /api/exports/{id}
   → Loading spinner
   → Success: "✅ Exported! Listing ID: CD-2026-0211-A3B4"
              Status badge → EXPORTED (purple)
   → Failure: "❌ Export failed: {error message}"
              "Suggested fix: {actionable suggestion}"
```

---

## 4. Track C: Infrastructure

### C1. Alerts (День 7)

```python
# services/alerting.py

import httpx
from enum import Enum

class Severity(Enum):
    HIGH = "high"      # Immediate notification
    MEDIUM = "medium"  # Hourly digest  
    LOW = "low"        # Daily digest

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "dispatch@y7agency.com")

async def send_alert(message: str, severity: Severity, context: dict = None):
    """
    Send alert via Slack (primary) or email (fallback).
    
    Usage:
        await send_alert(
            "DLQ: Corrupted PDF from dispatch@copart.com",
            Severity.HIGH,
            {"dispatch_id": "D-001", "error": "PDF parse failed"}
        )
    """
    payload = {
        "text": f"{'🔴' if severity == Severity.HIGH else '🟡'} [{severity.value.upper()}] {message}",
        "blocks": [...]  # Rich formatting if needed
    }
    
    if SLACK_WEBHOOK_URL:
        await httpx.AsyncClient().post(SLACK_WEBHOOK_URL, json=payload)
    else:
        # Email fallback
        await send_email(ALERT_EMAIL, f"Y7Dispatch Alert: {message}", str(context))
```

**Триггеры алертов (добавить в соответствующие сервисы):**

```python
# В email_worker.py:
except Exception as e:
    await dlq.add(email_id, error=str(e))
    await send_alert(f"DLQ: {e}", Severity.HIGH, {"email_id": email_id})

# В cd_exporter.py:
if not result.success:
    await send_alert(f"CD Export failed: {result.error}", Severity.HIGH, 
                     {"dispatch_id": dispatch_id})

# В cost_tracker.py (daily cron):
if daily_cost > 5.0:
    await send_alert(f"Claude API cost ${daily_cost:.2f} today", Severity.MEDIUM)

# В evaluation runner (if accuracy < threshold):
if accuracy < 0.90:
    await send_alert(f"Extraction accuracy {accuracy:.1%} below 90%", Severity.HIGH,
                     {"document_id": doc_id})
```

---

## 5. Финальный Timeline

```
НЕДЕЛЯ 1: Clean + Stabilize
═══════════════════════════════════════════════════

День 1 (Пн) ──────────────────────────────────────
  TRACK A: Dead code removal (A1)
    ✂ Delete sheets v1/v2, rename v3
    ✂ Delete ClickUp
    ✂ Refactor training_service → correction_rules_service
    ✂ Endpoint audit: disable unused
    ✓ Run full test suite
    ✓ Commit
    
  TRACK B: Evidence Overlay (B1)
    🔧 Fix coordinate transform formula
    🧪 Test with 5 documents

День 2 (Вт) ──────────────────────────────────────
  TRACK A: E2E tests — Copart + IAA (A2)
    ✍ test_copart_pipeline.py (5 assertions)
    ✍ test_iaa_pipeline.py (5 assertions)
    
  TRACK B: Evidence Overlay continued
    🧪 Test remaining documents
    📝 If broken → fallback to text evidence

День 3 (Ср) ──────────────────────────────────────
  TRACK A: E2E test — Manheim (A2)
    ✍ test_manheim_pipeline.py
    
  TRACK B: Documents page stabilization (B2)
    🔧 Status badges, filters, sort

День 4 (Чт) ──────────────────────────────────────
  TRACK A: Sheets consolidation (A3) + E2E tests 4-5
    🔧 Verify webhook override
    🔧 Add reconciliation job
    ✍ test_cd_export.py
    ✍ test_error_handling.py
    
  TRACK B: Review page stabilization (B2)
    🔧 Field list, confidence colors, inline edit

День 5 (Пт) ──────────────────────────────────────
  TRACK A: All 5 E2E tests must pass
    ✓ Green CI pipeline
    
  TRACK B: TestLab + Settings pages (B2)
    🔧 Upload + extract flow
    🔧 Connection status indicators

  ┌──────────────────────────────────────────────┐
  │ WEEK 1 EXIT GATE:                            │
  │ ☐ 5 E2E tests passing                       │
  │ ☐ Zero dead code                             │
  │ ☐ One sheets exporter                        │
  │ ☐ 4 UI pages functional (may have rough UX)  │
  └──────────────────────────────────────────────┘


НЕДЕЛЯ 2: Pricing + Export + Ship
═══════════════════════════════════════════════════

День 6 (Пн) ──────────────────────────────────────
  TRACK A: PricingEngine audit + implementation (A4)
    📋 Audit existing pricing_engine.py vs checklist
    🔧 Fix GAPs in formula/floor/ceiling
    
  TRACK B: Pricing UI with mock data (B3)
    🎨 Market range display
    🎨 Price slider visualization
    🎨 Urgency dropdown

День 7 (Вт) ──────────────────────────────────────
  TRACK A: CD Market Intelligence integration (A4)
    🔧 Connect PricingEngine to CD API
    🔧 Add 24h cache
    🔧 Implement alerting service (C1)
    
  TRACK B: Connect Pricing UI to real API (B3)
    🔌 Replace mock data with API calls
    🔧 Handle MANUAL_REQUIRED state

День 8 (Ср) ──────────────────────────────────────
  TRACK A: Floor/ceiling/warnings + fallback (A4)
    🧪 Test pricing with various routes
    🧪 Test fallback when API down
    
  TRACK B: Preflight check UI (B4)
    🎨 Preflight button → error/warning/green display

День 9 (Чт) ──────────────────────────────────────
  TRACK A: E2E test for pricing + export flow
    ✍ Add pricing assertions to test_cd_export.py
    
  TRACK B: Export flow UI completion (B4)
    🎨 ExportPreviewModal with pricing
    🎨 Success/failure states

День 10 (Пт) ─────────────────────────────────────
  BOTH TRACKS: Full pipeline test
    🧪 Process 20 real documents end-to-end
    🧪 Full UI walkthrough for each
    📋 Note failures → backlog for Week 3
    ✓ All 6 Production Gates check

  ┌──────────────────────────────────────────────┐
  │ WEEK 2 EXIT GATE (= PRODUCTION READY):       │
  │ ☐ All 6 Production Gates GREEN               │
  │ ☐ 20 real documents processed E2E            │
  │ ☐ Pricing works with CD Market Intelligence  │
  │ ☐ Export flow works from UI                  │
  │ ☐ Alerts functional (Slack)                  │
  └──────────────────────────────────────────────┘


НЕДЕЛЯ 3+: Hardening
═══════════════════════════════════════════════════
  - Golden dataset expansion (23 → 150)
  - Fix failures found in Week 2 testing
  - UI polish based on real usage
  - Performance optimization if latency > 60 sec
  - Evaluate: is correction_rules_service adding value?
```

---

## 6. Масштабирование — Что Разблокируется После v3.1

**Только после всех 6 Gates GREEN:**

| Этап | Триггер | Что делать |
|------|---------|-----------|
| **2+ оператора** | Наём второго диспетчера | Включить auth (oauth.py уже есть), раскомментировать template management endpoints, восстановить VisualZoneEditor из `_archive/` |
| **100+ docs/day** | Объём выросил | SQLite → PostgreSQL, добавить worker queue (Celery/ARQ), включить batch processing |
| **Accuracy < 95%** | Golden set regression | Оценить correction_rules effectiveness. Если < 2% gain → рассмотреть Claude Sonnet вместо Haiku для сложных документов (дороже, но точнее) |
| **Новые аукционы** | Клиент требует | Добавить extractor + 50 docs в golden set. Template = YAML, не UI |
| **Carrier automation** | Core pipeline стабилен 30+ дней | Разморозить Phase 4 (RingCentral SMS). Отдельный сервис, не в монолите |

**Правило**: каждый этап масштабирования активируется по триггеру, не по расписанию. Не строить заранее.

---

## 7. Definition of Done (финальное)

```
Y7Dispatch v3.1 SHIPPED когда:

✅ GATE 1: Email → DB row < 60 sec (all 3 auctions)
✅ GATE 2: VIN accuracy ≥ 99%
✅ GATE 3: Address accuracy ≥ 95%  
✅ GATE 4: CD export success ≥ 98% (20 real listings)
✅ GATE 5: Zero silent failures
✅ GATE 6: Market Intelligence pricing + fallback

✅ 5 E2E tests green in CI
✅ Zero dead code
✅ 4 UI pages operational
✅ 20 real documents processed without manual intervention
✅ Alerts configured and tested
```

---

*Документ согласован. Нет открытых вопросов. Можно начинать Day 1.*
