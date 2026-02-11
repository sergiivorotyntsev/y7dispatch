# Y7Dispatch Directive v3.0 — План Действий для Согласования

> Документ сопоставляет требования директивы с текущим состоянием проекта и определяет конкретные шаги.

---

## 1. Сводка Расхождений

| Требование Директивы | Текущее Состояние | GAP | Приоритет |
|---------------------|-------------------|-----|-----------|
| Удалить `training_service.py` | Существует, функционален | **ТРЕБУЕТ ОБСУЖДЕНИЯ** | HIGH |
| Удалить Sheets v1/v2 | `sheets_exporter_v1.py`, `sheets_exporter_v2.py` существуют | Нужно удалить | HIGH |
| Удалить ClickUp интеграцию | `services/clickup.py` + `api/routes/integrations/clickup.py` существуют | Нужно удалить | HIGH |
| 5 E2E тестов | Только `smoke.spec.ts` (smoke-тесты) | Нужно написать | HIGH |
| Evidence overlay формула | Реализован, статус "needs testing" | Нужно проверить | MEDIUM |
| PricingEngine | `services/pricing_engine.py` существует | Нужно аудировать | MEDIUM |
| Golden dataset 150 docs | 23 документа | Постепенное расширение | ONGOING |
| Audit 58 endpoints | 42+ endpoints в integrations | Нужен аудит | HIGH |

---

## 2. Track A: Backend Pipeline — Детальный План

### A1. Dead Code Removal (День 1)

#### 2.1.1 Вопрос для согласования: `training_service.py`

**Директива говорит:** "Delete `training_service.py` (ML placeholder, 0% functional)"

**Факт:** Файл существует и содержит логику для:
- Обучения на corrections из Review UI
- Создания extraction rules

**Варианты:**
- [ ] **A)** Удалить как указано в директиве (следуем букве)
- [ ] **B)** Сохранить, т.к. функционал нужен для improvement loop
- [ ] **C)** Переименовать в `correction_rules.py` (убрать ML коннотацию)

#### 2.1.2 Sheets Exporter Consolidation

```bash
# Файлы к удалению:
services/sheets_exporter_v1.py   # DELETE
services/sheets_exporter_v2.py   # DELETE

# Файл к сохранению:
services/sheets_exporter_v3.py → services/sheets_exporter.py  # RENAME
```

**Действия:**
1. Найти все imports v1/v2 и удалить/заменить
2. Обновить routes, если есть ссылки
3. Переименовать v3 → canonical

#### 2.1.3 ClickUp Integration

```bash
# Файлы к удалению:
services/clickup.py                     # DELETE
api/routes/integrations/clickup.py      # DELETE
```

**Действия:**
1. Найти зависимости
2. Удалить imports
3. Удалить endpoints

#### 2.1.4 Endpoint Audit

**Необходим аудит следующих групп:**
- `api/routes/integrations/*.py` — 42+ функций
- `api/routes/training.py` — если существует
- `api/routes/templates.py` — template builder запрещен

**Критерий удаления:** endpoint НЕ служит 6 Production Gates

---

### A2. E2E Tests (Неделя 1)

**Требуется написать 5 тестов:**

| # | Тест | Описание | Файл |
|---|------|----------|------|
| 1 | Copart Pipeline | Upload copart.pdf → Extract → Verify fields | `e2e/tests/copart.spec.ts` |
| 2 | IAA Pipeline | Upload iaa.pdf → Extract → Verify fields | `e2e/tests/iaa.spec.ts` |
| 3 | Manheim Pipeline | Upload manheim.pdf → Extract → Verify fields | `e2e/tests/manheim.spec.ts` |
| 4 | CD Export Validation | Review → Preflight → Export → Verify CD response | `e2e/tests/cd-export.spec.ts` |
| 5 | Error Handling | DLQ capture, alert trigger, graceful degradation | `e2e/tests/errors.spec.ts` |

**Зависимости:**
- Golden dataset документы для каждого типа аукциона
- CD API mock или sandbox

---

### A3. Sheets Exporter (Неделя 1)

После удаления v1/v2:
1. Rename `sheets_exporter_v3.py` → `sheets_exporter.py`
2. Verify DB→Sheets sync работает
3. Add 5-minute reconciliation job (если отсутствует)

---

### A4. PricingEngine Audit (Неделя 2)

**Проверить в `services/pricing_engine.py`:**

| Компонент | Требование | Статус |
|-----------|-----------|--------|
| Base formula | dispatch/listing spread | ? |
| STANDARD modifier | ×1.0 | ? |
| PRIORITY modifier | ×1.12 | ? |
| URGENT modifier | ×1.25 | ? |
| Floor/ceiling | Constraints | ? |
| Fallback | MANUAL_REQUIRED status | ? |

