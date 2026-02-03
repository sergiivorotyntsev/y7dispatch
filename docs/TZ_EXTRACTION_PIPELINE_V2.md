# Техническое Задание: Пайплайн Извлечения Данных из Документов
## Версия 2.0 | CENTRALDISPATCH

---

## СОДЕРЖАНИЕ

1. [P0: Обязательные уточнения](#p0-обязательные-уточнения)
2. [Архитектура данных](#архитектура-данных)
3. [Пайплайн извлечения](#пайплайн-извлечения)
4. [OCR стратегия](#ocr-стратегия)
5. [Layout-Aware Extraction](#layout-aware-extraction)
6. [Auction Template Profiles](#auction-template-profiles)
7. [Observability](#observability)
8. [Phase 1: Диагностика](#phase-1-диагностика)
9. [Phase 2: Quick Fixes](#phase-2-quick-fixes)
10. [Phase 3: Layout-Aware Extraction](#phase-3-layout-aware-extraction)
11. [Golden Dataset и Метрики](#golden-dataset-и-метрики)

---

## P0: ОБЯЗАТЕЛЬНЫЕ УТОЧНЕНИЯ

### P0-1: Canonical Keys — Единый Набор Ключей

**Принцип:** Один набор ключей используется везде: extraction → UI → blocking issues → CD payload.

#### Canonical Keyset (listing_fields.py — источник правды)

| Секция | Ключ | CD API Key | Обязательное |
|--------|------|------------|--------------|
| vehicle | `vehicle_vin` | `vehicles[0].vin` | ✓ |
| vehicle | `vehicle_year` | `vehicles[0].year` | ✓ |
| vehicle | `vehicle_make` | `vehicles[0].make` | ✓ |
| vehicle | `vehicle_model` | `vehicles[0].model` | ✓ |
| vehicle | `vehicle_color` | `vehicles[0].color` | |
| vehicle | `vehicle_type` | `vehicles[0].vehicleType` | ✓ |
| vehicle | `vehicle_condition` | `vehicles[0].isOperable` | ✓ |
| vehicle | `vehicle_lot` | `vehicles[0].lotNumber` | |
| pickup | `pickup_name` | `stops[0].locationName` | |
| pickup | `pickup_address` | `stops[0].address.street` | ✓ |
| pickup | `pickup_city` | `stops[0].address.city` | ✓ |
| pickup | `pickup_state` | `stops[0].address.state` | ✓ |
| pickup | `pickup_zip` | `stops[0].address.postalCode` | ✓ |
| pickup | `pickup_phone` | `stops[0].contact.phone` | |
| pickup | `pickup_contact` | `stops[0].contact.name` | |
| delivery | `delivery_name` | `stops[1].locationName` | |
| delivery | `delivery_address` | `stops[1].address.street` | ✓ |
| delivery | `delivery_city` | `stops[1].address.city` | ✓ |
| delivery | `delivery_state` | `stops[1].address.state` | ✓ |
| delivery | `delivery_zip` | `stops[1].address.postalCode` | ✓ |
| delivery | `delivery_phone` | `stops[1].contact.phone` | |
| additional | `available_date` | `availableDate` | ✓ |
| additional | `expiration_date` | `expirationDate` | |
| additional | `trailer_type` | `trailerType` | ✓ |
| additional | `external_id` | `externalId` | |
| additional | `buyer_id` | — (internal) | |
| additional | `buyer_name` | — (internal) | |
| additional | `sale_date` | — (internal) | |
| notes | `transport_special_instructions` | `transportationReleaseNotes` | |

#### Back-Compat Mapping (Legacy → Canonical)

| Legacy Key | Canonical Key | Удалить после |
|------------|---------------|---------------|
| `vin` | `vehicle_vin` | 2026-03-01 |
| `year` | `vehicle_year` | 2026-03-01 |
| `make` | `vehicle_make` | 2026-03-01 |
| `model` | `vehicle_model` | 2026-03-01 |
| `lot_number` | `vehicle_lot` | 2026-03-01 |
| `pickup_street` | `pickup_address` | 2026-03-01 |
| `delivery_street` | `delivery_address` | 2026-03-01 |
| `reference_id` | `external_id` | 2026-03-01 |

**Реализация:** В `api/routes/extractions.py` добавить маппинг:

```python
LEGACY_KEY_MAP = {
    "vin": "vehicle_vin",
    "year": "vehicle_year",
    # ... etc
}

def normalize_keys(outputs: dict) -> dict:
    """Convert legacy keys to canonical keys."""
    normalized = {}
    for key, value in outputs.items():
        canonical = LEGACY_KEY_MAP.get(key, key)
        normalized[canonical] = value
    return normalized
```

---

### P0-2: Порядок Приоритетов (Precedence) для Автозаполнения

**Правило:** Значения полей определяются в следующем порядке приоритета:

```
1. USER_OVERRIDE      — ручная правка в UI (высший приоритет)
2. WAREHOUSE_CONST    — из справочника склада
3. AUCTION_CONST      — из профиля аукциона
4. EXTRACTED          — извлечённое из документа
5. DEFAULT            — значение по умолчанию
6. EMPTY              — пусто (низший приоритет)
```

#### Какие поля можно перезаписывать при выборе Warehouse:

| Поле | Warehouse Override | Комментарий |
|------|-------------------|-------------|
| `delivery_name` | ✓ | Всегда из warehouse |
| `delivery_address` | ✓ | Всегда из warehouse |
| `delivery_city` | ✓ | Всегда из warehouse |
| `delivery_state` | ✓ | Всегда из warehouse |
| `delivery_zip` | ✓ | Всегда из warehouse |
| `delivery_phone` | ✓ | Всегда из warehouse |
| `transport_special_instructions` | ✓ | Merge с извлечённым |
| `vehicle_vin` | ✗ | Никогда не трогать |
| `pickup_*` | ✗ | Никогда не трогать |

#### Структура хранения источника значения:

```python
@dataclass
class FieldValue:
    value: Any
    source: ValueSource  # USER_OVERRIDE | WAREHOUSE_CONST | AUCTION_CONST | EXTRACTED | DEFAULT
    confidence: float    # 0.0-1.0 (для EXTRACTED)
    evidence_block_id: Optional[int]  # Ссылка на блок текста
    updated_at: datetime
```

---

### P0-3: Layout-Aware Extraction — Конкретный Алгоритм

#### Вход:
- PDF файл
- pdfplumber words: `[{text, x0, top, x1, bottom, page}, ...]`

#### Алгоритм:

```python
def extract_blocks(pdf_path: str, y_tolerance: float = 3.0) -> List[TextBlock]:
    """
    Алгоритм кластеризации слов → строк → блоков.

    Шаг 1: Cluster words в lines по top с допуском y_tolerance
    Шаг 2: Sort слова внутри line по x0 (left-to-right)
    Шаг 3: Merge lines в blocks по вертикальному gap
    Шаг 4: Multi-column detection по распределению x0
    """
    blocks = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words()
            if not words:
                continue

            # Step 1: Group words into lines by y-coordinate
            lines = cluster_words_to_lines(words, y_tolerance)

            # Step 2: Sort words within each line by x-coordinate
            for line in lines:
                line['words'].sort(key=lambda w: w['x0'])

            # Step 3: Detect columns
            columns = detect_columns(lines, page.width)

            # Step 4: Build blocks respecting column order
            page_blocks = build_blocks_from_columns(lines, columns, page_num)
            blocks.extend(page_blocks)

    return blocks


def cluster_words_to_lines(words: List[dict], y_tolerance: float) -> List[dict]:
    """Кластеризация слов в строки по Y-координате."""
    if not words:
        return []

    # Sort by top coordinate
    sorted_words = sorted(words, key=lambda w: (w['top'], w['x0']))

    lines = []
    current_line = {'top': sorted_words[0]['top'], 'words': [sorted_words[0]]}

    for word in sorted_words[1:]:
        # Same line if within y_tolerance
        if abs(word['top'] - current_line['top']) <= y_tolerance:
            current_line['words'].append(word)
        else:
            lines.append(current_line)
            current_line = {'top': word['top'], 'words': [word]}

    lines.append(current_line)
    return lines


def detect_columns(lines: List[dict], page_width: float) -> List[tuple]:
    """
    Detect column boundaries based on x0 distribution.

    Returns list of (x_start, x_end) tuples for each column.
    """
    # Collect all x0 values
    x_positions = []
    for line in lines:
        for word in line['words']:
            x_positions.append(word['x0'])

    if not x_positions:
        return [(0, page_width)]

    # Simple heuristic: if there's a gap > 20% of page width, it's a column break
    x_positions.sort()

    # Find significant gaps
    gaps = []
    for i in range(1, len(x_positions)):
        gap = x_positions[i] - x_positions[i-1]
        if gap > page_width * 0.15:  # 15% threshold
            gaps.append((x_positions[i-1], x_positions[i]))

    # Build columns from gaps
    if not gaps:
        return [(0, page_width)]

    columns = []
    prev_end = 0
    for gap_start, gap_end in gaps:
        columns.append((prev_end, gap_start))
        prev_end = gap_end
    columns.append((prev_end, page_width))

    return columns


def build_blocks_from_columns(
    lines: List[dict],
    columns: List[tuple],
    page_num: int
) -> List[TextBlock]:
    """Build text blocks respecting column boundaries."""
    blocks = []

    for col_idx, (col_start, col_end) in enumerate(columns):
        col_lines = []

        for line in lines:
            # Filter words that belong to this column
            col_words = [
                w for w in line['words']
                if col_start <= w['x0'] < col_end
            ]
            if col_words:
                col_lines.append({
                    'top': line['top'],
                    'words': col_words,
                    'text': ' '.join(w['text'] for w in col_words)
                })

        # Merge consecutive lines into blocks
        if col_lines:
            block_text = '\n'.join(l['text'] for l in col_lines)
            bbox = (
                min(w['x0'] for l in col_lines for w in l['words']),
                min(l['top'] for l in col_lines),
                max(w['x1'] for l in col_lines for w in l['words']),
                max(l['top'] for l in col_lines) + 10  # Approximate bottom
            )

            blocks.append(TextBlock(
                text=block_text,
                page=page_num,
                bbox=bbox,
                reading_order=col_idx,
                column_index=col_idx
            ))

    return blocks
```

#### Система координат:
- **Origin:** Top-left (0, 0)
- **Units:** Points (1/72 inch)
- **Для UI подсветки:** Конвертация в проценты от размера страницы

```python
def bbox_to_percent(bbox: tuple, page_width: float, page_height: float) -> dict:
    """Convert bbox to percentage coordinates for UI overlay."""
    x0, y0, x1, y1 = bbox
    return {
        'left': x0 / page_width * 100,
        'top': y0 / page_height * 100,
        'width': (x1 - x0) / page_width * 100,
        'height': (y1 - y0) / page_height * 100,
    }
```

---

### P0-4: OCR Стратегия

#### Правила применения OCR:

| Условие | Действие |
|---------|----------|
| `words_count == 0` | OCR обязателен |
| `raw_text_len < 100` | OCR обязателен |
| `raw_text_len < 500` AND `pages > 1` | Возможен hybrid |
| Страница без слов в multi-page PDF | OCR только для этой страницы (hybrid) |

#### Режимы:

```python
class TextExtractionMode(Enum):
    PDF_TEXT = "pdf"      # Native text layer
    OCR = "ocr"           # Full OCR
    HYBRID = "hybrid"     # Mix of PDF text + OCR for some pages
```

#### Реализация с OCRmyPDF:

```python
import subprocess
import tempfile

def ensure_text_layer(pdf_path: str) -> tuple[str, TextExtractionMode]:
    """
    Ensure PDF has a text layer, using OCR if needed.

    Returns: (path_to_pdf_with_text, mode_used)
    """
    # Check if text layer exists
    with pdfplumber.open(pdf_path) as pdf:
        total_words = sum(len(page.extract_words() or []) for page in pdf.pages)
        total_chars = sum(len(page.extract_text() or '') for page in pdf.pages)

    if total_words > 20 and total_chars > 100:
        return pdf_path, TextExtractionMode.PDF_TEXT

    # Need OCR - use ocrmypdf
    output_path = tempfile.mktemp(suffix='.pdf')

    try:
        result = subprocess.run([
            'ocrmypdf',
            '--skip-text',      # Don't re-OCR pages with text
            '--deskew',         # Fix skewed scans
            '--rotate-pages',   # Auto-rotate
            '--language', 'eng',
            '--output-type', 'pdf',
            pdf_path,
            output_path
        ], capture_output=True, timeout=120)

        if result.returncode == 0:
            # Determine mode based on whether we had some text
            mode = TextExtractionMode.HYBRID if total_words > 0 else TextExtractionMode.OCR
            return output_path, mode
        else:
            logger.warning(f"OCR failed: {result.stderr}")
            return pdf_path, TextExtractionMode.PDF_TEXT

    except subprocess.TimeoutExpired:
        logger.error("OCR timeout")
        return pdf_path, TextExtractionMode.PDF_TEXT
```

#### Что сохранять в extraction_runs:

```sql
ALTER TABLE extraction_runs ADD COLUMN text_mode TEXT;           -- 'pdf', 'ocr', 'hybrid'
ALTER TABLE extraction_runs ADD COLUMN words_count INTEGER;
ALTER TABLE extraction_runs ADD COLUMN raw_text_len INTEGER;
ALTER TABLE extraction_runs ADD COLUMN ocr_applied BOOLEAN;
ALTER TABLE extraction_runs ADD COLUMN ocr_confidence_avg REAL;
```

---

### P0-5: Auction Template Profiles — JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AuctionTemplateProfile",
  "type": "object",
  "required": ["auction_type", "version", "match", "fields"],
  "properties": {
    "auction_type": {
      "type": "string",
      "enum": ["COPART", "IAA", "MANHEIM", "OTHER"]
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "match": {
      "type": "object",
      "description": "Rules for matching this profile to a document",
      "properties": {
        "sender_domains": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Email sender domains (e.g., copart.com)"
        },
        "subject_keywords": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Email subject keywords"
        },
        "text_indicators": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "pattern": {"type": "string"},
              "weight": {"type": "number", "default": 1.0}
            }
          }
        },
        "confidence_threshold": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "default": 0.6
        }
      }
    },
    "constants": {
      "type": "object",
      "description": "Fixed values for this auction type",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "value": {},
          "description": {"type": "string"}
        }
      }
    },
    "fields": {
      "type": "object",
      "description": "Extraction rules per field",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "extractor_type": {
            "type": "string",
            "enum": ["regex", "label_value", "table_cell", "spatial", "heuristic"]
          },
          "patterns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Regex patterns or label patterns"
          },
          "evidence_strategy": {
            "type": "string",
            "enum": ["nearest_block", "same_line", "below_label", "right_of_label"]
          },
          "postprocess": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": ["normalize_state", "zip_fix", "vin_strip", "date_parse", "uppercase", "titlecase"]
            }
          },
          "confidence_rule": {
            "type": "object",
            "properties": {
              "type": {"type": "string", "enum": ["hard", "soft"]},
              "threshold": {"type": "number"}
            }
          },
          "fallback_value": {}
        }
      }
    },
    "guaranteed_fields": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Fields this profile guarantees to extract (for quality metrics)"
    }
  }
}
```

#### Пример профиля для Copart:

```json
{
  "auction_type": "COPART",
  "version": "1.0.0",
  "match": {
    "sender_domains": ["copart.com", "copartmail.com"],
    "subject_keywords": ["Bill of Sale", "Sales Receipt", "Vehicle Release"],
    "text_indicators": [
      {"pattern": "SOLD THROUGH COPART", "weight": 5.0},
      {"pattern": "PHYSICAL ADDRESS OF LOT", "weight": 2.0},
      {"pattern": "copart.com", "weight": 4.0},
      {"pattern": "MEMBER:", "weight": 1.5}
    ],
    "confidence_threshold": 0.6
  },
  "constants": {
    "pickup_name_prefix": {
      "value": "Copart",
      "description": "Prefix for pickup location name"
    },
    "vehicle_condition_default": {
      "value": "OPERABLE",
      "description": "Default if not extracted"
    }
  },
  "fields": {
    "vehicle_vin": {
      "extractor_type": "regex",
      "patterns": ["VIN[:\\s]+([A-HJ-NPR-Z0-9]{17})", "\\b([A-HJ-NPR-Z0-9]{17})\\b"],
      "evidence_strategy": "nearest_block",
      "postprocess": ["vin_strip", "uppercase"],
      "confidence_rule": {"type": "hard", "threshold": 0.9}
    },
    "pickup_address": {
      "extractor_type": "label_value",
      "patterns": ["PHYSICAL ADDRESS OF LOT", "LOT LOCATION"],
      "evidence_strategy": "below_label",
      "postprocess": ["normalize_state"],
      "confidence_rule": {"type": "soft", "threshold": 0.7}
    },
    "buyer_id": {
      "extractor_type": "regex",
      "patterns": ["MEMBER[:\\s]+(\\d+)"],
      "evidence_strategy": "same_line",
      "confidence_rule": {"type": "hard", "threshold": 0.95}
    }
  },
  "guaranteed_fields": [
    "vehicle_vin",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "buyer_id",
    "pickup_city",
    "pickup_state"
  ]
}
```

---

### P0-6: Golden Dataset и Метрики

#### Структура датасета:

```
tests/golden_dataset/
├── copart/
│   ├── doc_001.pdf
│   ├── doc_001.json  # Ground truth
│   ├── doc_002.pdf
│   ├── doc_002.json
│   └── ...
├── iaa/
│   └── ...
├── manheim/
│   └── ...
└── scans/
    └── ...
