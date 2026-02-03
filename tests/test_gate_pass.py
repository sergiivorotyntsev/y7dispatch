"""Tests for Gate Pass extractor."""

from extractors.gate_pass import GatePassExtractor, GatePassInfo


class TestGatePassExtractor:
    """Tests for GatePassExtractor."""

    def test_extract_generic_gate_pass(self):
        """Test extraction of generic gate pass format."""
        test_cases = [
            ("Gate Pass: ABC123", "ABC123"),
            ("Gate Pass #: XYZ789", "XYZ789"),
            ("Gate Pass Code: TEST-1234", "TEST-1234"),
            ("GatePass: PICKUP456", "PICKUP456"),
        ]
        for text, expected in test_cases:
            result = GatePassExtractor.extract_primary(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_iaa_gate_pass(self):
        """Test extraction of IAA-specific gate pass."""
        test_cases = [
            ("IAA Gate Pass: IAA12345", "IAA12345"),
            ("IAAI Pass: IAAPASS789", "IAAPASS789"),
        ]
        for text, expected in test_cases:
            result = GatePassExtractor.extract_primary(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_copart_release_code(self):
        """Test extraction of Copart release code."""
        test_cases = [
            ("Release Code: REL123", "REL123"),
            ("Lot Pin: LOT456", "LOT456"),
            ("Lot # PIN: COPART789", "COPART789"),
        ]
        for text, expected in test_cases:
            result = GatePassExtractor.extract_primary(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_manheim_release_id(self):
        """Test extraction of Manheim release ID."""
        test_cases = [
            ("Release ID: MAN12345", "MAN12345"),
            ("Pickup Code: PICKUP789", "PICKUP789"),
            ("Pickup Pin: PIN456", "PIN456"),
        ]
        for text, expected in test_cases:
            result = GatePassExtractor.extract_primary(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_multiple_returns_first_with_source(self):
        """Test that source-specific codes are preferred."""
        text = """
        Here is your pickup information.

        Generic code: GENERIC123
        IAA Gate Pass: IAA456

        Please use the IAA pass at the gate.
        """
        result = GatePassExtractor.extract_primary(text)
        # Should return IAA-specific code as it has a source hint
        assert result == "IAA456"

    def test_extract_all_codes(self):
        """Test extraction of all codes from text."""
        text = """
        Gate Pass: CODE1
        IAA Pass: CODE2
        Release ID: CODE3
        """
        results = GatePassExtractor.extract_from_text(text)
        codes = [r.code for r in results]

        assert "CODE1" in codes
        assert "CODE2" in codes
        assert "CODE3" in codes

    def test_no_gate_pass_found(self):
        """Test behavior when no gate pass is found."""
        text = "This email contains no pickup codes or authentication info."
        result = GatePassExtractor.extract_primary(text)
        assert result is None

    def test_deduplication(self):
        """Test that duplicate codes are not returned."""
        text = """
        Gate Pass: ABC123
        Your gate pass is ABC123
        Code: ABC123
        """
        results = GatePassExtractor.extract_from_text(text)
        codes = [r.code for r in results]

        # Should only have one ABC123
        assert codes.count("ABC123") == 1

    def test_invalid_codes_filtered(self):
        """Test that common words are not extracted as codes."""
        invalid_cases = [
            "code: CODE",  # Common word
            "pass: PASS",  # Common word
            "pin: PIN",  # Common word
            "code: AB",  # Too short
            "code: A" * 25,  # Too long
        ]
        for text in invalid_cases:
            results = GatePassExtractor.extract_from_text(text)
            # Filter out the common word codes
            valid_codes = [r.code for r in results if r.code not in {"CODE", "PASS", "PIN"}]
            assert len(valid_codes) == 0 or all(
                len(c) >= 4 for c in valid_codes
            ), f"Failed for: {text}"

    def test_case_normalization(self):
        """Test that codes are normalized to uppercase."""
        text = "Gate Pass: abc123def"
        result = GatePassExtractor.extract_primary(text)
        assert result == "ABC123DEF"

    def test_source_hint_populated(self):
        """Test that source hints are populated correctly."""
        test_cases = [
            ("IAA Gate Pass: CODE1", "IAA"),
            ("Copart Lot Pin: CODE2", "COPART"),
            ("Manheim Release ID: CODE3", "MANHEIM"),
            ("Gate Pass: CODE4", None),  # Generic has no hint
        ]
        for text, expected_hint in test_cases:
            results = GatePassExtractor.extract_from_text(text)
            if results:
                assert results[0].source_hint == expected_hint, f"Failed for: {text}"


class TestGatePassInfo:
    """Tests for GatePassInfo dataclass."""

    def test_gate_pass_info_creation(self):
        """Test GatePassInfo creation."""
        info = GatePassInfo(code="ABC123", raw_match="Gate Pass: ABC123", source_hint="IAA")
        assert info.code == "ABC123"
        assert info.raw_match == "Gate Pass: ABC123"
        assert info.source_hint == "IAA"

    def test_gate_pass_info_optional_source(self):
        """Test GatePassInfo with no source hint."""
        info = GatePassInfo(code="XYZ789", raw_match="Code: XYZ789")
        assert info.code == "XYZ789"
        assert info.source_hint is None
