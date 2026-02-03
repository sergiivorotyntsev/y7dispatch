# CENTRALDISPATCH - Developer Documentation

## Overview

CENTRALDISPATCH is a vehicle transport document extraction system that processes auction invoices (Copart, IAA, Manheim) and exports structured data to Central Dispatch API for creating transport listings.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CENTRALDISPATCH                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────────┐    │
│  │   Frontend  │    │    FastAPI       │    │      Extractors         │    │
│  │   (React)   │◄──►│    Backend       │◄──►│   (PDF Processing)      │    │
│  │   Port 3000 │    │    Port 8000     │    │                         │    │
│  └─────────────┘    └──────────────────┘    └─────────────────────────┘    │
│                              │                         │                    │
│                              ▼                         ▼                    │
│                     ┌────────────────┐       ┌─────────────────────┐       │
│                     │   SQLite DB    │       │   Spatial Parser    │       │
│                     │   (SQLAlchemy) │       │   (pdfplumber)      │       │
│                     └────────────────┘       └─────────────────────┘       │
│                              │                                              │
│                              ▼                                              │
│                     ┌────────────────────────────────────────────┐         │
│                     │           External Services                 │         │
│                     │  - Central Dispatch API                    │         │
│                     │  - Google Sheets                           │         │
│                     │  - Gmail (Email ingestion)                 │         │
│                     │  - ClickUp (Task management)               │         │
│                     └────────────────────────────────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
CENTRALDISPATCH/
├── api/                          # FastAPI Backend
│   ├── main.py                   # FastAPI app initialization
│   ├── database.py               # SQLAlchemy database setup
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── training_db.py            # Training database session
│   ├── routes/                   # API route handlers
│   │   ├── documents.py          # Document CRUD operations
│   │   ├── extractions.py        # Extraction endpoints
│   │   ├── runs.py               # Extraction run management
│   │   ├── reviews.py            # Review queue endpoints
│   │   ├── training.py           # Training system endpoints
│   │   ├── settings.py           # Application settings
│   │   ├── auction_types.py      # Auction type configuration
│   │   ├── field_mappings.py     # Field mapping configuration
│   │   ├── exports.py            # Export functionality
│   │   └── integrations/         # External service integrations
│   │       ├── cd.py             # Central Dispatch API
│   │       ├── sheets.py         # Google Sheets
│   │       ├── email.py          # Email/Gmail
│   │       ├── clickup.py        # ClickUp integration
│   │       └── oauth.py          # OAuth handlers
│   └── workers/                  # Background workers
│       └── email_worker.py       # Email processing worker
│
├── extractors/                   # Document Extraction Engine
│   ├── base.py                   # BaseExtractor (abstract class)
│   ├── copart.py                 # Copart invoice extractor
│   ├── iaa.py                    # IAA (Insurance Auto Auctions) extractor
│   ├── manheim.py                # Manheim extractor
│   ├── gate_pass.py              # Gate pass extractor
│   ├── address_parser.py         # Address parsing utilities
│   └── spatial_parser.py         # Block-based spatial parsing
│
├── models/                       # Data Models
│   ├── vehicle.py                # Core data models (Pydantic)
│   └── training.py               # Training-related models
│
├── services/                     # Business Logic Services
│   ├── orchestrator.py           # Extraction orchestration
│   ├── training_service.py       # Training/learning service
│   ├── central_dispatch.py       # CD API client
│   ├── cd_exporter.py            # Export to Central Dispatch
│   ├── sheets.py                 # Google Sheets client
│   ├── clickup.py                # ClickUp client
│   └── warehouse.py              # Warehouse management
│
├── web/                          # React Frontend
│   ├── src/
│   │   ├── api.js                # API client
│   │   ├── App.jsx               # Main app component
│   │   ├── pages/                # Page components
│   │   │   ├── Dashboard.jsx
│   │   │   ├── Documents.jsx
│   │   │   ├── DocumentDetail.jsx
│   │   │   ├── Runs.jsx
│   │   │   ├── Review.jsx
│   │   │   ├── ListingReview.jsx
│   │   │   ├── TestLab.jsx
│   │   │   └── Settings.jsx
│   │   └── components/           # Shared components
│   └── package.json
│
├── tests/                        # Test Suite
│   ├── conftest.py               # Pytest fixtures
│   ├── test_extraction.py        # Extraction tests
│   ├── test_extractors.py        # Individual extractor tests
│   ├── test_training_system.py   # Training system tests
│   └── test_api_contracts.py     # API contract tests
│
├── core/                         # Core Utilities
│   ├── config.py                 # Configuration management
│   └── logging_config.py         # Logging setup
│
├── schemas/                      # Data Schemas
│   └── sheets_schema_*.py        # Google Sheets schemas
│
├── docs/                         # Documentation
│   ├── FRONTEND_BLOCKS.md        # Frontend component reference
│   └── DEVELOPER_GUIDE.md        # This file
│
└── uploads/                      # Uploaded PDF storage
```

## Core Concepts

### 1. Auction Sources

The system supports three auction sources:

| Source | Class | Key Indicators |
|--------|-------|----------------|
| Copart | `CopartExtractor` | "SOLD THROUGH COPART", "copart.com", "MEMBER:" |
| IAA | `IAAExtractor` | "Insurance Auto Auctions", "IAAI", "Buyer Receipt" |
| Manheim | `ManheimExtractor` | "Manheim", "Cox Automotive", "Release ID" |

### 2. Extraction Pipeline

```
PDF Upload → Text Extraction → Source Detection → Field Extraction → Review → Export
     │              │                  │                 │            │         │
     ▼              ▼                  ▼                 ▼            ▼         ▼
 Store file   pdfplumber         Score each        Extract fields  Human   CD API
  in DB       + spatial          extractor,        using patterns  review  POST
              parser             select best       + learned rules