```

#### Формат ground truth JSON:

```json
{
  "document_id": "copart_001",
  "source": "copart",
  "is_scan": false,
  "fields": {
    "vehicle_vin": "1HGCV1F34LA123456",
    "vehicle_year": 2020,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "pickup_address": "12020 US Highway 301 South",
    "pickup_city": "Riverview",
    "pickup_state": "FL",
    "pickup_zip": "33578"
  },
  "annotated_by": "human",
  "annotated_at": "2026-02-01T12:00:00Z"
}
```

#### Метрики по полям:

| Поле | Метрика | Формула | Target |
|------|---------|---------|--------|
| `vehicle_vin` | Exact Match | `extracted == ground_truth` | ≥ 95% |
| `vehicle_year` | Exact Match | `int(extracted) == int(ground_truth)` | ≥ 95% |
| `vehicle_make` | Fuzzy Match | `levenshtein(lower(extracted), lower(gt)) ≤ 2` | ≥ 90% |
| `vehicle_model` | Fuzzy Match | `levenshtein(lower(extracted), lower(gt)) ≤ 3` | ≥ 85% |
| `pickup_state` | Exact (normalized) | `normalize_state(extracted) == normalize_state(gt)` | ≥ 95% |
| `pickup_zip` | Exact (5 digits) | `extracted[:5] == gt[:5]` | ≥ 90% |
| `pickup_address` | Token Overlap | `jaccard(tokens(extracted), tokens(gt)) ≥ 0.7` | ≥ 80% |
| `pickup_city` | Fuzzy Match | `levenshtein ≤ 2` | ≥ 85% |

#### Minimum Dataset Size:

| Тип | Количество | Приоритет |
|-----|------------|-----------|
| Copart | 50 | P0 |
| IAA | 50 | P0 |
| Manheim | 30 | P1 |
| Scans (OCR) | 20 | P1 |
| **Total** | **150** | |

#### Целевые пороги по фазам:

| Метрика | Phase 2 | Phase 3 |
|---------|---------|---------|
| VIN Accuracy | ≥ 90% | ≥ 95% |
| Address Parts (city/state/zip) | ≥ 75% | ≥ 90% |
| Field Fill Rate | ≥ 60% | ≥ 80% |
| Zero-extraction rate | < 10% | < 2% |

---

### P0-7: Observability — Must Log & Persist

#### Для каждого extraction_run логировать и сохранять:

```python
@dataclass
class ExtractionMetrics:
    # Ingestion
    ingest_ok: bool
    pdf_open_ok: bool
    pages_count: int
    file_size_bytes: int

    # Text extraction
    text_mode: str  # pdf, ocr, hybrid
    words_count: int
    raw_text_len: int
    ocr_applied: bool
    ocr_elapsed_ms: Optional[int]

    # Classification
    auction_detected: str
    detector_score: float
    detector_patterns_matched: List[str]

    # Field extraction
    fields_filled_count: int
    required_missing_count: int
    blocking_issues_count: int

    # Performance
    extraction_elapsed_ms: int

    # Errors
    errors: List[str]
    warnings: List[str]
