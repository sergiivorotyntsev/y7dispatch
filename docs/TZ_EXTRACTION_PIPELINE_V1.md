# Техническое Задание: Пайплайн Извлечения Данных из Документов
## Версия 1.0 | CENTRALDISPATCH

---

## 1. ДИАГНОСТИКА ТЕКУЩЕЙ ПРОБЛЕМЫ

### 1.1 Симптомы (что видно сейчас)

- **Review & Post**: все обязательные поля пустые, огромный список Blocking Issues
- **Review & Train**: документ отображается, но все поля пустые
- **Вывод**: проблема НЕ в UI, а **раньше по пайплайну**: текст → классификация → извлечение → сохранение

### 1.2 Контрольные точки пайплайна

| # | Этап | Таблица/Поле | Что проверить |
|---|------|--------------|---------------|
| 1 | Text Extraction | `documents.raw_text` | Длина текста > 100 символов |
| 2 | Classification | `extraction_runs.auction_type_id` | Правильный тип определён |
| 3 | Field Extraction | `extraction_runs.outputs_json` | НЕ пустой JSON |
| 4 | Review Items | `review_items.predicted_value` | Значения заполнены |
| 5 | UI Fetch | `/api/extractions/{id}` | Поля в ответе |

### 1.3 Диагностический SQL-запрос

```sql
-- Проверить последние загруженные документы
SELECT
    d.id as doc_id,
    d.filename,
    LENGTH(d.raw_text) as text_length,
    er.id as run_id,
    er.status,
    er.extraction_score,
    LENGTH(er.outputs_json) as outputs_length,
    (SELECT COUNT(*) FROM review_items ri WHERE ri.run_id = er.id AND ri.predicted_value IS NOT NULL) as filled_fields
FROM documents d
LEFT JOIN extraction_runs er ON er.document_id = d.id
ORDER BY d.created_at DESC
LIMIT 10;
```

### 1.4 Наиболее вероятные причины (P1)

| Причина | Как проверить | Решение |
|---------|---------------|---------|
| **PDF-изображение** (OCR нужен) | `raw_text` < 100 chars | Добавить Tesseract OCR |
| **Экстрактор не распознал** | `extraction_score` < 0.3 | Добавить паттерны для нового типа |
| **Regex не совпал** | `outputs_json = {}` или `null` | Обновить regex в extractors/ |
| **Ключи не совпадают** | UI ожидает `vehicle_vin`, а получает `vin` | Синхронизировать naming |
| **Ошибка сохранения** | `errors_json` не пуст | Исправить exception |

---

## 2. АРХИТЕКТУРА ДАННЫХ

### 2.1 Текущие таблицы

```
documents
├── id, uuid, filename, file_path
├── raw_text         ← Извлечённый текст (pdfplumber)
├── auction_type_id  ← Определённый тип документа
└── created_at

extraction_runs
├── id, uuid, document_id
├── auction_type_id
├── status           ← pending → processing → needs_review → exported | failed
├── extraction_score ← Confidence 0.0-1.0
├── outputs_json     ← ⭐ КЛЮЧЕВОЕ: извлечённые поля
├── errors_json
└── created_at

review_items
├── id, run_id
├── source_key       ← "vehicle_vin", "pickup_address"
├── predicted_value  ← ⭐ Значение из extraction
├── corrected_value  ← Правка пользователя
├── confidence
└── status
```

### 2.2 Новые сущности (добавить)

