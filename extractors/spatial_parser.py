"""
Spatial Document Parser

Provides block-based document parsing with spatial awareness.
Understands document layout by grouping text into logical regions/blocks,
enabling more accurate field extraction based on visual structure.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class TextElement:
    """A text element with position information."""

    text: str
    x0: float  # Left edge
    y0: float  # Top edge (from page top)
    x1: float  # Right edge
    y1: float  # Bottom edge
    page: int = 0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class DocumentBlock:
    """A logical block/region in the document."""

    id: str
    label: Optional[str]  # Detected label (e.g., "PHYSICAL ADDRESS OF LOT")
    elements: list[TextElement] = field(default_factory=list)
    x0: float = 0
    y0: float = 0
    x1: float = 0
    y1: float = 0
    page: int = 0
    block_type: str = "unknown"  # 'header', 'label', 'data', 'table', 'footer'

    @property
    def text(self) -> str:
        """Get all text in this block, sorted by position."""
        sorted_elements = sorted(self.elements, key=lambda e: (e.y0, e.x0))
        return "\n".join(e.text for e in sorted_elements)

    @property
    def lines(self) -> list[str]:
        """Get text as lines, grouped by Y position."""
        if not self.elements:
            return []

        # Group elements by Y position (with tolerance)
        y_tolerance = 5
        lines_dict: dict[float, list[TextElement]] = {}

        for elem in self.elements:
            # Find matching Y group
            matched_y = None
            for y in lines_dict.keys():
                if abs(elem.y0 - y) < y_tolerance:
                    matched_y = y
                    break

            if matched_y is not None:
                lines_dict[matched_y].append(elem)
            else:
                lines_dict[elem.y0] = [elem]

        # Sort lines by Y, then elements within each line by X
        result = []
        for y in sorted(lines_dict.keys()):
            line_elems = sorted(lines_dict[y], key=lambda e: e.x0)
            line_text = " ".join(e.text for e in line_elems)
            result.append(line_text.strip())

        return result

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point is within this block."""
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def overlaps(self, other: "DocumentBlock") -> bool:
        """Check if this block overlaps with another."""
        return not (
            self.x1 < other.x0 or self.x0 > other.x1 or self.y1 < other.y0 or self.y0 > other.y1
        )


@dataclass
class DocumentStructure:
    """Parsed document structure with blocks and metadata."""

    blocks: list[DocumentBlock] = field(default_factory=list)
    raw_text: str = ""
    page_count: int = 0
    width: float = 0
    height: float = 0

    # Detected regions by type
    header_blocks: list[DocumentBlock] = field(default_factory=list)
    data_blocks: list[DocumentBlock] = field(default_factory=list)
    table_blocks: list[DocumentBlock] = field(default_factory=list)

    # Label to block mapping
    labeled_blocks: dict[str, DocumentBlock] = field(default_factory=dict)

    # Column detection (M3.P1.1)
    detected_columns: list[tuple[float, float]] = field(
        default_factory=list
    )  # (x_start, x_end) per column
    column_count: int = 1
    reading_order_strategy: str = "linear"  # linear, column_aware

    def get_block_by_label(self, label_pattern: str) -> Optional[DocumentBlock]:
        """Find a block by its label pattern."""
        pattern = re.compile(label_pattern, re.IGNORECASE)
        for label, block in self.labeled_blocks.items():
            if pattern.search(label):
                return block
        return None

    def get_text_near_label(self, label_pattern: str, max_lines: int = 5) -> list[str]:
        """Get text lines below/after a label."""
        block = self.get_block_by_label(label_pattern)
        if block:
            return block.lines[:max_lines]

        # Fallback: search in raw text
        lines = self.raw_text.split("\n")
        pattern = re.compile(label_pattern, re.IGNORECASE)
        for i, line in enumerate(lines):
            if pattern.search(line):
                return lines[i + 1 : i + 1 + max_lines]
        return []

    def get_blocks_in_region(self, region: str) -> list[DocumentBlock]:
        """Get blocks in a named region (left, right, top, bottom, center)."""
        if not self.blocks:
            return []

        mid_x = self.width / 2
        mid_y = self.height / 2

        result = []
        for block in self.blocks:
            if region == "left" and block.center_x < mid_x:
                result.append(block)
            elif region == "right" and block.center_x >= mid_x:
                result.append(block)
            elif region == "top" and block.center_y < mid_y * 0.5:
                result.append(block)
            elif region == "bottom" and block.center_y > mid_y * 1.5:
                result.append(block)
            elif region == "center":
                if mid_x * 0.3 < block.center_x < mid_x * 1.7:
                    result.append(block)

        return result

    @property
    def center_x(self) -> float:
        return self.width / 2