```

#### API Endpoint: Run Debug (read-only)

```
GET /api/extractions/{id}/debug
```

Response:
```json
{
  "run_id": 123,
  "document_id": 456,
  "metrics": {
    "ingest_ok": true,
    "pdf_open_ok": true,
    "pages_count": 1,
    "text_mode": "pdf",
    "words_count": 178,
    "raw_text_len": 1202,
    "auction_detected": "IAA",
    "detector_score": 1.0,
    "fields_filled_count": 12,
    "required_missing_count": 2,
    "blocking_issues_count": 3
  },
  "raw_text_preview": "First 500 chars...",
  "detected_patterns": ["Insurance Auto Auctions", "Buyer Receipt"],
  "field_sources": {
    "vehicle_vin": {"value": "WA1CCAFP4GA133227", "source": "EXTRACTED", "confidence": 0.95},
    "delivery_address": {"value": "123 Main St", "source": "WAREHOUSE_CONST", "confidence": 1.0}
  }
}
```

#### UI: Preflight Diagnostics Banner

В Review & Post показывать сверху:

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Extraction Details                                       │
├─────────────────────────────────────────────────────────────┤
│ Mode: PDF Text | Words: 178 | Chars: 1,202                  │
│ Detected: IAA (100%) | Fields: 12/14 | Issues: 3 blocking  │
│ ⚠️ Missing: pickup_address, pickup_phone                    │
└─────────────────────────────────────────────────────────────┘
```