```

### 3. Multi-Strategy Extraction

Each field uses multiple extraction strategies (in order of priority):

1. **Learned Rules** - Patterns learned from user corrections
2. **Spatial Parsing** - Block-based document parsing using coordinates
3. **Text Patterns** - Regex patterns for labeled fields
4. **Fallback** - Generic parsers

### 4. Training System

The system learns from user corrections:

```
User Correction → Pattern Detection → Rule Creation → Improved Extraction
       │                 │                  │                  │
       ▼                 ▼                  ▼                  ▼
   Correct value   Find preceding    Store in         Next extraction
   in Review       label/context     training DB      uses new rule
```

## Key Classes and Interfaces

### BaseExtractor (extractors/base.py)

Abstract base class for all document extractors.

```python
class BaseExtractor(ABC):
    @property
    @abstractmethod
    def source(self) -> AuctionSource:
        """Returns the auction source (COPART, IAA, MANHEIM)"""
        pass

    @property
    @abstractmethod
    def indicators(self) -> List[str]:
        """Text patterns that identify this document type"""
        pass

    @abstractmethod
    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        """Main extraction method"""
        pass

    def score(self, text: str) -> Tuple[float, List[str]]:
        """Calculate confidence score for document type detection"""
        pass

    def extract_pickup_address_universal(
        self,
        text: str,
        pdf_path: str = None,
        label_patterns: List[str] = None,
        source_name: str = None
    ) -> Optional[Address]:
        """Universal address extraction using multiple strategies"""
        pass
```

### AuctionInvoice (models/vehicle.py)

Core data model for extracted document data.

```python
@dataclass
class AuctionInvoice:
    source: AuctionSource
    buyer_id: str
    buyer_name: str
    seller_name: str = ""
    sale_date: Optional[datetime] = None
    pickup_address: Optional[Address] = None
    delivery_address: Optional[Address] = None
    vehicles: List[Vehicle] = field(default_factory=list)
    total_amount: Optional[float] = None
    lot_number: str = ""
    stock_number: str = ""
    receipt_number: str = ""
    release_id: str = ""
    location_type: LocationType = LocationType.ONSITE
```

### Address (models/vehicle.py)

```python
@dataclass
class Address:
    name: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    phone: str = ""
    contact: str = ""
```

### Vehicle (models/vehicle.py)

```python
@dataclass
class Vehicle:
    vin: str
    year: int
    make: str
    model: str
    color: str = ""
    mileage: Optional[int] = None
    vehicle_type: VehicleType = VehicleType.CAR
    lot_number: str = ""
```

## API Endpoints

### Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/documents` | List all documents |
| POST | `/api/documents/upload` | Upload PDF document |
| GET | `/api/documents/{id}` | Get document details |
| DELETE | `/api/documents/{id}` | Delete document |
| POST | `/api/documents/{id}/extract` | Trigger extraction |

### Extractions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/runs` | List extraction runs |
| GET | `/api/runs/{id}` | Get run details |
| GET | `/api/runs/{id}/results` | Get extraction results |