class SpatialParser:
    """
    Parser that extracts document structure with spatial awareness.

    Uses pdfplumber to get word-level positions and groups them into
    logical blocks based on visual proximity and labels.
    """

    # Common document labels that indicate data blocks
    BLOCK_LABELS = [
        r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT",
        r"MEMBER",
        r"SELLER",
        r"BUYER",
        r"VEHICLE",
        r"PICKUP\s*(?:LOCATION|ADDRESS)",
        r"DELIVERY\s*(?:LOCATION|ADDRESS)",
        r"LOT\s*#",
        r"VIN",
        r"CHARGES?\s*(?:AND\s*)?PAYMENTS?",
        r"TOTAL",
        r"SALE\s*(?:DATE|PRICE)",
    ]

    # Vertical gap threshold to separate blocks (in points)
    BLOCK_GAP_THRESHOLD = 15

    # Horizontal gap threshold for same-line grouping
    LINE_GAP_THRESHOLD = 50

    def __init__(self):
        self._cached_structures: dict[str, DocumentStructure] = {}

    def parse(self, pdf_path: str) -> DocumentStructure:
        """
        Parse a PDF document and extract its spatial structure.

        Returns a DocumentStructure with blocks, labels, and regions identified.
        """
        # Check cache
        if pdf_path in self._cached_structures:
            return self._cached_structures[pdf_path]

        structure = DocumentStructure()
        all_elements: list[TextElement] = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                structure.page_count = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    if page_num == 0:
                        structure.width = page.width
                        structure.height = page.height

                    # Extract words with positions
                    words = page.extract_words(
                        keep_blank_chars=False,
                        x_tolerance=3,
                        y_tolerance=3,
                    )

                    for word in words:
                        elem = TextElement(
                            text=word["text"],
                            x0=word["x0"],
                            y0=word["top"],
                            x1=word["x1"],
                            y1=word["bottom"],
                            page=page_num,
                        )
                        all_elements.append(elem)

                    # Get full text for fallback
                    page_text = page.extract_text()
                    if page_text:
                        structure.raw_text += page_text + "\n"

        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            return structure

        # Group elements into blocks
        structure.blocks = self._group_into_blocks(all_elements, structure)

        # Identify labeled blocks
        self._identify_labels(structure)

        # Classify block types
        self._classify_blocks(structure)

        # M3.P1.1: Detect columns
        self.detect_columns(structure)

        # M3.P1.2: Sort in reading order
        structure.blocks = self.sort_reading_order(structure)

        # Cache result
        self._cached_structures[pdf_path] = structure

        return structure

    def _group_into_blocks(
        self, elements: list[TextElement], structure: DocumentStructure
    ) -> list[DocumentBlock]:
        """Group text elements into logical blocks based on spatial proximity."""
        if not elements:
            return []

        # Sort by page, then Y, then X
        sorted_elements = sorted(elements, key=lambda e: (e.page, e.y0, e.x0))

        blocks: list[DocumentBlock] = []
        current_block: Optional[DocumentBlock] = None

        for elem in sorted_elements:
            if current_block is None:
                # Start new block
                current_block = DocumentBlock(
                    id=f"block_{len(blocks)}",
                    label=None,
                    elements=[elem],
                    x0=elem.x0,
                    y0=elem.y0,
                    x1=elem.x1,
                    y1=elem.y1,
                    page=elem.page,
                )
            else:
                # Check if element belongs to current block
                # Same page, vertically close, and horizontally reasonable
                same_page = elem.page == current_block.page
                vertical_close = elem.y0 - current_block.y1 < self.BLOCK_GAP_THRESHOLD
                horizontal_overlap = not (elem.x0 > current_block.x1 + self.LINE_GAP_THRESHOLD * 3)

                if same_page and vertical_close and horizontal_overlap:
                    # Add to current block
                    current_block.elements.append(elem)
                    current_block.x0 = min(current_block.x0, elem.x0)
                    current_block.y0 = min(current_block.y0, elem.y0)
                    current_block.x1 = max(current_block.x1, elem.x1)
                    current_block.y1 = max(current_block.y1, elem.y1)
                else:
                    # Save current block and start new one
                    blocks.append(current_block)
                    current_block = DocumentBlock(
                        id=f"block_{len(blocks)}",
                        label=None,
                        elements=[elem],
                        x0=elem.x0,
                        y0=elem.y0,
                        x1=elem.x1,
                        y1=elem.y1,
                        page=elem.page,
                    )

        # Don't forget the last block
        if current_block:
            blocks.append(current_block)

        return blocks

    def _identify_labels(self, structure: DocumentStructure) -> None:
        """Identify blocks that match known label patterns."""
        for block in structure.blocks:
            block_text = block.text
            for label_pattern in self.BLOCK_LABELS:
                if re.search(label_pattern, block_text, re.IGNORECASE):
                    # Extract the matched label
                    match = re.search(label_pattern, block_text, re.IGNORECASE)
                    if match:
                        label_key = match.group(0).upper().strip()
                        block.label = label_key
                        structure.labeled_blocks[label_key] = block
                        break

    def _classify_blocks(self, structure: DocumentStructure) -> None:
        """Classify blocks by their type (header, data, table, etc.)."""
        for block in structure.blocks:
            # Header blocks are at the top
            if block.y0 < structure.height * 0.15:
                block.block_type = "header"
                structure.header_blocks.append(block)
            # Footer blocks are at the bottom
            elif block.y0 > structure.height * 0.85:
                block.block_type = "footer"
            # Labeled blocks are data blocks
            elif block.label:
                block.block_type = "label"
                structure.data_blocks.append(block)
            # Check for table-like structure (multiple aligned columns)
            elif self._looks_like_table(block):
                block.block_type = "table"
                structure.table_blocks.append(block)
            else:
                block.block_type = "data"
                structure.data_blocks.append(block)

    def _looks_like_table(self, block: DocumentBlock) -> bool:
        """Check if a block looks like a table based on alignment patterns."""
        lines = block.lines
        if len(lines) < 3:
            return False

        # Check for consistent column alignment
        # This is a simple heuristic - could be improved
        x_positions = []
        for elem in block.elements:
            x_positions.append(round(elem.x0, -1))  # Round to nearest 10

        # If many elements share similar X positions, likely a table
        from collections import Counter

        x_counts = Counter(x_positions)
        if len(x_counts) > 2 and max(x_counts.values()) >= len(lines):
            return True

        return False

    # =========================================================================
    # M3.P1.1: COLUMN DETECTION
    # =========================================================================

    def detect_columns(
        self,
        structure: DocumentStructure,
        min_gap_ratio: float = 0.10,
    ) -> int:
        """
        Detect columns in the document based on horizontal gap analysis.

        Args:
            structure: DocumentStructure to analyze
            min_gap_ratio: Minimum gap as ratio of page width to separate columns

        Returns:
            Number of detected columns
        """
        if not structure.blocks or structure.width == 0:
            structure.column_count = 1
            return 1

        min_gap = structure.width * min_gap_ratio

        # Collect all block x-coordinates
        block_positions = []
        for block in structure.blocks:
            if block.block_type in ("data", "label"):
                block_positions.append(
                    {
                        "x0": block.x0,
                        "x1": block.x1,
                        "center_x": (block.x0 + block.x1) / 2,
                        "block": block,
                    }
                )

        if len(block_positions) < 2:
            structure.column_count = 1
            return 1

        # Sort by x position
        block_positions.sort(key=lambda b: b["x0"])

        # Find gaps between blocks
        gaps = []
        for i in range(len(block_positions) - 1):
            current = block_positions[i]
            next_block = block_positions[i + 1]
            gap = next_block["x0"] - current["x1"]
            if gap > min_gap:
                gaps.append(
                    {
                        "position": (current["x1"] + next_block["x0"]) / 2,
                        "size": gap,
                    }
                )

        if not gaps:
            structure.column_count = 1
            structure.detected_columns = [(0, structure.width)]
            return 1

        # Sort gaps by size (largest first) and take significant ones
        gaps.sort(key=lambda g: g["size"], reverse=True)

        # Determine column boundaries
        column_dividers = [g["position"] for g in gaps[:3]]  # Max 4 columns
        column_dividers.sort()

        # Build column ranges
        columns = []
        prev_x = 0
        for divider in column_dividers:
            columns.append((prev_x, divider))
            prev_x = divider
        columns.append((prev_x, structure.width))

        structure.detected_columns = columns
        structure.column_count = len(columns)
        structure.reading_order_strategy = "column_aware" if len(columns) > 1 else "linear"

        logger.debug(f"Detected {len(columns)} columns: {columns}")
        return len(columns)

    def sort_reading_order(
        self,
        structure: DocumentStructure,
    ) -> list[DocumentBlock]:
        """
        Sort blocks in reading order (M3.P1.2).

        For multi-column documents:
        - Within each column: top to bottom
        - Columns: left to right
        - Cross-column: complete left column before right

        Args:
            structure: DocumentStructure with blocks

        Returns:
            List of blocks in reading order
        """
        if not structure.blocks:
            return []

        # Ensure columns are detected
        if not structure.detected_columns:
            self.detect_columns(structure)

        if structure.column_count <= 1:
            # Single column: simple top-to-bottom, left-to-right
            return sorted(structure.blocks, key=lambda b: (b.page, b.y0, b.x0))

        # Multi-column: assign blocks to columns, then sort
        columns = structure.detected_columns

        def get_column_index(block: DocumentBlock) -> int:
            """Get the column index for a block based on its center_x."""
            center_x = (block.x0 + block.x1) / 2
            for i, (col_start, col_end) in enumerate(columns):
                if col_start <= center_x <= col_end:
                    return i
            # Fallback: find closest column
            min_dist = float("inf")
            best_col = 0
            for i, (col_start, col_end) in enumerate(columns):
                col_center = (col_start + col_end) / 2
                dist = abs(center_x - col_center)
                if dist < min_dist:
                    min_dist = dist
                    best_col = i
            return best_col

        # Sort by: page, column index, y position, x position
        return sorted(structure.blocks, key=lambda b: (b.page, get_column_index(b), b.y0, b.x0))

    def get_column_text(
        self,
        structure: DocumentStructure,
        column_index: int = 0,
    ) -> str:
        """
        Get text from a specific column in reading order.

        Args:
            structure: DocumentStructure
            column_index: Column index (0-based, left to right)

        Returns:
            Text from the specified column
        """
        if not structure.detected_columns:
            self.detect_columns(structure)

        if column_index >= len(structure.detected_columns):
            return ""

        col_start, col_end = structure.detected_columns[column_index]

        # Get blocks in this column
        column_blocks = []
        for block in structure.blocks:
            center_x = (block.x0 + block.x1) / 2
            if col_start <= center_x <= col_end:
                column_blocks.append(block)

        # Sort by y position
        column_blocks.sort(key=lambda b: (b.page, b.y0))

        # Join text
        return "\n".join(b.text for b in column_blocks if b.text)

    def extract_field_by_label(
        self,
        structure: DocumentStructure,
        label_patterns: list[str],
        field_type: str = "text",
        max_lines: int = 5,
        region_hint: str = None,
    ) -> Optional[str]:
        """
        Extract a field value by looking for it near specified labels.

        Args:
            structure: Parsed document structure
            label_patterns: List of regex patterns to match labels
            field_type: Expected type ('text', 'address', 'phone', etc.)
            max_lines: Maximum lines to capture after label
            region_hint: Optional region to search in ('left', 'right', 'top', 'bottom')

        Returns:
            Extracted value or None
        """
        # Try each label pattern
        for pattern in label_patterns:
            # First try labeled blocks
            block = structure.get_block_by_label(pattern)
            if block:
                lines = block.lines
                # Skip the label line itself
                data_lines = []
                found_label = False
                for line in lines:
                    if re.search(pattern, line, re.IGNORECASE):
                        found_label = True
                        # Check if value is on same line
                        after_label = re.split(pattern, line, flags=re.IGNORECASE)[-1].strip()
                        if after_label and len(after_label) > 2:
                            data_lines.append(after_label)
                        continue
                    if found_label:
                        if line.strip():
                            data_lines.append(line.strip())
                        if len(data_lines) >= max_lines:
                            break

                if data_lines:
                    return self._format_extracted_value(data_lines, field_type)

            # Fallback: search in raw text
            lines = structure.raw_text.split("\n")
            for i, line in enumerate(lines):
                if re.search(pattern, line, re.IGNORECASE):
                    # Check same line
                    after_label = re.split(pattern, line, flags=re.IGNORECASE)[-1].strip()
                    if after_label and len(after_label) > 2:
                        return after_label

                    # Get lines after
                    data_lines = []
                    for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
                        if lines[j].strip():
                            data_lines.append(lines[j].strip())

                    if data_lines:
                        return self._format_extracted_value(data_lines, field_type)

        return None

    def _format_extracted_value(self, lines: list[str], field_type: str) -> str:
        """Format extracted lines based on field type."""
        if field_type == "address":
            # For addresses, join with comma
            return ", ".join(lines)
        elif field_type == "single":
            # Return just the first line
            return lines[0] if lines else ""
        else:
            # Default: join with newlines
            return "\n".join(lines)

    def get_adjacent_block(
        self, structure: DocumentStructure, label_pattern: str, direction: str = "below"
    ) -> Optional[DocumentBlock]:
        """
        Get the block adjacent to a labeled block in the specified direction.

        Args:
            structure: Parsed document structure
            label_pattern: Pattern to find the reference block
            direction: 'below', 'above', 'right', 'left'

        Returns:
            Adjacent DocumentBlock or None
        """
        ref_block = structure.get_block_by_label(label_pattern)
        if not ref_block:
            return None

        candidates = []
        for block in structure.blocks:
            if block.id == ref_block.id:
                continue

            if direction == "below":
                # Block should be below and horizontally overlapping
                if block.y0 > ref_block.y1 and block.x0 < ref_block.x1 and block.x1 > ref_block.x0:
                    distance = block.y0 - ref_block.y1
                    candidates.append((distance, block))

            elif direction == "above":
                if block.y1 < ref_block.y0 and block.x0 < ref_block.x1 and block.x1 > ref_block.x0:
                    distance = ref_block.y0 - block.y1
                    candidates.append((distance, block))

            elif direction == "right":
                if block.x0 > ref_block.x1 and block.y0 < ref_block.y1 and block.y1 > ref_block.y0:
                    distance = block.x0 - ref_block.x1
                    candidates.append((distance, block))

            elif direction == "left":
                if block.x1 < ref_block.x0 and block.y0 < ref_block.y1 and block.y1 > ref_block.y0:
                    distance = ref_block.x0 - block.x1
                    candidates.append((distance, block))

        # Return the closest block
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        return None


# Singleton instance
_parser = None


def get_spatial_parser() -> SpatialParser:
    """Get or create the spatial parser singleton."""
    global _parser
    if _parser is None:
        _parser = SpatialParser()
    return _parser


def parse_document(pdf_path: str) -> DocumentStructure:
    """Convenience function to parse a document."""
    return get_spatial_parser().parse(pdf_path)
