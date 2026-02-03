"""Gate Pass / PIN extractor from email body."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GatePassInfo:
    code: str
    raw_match: str
    source_hint: Optional[str] = None


class GatePassExtractor:
    """Extracts gate pass/PIN codes from email body text."""

    # Patterns ordered by specificity: source-specific first, then generic
    PATTERNS = [
        # IAA-specific patterns (check before generic Gate Pass)
        (r"(?:IAA|IAAI)\s*(?:Gate\s*)?Pass\s*[:#]?\s*([A-Za-z0-9\-]{4,20})", "IAA"),
        # Copart-specific patterns
        (r"Copart\s*(?:Release|Lot)\s*(?:Code|#|Pin)\s*[:#]?\s*([A-Za-z0-9\-]{4,20})", "COPART"),
        (r"(?:Lot\s*#?\s*Pin|Lot\s*Pin)\s*[:#]?\s*([A-Za-z0-9\-]{4,20})", "COPART"),
        # Manheim-specific patterns
        (r"(?:Manheim\s*)?Release\s*ID\s*[:#]?\s*([A-Za-z0-9\-]{4,20})", "MANHEIM"),
        (r"Pickup\s*(?:Code|Pin)\s*[:#]?\s*([A-Za-z0-9\-]{4,20})", "MANHEIM"),
        # Generic patterns (after source-specific)
        (r"Gate\s*Pass\s*(?:Pin|Code|#|Number)?\s*[:#]\s*([A-Za-z0-9\-]{4,20})", "generic"),
        (r"Release\s*Code\s*[:#]\s*([A-Za-z0-9\-]{4,20})", "COPART"),
        (r"(?:Pickup|Gate|Access)\s*PIN\s*[:#]\s*([A-Za-z0-9\-]{4,20})", "generic"),
        (r"Auth(?:orization)?\s*Code\s*[:#]\s*([A-Za-z0-9\-]{4,20})", "generic"),
        (r"Pass\s*(?:Code|#)\s*[:#]\s*([A-Za-z0-9\-]{4,20})", "generic"),
        (r"\b(?:code|pin)\s*[:#]\s*([A-Za-z0-9\-]{4,20})\b", "generic"),
    ]

    @classmethod
    def extract_from_text(cls, text: str) -> list[GatePassInfo]:
        results = []
        seen_codes = set()

        for pattern, source_hint in cls.PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                code = match.group(1).strip().upper()
                if code in seen_codes:
                    continue
                if cls._is_valid_code(code):
                    seen_codes.add(code)
                    results.append(
                        GatePassInfo(
                            code=code,
                            raw_match=match.group(0).strip(),
                            source_hint=source_hint if source_hint != "generic" else None,
                        )
                    )
        return results

    @classmethod
    def extract_primary(cls, text: str) -> Optional[str]:
        results = cls.extract_from_text(text)
        if not results:
            return None
        for r in results:
            if r.source_hint:
                return r.code
        return results[0].code

    @staticmethod
    def _is_valid_code(code: str) -> bool:
        if len(code) < 4 or len(code) > 20:
            return False
        if not re.match(r"^[A-Z0-9\-]+$", code):
            return False
        common_words = {"CODE", "PASS", "GATE", "PIN", "NONE", "NULL", "TEST"}
        if code in common_words:
            return False
        return True


def extract_text_from_email_body(msg) -> str:
    """Extract plain text from email message body."""
    text_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    text_parts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    text_parts.append(_html_to_text(html))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                content = _html_to_text(content)
            text_parts.append(content)

    return "\n\n".join(text_parts)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return text.strip()