### Reviews

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reviews` | Get review queue |
| GET | `/api/reviews/{id}` | Get review item |
| POST | `/api/reviews/{id}/accept` | Accept extracted value |
| POST | `/api/reviews/{id}/correct` | Submit correction |

### Training

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/training/rules` | Get learned rules |
| GET | `/api/training/stats` | Get training statistics |
| POST | `/api/training/learn` | Manually trigger learning |
| DELETE | `/api/training/rules` | Clear learned rules |

### Exports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/exports/listings` | Get listings ready for export |
| POST | `/api/exports/cd` | Export to Central Dispatch |
| GET | `/api/exports/history` | Export history |

## Database Schema

### Main Tables (SQLAlchemy)

```sql
-- Documents table
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    source TEXT,  -- COPART, IAA, MANHEIM
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    is_test BOOLEAN DEFAULT FALSE
);

-- Extraction runs
CREATE TABLE extraction_runs (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    auction_type_id INTEGER,
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    score REAL,
    raw_text TEXT,
    extracted_data JSON
);

-- Extracted vehicles
CREATE TABLE extracted_vehicles (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES extraction_runs(id),
    vin TEXT,
    year INTEGER,
    make TEXT,
    model TEXT,
    color TEXT,
    mileage INTEGER
);

-- Review items
CREATE TABLE review_items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES extraction_runs(id),
    field_key TEXT,
    extracted_value TEXT,
    corrected_value TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending'
);

-- Learned extraction rules
CREATE TABLE extraction_rules (
    id INTEGER PRIMARY KEY,
    auction_type TEXT,
    field_key TEXT,
    rule_type TEXT,
    label_patterns JSON,
    exclude_patterns JSON,
    confidence REAL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Training examples
CREATE TABLE training_examples (
    id INTEGER PRIMARY KEY,
    auction_type TEXT,
    field_key TEXT,
    source_text TEXT,
    extracted_value TEXT,
    correct_value TEXT,
    context TEXT,
    created_at TIMESTAMP
);
```

## Adding a New Extractor

To add support for a new auction source:

### 1. Create Extractor Class

```python
# extractors/newauction.py
from extractors.base import BaseExtractor
from models.vehicle import AuctionInvoice, AuctionSource

class NewAuctionExtractor(BaseExtractor):
    @property
    def source(self) -> AuctionSource:
        return AuctionSource.NEWAUCTION  # Add to enum first

    @property
    def indicators(self) -> list:
        return [
            'New Auction Corp',
            'NEWAUCTION.COM',
            # ... unique text patterns
        ]

    @property
    def indicator_weights(self) -> dict:
        return {
            'New Auction Corp': 5.0,  # High weight = strong indicator
            'NEWAUCTION.COM': 4.0,
        }

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        text = self.extract_text(pdf_path)
        if not self.can_extract(text):
            return None

        self.load_learned_rules()
        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        # Extract fields...
        invoice.buyer_name = self._extract_buyer_name(text)
        invoice.pickup_address = self._extract_pickup_location(text, pdf_path)

        return invoice

    def _extract_pickup_location(self, text: str, pdf_path: str) -> Optional[Address]:
        # Use universal method with custom patterns
        patterns = [
            r'LOCATION[:\s]*',
            r'PICKUP\s*ADDRESS[:\s]*',
        ]
        return self.extract_pickup_address_universal(
            text=text,
            pdf_path=pdf_path,
            label_patterns=patterns,
            source_name="NewAuction"
        )
```

### 2. Add to AuctionSource Enum

```python
# models/vehicle.py
class AuctionSource(Enum):
    COPART = "copart"
    IAA = "iaa"
    MANHEIM = "manheim"
    NEWAUCTION = "newauction"  # Add new source
```

### 3. Register Extractor

```python
# extractors/__init__.py
from extractors.newauction import NewAuctionExtractor

ALL_EXTRACTORS = [
    CopartExtractor(),
    IAAExtractor(),
    ManheimExtractor(),
    NewAuctionExtractor(),  # Add to list
]
```

### 4. Add Tests

```python
# tests/test_newauction.py
def test_newauction_detection():
    extractor = NewAuctionExtractor()
    text = "New Auction Corp\nNEWAUCTION.COM\n..."
    score, matched = extractor.score(text)
    assert score > 0.6
    assert 'New Auction Corp' in matched
```