**Действие:** Прочитать файл, сверить с требованиями, исправить GAPs.

---

### A5. Golden Dataset (Ongoing)

**Текущее:** 23 документа
**Цель:** 150 документов

**Приоритеты расширения:**
1. Production errors (документы, которые failed)
2. Geographic variety (разные штаты, zip codes)
3. Missing fields edge cases
4. Multi-vehicle lots

---

## 3. Track B: Frontend UI — Детальный План

### B1. Evidence Overlay (Неделя 1)

**Требование:** Проверить формулу:
```javascript
canvas_y = page_height - pdf_y - bbox_height
```

**Файл:** `web/src/components/PDFViewer.jsx` или `PdfZoneViewer.jsx`

**Действие:** Code review + тест с реальным документом

---

### B2. Stabilize 4 Pages (Неделя 1-2)

| Страница | Файл | Требования |
|----------|------|-----------|
| Documents | `pages/Documents.jsx` | List, upload, status filter |
| Review | `pages/Review.jsx` | PDF overlay, field editing, preflight |
| TestLab | `pages/TestLab.jsx` | Sandbox extraction testing |
| Settings | `pages/Settings.jsx` | Connection status indicators |

**Особый фокус:** Connection status indicators в Settings (CD, Email, Sheets статусы)

---

### B3. Pricing UI (Неделя 2)

**Добавить в Review page:**
- Market data display
- Recommended price
- Floor/ceiling визуализация
- Warnings
- Final price override field

---

### B4. Export Flow UI (Неделя 2)

**Проверить наличие:**
- [x] `PreflightBanner.jsx` — существует
- [x] `ExportPreviewModal.jsx` — существует
- [ ] Preflight check button — проверить
- [ ] Result status display — проверить

---

## 4. Track C: Infrastructure

### C1. Monitoring

**Требования:**
- Structured logging to stdout
- Alerts для: DLQ items, export failures, daily cost, accuracy drops

**Проверить:** `api/audit_log.py`, DLQ endpoints

### C2. Database

**Решение:** SQLite (финальное, не обсуждается)

---

## 5. Explicit Prohibitions — Контрольный Список

| Запрет | Текущий Код | Действие |
|--------|-------------|----------|
| No new API endpoints | — | Не создавать |
| No ML/PEFT | `training_service.py` | **ОБСУДИТЬ** |
| No template builder UI | `VisualZoneEditor.jsx`? | Проверить |
| No ClickUp | Существует | Удалить |
| No auth systems | `oauth.py` существует | **ОБСУДИТЬ** |
| No microservices | — | Не создавать |
| No WebSocket | — | Не создавать |
| No ADRs | — | Не создавать |
| No Prometheus/Grafana | — | Не добавлять |
| No RingCentral SMS | — | Не добавлять |

---

## 6. Вопросы для Согласования

### Критические

1. **training_service.py** — Удалять или сохранять? Директива говорит удалить, но функционал может быть нужен.

2. **oauth.py** — Это часть auth system. Используется ли? Удалять?

3. **VisualZoneEditor.jsx** — Это template builder UI? Подпадает под запрет?

4. **CD API Sandbox** — Есть ли sandbox для E2E тестов export?

### Уточняющие

5. **Webhook override mechanism** — Реализован ли в Sheets exporter v3?

6. **5-minute reconciliation job** — Существует ли?

7. **DLQ alerts** — Как настроены? Куда отправляются?

---

## 7. Предлагаемый Timeline

```
НЕДЕЛЯ 1 (День 1-5):
├── День 1: Dead code removal (A1)
│   ├── Удалить sheets v1/v2
│   ├── Удалить ClickUp
│   └── Решить вопрос training_service
├── День 2-3: E2E тесты 1-3 (Copart, IAA, Manheim)
├── День 4: E2E тесты 4-5 (CD export, errors)
└── День 5: Evidence overlay fix + UI stabilization

НЕДЕЛЯ 2 (День 6-10):
├── День 6-7: PricingEngine audit + implementation
├── День 8: Pricing UI
├── День 9: Export flow UI completion
└── День 10: Full 20-document test

НЕДЕЛЯ 3+:
├── Golden dataset expansion (23→150)
├── Production failure fixes
└── UI polish
```

---

## 8. Definition of Done

- [ ] Все 6 Production Gates — GREEN
- [ ] 5 E2E тестов — PASSING
- [ ] Zero dead code
- [ ] Operational UI (4 pages stable)
- [ ] 20 real documents processed E2E
- [ ] Alerts functional

---

*Создано: 2026-02-11*
*Требует согласования: Вопросы из секции 6*
