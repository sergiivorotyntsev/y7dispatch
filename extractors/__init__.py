"""Extractor manager - auto-detects document type using scoring."""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from extractors.base import BaseExtractor, ExtractionResult
from extractors.copart import CopartExtractor
from extractors.iaa import IAAExtractor
from extractors.manheim import ManheimExtractor
from models.vehicle import AuctionInvoice, AuctionSource

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of document classification."""

    source: AuctionSource
    score: float
    extractor: Optional[BaseExtractor]
    matched_patterns: list[str]
    text: str = ""  # Cached text for subsequent extraction


class ExtractorManager:
    """Manages multiple extractors and auto-detects document types using scoring."""

    # Minimum score to consider a document matched
    MIN_SCORE_THRESHOLD = 0.3

    # Score difference threshold - if multiple extractors match,
    # the winner must be this much higher than second place
    SCORE_MARGIN = 0.1

    def __init__(self):
        self.extractors: list[BaseExtractor] = [
            IAAExtractor(),
            ManheimExtractor(),
            CopartExtractor(),
        ]
        self._text_cache = {}

    def _get_text(self, pdf_path: str) -> str:
        """Get text from PDF, using cache to avoid re-extraction."""
        if pdf_path not in self._text_cache:
            # Use any extractor to get text (they all use the same method)
            self._text_cache[pdf_path] = self.extractors[0].extract_text(pdf_path)
        return self._text_cache[pdf_path]

    def classify(self, pdf_path: str) -> ClassificationResult:
        """
        Classify a document by scoring against all extractors.
        Returns the best match with score and matched patterns.
        """
        text = self._get_text(pdf_path)

        results = []
        for extractor in self.extractors:
            score, patterns = extractor.score(text)
            results.append(
                ClassificationResult(
                    source=extractor.source,
                    score=score,
                    extractor=extractor,
                    matched_patterns=patterns,
                    text=text,
                )
            )

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)

        # Log all scores for debugging
        for r in results:
            logger.debug(f"  {r.source.value}: score={r.score:.2f}, patterns={r.matched_patterns}")

        best = results[0]

        # Check if best is above threshold
        if best.score < self.MIN_SCORE_THRESHOLD:
            logger.warning(
                f"No confident match. Best: {best.source.value} with score {best.score:.2f}"
            )
            return ClassificationResult(
                source=AuctionSource.IAA,  # Default fallback
                score=0.0,
                extractor=None,
                matched_patterns=[],
                text=text,
            )

        # Check margin against second place
        if len(results) > 1:
            second = results[1]
            margin = best.score - second.score
            if margin < self.SCORE_MARGIN and second.score > self.MIN_SCORE_THRESHOLD:
                logger.warning(
                    f"Ambiguous classification: {best.source.value}={best.score:.2f} vs "
                    f"{second.source.value}={second.score:.2f}"
                )

        logger.info(
            f"Classified as {best.source.value} (score={best.score:.2f}, "
            f"patterns={best.matched_patterns})"
        )
        return best

    def classify_pdf(self, pdf_path: str) -> ClassificationResult:
        """Alias for classify() - classify a PDF document."""
        return self.classify(pdf_path)

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        """Extract data from a PDF, auto-detecting the document type."""
        # Get text once
        text = self._get_text(pdf_path)

        # Check if text is sufficient (might need OCR)
        if len(text) < 100:
            logger.warning(
                f"Document has very little text ({len(text)} chars). "
                "May be a scanned document requiring OCR."
            )

        # Classify and extract
        classification = self.classify(pdf_path)

        if classification.extractor is None:
            logger.error("Could not classify document - no extractor matched")
            return None

        try:
            result = classification.extractor.extract(pdf_path)
            if result:
                logger.info(
                    f"Extracted: source={result.source.value}, "
                    f"vehicles={len(result.vehicles)}, "
                    f"reference={result.reference_id}"
                )
            return result
        except Exception as e:
            logger.error(f"Extraction failed: {e}", exc_info=True)
            return None

    def extract_with_result(self, pdf_path: str) -> ExtractionResult:
        """Extract with full metadata including confidence scores."""
        text = self._get_text(pdf_path)
        classification = self.classify(pdf_path)

        if classification.extractor is None:
            return ExtractionResult(
                invoice=None,
                source=AuctionSource.IAA,
                score=0.0,
                text_length=len(text),
                needs_ocr=len(text) < 100,
                matched_patterns=[],
            )

        return classification.extractor.extract_with_result(pdf_path, text)

    def get_all_scores(self, pdf_path: str) -> list[tuple[AuctionSource, float, list[str]]]:
        """Get scores from all extractors for debugging."""
        text = self._get_text(pdf_path)
        results = []
        for extractor in self.extractors:
            score, patterns = extractor.score(text)
            results.append((extractor.source, score, patterns))
        return sorted(results, key=lambda x: x[1], reverse=True)

    def get_extractor_for_text(self, text: str) -> Optional[BaseExtractor]:
        """Get best extractor for given text (legacy compatibility)."""
        best_extractor = None
        best_score = 0.0

        for extractor in self.extractors:
            score, _ = extractor.score(text)
            if score > best_score and score >= self.MIN_SCORE_THRESHOLD:
                best_score = score
                best_extractor = extractor

        return best_extractor

    def clear_cache(self):
        """Clear the text extraction cache."""
        self._text_cache.clear()


def extract_from_pdf(pdf_path: str) -> Optional[AuctionInvoice]:
    """Extract auction invoice data from a PDF file."""
    manager = ExtractorManager()
    return manager.extract(pdf_path)


def extract_with_details(pdf_path: str) -> ExtractionResult:
    """Extract with full result details including confidence."""
    manager = ExtractorManager()
    return manager.extract_with_result(pdf_path)