## Spatial Parser

The spatial parser (`extractors/spatial_parser.py`) provides block-based document parsing using word-level coordinates from pdfplumber.

### Key Classes

```python
@dataclass
class TextElement:
    """Single word/text element with position."""
    text: str
    x0: float  # Left edge
    y0: float  # Top edge
    x1: float  # Right edge
    y1: float  # Bottom edge
    page: int

@dataclass
class DocumentBlock:
    """Logical block of text elements."""
    elements: List[TextElement]
    lines: List[str]  # Text content as lines

    def get_block_by_label(self, pattern: str) -> Optional['DocumentBlock']:
        """Find block containing a label pattern."""

class SpatialParser:
    def parse(self, pdf_path: str) -> DocumentStructure:
        """Parse PDF into document structure with blocks."""
```

### Usage

```python
from extractors.spatial_parser import parse_document

# Parse document into blocks
structure = parse_document(pdf_path)

# Find block by label
block = structure.get_block_by_label(r'PHYSICAL\s*ADDRESS')
if block:
    for line in block.lines:
        print(line)
```

## Training Service

The training service (`services/training_service.py`) manages the learning system.

### Key Methods

```python
class TrainingService:
    def record_correction(
        self,
        auction_type: str,
        field_key: str,
        source_text: str,
        extracted_value: str,
        correct_value: str
    ):
        """Record a user correction for learning."""

    def learn_patterns(self, auction_type: str = None):
        """Analyze corrections and update extraction rules."""

    def get_rules_for_extractor(self, auction_type: str) -> Dict[str, dict]:
        """Get all learned rules for an extractor."""
```

## Configuration

Environment variables:

```bash
# Database
DATABASE_PATH=/path/to/database.db

# Directories
DATA_DIR=/path/to/data
UPLOADS_DIR=/path/to/uploads

# API Keys
CD_API_KEY=your_central_dispatch_api_key
GOOGLE_CREDENTIALS_FILE=/path/to/credentials.json

# Logging
LOG_LEVEL=INFO
```

## Development Setup

### Backend

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn api.main:app --reload --port 8000
```

### Frontend

```bash
cd web

# Install dependencies
npm install

# Run development server
npm run dev
```

### Run Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_extraction.py -v

# With coverage
pytest --cov=. --cov-report=html
```

## Common Development Tasks

### Add a New Field

1. Add field to `models/vehicle.py` data classes
2. Add extraction logic to relevant extractor(s)
3. Add field mapping in `api/routes/field_mappings.py`
4. Update frontend review form if needed
5. Add tests

### Debug Extraction Issues

```python
# Enable debug logging
import logging
logging.getLogger('extractors').setLevel(logging.DEBUG)

# Test extraction manually
from extractors.copart import CopartExtractor

extractor = CopartExtractor()
text = extractor.extract_text('/path/to/document.pdf')
print(f"Text length: {len(text)}")
print(f"Score: {extractor.score(text)}")

result = extractor.extract_with_result('/path/to/document.pdf')
print(f"Invoice: {result.invoice}")
print(f"Matched patterns: {result.matched_patterns}")
```

### Test Spatial Parser

```python
from extractors.spatial_parser import parse_document

structure = parse_document('/path/to/document.pdf')
for block in structure.blocks:
    print(f"Block ({len(block.elements)} elements):")
    for line in block.lines[:3]:
        print(f"  {line}")
```

## Error Handling

### Common Issues

1. **Low text extraction**: Document may be scanned image, needs OCR
2. **Wrong source detection**: Check indicator weights, add negative indicators
3. **Address parsing fails**: Check spatial parser, add label patterns
4. **Training not improving**: Ensure corrections are being recorded, run learning

### Logging

```python
import logging

# Set up logging for debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('extractors.base')
logger.setLevel(logging.DEBUG)
```

## Performance Considerations

1. **PDF parsing**: pdfplumber is used for text extraction; large PDFs may be slow
2. **Spatial parsing**: Adds overhead but improves accuracy for complex layouts
3. **Database**: SQLite is used; consider PostgreSQL for production scale
4. **Caching**: Learned rules are cached per-extractor instance

## Security Notes

1. **File uploads**: Only PDF files accepted, validated on upload
2. **API keys**: Stored in database, not in code
3. **OAuth tokens**: Encrypted in database
4. **SQL injection**: SQLAlchemy ORM used throughout
