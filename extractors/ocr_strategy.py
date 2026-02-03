"""
OCR Strategy Module

Provides decision logic for when to use native PDF text extraction
vs OCR processing. Tracks text quality metrics and determines the
optimal extraction approach for each document.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TextMode(Enum):
    """Text extraction mode used."""

    NATIVE = "native"  # Text layer from PDF
    OCR = "ocr"  # OCR processed (Tesseract, etc.)
    HYBRID = "hybrid"  # Mix of native and OCR


class TextQuality(Enum):
    """Quality assessment of extracted text."""

    EXCELLENT = "excellent"  # High-quality native text
    GOOD = "good"  # Adequate for extraction
    POOR = "poor"  # May need OCR fallback
    UNUSABLE = "unusable"  # Definitely needs OCR


@dataclass
class TextQualityMetrics:
    """Metrics for assessing text quality."""

    total_chars: int = 0
    word_count: int = 0
    line_count: int = 0
    avg_word_length: float = 0.0
    alpha_ratio: float = 0.0  # Ratio of alphabetic chars
    digit_ratio: float = 0.0  # Ratio of digit chars
    garbled_ratio: float = 0.0  # Ratio of likely OCR errors
    whitespace_ratio: float = 0.0  # Ratio of whitespace
    has_valid_vin: bool = False  # Contains valid 17-char VIN
    has_valid_dates: bool = False  # Contains parseable dates
    has_valid_amounts: bool = False  # Contains dollar amounts
    quality: TextQuality = TextQuality.POOR
    recommended_mode: TextMode = TextMode.NATIVE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "total_chars": self.total_chars,
            "word_count": self.word_count,
            "line_count": self.line_count,
            "avg_word_length": round(self.avg_word_length, 2),
            "alpha_ratio": round(self.alpha_ratio, 3),
            "digit_ratio": round(self.digit_ratio, 3),
            "garbled_ratio": round(self.garbled_ratio, 3),
            "whitespace_ratio": round(self.whitespace_ratio, 3),
            "has_valid_vin": self.has_valid_vin,
            "has_valid_dates": self.has_valid_dates,
            "has_valid_amounts": self.has_valid_amounts,
            "quality": self.quality.value,
            "recommended_mode": self.recommended_mode.value,
        }


class OCRStrategy:
    """
    Determines the optimal text extraction strategy for documents.

    Analyzes text quality and decides whether to use native PDF text,
    OCR, or a hybrid approach.
    """

    # Thresholds for quality assessment
    MIN_CHARS_GOOD = 200  # Minimum chars for "good" quality
    MIN_CHARS_USABLE = 50  # Minimum chars for any extraction
    MIN_WORDS_GOOD = 30  # Minimum words for "good" quality
    MIN_ALPHA_RATIO = 0.5  # Minimum ratio of alphabetic chars
    MAX_GARBLED_RATIO = 0.1  # Maximum acceptable garbled char ratio

    # Patterns for quality indicators
    VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
    DATE_PATTERN = re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")
    AMOUNT_PATTERN = re.compile(r"\$[\d,]+\.?\d*")
    GARBLED_PATTERN = re.compile(r"[^\x00-\x7F]|[\x00-\x08\x0B\x0C\x0E-\x1F]")

    def analyze_text_quality(self, text: str) -> TextQualityMetrics:
        """
        Analyze text quality and return metrics.

        Args:
            text: Extracted text to analyze

        Returns:
            TextQualityMetrics with quality assessment
        """
        metrics = TextQualityMetrics()

        if not text:
            metrics.quality = TextQuality.UNUSABLE
            metrics.recommended_mode = TextMode.OCR
            return metrics

        # Basic counts
        metrics.total_chars = len(text)
        metrics.word_count = len(text.split())
        metrics.line_count = text.count("\n") + 1

        # Character analysis
        alpha_count = sum(1 for c in text if c.isalpha())
        digit_count = sum(1 for c in text if c.isdigit())
        whitespace_count = sum(1 for c in text if c.isspace())
        garbled_matches = self.GARBLED_PATTERN.findall(text)

        if metrics.total_chars > 0:
            metrics.alpha_ratio = alpha_count / metrics.total_chars
            metrics.digit_ratio = digit_count / metrics.total_chars
            metrics.whitespace_ratio = whitespace_count / metrics.total_chars
            metrics.garbled_ratio = len(garbled_matches) / metrics.total_chars

        # Word length analysis
        words = text.split()
        if words:
            metrics.avg_word_length = sum(len(w) for w in words) / len(words)

        # Look for key data indicators
        metrics.has_valid_vin = bool(self.VIN_PATTERN.search(text))
        metrics.has_valid_dates = bool(self.DATE_PATTERN.search(text))
        metrics.has_valid_amounts = bool(self.AMOUNT_PATTERN.search(text))

        # Determine quality level
        metrics.quality = self._assess_quality(metrics)
        metrics.recommended_mode = self._recommend_mode(metrics)

        return metrics

    def _assess_quality(self, metrics: TextQualityMetrics) -> TextQuality:
        """Assess overall text quality from metrics."""

        # Unusable: too short or too garbled
        if metrics.total_chars < self.MIN_CHARS_USABLE:
            return TextQuality.UNUSABLE

        if metrics.garbled_ratio > self.MAX_GARBLED_RATIO * 2:
            return TextQuality.UNUSABLE

        # Poor: short text or low alpha ratio
        if metrics.total_chars < self.MIN_CHARS_GOOD or metrics.alpha_ratio < self.MIN_ALPHA_RATIO:
            return TextQuality.POOR

        # Excellent: has key data indicators and good metrics
        if (
            metrics.has_valid_vin
            and metrics.has_valid_dates
            and metrics.word_count >= self.MIN_WORDS_GOOD
            and metrics.garbled_ratio < self.MAX_GARBLED_RATIO
        ):
            return TextQuality.EXCELLENT

        # Good: meets basic thresholds
        if (
            metrics.word_count >= self.MIN_WORDS_GOOD
            and metrics.garbled_ratio < self.MAX_GARBLED_RATIO
        ):
            return TextQuality.GOOD

        return TextQuality.POOR

    def _recommend_mode(self, metrics: TextQualityMetrics) -> TextMode:
        """Recommend extraction mode based on quality."""

        if metrics.quality == TextQuality.UNUSABLE:
            return TextMode.OCR

        if metrics.quality == TextQuality.EXCELLENT:
            return TextMode.NATIVE

        if metrics.quality == TextQuality.GOOD:
            return TextMode.NATIVE

        # Poor quality - check if OCR might help
        if not metrics.has_valid_vin and not metrics.has_valid_dates and metrics.alpha_ratio < 0.3:
            return TextMode.OCR

        # Borderline - might benefit from hybrid
        return TextMode.HYBRID

    def should_use_ocr(self, text: str) -> tuple[bool, str]:
        """
        Quick check if OCR should be used for this document.

        Args:
            text: Extracted native text

        Returns:
            Tuple of (should_use_ocr, reason)
        """
        metrics = self.analyze_text_quality(text)

        if metrics.recommended_mode == TextMode.OCR:
            return True, f"Text quality: {metrics.quality.value}, chars: {metrics.total_chars}"

        if metrics.recommended_mode == TextMode.HYBRID:
            return True, f"Hybrid recommended: low quality ({metrics.quality.value})"

        return False, f"Native text sufficient: {metrics.quality.value}"

    def get_extraction_strategy(
        self,
        text: str,
        page_count: int = 1,
    ) -> dict[str, Any]:
        """
        Get the full extraction strategy for a document.

        Args:
            text: Extracted native text
            page_count: Number of pages in document

        Returns:
            Dict with strategy details and metrics
        """
        metrics = self.analyze_text_quality(text)

        return {
            "recommended_mode": metrics.recommended_mode.value,
            "text_quality": metrics.quality.value,
            "needs_ocr": metrics.recommended_mode in (TextMode.OCR, TextMode.HYBRID),
            "metrics": metrics.to_dict(),
            "pages": page_count,
            "confidence": self._calculate_confidence(metrics),
        }

    def _calculate_confidence(self, metrics: TextQualityMetrics) -> float:
        """Calculate confidence in the extraction strategy."""
        if metrics.quality == TextQuality.EXCELLENT:
            return 0.95
        if metrics.quality == TextQuality.GOOD:
            return 0.85
        if metrics.quality == TextQuality.POOR:
            return 0.60
        return 0.20  # UNUSABLE


def analyze_document_text(text: str, page_count: int = 1) -> dict[str, Any]:
    """
    Convenience function to analyze document text quality.

    Args:
        text: Extracted text from document
        page_count: Number of pages

    Returns:
        Strategy and metrics dict
    """
    strategy = OCRStrategy()
    return strategy.get_extraction_strategy(text, page_count)


def needs_ocr(text: str) -> tuple[bool, str]:
    """
    Quick check if document needs OCR processing.

    Args:
        text: Native extracted text

    Returns:
        Tuple of (needs_ocr, reason)
    """
    strategy = OCRStrategy()
    return strategy.should_use_ocr(text)


# Singleton instance
_ocr_strategy = None


def get_ocr_strategy() -> OCRStrategy:
    """Get or create the OCR strategy singleton."""
    global _ocr_strategy
    if _ocr_strategy is None:
        _ocr_strategy = OCRStrategy()
    return _ocr_strategy