Если `words_count == 0`:
```
┌─────────────────────────────────────────────────────────────┐
│ ⚠️ Document appears to be a scan without text layer         │
│ OCR processing required. [Run OCR] button                   │
└─────────────────────────────────────────────────────────────┘
```

---

## PHASE 1: ДИАГНОСТИКА (Root Cause)

**Цель:** Точно установить, почему после аплоада поля пустые.

### Чек-лист

#### 1) Воспроизводимость
- [ ] Собрать 3–5 реальных PDF (IAA/Copart + 1 скан)
- [ ] Для каждого: зафиксировать doc_id/run_id, source, тип, размер, страницы
- [ ] Проверить поведение в UI: Documents, Review & Post, Review & Train

#### 2) Инструментация пайплайна
Добавить логирование по шагам:
- [ ] Ingestion: файл получен, storage path, MIME, pages_count
- [ ] PDF Text Layer Check: есть ли текст (true/false), char_count
- [ ] OCR (если включен): применялся/нет, время, итоговый char_count
- [ ] Classification: detected_auction, score, features used
- [ ] Extraction: extractor_name, extracted_fields_count, empty_required_count
- [ ] Mapping → Field Registry: сколько ключей совпало, сколько потеряно
- [ ] Persist: запись в БД, размеры, json keys
- [ ] API Response: что возвращает бек (counts, schema_version)

