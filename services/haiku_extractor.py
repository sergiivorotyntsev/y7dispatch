"""
Claude Haiku Extractor Service for auction document extraction.

Phase 1.1 from IMPLEMENTATION_PHASES.md:
- PDF + email body extraction via Claude Haiku
- Structured output with evidence tracking
- Cost tracking per request
"""

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

import pdfplumber

logger = logging.getLogger(__name__)


class FieldSource(Enum):
    """Source of extracted field value."""
    EXTRACTED = "extracted"      # From document via LLM
    VALIDATED = "validated"      # Extracted + validated (VIN decode, etc.)
    DEFAULT = "default"          # Fallback default value
    USER_OVERRIDE = "user_override"


@dataclass
class TokenUsage:
    """Token usage for cost tracking."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def calculate_cost(self, model: str = "claude-haiku-4-5-20251001") -> float:
        """Calculate cost in USD based on model pricing."""
        # Haiku pricing (as of 2026)
        if "haiku" in model.lower():
            input_price = 0.25 / 1_000_000   # $0.25 per 1M input tokens
            output_price = 1.25 / 1_000_000  # $1.25 per 1M output tokens
            cache_read_price = 0.03 / 1_000_000  # $0.03 per 1M cache read
        else:
            # Sonnet fallback pricing
            input_price = 3.0 / 1_000_000
            output_price = 15.0 / 1_000_000
            cache_read_price = 0.30 / 1_000_000

        cost = (
            self.input_tokens * input_price +
            self.output_tokens * output_price +
            self.cache_read_tokens * cache_read_price
        )
        return round(cost, 6)


@dataclass
class ExtractedField:
    """A single extracted field with metadata."""
    value: Any
    confidence: float = 1.0  # 0.0-1.0
    source: FieldSource = FieldSource.EXTRACTED


@dataclass
class Citation:
    """Evidence/citation for an extracted field."""
    field_name: str
    page_number: int
    text_span: str
    bbox: Optional[tuple] = None  # (x0, y0, x1, y1) for PDF


@dataclass
class ExtractionResult:
    """Complete extraction result with fields and evidence."""
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    evidence: dict[str, Citation] = field(default_factory=dict)
    confidence: float = 0.0
    tokens_used: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    auction_type: str = "UNKNOWN"
    error: Optional[str] = None
    raw_response: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "fields": {k: {"value": v.value, "confidence": v.confidence, "source": v.source.value}
                      for k, v in self.fields.items()},
            "evidence": {k: {"page": v.page_number, "text": v.text_span}
                        for k, v in self.evidence.items()},
            "confidence": self.confidence,
            "tokens": {
                "input": self.tokens_used.input_tokens,
                "output": self.tokens_used.output_tokens,
                "cache_read": self.tokens_used.cache_read_tokens,
            },
            "cost_usd": self.cost_usd,
            "auction_type": self.auction_type,
            "error": self.error,
        }


# Extraction prompt template (will be refined iteratively)
EXTRACTION_PROMPT = """You are an expert document extractor for vehicle auction invoices.

Extract the following fields from this auction document. For each field, provide the exact value as found in the document.

## Required Fields:
- vehicle_vin: 17-character Vehicle Identification Number
- vehicle_year: 4-digit year (e.g., 2024)
- vehicle_make: Manufacturer (e.g., Honda, Toyota, Ford)
- vehicle_model: Model name (e.g., Accord, Camry, F-150)
- vehicle_color: Color if mentioned
- vehicle_type: CAR, SUV, TRUCK, VAN, or MOTORCYCLE
- vehicle_lot: Lot number or Stock number

- pickup_name: Location/yard name (e.g., "Copart Dallas")
- pickup_address: Street address of pickup location
- pickup_city: City
- pickup_state: 2-letter state code (e.g., TX, CA)
- pickup_zip: 5-digit ZIP code
- pickup_phone: Phone number if available

- buyer_id: Buyer/Member ID number
- buyer_name: Buyer company or person name
- seller_name: Seller/Insurance company name
- sale_date: Date of sale (YYYY-MM-DD format)
- total_amount: Total sale amount in USD (number only, no $)

## Auction Type Detection:
Identify the auction type based on document content:
- COPART: Look for "Copart", "SOLD THROUGH COPART", "copart.com"
- IAA: Look for "Insurance Auto Auctions", "IAA", "iaai.com"
- MANHEIM: Look for "Manheim", "manheim.com"

## Output Format:
Return a JSON object with exactly this structure:
{
  "auction_type": "COPART" | "IAA" | "MANHEIM" | "UNKNOWN",
  "fields": {
    "vehicle_vin": {"value": "...", "confidence": 0.0-1.0, "evidence": "quoted text from document"},
    "vehicle_year": {"value": ..., "confidence": 0.0-1.0, "evidence": "..."},
    ...
  }
}

