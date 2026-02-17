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
import time as _time
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
        """
        Calculate cost in USD based on model pricing.

        Anthropic prompt caching pricing (Phase 1.6):
        - Cache reads: 90% cheaper than regular input tokens
        - Cache creation: 25% more expensive than regular input
        - Regular input: base price
        """
        # Haiku pricing (as of 2026)
        if "haiku" in model.lower():
            input_price = 0.25 / 1_000_000   # $0.25 per 1M input tokens
            output_price = 1.25 / 1_000_000  # $1.25 per 1M output tokens
            cache_read_price = 0.025 / 1_000_000  # 90% discount: $0.025 per 1M
            cache_write_price = 0.3125 / 1_000_000  # 25% premium: $0.3125 per 1M
        else:
            # Sonnet fallback pricing
            input_price = 3.0 / 1_000_000
            output_price = 15.0 / 1_000_000
            cache_read_price = 0.30 / 1_000_000  # 90% discount
            cache_write_price = 3.75 / 1_000_000  # 25% premium

        # Calculate total cost with caching
        regular_input = self.input_tokens - self.cache_read_tokens - self.cache_creation_tokens
        cost = (
            max(0, regular_input) * input_price +
            self.output_tokens * output_price +
            self.cache_read_tokens * cache_read_price +
            self.cache_creation_tokens * cache_write_price
        )
        return round(cost, 6)

    @property
    def cache_efficiency(self) -> float:
        """Calculate cache hit ratio (0.0 to 1.0)."""
        total_input = self.input_tokens
        if total_input == 0:
            return 0.0
        return self.cache_read_tokens / total_input


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