```sql
-- Блоки текста с координатами (для layout-based extraction)
CREATE TABLE extracted_blocks (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES extraction_runs(id),
    page_number INTEGER NOT NULL,
    block_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    bbox_x1 REAL,
    bbox_y1 REAL,
    bbox_x2 REAL,
    bbox_y2 REAL,
    reading_order INTEGER,
    block_type TEXT,  -- 'text', 'table', 'header', 'label', 'value'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evidence: привязка поля к блокам (для обучения)
CREATE TABLE field_evidence (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    block_id INTEGER REFERENCES extracted_blocks(id),
    confidence REAL,
    extraction_method TEXT,  -- 'regex', 'label_below', 'spatial', 'ml'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Коррекции для обучения
CREATE TABLE correction_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT,  -- 'user_edit', 'warehouse_const', 'auction_const'
    applied_to_training BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Профили шаблонов для аукционов
CREATE TABLE auction_template_profiles (
    id INTEGER PRIMARY KEY,
    auction_type_id INTEGER NOT NULL REFERENCES auction_types(id),
    field_key TEXT NOT NULL,
    extraction_method TEXT NOT NULL,  -- 'regex', 'label_below', 'label_inline', 'position'
    label_patterns TEXT,  -- JSON array
    regex_pattern TEXT,
    default_value TEXT,   -- Константа для этого типа
    confidence_threshold REAL DEFAULT 0.5,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. ПАЙПЛАЙН ИЗВЛЕЧЕНИЯ (новая версия)

### 3.1 Этапы обработки

```
┌─────────────────┐
│ 1. INGEST       │ PDF/Email → documents table
│    (upload)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. TEXT         │ pdfplumber → raw_text
│    EXTRACTION   │ IF text < 100 chars → OCR (Tesseract)
│                 │ Результат: extracted_blocks + raw_text
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. CLASSIFY     │ ExtractorManager.classify(text)
│                 │ → auction_type_id + confidence
│                 │ IF confidence < 0.3 → status="needs_classification"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. EXTRACT      │ extractor.extract(pdf_path, text, blocks)
│    FIELDS       │ → outputs_json + field_evidence
│                 │ Комбинация: template rules + regex + spatial
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. CREATE       │ outputs → review_items
│    REVIEW ITEMS │ field_mappings + auction_template_profiles
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 6. UI REVIEW    │ ListingReview / Review & Train
│                 │ User corrections → correction_events
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 7. EXPORT       │ build_cd_payload() → Central Dispatch API
│                 │ ETag/If-Match, retry-safe POST
└─────────────────┘
```

### 3.2 Новый модуль извлечения текста

**Файл:** `extractors/text_extractor.py`

```python
"""
Layout-aware text extraction with block detection.
Решает проблему "линейного текста" - извлекает блоками как читает человек.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import pdfplumber
import pytesseract
from PIL import Image

@dataclass
class TextBlock:
    """Блок текста с координатами."""
    text: str
    page: int
    bbox: Tuple[float, float, float, float]  # x0, y0, x1, y1
    reading_order: int
    block_type: str = "text"  # text, label, value, table

@dataclass
class DocumentStructure:
    """Структура документа с блоками."""
    raw_text: str
    blocks: List[TextBlock]
    page_count: int
    text_mode: str  # "pdf", "ocr", "hybrid"
    needs_ocr: bool = False

def extract_document_structure(pdf_path: str) -> DocumentStructure:
    """
    Извлечь текст и структуру документа.

    1. Пробуем pdfplumber (для текстовых PDF)
    2. Если текста < 100 chars → OCR
    3. Возвращаем блоки с координатами
    """
    blocks = []
    raw_text = ""
    text_mode = "pdf"

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            # Извлечь текст с координатами
            words = page.extract_words()

            if words:
                # Группировать слова в блоки по proximity
                page_blocks = _group_words_to_blocks(words, page_num)
                blocks.extend(page_blocks)
                raw_text += page.extract_text() or ""
            else:
                # Нет текста - нужен OCR
                text_mode = "ocr"
                ocr_blocks = _extract_with_ocr(page, page_num)
                blocks.extend(ocr_blocks)
                raw_text += "\n".join(b.text for b in ocr_blocks)

    # Сортировать блоки по reading order
    blocks.sort(key=lambda b: (b.page, b.reading_order))

    return DocumentStructure(
        raw_text=raw_text,
        blocks=blocks,
        page_count=len(pdf.pages),
        text_mode=text_mode,
        needs_ocr=text_mode == "ocr" or len(raw_text) < 100,
    )

def _group_words_to_blocks(words: List[dict], page_num: int) -> List[TextBlock]:
    """Группировать слова в логические блоки по proximity."""
    # Алгоритм: слова близкие по Y-координате → одна строка
    # Строки близкие по Y-gap → один блок
    # ...реализация алгоритма кластеризации...
    pass

def _extract_with_ocr(page, page_num: int) -> List[TextBlock]:
    """OCR для страницы-изображения."""
    # Конвертировать страницу в изображение
    img = page.to_image(resolution=300).original

    # Tesseract с данными о координатах
    ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    blocks = []
    # ...парсинг OCR данных в TextBlock...
    return blocks
```

### 3.3 Улучшенный экстрактор полей

**Файл:** `extractors/field_extractor.py`

```python
"""
Field extraction using multiple strategies with evidence tracking.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class FieldExtraction:
    """Результат извлечения одного поля."""
    value: Optional[str]
    confidence: float
    method: str  # 'regex', 'label_below', 'spatial', 'template_const'
    evidence_block_ids: List[int] = None
    source: str = "extracted"  # 'extracted', 'template_const', 'default'