Rules:
- If a field is not found, set value to null and confidence to 0.0
- confidence should reflect how certain you are (1.0 = found exact match, 0.5 = inferred)
- evidence should be the exact text snippet where you found the value
- For VIN: must be exactly 17 characters, no I, O, or Q
- For dates: convert to YYYY-MM-DD format
- For amounts: extract number only, no currency symbols or commas

Document text follows:
---
{document_text}
---

Return only the JSON object, no additional text."""


class HaikuExtractor:
    """
    Claude Haiku-based document extractor.

    Extracts structured data from auction PDFs using Claude Haiku
    with evidence tracking and cost monitoring.
    """

    MODEL = "claude-haiku-4-5-20251001"
    MAX_TEXT_LENGTH = 50000  # Max chars to send to API

    def __init__(self, api_key: Optional[str] = None):
        """Initialize extractor with API key."""
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - extraction will fail")

        self._client = None

    @property
    def client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def extract_text_from_pdf(self, pdf_path: str) -> tuple[str, int]:
        """
        Extract text from PDF using pdfplumber.

        Returns: (text, page_count)
        """
        text_parts = []
        page_count = 0

        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {e}")
            return "", 0

        full_text = "\n\n".join(text_parts)

        # Truncate if too long
        if len(full_text) > self.MAX_TEXT_LENGTH:
            logger.warning(f"Text truncated from {len(full_text)} to {self.MAX_TEXT_LENGTH} chars")
            full_text = full_text[:self.MAX_TEXT_LENGTH]

        return full_text, page_count

    def extract(
        self,
        pdf_path: str,
        document_type: Literal["pdf", "email"] = "pdf"
    ) -> ExtractionResult:
        """
        Extract fields from a document.

        Args:
            pdf_path: Path to PDF file
            document_type: Type of document (pdf or email)

        Returns:
            ExtractionResult with fields, evidence, and cost
        """
        result = ExtractionResult()

        # Extract text
        if document_type == "pdf":
            text, page_count = self.extract_text_from_pdf(pdf_path)
        else:
            # For email, read as text
            text = Path(pdf_path).read_text(encoding="utf-8", errors="ignore")
            page_count = 1

        if not text or len(text) < 50:
            result.error = "Insufficient text extracted from document"
            return result

        # Call Claude Haiku
        try:
            prompt = EXTRACTION_PROMPT.format(document_text=text)

            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            # Track tokens
            result.tokens_used = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_tokens=getattr(response.usage, 'cache_read_input_tokens', 0),
            )
            result.cost_usd = result.tokens_used.calculate_cost(self.MODEL)

            # Parse response
            response_text = response.content[0].text
            result.raw_response = response_text

            # Extract JSON from response
            parsed = self._parse_response(response_text)

            if parsed:
                result.auction_type = parsed.get("auction_type", "UNKNOWN")

                for field_name, field_data in parsed.get("fields", {}).items():
                    if isinstance(field_data, dict):
                        value = field_data.get("value")
                        confidence = field_data.get("confidence", 1.0)
                        evidence_text = field_data.get("evidence", "")

                        if value is not None:
                            result.fields[field_name] = ExtractedField(
                                value=value,
                                confidence=confidence,
                                source=FieldSource.EXTRACTED
                            )

                            if evidence_text:
                                result.evidence[field_name] = Citation(
                                    field_name=field_name,
                                    page_number=1,  # TODO: detect actual page
                                    text_span=evidence_text[:200]  # Truncate long evidence
                                )

                # Calculate overall confidence
                if result.fields:
                    confidences = [f.confidence for f in result.fields.values()]
                    result.confidence = sum(confidences) / len(confidences)

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            result.error = str(e)

        return result

    def _parse_response(self, response_text: str) -> Optional[dict]:
        """Parse JSON from Claude response."""
        try:
            # Try direct JSON parse
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in response
        try:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response_text[start:end])
        except json.JSONDecodeError:
            pass

        logger.warning("Could not parse JSON from response")
        return None

    def extract_batch(
        self,
        pdf_paths: list[str],
        progress_callback: Optional[callable] = None
    ) -> list[ExtractionResult]:
        """
        Extract from multiple PDFs.

        Args:
            pdf_paths: List of PDF file paths
            progress_callback: Optional callback(current, total, result)

        Returns:
            List of ExtractionResult
        """
        results = []
        total = len(pdf_paths)

        for i, pdf_path in enumerate(pdf_paths):
            try:
                result = self.extract(pdf_path)
            except Exception as e:
                result = ExtractionResult(error=str(e))

            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total, result)

        return results


# Convenience function for testing
def extract_document(pdf_path: str, api_key: Optional[str] = None) -> ExtractionResult:
    """Extract fields from a single document."""
    extractor = HaikuExtractor(api_key=api_key)
    return extractor.extract(pdf_path)
