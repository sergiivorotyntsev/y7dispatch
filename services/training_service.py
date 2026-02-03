"""
Training Service for Extraction Learning System

This service handles:
1. Saving user corrections from review
2. Analyzing corrections to learn extraction patterns
3. Generating and updating extraction rules
4. Providing learned rules to extractors
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from models.training import (
    ExtractionRule,
    FieldCorrection,
    FieldCorrectionCreate,
    TrainingExample,
)

logger = logging.getLogger(__name__)


class TrainingService:
    """Service for managing extraction training and learning."""

    def __init__(self, session: Session):
        self.session = session

    # =========================================================================
    # CORRECTION HANDLING
    # =========================================================================

    def save_corrections(
        self, run_id: int, corrections: list[FieldCorrectionCreate], mark_validated: bool = True
    ) -> tuple[int, int]:
        """
        Save field corrections from user review.

        Returns: (saved_count, error_count)
        """
        # Get run info from main database
        run_info = self._get_run_info(run_id)
        if not run_info:
            raise ValueError(f"Extraction run {run_id} not found")

        auction_type_id = run_info.get("auction_type_id", 1)
        document_id = run_info.get("document_id", run_id)
        extracted_text = run_info.get("extracted_text", "")

        saved_count = 0
        error_count = 0

        for correction in corrections:
            try:
                # Create field correction record
                fc = FieldCorrection(
                    extraction_run_id=run_id,
                    auction_type_id=auction_type_id,
                    document_id=document_id,
                    field_key=correction.field_key,
                    predicted_value=correction.predicted_value,
                    corrected_value=correction.corrected_value,
                    was_correct=correction.was_correct,
                    context_text=self._find_context(extracted_text, correction.corrected_value),
                    preceding_label=self._find_preceding_label(
                        extracted_text, correction.corrected_value
                    ),
                )
                self.session.add(fc)
                saved_count += 1
            except Exception as e:
                logger.error(f"Error saving correction for {correction.field_key}: {e}")
                error_count += 1

        # Create training example
        if saved_count > 0:
            corrected_fields = {
                c.field_key: c.corrected_value or c.predicted_value for c in corrections
            }
            example = TrainingExample(
                auction_type_id=auction_type_id,
                document_id=document_id,
                corrected_fields=json.dumps(corrected_fields),
                raw_text=extracted_text[:5000] if extracted_text else None,
                is_validated=mark_validated,
                validated_at=datetime.utcnow() if mark_validated else None,
            )
            self.session.add(example)

        self.session.commit()

        # Trigger learning from corrections
        if saved_count > 0:
            try:
                self._learn_from_corrections(auction_type_id)
            except Exception as e:
                logger.error(f"Error during learning: {e}")

        return saved_count, error_count

    def _get_run_info(self, run_id: int) -> Optional[dict[str, Any]]:
        """Get extraction run info from main database."""
        try:
            from api.database import get_connection

            with get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM extraction_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.warning(f"Could not get run info: {e}")
        return {"auction_type_id": 1, "document_id": run_id, "extracted_text": ""}

    def _find_context(self, text: str, value: str, window: int = 200) -> Optional[str]:
        """Find context around a value in text."""
        if not text or not value:
            return None

        pos = text.find(value)
        if pos == -1:
            return None

        start = max(0, pos - window)
        end = min(len(text), pos + len(value) + window)
        return text[start:end]

    def _find_preceding_label(self, text: str, value: str) -> Optional[str]:
        """Find the label that precedes a value in text."""
        if not text or not value:
            return None

        pos = text.find(value)
        if pos == -1:
            # Try partial match for addresses (first word)
            first_word = value.split()[0] if value else None
            if first_word and len(first_word) > 3:
                pos = text.find(first_word)

        if pos == -1:
            return None

        # Look at the lines before the value
        before = text[:pos]
        lines = before.split("\n")

        # Try to find the closest label
        for i in range(len(lines) - 1, max(len(lines) - 5, -1), -1):
            line = lines[i].strip() if i < len(lines) else ""
            if not line:
                continue

            # Check if it looks like a label
            # Common label patterns in auction documents
            label_indicators = [
                r"PHYSICAL\s*ADDRESS",
                r"LOT\s*(LOCATION|ADDRESS)",
                r"PICKUP",
                r"DELIVERY",
                r"MEMBER",
                r"SELLER",
                r"BUYER",
                r"VEHICLE",
                r"VIN",
                r"LOT\s*#",
            ]

            for indicator in label_indicators:
                if re.search(indicator, line, re.IGNORECASE):
                    return line.rstrip(":").strip()

            # Generic: ends with colon or is ALL CAPS short phrase
            if line.endswith(":"):
                return line.rstrip(":").strip()
            if line.isupper() and 3 < len(line) < 50:
                return line

        return None

    def _extract_text_patterns(self, text: str, value: str) -> list[str]:
        """
        Extract patterns that could identify this value in similar documents.

        Returns a list of regex patterns that match the value location.
        """
        patterns = []

        if not text or not value:
            return patterns

        pos = text.find(value)
        if pos == -1:
            return patterns

        # Get preceding text (up to 200 chars)
        before = text[max(0, pos - 200) : pos]
        lines_before = before.split("\n")

        # Pattern 1: Direct preceding label
        for line in reversed(lines_before[-3:]):
            line = line.strip()
            if line and (line.endswith(":") or line.isupper()):
                # Create regex pattern from the label
                escaped = re.escape(line.rstrip(":"))
                patterns.append(escaped)
                break

        # Pattern 2: Same-line prefix (e.g., "Address: 123 Main St")
        same_line_start = before.rfind("\n")
        if same_line_start >= 0:
            same_line_prefix = before[same_line_start + 1 :].strip()
            if same_line_prefix:
                escaped = re.escape(same_line_prefix)
                patterns.append(f"{escaped}[:\\s]*")

        return patterns

    # =========================================================================
    # LEARNING
    # =========================================================================

    def _learn_from_corrections(self, auction_type_id: int):
        """Analyze corrections and update extraction rules."""
        # Get recent corrections for this auction type
        corrections = self.session.exec(
            select(FieldCorrection)
            .where(FieldCorrection.auction_type_id == auction_type_id)
            .where(not FieldCorrection.is_processed)
            .order_by(FieldCorrection.created_at.desc())
            .limit(100)
        ).all()

        if not corrections:
            return

        # Group by field_key
        by_field: dict[str, list[FieldCorrection]] = {}
        for c in corrections:
            if c.field_key not in by_field:
                by_field[c.field_key] = []
            by_field[c.field_key].append(c)

        # Learn patterns for each field
        for field_key, field_corrections in by_field.items():
            self._learn_field_patterns(auction_type_id, field_key, field_corrections)

        # Mark corrections as processed
        for c in corrections:
            c.is_processed = True
        self.session.commit()

    def _learn_field_patterns(
        self, auction_type_id: int, field_key: str, corrections: list[FieldCorrection]
    ):
        """
        Learn extraction patterns for a specific field.

        This method:
        1. Collects labels that preceded corrected values
        2. Extracts regex patterns from the correction contexts
        3. Updates or creates extraction rules with learned patterns
        """
        # Collect labels and patterns from corrections
        labels = []

        for c in corrections:
            if c.preceding_label:
                labels.append(c.preceding_label)

            # Also extract patterns from context
            if c.context_text and c.corrected_value:
                extracted = self._extract_text_patterns(c.context_text, c.corrected_value)
                labels.extend(extracted)

            # If correction changed the value, the predicted value might be an exclude pattern
            if not c.was_correct and c.predicted_value and c.corrected_value:
                if c.predicted_value != c.corrected_value:
                    # The predicted value came from somewhere wrong - could be an exclude pattern
                    pass  # TODO: analyze why prediction was wrong

        if not labels:
            # Try to generate patterns from corrected values themselves
            for c in corrections:
                if c.corrected_value:
                    # For address fields, look for common address label patterns
                    if "address" in field_key or "city" in field_key or "state" in field_key:
                        labels.extend(
                            [
                                r"PHYSICAL\s*ADDRESS",
                                r"LOT\s*(LOCATION|ADDRESS)",
                                r"PICKUP\s*(LOCATION|ADDRESS)?",
                            ]
                        )
                        break
            if not labels:
                return

        # Deduplicate and clean patterns
        label_patterns = []
        seen = set()
        for label in labels:
            # Clean up the label
            clean_label = label.strip()
            if not clean_label or clean_label.lower() in seen:
                continue
            if len(clean_label) < 3:
                continue

            seen.add(clean_label.lower())

            # Convert to regex-friendly pattern
            # Escape special characters but keep the pattern flexible
            pattern = re.escape(clean_label)
            # Make whitespace flexible
            pattern = re.sub(r"\\ +", r"\\s+", pattern)
            label_patterns.append(pattern)

        if not label_patterns:
            return

        # Get or create rule
        rule = self.session.exec(
            select(ExtractionRule)
            .where(ExtractionRule.auction_type_id == auction_type_id)
            .where(ExtractionRule.field_key == field_key)
            .where(ExtractionRule.is_active)
        ).first()

        if not rule:
            rule = ExtractionRule(
                auction_type_id=auction_type_id,
                field_key=field_key,
                rule_type="label_below",
            )
            self.session.add(rule)

        # Update rule with learned patterns
        existing_patterns = rule.get_label_patterns()

        # Merge patterns, prioritizing new ones
        all_patterns = existing_patterns + label_patterns
        # Deduplicate while preserving order
        unique_patterns = []
        seen_lower = set()
        for p in all_patterns:
            p_lower = p.lower()
            if p_lower not in seen_lower:
                seen_lower.add(p_lower)
                unique_patterns.append(p)

        rule.set_label_patterns(unique_patterns[:20])  # Keep top 20 patterns

        # Update confidence based on correction results
        correct_count = sum(1 for c in corrections if c.was_correct)
        total_count = len(corrections)

        # Weighted average with existing confidence
        old_weight = min(rule.validation_count, 10) / 10
        new_weight = 1 - old_weight
        new_confidence = correct_count / total_count if total_count > 0 else 0.5
        rule.confidence = rule.confidence * old_weight + new_confidence * new_weight

        rule.validation_count += total_count
        rule.updated_at = datetime.utcnow()

        self.session.commit()

        logger.info(
            f"Updated rule for {field_key}: {len(unique_patterns)} patterns, confidence={rule.confidence:.2f}"
        )

    # =========================================================================
    # STATS AND QUERIES
    # =========================================================================

    def get_training_stats(self, auction_type_id: Optional[int] = None) -> dict[str, Any]:
        """Get training statistics."""
        stats = {"by_auction_type": {}}

        # Get auction types from main database
        auction_types = self._get_auction_types()

        for at in auction_types:
            at_id = at["id"]
            at_code = at["code"]

            if auction_type_id and at_id != auction_type_id:
                continue

            # Count corrections
            correction_count = self.session.exec(
                select(FieldCorrection).where(FieldCorrection.auction_type_id == at_id)
            ).all()

            # Count examples
            examples = self.session.exec(
                select(TrainingExample).where(TrainingExample.auction_type_id == at_id)
            ).all()

            # Count rules
            rules = self.session.exec(
                select(ExtractionRule)
                .where(ExtractionRule.auction_type_id == at_id)
                .where(ExtractionRule.is_active)
            ).all()

            validated = sum(1 for e in examples if e.is_validated)
            avg_confidence = sum(r.confidence for r in rules) / len(rules) if rules else 0

            stats["by_auction_type"][at_code] = {
                "auction_type_id": at_id,
                "correction_count": len(correction_count),
                "total_examples": len(examples),
                "validated_examples": validated,
                "rules_count": len(rules),
                "avg_confidence": round(avg_confidence, 2),
            }

        return stats

    def _get_auction_types(self) -> list[dict[str, Any]]:
        """Get auction types from main database."""
        try:
            from api.database import get_connection

            with get_connection() as conn:
                rows = conn.execute("SELECT id, code, name FROM auction_types").fetchall()
                return [dict(row) for row in rows]
        except Exception:
            # Return defaults if table doesn't exist
            return [
                {"id": 1, "code": "copart", "name": "Copart"},
                {"id": 2, "code": "iaa", "name": "IAA"},
                {"id": 3, "code": "manheim", "name": "Manheim"},
            ]

    def get_extraction_rules(
        self, auction_type_id: int, field_key: Optional[str] = None
    ) -> list[ExtractionRule]:
        """Get extraction rules for an auction type."""
        query = select(ExtractionRule).where(
            ExtractionRule.auction_type_id == auction_type_id, ExtractionRule.is_active
        )

        if field_key:
            query = query.where(ExtractionRule.field_key == field_key)

        return list(self.session.exec(query).all())

    def get_rules_for_extractor(self, auction_type_code: str) -> dict[str, Any]:
        """Get rules in format suitable for extractors."""
        # Find auction type ID
        auction_types = self._get_auction_types()
        auction_type_id = None
        for at in auction_types:
            if at["code"].lower() == auction_type_code.lower():
                auction_type_id = at["id"]
                break

        if not auction_type_id:
            return {}

        rules = self.get_extraction_rules(auction_type_id)

        result = {}
        for rule in rules:
            result[rule.field_key] = {
                "rule_type": rule.rule_type,
                "label_patterns": rule.get_label_patterns(),
                "exclude_patterns": rule.get_exclude_patterns(),
                "confidence": rule.confidence,
            }

        return result
