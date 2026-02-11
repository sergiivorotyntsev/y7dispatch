"""
Phase 0: Evaluation Framework for Y7Dispatch Extraction Pipeline

This package provides:
- metrics.py: Precision, Recall, F1, extraction score calculation
- test_extraction_accuracy.py: Test harness for golden dataset
- cost_tracker.py: Token and cost tracking per request
- baseline_runner.py: Establish baseline metrics from current extractors

Directory structure:
    tests/evaluation/
    ├── golden_dataset/
    │   ├── copart/           # 50 documents
    │   │   ├── standard/     # 30 typical documents
    │   │   ├── edge_cases/   # 10 unusual formats
    │   │   ├── missing_fields/ # 5 docs with missing data
    │   │   └── multi_vehicle/  # 5 multi-vehicle lots
    │   ├── iaa/              # 50 documents (same structure)
    │   └── manheim/          # 50 documents (same structure)
    ├── metrics.py
    ├── test_extraction_accuracy.py
    ├── cost_tracker.py
    └── conftest.py
"""

from .metrics import (
    ExtractionMetrics,
    FieldMetrics,
    calculate_metrics,
    calculate_field_metrics,
)

__all__ = [
    "ExtractionMetrics",
    "FieldMetrics",
    "calculate_metrics",
    "calculate_field_metrics",
]