# Extraction prompt template (will be refined iteratively based on user feedback)
EXTRACTION_PROMPT = """Extract auction invoice fields from this document. Return ONLY valid JSON.

Fields to extract:
- auction_type: "COPART" | "IAA" | "MANHEIM" | "UNKNOWN"
- vehicle_vin: 17-character VIN
- vehicle_year: 4-digit year (integer)
- vehicle_make: Manufacturer name
- vehicle_model: Model name
- vehicle_color: Color if mentioned, else null
- vehicle_type: "CAR" | "SUV" | "TRUCK" | "VAN" | "MOTORCYCLE"
- vehicle_lot: Lot/Stock number
- vehicle_is_inoperable: true if vehicle is inoperable/non-running, false otherwise (default false)
- pickup_name: Location name (e.g., "Copart Dallas")
- pickup_address: Street address
- pickup_city: City name
- pickup_state: 2-letter state code
- pickup_zip: 5-digit ZIP
- pickup_phone: Phone number if available, else null
- buyer_id: Buyer/Member ID number
- buyer_name: Buyer name/company
- seller_name: Seller/Insurance company
- sale_date: Date in YYYY-MM-DD format
- total_amount: Total in USD (number only)
- manheim_release_date: For MANHEIM docs only (null for others). See Manheim rules below.
- manheim_offsite: For MANHEIM docs only (null for others). true if vehicle is not at a Manheim facility.
- offsite_pickup_address: If manheim_offsite is true, the offsite street address. null otherwise.
- offsite_pickup_city: If manheim_offsite is true, the offsite city. null otherwise.
- offsite_pickup_state: If manheim_offsite is true, the offsite 2-letter state. null otherwise.
- offsite_pickup_zip: If manheim_offsite is true, the offsite ZIP. null otherwise.

Auction detection:
- COPART: "Copart", "SOLD THROUGH COPART", "copart.com"
- IAA: "Insurance Auto Auctions", "IAA", "iaai.com"
- MANHEIM: "Manheim", "manheim.com"

Inoperable detection:
- Default: false (vehicle is operable)
- Set true if document contains: "INOP", "INOPERABLE", "NON-RUNNING", "NON-RUN", "DOES NOT RUN"
- Set false if document contains: "RUN AND DRIVE", "RUNS AND DRIVES", "OPERABLE"
- The explicit operable keywords override inoperable keywords if both appear

Manheim release date rules:
- Look for "ONSITE VEHICLE RELEASE" section in the document
- If found with a date like "Vehicle is releasable on Feb 03, 2026 at 12:00 CST":
  Extract as manheim_release_date in YYYY-MM-DD format (e.g., "2026-02-03")
- If "ONSITE VEHICLE RELEASE" section exists but NO specific release date mentioned:
  Set manheim_release_date = "AVAILABLE_NOW"
- If NO "ONSITE VEHICLE RELEASE" section at all in the document:
  Set manheim_release_date = "NO_RELEASE_DOCUMENT"
- If document says "This vehicle is not located at a Manheim facility" or "OFFSITE VEHICLE RELEASE":
  Set manheim_offsite = true and extract the offsite address fields separately

Here are 3 verified correct extractions as examples:

Example 1 (Copart):
Document begins: "Sales Receipt/Bill of Sale Date: 12/31/25 ... MEMBER:535527 ... GEICO - HOME OFFICE ... BROADWAY MOTORING INC ... 12020 US HIGHWAY 301 SOUTH SOLD THROUGH COPART ... RIVERVIEW FL 33578 ... LOT# 95541835 ... JTDKAMFU6N3164401 ... 2022 TOYOTA PRIUS ..."
Correct extraction:
{{"auction_type":"COPART","vehicle_vin":"JTDKAMFU6N3164401","vehicle_year":2022,"vehicle_make":"TOYOTA","vehicle_model":"PRIUS","vehicle_color":"RED","vehicle_type":"CAR","vehicle_lot":"95541835","vehicle_is_inoperable":false,"pickup_name":"Copart Riverview","pickup_address":"12020 US HIGHWAY 301 SOUTH","pickup_city":"RIVERVIEW","pickup_state":"FL","pickup_zip":"33578","pickup_phone":null,"buyer_id":"535527","buyer_name":"BROADWAY MOTORING INC","seller_name":"GEICO - HOME OFFICE","sale_date":"2025-12-30","total_amount":7275,"manheim_release_date":null,"manheim_offsite":null,"offsite_pickup_address":null,"offsite_pickup_city":null,"offsite_pickup_state":null,"offsite_pickup_zip":null}}

Example 2 (IAA):
Document begins: "Buyer Receipt ... Insurance Auto Auctions Corp ... Sold At Branch 332 - East Bay ... Pick-Up Location: East Bay 2780 Willow Pass Road Bay Point California 94565 (925) 458-7610 ... Buyer # 593509 ... Broadway Motoring Inc ... WA1CCAFP4GA133227 2016 AUDI SQ5 ..."
Correct extraction:
{{"auction_type":"IAA","vehicle_vin":"WA1CCAFP4GA133227","vehicle_year":2016,"vehicle_make":"AUDI","vehicle_model":"SQ5","vehicle_color":"Black","vehicle_type":"SUV","vehicle_lot":"43666048","vehicle_is_inoperable":false,"pickup_name":"East Bay","pickup_address":"2780 Willow Pass Road","pickup_city":"Bay Point","pickup_state":"CA","pickup_zip":"94565","pickup_phone":"(925) 458-7610","buyer_id":"593509","buyer_name":"Broadway Motoring Inc","seller_name":"Insurance Auto Auctions Corp","sale_date":"2025-12-24","total_amount":8955,"manheim_release_date":null,"manheim_offsite":null,"offsite_pickup_address":null,"offsite_pickup_city":null,"offsite_pickup_state":null,"offsite_pickup_zip":null}}

Example 3 (Manheim):
Document begins: "BILL OF SALE ... myCentralAuction Sale Date Vehicle Purchase Price ... 15-DEC-2025 ... Sale Price $ 6,500.00 ... 2025-51-94-275 ... Seller: CARVANA, LLC ... Manheim Portland 3000 N Hayden Island Dr Portland, OR 97217 ... YV4A22PMXG1037898 2016 Volvo XC90 ... ONSITE VEHICLE RELEASE ... Vehicle is releasable on Feb 03, 2026 at 12:00 CST"
Correct extraction:
{{"auction_type":"MANHEIM","vehicle_vin":"YV4A22PMXG1037898","vehicle_year":2016,"vehicle_make":"Volvo","vehicle_model":"XC90","vehicle_color":"Silver","vehicle_type":"SUV","vehicle_lot":"2025-51-94-275","vehicle_is_inoperable":false,"pickup_name":"Manheim Portland","pickup_address":"3000 N Hayden Island Dr","pickup_city":"Portland","pickup_state":"OR","pickup_zip":"97217","pickup_phone":"(503) 286-3000","buyer_id":"5515588","buyer_name":"BROADWAY MOTORING INC","seller_name":"CARVANA, LLC","sale_date":"2025-12-15","total_amount":6832,"manheim_release_date":"2026-02-03","manheim_offsite":false,"offsite_pickup_address":null,"offsite_pickup_city":null,"offsite_pickup_state":null,"offsite_pickup_zip":null}}

IMPORTANT for IAA: The lot number often appears as "000-XXXXXXXX". Extract ONLY the numeric part after "000-" (e.g., "000-43666048" → "43666048").

Return JSON only, no markdown, no explanation:
{{
  "auction_type": "...",
  "vehicle_vin": "...",
  "vehicle_year": 2024,
  "vehicle_make": "...",
  "vehicle_model": "...",
  "vehicle_color": "...",
  "vehicle_type": "...",
  "vehicle_lot": "...",
  "vehicle_is_inoperable": false,
  "pickup_name": "...",
  "pickup_address": "...",
  "pickup_city": "...",
  "pickup_state": "XX",
  "pickup_zip": "12345",
  "pickup_phone": null,
  "buyer_id": "...",
  "buyer_name": "...",
  "seller_name": "...",
  "sale_date": "YYYY-MM-DD",
  "total_amount": 0.00,
  "manheim_release_date": null,
  "manheim_offsite": null,
  "offsite_pickup_address": null,
  "offsite_pickup_city": null,
  "offsite_pickup_state": null,
  "offsite_pickup_zip": null
}}

Document:
---
{document_text}
---"""


