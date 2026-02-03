"""
Training Models for Extraction Learning System

This module defines the database schema for storing extraction rules,
field corrections, and learned patterns that improve extraction accuracy
over time for each auction type.
"""

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class ExtractionRule(SQLModel, table=True):
    """
    Stores learned extraction rules for each field per auction type.

    Rules are generated from user corrections and define how to
    extract specific fields from documents.
    """

    __tablename__ = "extraction_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    auction_type_id: int = Field(index=True)  # References auction_types in main DB
    field_key: str = Field(index=True)  # e.g., 'pickup_address', 'buyer_name'

    # Rule definition
    rule_type: str = Field(default="label_below")  # label_below, label_inline, regex, position

    # Label patterns to look for (JSON array of regex patterns)
    label_patterns: str = Field(default="[]", sa_column=Column(Text))

    # Patterns/labels to AVOID (negative patterns)
    exclude_patterns: str = Field(default="[]", sa_column=Column(Text))

    # Position hints (e.g., "after PHYSICAL ADDRESS OF LOT", "before SELLER")
    position_hints: str = Field(default="[]", sa_column=Column(Text))

    # Priority (higher = preferred)
    priority: int = Field(default=0)

    # Confidence score based on training examples
    confidence: float = Field(default=0.5)

    # Number of times this rule was validated by user
    validation_count: int = Field(default=0)

    # Whether this rule is active
    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_label_patterns(self) -> list[str]:
        return json.loads(self.label_patterns) if self.label_patterns else []

    def set_label_patterns(self, patterns: list[str]):
        self.label_patterns = json.dumps(patterns)

    def get_exclude_patterns(self) -> list[str]:
        return json.loads(self.exclude_patterns) if self.exclude_patterns else []

    def set_exclude_patterns(self, patterns: list[str]):
        self.exclude_patterns = json.dumps(patterns)

    def get_position_hints(self) -> list[str]:
        return json.loads(self.position_hints) if self.position_hints else []


class FieldCorrection(SQLModel, table=True):
    """
    Stores individual field corrections made by users during review.

    Each correction is a training example that helps the system learn
    what values are correct for specific fields.
    """

    __tablename__ = "field_corrections"

    id: Optional[int] = Field(default=None, primary_key=True)
    extraction_run_id: int = Field(index=True)  # References extraction_runs in main DB
    auction_type_id: int = Field(index=True)  # References auction_types in main DB
    document_id: int = Field(index=True)  # References documents in main DB

    field_key: str = Field(index=True)  # e.g., 'pickup_address'

    # Original extracted value (may be wrong)
    predicted_value: Optional[str] = Field(default=None, sa_column=Column(Text))

    # User-corrected value (ground truth)
    corrected_value: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Whether the prediction was correct
    was_correct: bool = Field(default=False)

    # Context: text around the correct value in the document
    context_text: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Label that preceded the correct value (learned from context)
    preceding_label: Optional[str] = Field(default=None)

    # Whether this correction has been used for training
    is_processed: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class TrainingExample(SQLModel, table=True):
    """
    Processed training examples derived from field corrections.

    These are validated examples used to train/improve extraction rules.
    """

    __tablename__ = "training_examples"

    id: Optional[int] = Field(default=None, primary_key=True)
    auction_type_id: int = Field(index=True)  # References auction_types in main DB
    document_id: int = Field(index=True)  # References documents in main DB

    # The complete corrected extraction data (JSON)
    corrected_fields: str = Field(default="{}", sa_column=Column(Text))

    # Raw text from document for reference
    raw_text: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Quality score (based on completeness and validation)
    quality_score: float = Field(default=0.0)

    # Whether this example has been validated by user
    is_validated: bool = Field(default=False)

    # Whether this example is used for training (vs. testing)
    dataset_split: str = Field(default="train")  # 'train', 'test', 'validation'

    created_at: datetime = Field(default_factory=datetime.utcnow)
    validated_at: Optional[datetime] = Field(default=None)

    def get_corrected_fields(self) -> dict[str, Any]:
        return json.loads(self.corrected_fields) if self.corrected_fields else {}

    def set_corrected_fields(self, fields: dict[str, Any]):
        self.corrected_fields = json.dumps(fields)


class ExtractionPattern(SQLModel, table=True):
    """
    Stores learned extraction patterns from training examples.

    Patterns are regex or positional rules learned from multiple
    training examples for specific fields.
    """

    __tablename__ = "extraction_patterns"

    id: Optional[int] = Field(default=None, primary_key=True)
    auction_type_id: int = Field(index=True)  # References auction_types in main DB
    field_key: str = Field(index=True)

    # Pattern type
    pattern_type: str = Field(default="regex")  # 'regex', 'label_value', 'positional'

    # The actual pattern (regex string or label)
    pattern: str = Field(sa_column=Column(Text))

    # How many times this pattern successfully extracted correct values
    success_count: int = Field(default=0)

    # How many times this pattern was tried
    attempt_count: int = Field(default=0)

    # Success rate
    accuracy: float = Field(default=0.0)

    # Whether this is a negative pattern (to avoid)
    is_negative: bool = Field(default=False)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Pydantic models for API requests/responses


class FieldCorrectionCreate(SQLModel):
    """Request model for submitting a field correction."""

    field_key: str
    predicted_value: Optional[str] = None
    corrected_value: Optional[str] = None
    was_correct: bool = False


class TrainingSubmission(SQLModel):
    """Request model for submitting training data from review."""

    extraction_run_id: int
    corrections: list[FieldCorrectionCreate]
    mark_as_validated: bool = True


class ExtractionRuleResponse(SQLModel):
    """Response model for extraction rules."""

    id: int
    field_key: str
    rule_type: str
    label_patterns: list[str]
    exclude_patterns: list[str]
    confidence: float
    validation_count: int


class TrainingStatsResponse(SQLModel):
    """Response model for training statistics."""

    auction_type_code: str
    total_examples: int
    validated_examples: int
    correction_count: int
    rules_count: int
    avg_confidence: float
