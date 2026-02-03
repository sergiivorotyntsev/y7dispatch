# Extraction Golden Set

This folder contains golden test data for regression testing the extraction pipeline.

## Structure

- `expected/` - Expected JSON outputs for each test document
- `../sample_docs/` - Source PDF documents

## Key Fields (Minimum 12)

1. **Vehicle Identification**
   - vehicle_vin (17 chars)
   - vehicle_year
   - vehicle_make
   - vehicle_model

2. **Pickup Location**
   - pickup_name / pickup_address
   - pickup_city
   - pickup_state
   - pickup_zip

3. **Transaction Info**
   - reference_id (lot number)
   - buyer_id
   - sale_date
   - total_amount

## Running Tests

```bash
python tests/test_golden_set.py
```

## Tolerances

- `phone`: Normalized to digits only for comparison
- `zip`: 5-digit or 5+4 format accepted
- `date`: ISO format comparison
- `amount`: Float comparison with tolerance