class HaikuExtractor:
    """
    Claude Haiku-based document extractor.

    Extracts structured data from auction PDFs using Claude Haiku
    with evidence tracking and cost monitoring.
    """

    MODEL = "claude-haiku-4-5-20251001"
    MAX_TEXT_LENGTH = 50000  # Max chars to send to API

    # System prompt for extraction - cached to reduce token costs (Phase 1.6)
    SYSTEM_PROMPT = """You are an expert at extracting structured data from auction documents.
Your task is to extract vehicle and transaction information from auction invoices.

You must return ONLY valid JSON with no markdown formatting or explanation.
Extract all available fields and provide your confidence level for each.

Key identification patterns:
- COPART: "Copart", "SOLD THROUGH COPART", "copart.com", lot numbers like "12345678"
- IAA: "Insurance Auto Auctions", "IAA", "iaai.com"
- MANHEIM: "Manheim", "manheim.com"

VIN validation: 17 alphanumeric characters, no I, O, Q
State codes: 2-letter US state abbreviations
Dates: Extract as YYYY-MM-DD format
Prices: Extract as numbers only (no $ or commas)

Manheim-specific rules:
- Look for "ONSITE VEHICLE RELEASE" or "VEHICLE RELEASE" sections
- Extract release dates when available (format: "Vehicle is releasable on Mon DD, YYYY")
- Detect offsite vs onsite release: "not located at a Manheim facility" means offsite
- For offsite releases, extract the offsite pickup address separately

Vehicle operability detection:
- Default to operable (vehicle_is_inoperable=false)
- Keywords for inoperable: INOP, INOPERABLE, NON-RUNNING, NON-RUN, DOES NOT RUN
- Keywords for operable: RUN AND DRIVE, RUNS AND DRIVES, OPERABLE
- Explicit operable keywords override inoperable keywords"""

    def __init__(self, api_key: Optional[str] = None, enable_caching: bool = True):
        """
        Initialize extractor with API key.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            enable_caching: Enable prompt caching for reduced costs (Phase 1.6)
        """
        self.api_key = api_key
        if not self.api_key:
            # Try credential store first, then env var
            try:
                from services.credential_store import get_credential_for_service

                cred = get_credential_for_service("anthropic")
                if cred:
                    self.api_key = cred.get("api_key")
            except Exception:
                pass
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - extraction will fail")

        self._client = None
        self.enable_caching = enable_caching

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

        # Call Claude Haiku with prompt caching (Phase 1.6) and retry logic
        MAX_RETRIES = 3
        RETRY_DELAYS = [1, 3, 10]  # seconds backoff

        try:
            # Build user message with document text
            user_message = EXTRACTION_PROMPT.format(document_text=text)

            # Build API request with caching support
            api_kwargs = {
                "model": self.MODEL,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": user_message}]
            }

            # Add system prompt with cache_control for prompt caching (Phase 1.6)
            # This caches the static system prompt across requests
            if self.enable_caching:
                api_kwargs["system"] = [
                    {
                        "type": "text",
                        "text": self.SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            else:
                api_kwargs["system"] = self.SYSTEM_PROMPT

            response = None
            for attempt in range(MAX_RETRIES):
                try:
                    response = self.client.messages.create(**api_kwargs)
                    break
                except Exception as api_err:
                    logger.warning(
                        f"Claude API attempt {attempt + 1}/{MAX_RETRIES} failed: {api_err}"
                    )
                    if attempt == MAX_RETRIES - 1:
                        logger.error(f"Claude API failed after {MAX_RETRIES} retries: {api_err}")
                        raise
                    _time.sleep(RETRY_DELAYS[attempt])

            if response is None:
                result.error = "Claude API returned no response"
                return result

            # Track tokens including cache stats
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            cache_creation = getattr(response.usage, 'cache_creation_input_tokens', 0)

            result.tokens_used = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
            )
            result.cost_usd = result.tokens_used.calculate_cost(self.MODEL)

            # Log cache efficiency
            if cache_read > 0:
                logger.info(f"Prompt caching active: {cache_read} tokens read from cache")
            elif cache_creation > 0:
                logger.info(f"Cache created: {cache_creation} tokens cached for future requests")

            # Parse response
            response_text = response.content[0].text
            result.raw_response = response_text

            # Extract JSON from response
            parsed = self._parse_response(response_text)

            if parsed:
                result.auction_type = parsed.get("auction_type", "UNKNOWN")

                # Handle both formats:
                # 1. Flat: {"auction_type": "COPART", "vehicle_vin": "..."}
                # 2. Nested: {"auction_type": "COPART", "fields": {"vehicle_vin": {"value": "..."}}}

                fields_data = parsed.get("fields", {})

                if fields_data:
                    # Nested format with fields object
                    for field_name, field_data in fields_data.items():
                        if isinstance(field_data, dict):
                            value = field_data.get("value")
                            confidence = field_data.get("confidence", 1.0)
                            evidence_text = field_data.get("evidence", "")
                        else:
                            value = field_data
                            confidence = 1.0
                            evidence_text = ""

                        if value is not None:
                            result.fields[field_name] = ExtractedField(
                                value=value,
                                confidence=confidence,
                                source=FieldSource.EXTRACTED
                            )
                            if evidence_text:
                                result.evidence[field_name] = Citation(
                                    field_name=field_name,
                                    page_number=1,
                                    text_span=str(evidence_text)[:200]
                                )
                else:
                    # Flat format - all fields at top level
                    field_names = [
                        "vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model",
                        "vehicle_color", "vehicle_type", "vehicle_lot",
                        "pickup_name", "pickup_address", "pickup_city", "pickup_state",
                        "pickup_zip", "pickup_phone",
                        "buyer_id", "buyer_name", "seller_name", "sale_date", "total_amount"
                    ]
                    for field_name in field_names:
                        value = parsed.get(field_name)
                        if value is not None:
                            result.fields[field_name] = ExtractedField(
                                value=value,
                                confidence=1.0,
                                source=FieldSource.EXTRACTED
                            )

                # Post-processing: IAA lot number cleanup
                # IAA invoices prefix lot numbers with "000-" (e.g., "000-43699659")
                # Strip the prefix to get the actual lot number (e.g., "43699659")
                if (
                    result.auction_type == "IAA"
                    and "vehicle_lot" in result.fields
                    and isinstance(result.fields["vehicle_lot"].value, str)
                    and result.fields["vehicle_lot"].value.startswith("000-")
                ):
                    result.fields["vehicle_lot"].value = result.fields["vehicle_lot"].value.replace("000-", "", 1)

                # Calculate overall confidence
                if result.fields:
                    confidences = [f.confidence for f in result.fields.values()]
                    result.confidence = sum(confidences) / len(confidences)

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            result.error = str(e)

        return result

    def _parse_response(self, response_text: str) -> Optional[dict]:
        """Parse JSON from Claude response, handling markdown code blocks."""
        import re

        # Remove markdown code blocks if present
        # Handle ```json ... ``` or ``` ... ```
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # Remove opening ```json or ```
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
            # Remove closing ```
            cleaned = re.sub(r'\n?```\s*$', '', cleaned)

        try:
            # Try direct JSON parse
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in response
        try:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass

        logger.warning(f"Could not parse JSON from response: {response_text[:100]}...")
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


def normalize_haiku_result(haiku_result: ExtractionResult) -> tuple[dict, dict]:
    """
    Convert HaikuExtractor output to standard extraction format.

    Returns:
        (outputs, field_sources) — flat dicts compatible with DB storage.
        outputs: {field_name: value}
        field_sources: {field_name: {"value", "source", "confidence", "method"}}
    """
    outputs = {}
    field_sources = {}

    for field_name, extracted_field in haiku_result.fields.items():
        value = extracted_field.value
        if value is not None:
            outputs[field_name] = value
            field_sources[field_name] = {
                "value": value,
                "source": "HAIKU_EXTRACTED",
                "confidence": extracted_field.confidence,
                "method": f"haiku:{HaikuExtractor.MODEL}",
            }

    return outputs, field_sources


# Singleton instance for reuse across requests (keeps prompt cache warm)
_haiku_extractor: Optional[HaikuExtractor] = None


def get_haiku_extractor() -> HaikuExtractor:
    """Get or create the HaikuExtractor singleton.

    Re-creates the singleton if api_key is missing (handles the case where
    credentials are added via Settings UI after server startup).
    """
    global _haiku_extractor
    if _haiku_extractor is None or not _haiku_extractor.api_key:
        _haiku_extractor = HaikuExtractor()
    return _haiku_extractor


# Convenience function for testing
def extract_document(pdf_path: str, api_key: Optional[str] = None) -> ExtractionResult:
    """Extract fields from a single document."""
    extractor = HaikuExtractor(api_key=api_key)
    return extractor.extract(pdf_path)