#### 3) Быстрая проверка БД
Для каждого проблемного run_id:
- [ ] `documents.raw_text`: NULL? пустой? длина?
- [ ] `extraction_runs.outputs_json`: NULL? пустой? keys?
- [ ] `extraction_runs.status`: какие статусы выставляются?
- [ ] Проверить: не перетёрли ли outputs_json при Save Draft

#### 4) Диагностика "пустые поля" — 4 гипотезы

**H1: Нет текстового слоя / OCR не применяется**
- [ ] Подтвердить char_count=0 до и после OCR
- [ ] Проверить настройки OCR

**H2: Сломалась классификация**
- [ ] Сравнить score/auction_type с эталоном
- [ ] Логировать признаки классификации

**H3: Mapping потеря ключей**
- [ ] Сравнить ключи outputs_json vs registry keys
- [ ] Проверить naming conventions

**H4: UI не биндится к API**
- [ ] Проверить response в Network tab
- [ ] Убедиться в использовании правильного ID (run_id vs document_id)

#### 5) Артефакты Phase 1
- [ ] RC Report (1–2 страницы): причина + доказательства
- [ ] Fix Plan: какие изменения идут в Phase 2/3
- [ ] Smoke-tests: минимум 3 теста

#### 6) Exit Criteria
- [ ] Для 3 документов известно: на каком этапе теряются данные
- [ ] В логах есть полный трейс по одному run_id
- [ ] Не осталось "unknown" по: OCR, classification, mapping, UI-binding