class FieldExtractor:
    """Извлекает поля используя комбинацию методов."""

    def __init__(self, auction_type_code: str):
        self.auction_type = auction_type_code
        self.template_profile = self._load_template_profile()

    def extract_all_fields(
        self,
        text: str,
        blocks: List[TextBlock],
        field_keys: List[str]
    ) -> Dict[str, FieldExtraction]:
        """
        Извлечь все поля для документа.

        Приоритет методов:
        1. Template constant (если поле = const для этого типа)
        2. Learned rules (из training)
        3. Spatial extraction (label → value nearby)
        4. Regex patterns
        5. Default value
        """
        results = {}

        for field_key in field_keys:
            # Проверить константу из профиля
            profile = self.template_profile.get(field_key)
            if profile and profile.get('default_value'):
                results[field_key] = FieldExtraction(
                    value=profile['default_value'],
                    confidence=1.0,
                    method='template_const',
                    source='template_const',
                )
                continue

            # Извлечь значение
            result = self._extract_field(field_key, text, blocks, profile)
            results[field_key] = result

        return results

    def _extract_field(
        self,
        field_key: str,
        text: str,
        blocks: List[TextBlock],
        profile: Dict = None
    ) -> FieldExtraction:
        """Извлечь одно поле."""

        # Strategy 1: Spatial (label-based)
        if profile and profile.get('label_patterns'):
            value, block_ids = self._extract_spatial(
                blocks, profile['label_patterns']
            )
            if value:
                return FieldExtraction(
                    value=value,
                    confidence=0.8,
                    method='label_below',
                    evidence_block_ids=block_ids,
                )

        # Strategy 2: Regex
        if profile and profile.get('regex_pattern'):
            value = self._extract_regex(text, profile['regex_pattern'])
            if value:
                return FieldExtraction(
                    value=value,
                    confidence=0.7,
                    method='regex',
                )

        # Strategy 3: Default field-specific patterns
        value = self._extract_default_patterns(field_key, text, blocks)
        if value:
            return FieldExtraction(
                value=value,
                confidence=0.5,
                method='default_pattern',
            )

        # Not found
        return FieldExtraction(
            value=None,
            confidence=0.0,
            method='not_found',
        )
