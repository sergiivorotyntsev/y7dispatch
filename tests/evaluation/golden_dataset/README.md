# Golden Dataset for Extraction Evaluation

This directory contains the ground truth dataset for measuring extraction accuracy.

## Structure

```
golden_dataset/
├── copart/                    # Copart auction documents (50 total)
│   ├── standard/              # 30 typical documents
│   ├── edge_cases/            # 10 unusual formats
│   ├── missing_fields/        # 5 docs with missing data
│   └── multi_vehicle/         # 5 multi-vehicle lots
├── iaa/                       # IAA auction documents (50 total)
│   ├── standard/
│   ├── edge_cases/
│   ├── missing_fields/
│   └── multi_vehicle/
├── manheim/                   # Manheim auction documents (50 total)
│   ├── standard/
│   ├── edge_cases/
│   ├── missing_fields/
│   └── multi_vehicle/
└── baseline_metrics.json      # Current baseline metrics
```

## Document Requirements

Each document should have:
1. A PDF file: `{document_id}.pdf`
2. An expected JSON file: `{document_id}.json`

### Expected JSON Format

```json
{
  "document_id": "copart_001",
  "auction_type": "COPART",
  "category": "standard",
  "source": "test_data_2026",

  "expected_fields": {
    "vehicle_vin": "1HGCM82633A123456",
    "vehicle_year": 2024,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "vehicle_color": "Silver",
    "vehicle_lot": "12345678",

    "pickup_city": "Denver",
    "pickup_state": "CO",
    "pickup_zip": "80216",
    "pickup_address": "123 Auction Blvd",
    "pickup_phone": "303-555-1234",

    "buyer_id": "87654321",
    "buyer_name": "ABC Motors LLC",
    "sale_date": "2026-02-01",
    "total_amount": 15500.00
  },

  "metadata": {
    "annotated_by": "human",
    "annotated_at": "2026-02-10",
    "notes": "Standard Copart invoice with all fields present",
    "quality_score": 1.0
  }
}
```

## Field Definitions

### CD Required Fields (Must be ≥99% accurate)
- `vehicle_vin`: 17-character VIN
- `vehicle_year`: 4-digit year
- `vehicle_make`: Manufacturer name
- `vehicle_model`: Model name
- `pickup_city`: City name
- `pickup_state`: 2-letter state code

### CD Recommended Fields (Target ≥90% accurate)
- `pickup_zip`: 5-digit ZIP code
- `pickup_address`: Street address
- `vehicle_lot`: Lot/stock number
- `vehicle_type`: Vehicle type (CAR, SUV, TRUCK, etc.)

### CD Optional Fields (Target ≥80% accurate)
- `pickup_phone`: Contact phone
- `pickup_name`: Location name
- `buyer_id`: Buyer/member ID
- `buyer_name`: Buyer name
- `sale_date`: Date of sale
- `total_amount`: Total sale amount
- `vehicle_color`: Vehicle color

## Adding Documents

1. Obtain a representative PDF document
2. Create the expected JSON file with ground truth values
3. Place both files in the appropriate category directory
4. Run validation: `python -m tests.evaluation.test_extraction_accuracy`

## Category Guidelines

### Standard (30 per auction)
- Typical format with all required fields
- Good OCR quality
- Single vehicle

### Edge Cases (10 per auction)
- Unusual layouts or formatting
- Multiple pages
- Low quality scans
- Non-standard field positions

### Missing Fields (5 per auction)
- Documents where some expected fields are absent
- Tests handling of incomplete data

### Multi-Vehicle (5 per auction)
- Documents with multiple vehicles
- Tests multi-vehicle extraction

## Validation

Run the test suite to validate documents:

```bash
# Validate golden dataset
pytest tests/evaluation/test_extraction_accuracy.py -v

# Generate baseline
python -m tests.evaluation.test_extraction_accuracy --save-baseline

# Check specific auction type
python -m tests.evaluation.test_extraction_accuracy --auction-type copart
```

## Metrics

The evaluation calculates:
- **Precision**: Of extracted values, how many are correct?
- **Recall**: Of expected values, how many did we extract?
- **F1 Score**: Harmonic mean of precision and recall
- **Extraction Score**: Weighted aggregate (0-100)

Target metrics:
- Overall extraction score: ≥75
- VIN precision: ≥99%
- Critical field F1: ≥80%

---

*Last updated: 2026-02-11*