---

## PHASE 2: QUICK FIXES

**Цель:** Реальные документы начинают заполнять ключевые поля.

### Чек-лист

#### 1) Text Layer / OCR fallback
- [ ] Правило: если char_count < threshold → OCR pipeline
- [ ] Сохранять: raw_text_before_ocr, raw_text_after_ocr, ocr_applied flag

#### 2) Починить классификацию
- [ ] Явные маркеры IAA/Copart: словарь/regex + confidence scoring
- [ ] Логи: top-5 matched markers, итоговый score
- [ ] Fallback: если не определили → generic extractor + "unknown_auction" tag

#### 3) Auction Template Profiles
- [ ] Сущность AuctionProfile: auction_type, fields_extracted[], constants[], parsing_rules
- [ ] UI в Settings: просмотр и редактирование профиля
- [ ] Версионирование: profile_version, applied_to_run_id

#### 4) Warehouse Directory
- [ ] Выбор warehouse заполняет delivery stop fields
- [ ] Заполняет transport_special_instructions
- [ ] Отображать source для delivery-полей

#### 5) Mapping "Extractor Output → Field Registry"
- [ ] Единый canonical keyset
- [ ] Слой алиасов для legacy keys
- [ ] Unit tests: минимум 10 кейсов

#### 6) Evidence/Provenance
- [ ] Для каждого поля: source_type, extractor_name, confidence, evidence_snippet