```

---

## 4. КОНСТАНТЫ И СПРАВОЧНИКИ

### 4.1 Auction Template Constants

Для каждого типа аукциона определить:

| Поле | IAA | Copart | Manheim |
|------|-----|--------|---------|
| `pickup_name` | "IAA {branch}" | "Copart {location}" | "Manheim" |
| `vehicle_condition` | extract | extract | default="OPERABLE" |
| `trailer_type` | default="OPEN" | default="OPEN" | extract |

**Пример конфигурации:**

```json
{
  "auction_type": "COPART",
  "field_profiles": {
    "pickup_name": {
      "extraction_method": "label_below",
      "label_patterns": ["PHYSICAL ADDRESS OF LOT", "LOT LOCATION"],
      "transform": "prefix:Copart"
    },
    "vehicle_condition": {
      "extraction_method": "regex",
      "regex_pattern": "(RUNS|INOP|INOPERABLE|STARTS)",
      "value_map": {
        "RUNS": "OPERABLE",
        "STARTS": "OPERABLE",
        "INOP": "INOPERABLE",
        "INOPERABLE": "INOPERABLE"
      },
      "default_value": "OPERABLE"
    }
  }
}
```

### 4.2 Warehouse Constants

При выборе склада автоматически заполняются:

| Поле | Источник |
|------|----------|
| `delivery_name` | `warehouses.name` |
| `delivery_address` | `warehouses.address` |
| `delivery_city` | `warehouses.city` |
| `delivery_state` | `warehouses.state` |
| `delivery_zip` | `warehouses.zip_code` |
| `delivery_phone` | `warehouses.contact.phone` |
| `transport_special_instructions` | `warehouses.requirements.special_instructions` |

---

## 5. ТРЕБОВАНИЯ CD API V2 (Validation Rules)

### 5.1 Правила валидации

| Поле | Правило | Код ошибки |
|------|---------|------------|
| `availableDate` | >= today, <= today+30 | CD_DATE_RANGE |
| `expirationDate` | >= today, <= today+30 | CD_DATE_RANGE |
| `desiredDeliveryDate` | >= availableDate, >= today, <= today+30 | CD_DATE_RANGE |
| `externalId` | <= 50 chars | CD_LENGTH_LIMIT |
| `partnerReferenceId` | <= 50 chars | CD_LENGTH_LIMIT |
| `shipperOrderId` | <= 50 chars | CD_LENGTH_LIMIT |
| `stops` | exactly 2 stops | CD_STOPS_COUNT |
| `vehicles` | 1-12 vehicles | CD_VEHICLE_COUNT |
| `vehicles[].vin` | 17 chars, no I/O/Q | CD_VIN_FORMAT |

### 5.2 Rate Limiting

- **Semaphore**: max 3 concurrent requests to CD API
- **Retry**: 429 → respect Retry-After header, exponential backoff
- **Retry**: 5xx → max 3 attempts, exponential backoff (2s, 4s, 8s)

---

## 6. UI/UX REQUIREMENTS

### 6.1 Documents Table

Добавить колонки:

| Колонка | Описание |
|---------|----------|
| `auto_fill_score` | % заполненных required полей |
| `text_mode` | "pdf" / "ocr" / "hybrid" |
| `blocks_count` | Количество извлечённых блоков |

### 6.2 Review & Post

Для каждого поля показывать:

- **Value**: текущее значение
- **Source badge**: `MODEL` / `CONST` / `USER` / `EMPTY`
- **Confidence**: (если MODEL) процент уверенности
- **Evidence icon**: клик → показать блок документа

### 6.3 Extraction Details Panel

В Review & Post добавить панель с метаданными:

```
┌─────────────────────────────────────────┐
│ Extraction Details                      │
├─────────────────────────────────────────┤
│ Run ID: 123                             │
│ Status: needs_review                    │
│ Text Mode: pdf                          │
│ Text Length: 2,456 chars                │
│ Blocks Count: 45                        │
│ Fields Extracted: 12/24                 │
│ Confidence: 78%                         │
└─────────────────────────────────────────┘
```

---

## 7. ACCEPTANCE CRITERIA

### 7.1 Критерий "Базовое извлечение работает"

На 1 тестовом документе:
- [ ] `raw_text` > 500 chars (или OCR blocks_count > 20)
- [ ] `extraction_score` > 0.3
- [ ] `extracted_fields_count` >= 5 (VIN, year, make, model, pickup_city)
- [ ] UI показывает значения без ручного ввода

### 7.2 Метрики качества

| Метрика | Target | Measurement |
|---------|--------|-------------|
| Doc type accuracy | >= 95% | correct_type / total_docs |
| Field precision (VIN) | >= 90% | correct_vin / extracted_vin |
| Field precision (address) | >= 70% | correct_addr / extracted_addr |
| Ready-to-post rate | >= 40% | ready_docs / total_docs |
| Manual edits per doc | <= 5 | avg(corrections_count) |

### 7.3 Тестовый датасет

- [ ] IAA: 50 PDF (разные филиалы)
- [ ] Copart: 50 PDF
- [ ] Сканы (OCR-only): 20 PDF

---

## 8. ПЛАН РЕАЛИЗАЦИИ

### Phase 1: Диагностика (1-2 дня)

1. Добавить логирование в `run_extraction()`:
   - `raw_text` length
   - `classification_score`
   - `outputs` keys count
2. Проверить 3 реальных документа через SQL
3. Определить root cause

### Phase 2: Quick Fixes (3-5 дней)

1. Если OCR нужен → добавить Tesseract
2. Если regex не совпадают → обновить паттерны
3. Если ключи не совпадают → синхронизировать naming

### Phase 3: Layout-Aware Extraction (1-2 недели)

1. Реализовать `extract_document_structure()`
2. Добавить `extracted_blocks` table
3. Обновить экстракторы для работы с блоками

### Phase 4: Training Pipeline (2-3 недели)

1. Реализовать `correction_events` → training ingestion
2. Добавить `auction_template_profiles` UI
3. Автоматическое обновление профилей из corrections

---

## 9. НЕМЕДЛЕННЫЕ ДЕЙСТВИЯ

### Шаг 1: Диагностика конкретного документа

```bash
# В Python shell
from api.models import DocumentRepository, ExtractionRunRepository

# Найти последний документ
docs = DocumentRepository.list_all(limit=5)
for doc in docs:
    print(f"Doc {doc.id}: {doc.filename}")
    print(f"  raw_text length: {len(doc.raw_text or '')}")

    # Найти extraction run
    runs = ExtractionRunRepository.list_by_document(doc.id)
    for run in runs:
        print(f"  Run {run.id}: status={run.status}, score={run.extraction_score}")
        print(f"    outputs_json: {run.outputs_json}")
```

### Шаг 2: Тестовое извлечение

```python
from extractors import ExtractorManager

manager = ExtractorManager()

# Загрузить текст документа
with open("/path/to/test.pdf", "rb") as f:
    text = manager.extractors[0].extract_text("/path/to/test.pdf")

print(f"Text length: {len(text)}")
print(f"First 500 chars:\n{text[:500]}")

# Классифицировать
classification = manager.classify("/path/to/test.pdf")
print(f"Detected: {classification.source}, score={classification.score}")

# Извлечь
result = manager.extract_with_result("/path/to/test.pdf")
print(f"Invoice: {result.invoice}")
```

---

## 10. КОНТАКТЫ И ОТВЕТСТВЕННОСТЬ

| Компонент | Ответственный |
|-----------|---------------|
| Text Extraction | Data Science |
| Field Extractors | Full Stack |
| CD API Integration | Backend |
| UI/UX | Frontend |
| Training Pipeline | Data Science + Backend |

---

**Документ создан:** 2026-02-02
**Версия:** 1.0
**Статус:** Draft for Review