#### 7) UI: Review & Post / Review & Train
- [ ] Показывать: значения, источник, required/optional, валидации
- [ ] Review & Train: извлечённые поля как baseline

#### 8) Exit Criteria
- [ ] IAA/Copart: ≥ 70% ключевых полей автозаполнены
- [ ] Warehouse закрывает delivery + instructions
- [ ] Ни одна страница не показывает "всё пустое" на валидных PDF
- [ ] Отчёт "Field Fill Rate" по 20+ документам

---

## PHASE 3: LAYOUT-AWARE EXTRACTION

**Цель:** Убрать проблему "линейного текста", перейти к block-based extraction.

### Чек-лист

#### 1) Структурное извлечение PDF
- [ ] `extract_document_structure()`: pages[], blocks[] с bbox
- [ ] Reading order sort (top-to-bottom, left-to-right)
- [ ] Multi-column detection

#### 2) Новые таблицы
- [ ] `extracted_blocks`: run_id, page_num, block_index, bbox, text, reading_order
- [ ] `field_evidence`: run_id, field_key, evidence_type, page_num, bbox, snippet

#### 3) Block-aware extractors
- [ ] Переписать extractors: найти "якорные" блоки, затем spatial window
- [ ] Address parser: street, city, state, zip + валидатор

#### 4) Confusion cases
- [ ] 2+ колонки
- [ ] Адрес разбит по строкам
- [ ] Похожие названия локаций
- [ ] Fallback: regex по normalized_text

#### 5) Метрики качества
- [ ] Field Fill Rate
- [ ] Address Accuracy (ручная разметка)
- [ ] Evidence Coverage
- [ ] Drift detection alarm

#### 6) Regression Dataset + тестирование
- [ ] Dataset: 150 PDF minimum
- [ ] Golden labels: 25 документов
- [ ] Автотесты: VIN/lot/addresses parsing

#### 7) UI enhancements
- [ ] Blocks overlay (debug mode)
- [ ] Клик по полю → подсветить evidence block

#### 8) Exit Criteria
- [ ] Pickup address ≥ 90% для IAA/Copart
- [ ] "Перепутанные адреса" < 2%
- [ ] Evidence у 80% auto-extracted полей
- [ ] Нет деградации по Phase 2 метрикам

---

## ПРИЛОЖЕНИЯ

### A. CD API V2 Validation Rules

| Поле | Правило |
|------|---------|
| `availableDate` | >= today, <= today+30 |
| `expirationDate` | >= today, <= today+30 |
| `desiredDeliveryDate` | >= availableDate, >= today, <= today+30 |
| `externalId` | <= 50 chars |
| `partnerReferenceId` | <= 50 chars |
| `stops` | exactly 2 |
| `vehicles` | 1-12 |
| `vehicles[].vin` | 17 chars, no I/O/Q |

### B. Rate Limiting

- Semaphore: max 3 concurrent CD API requests
- 429 → respect Retry-After header
- 5xx → max 3 attempts, exponential backoff (2s, 4s, 8s)

### C. ETag/If-Match

- GET returns ETag header
- PUT requires If-Match header with ETag
- 412 Precondition Failed → re-fetch ETag and retry

---

**Документ создан:** 2026-02-02
**Версия:** 2.0
**Статус:** Approved for Development
