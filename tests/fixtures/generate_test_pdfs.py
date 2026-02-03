"""
Generate valid test PDF fixtures for smoke testing.

Run this script to create test PDFs that simulate auction invoices.
These PDFs are used for integration testing of the extraction pipeline.

Usage:
    python tests/fixtures/generate_test_pdfs.py
"""

from pathlib import Path

# Try reportlab first, then fpdf2
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    USE_REPORTLAB = True
except ImportError:
    USE_REPORTLAB = False
    try:
        from fpdf import FPDF
    except ImportError:
        print("ERROR: Neither reportlab nor fpdf2 is installed.")
        print("Install with: pip install reportlab  OR  pip install fpdf2")
        exit(1)

FIXTURES_DIR = Path(__file__).parent


def create_pdf_reportlab(filepath: str, lines: list[str], title: str = "Test Document"):
    """Create a PDF using reportlab."""
    c = canvas.Canvas(filepath, pagesize=letter)
    width, height = letter

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, title)

    # Content
    c.setFont("Helvetica", 11)
    y_position = height - 110

    for line in lines:
        if y_position < 72:
            c.showPage()
            c.setFont("Helvetica", 11)
            y_position = height - 72
        c.drawString(72, y_position, line)
        y_position -= 16

    c.save()


def create_pdf_fpdf(filepath: str, lines: list[str], title: str = "Test Document"):
    """Create a PDF using fpdf2."""
    pdf = FPDF()
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=True)
    pdf.ln(5)

    # Content
    pdf.set_font("Helvetica", "", 11)
    for line in lines:
        pdf.cell(0, 8, line, ln=True)

    pdf.output(filepath)


def create_pdf(filepath: str, lines: list[str], title: str = "Test Document"):
    """Create a PDF using the available library."""
    if USE_REPORTLAB:
        create_pdf_reportlab(filepath, lines, title)
    else:
        create_pdf_fpdf(filepath, lines, title)


def generate_iaa_invoice():
    """Generate a sample IAA auction invoice PDF."""
    lines = [
        "Insurance Auto Auctions, Inc.",
        "BUYER RECEIPT",
        "",
        "IAAI Branch: Tampa South",
        "Branch Phone: (813) 555-1234",
        "",
        "Date: 01/15/2024",
        "Stock Number: 34567890",
        "",
        "VEHICLE INFORMATION",
        "VIN: 1HGBH41JXMN109186",
        "Year: 2021",
        "Make: HONDA",
        "Model: CIVIC",
        "Color: SILVER",
        "Odometer: 45,678 Miles",
        "",
        "BUYER INFORMATION",
        "Buyer ID: ABC12345",
        "Buyer Name: TEST TRANSPORT LLC",
        "",
        "PICK-UP LOCATION",
        "Name: Tampa South IAA",
        "Address: 1234 Auction Way",
        "City: Tampa",
        "State: FL",
        "ZIP: 33619",
        "Phone: (813) 555-4567",
        "",
        "SALE INFORMATION",
        "Sale Date: 01/15/2024",
        "Sale Price: $8,500.00",
        "Buyer Fee: $425.00",
        "Total Amount Due: $8,925.00",
        "",
        "Thank you for your business!",
        "Visit iaai.com for more information.",
    ]

    filepath = FIXTURES_DIR / "sample_iaa_invoice.pdf"
    create_pdf(str(filepath), lines, "Insurance Auto Auctions - Buyer Receipt")
    print(f"Created: {filepath}")


def generate_copart_invoice():
    """Generate a sample Copart auction invoice PDF."""
    lines = [
        "Copart",
        "Sales Receipt/Bill of Sale",
        "",
        "SOLD THROUGH COPART",
        "",
        "MEMBER: 87654321",
        "Member Name: TEST BUYERS INC",
        "",
        "Date: 01/16/2024",
        "LOT# 45678901",
        "",
        "VEHICLE DETAILS",
        "VIN: 5YFBURHE8LP123456",
        "Year: 2020",
        "Make: TOYOTA",
        "Model: COROLLA",
        "Color: WHITE",
        "Odometer: 32,150 Miles",
        "Title State: TX",
        "",
        "PHYSICAL ADDRESS OF LOT",
        "Copart - Houston",
        "5678 Industrial Blvd",
        "Houston, TX 77001",
        "Phone: (281) 555-7890",
        "",
        "FINANCIAL SUMMARY",
        "High Bid: $6,200.00",
        "Buyer Premium: $620.00",
        "Gate Fee: $79.00",
        "Total: $6,899.00",
        "",
        "Thank you for using Copart!",
        "Visit copart.com for details.",
    ]

    filepath = FIXTURES_DIR / "sample_copart_invoice.pdf"
    create_pdf(str(filepath), lines, "Copart - Sales Receipt")
    print(f"Created: {filepath}")


def generate_manheim_invoice():
    """Generate a sample Manheim auction invoice PDF."""
    lines = [
        "Manheim Auto Auction",
        "Cox Automotive",
        "BILL OF SALE",
        "",
        "VEHICLE RELEASE",
        "Release ID: MAN2024011700123",
        "",
        "Sale Date: 01/17/2024",
        "Lane: 5",
        "Run: 42",
        "",
        "YMMT: 2019 FORD F-150",
        "",
        "VEHICLE INFORMATION",
        "VIN: 1FTEW1E50KFA12345",
        "Year: 2019",
        "Make: FORD",
        "Model: F-150 XLT",
        "Color: BLUE",
        "Mileage: 58,432",
        "Engine: 3.5L V6 ECOBOOST",
        "",
        "BUYER INFORMATION",
        "Dealer: QUALITY AUTO SALES",
        "Dealer ID: DLR789456",
        "",
        "PICKUP LOCATION",
        "Manheim Dallas",
        "9001 Auction Lane",
        "Dallas, TX 75234",
        "Contact: (972) 555-3456",
        "",
        "TRANSACTION",
        "Hammer Price: $24,500.00",
        "Buy Fee: $350.00",
        "Total Due: $24,850.00",
        "",
        "Visit Manheim.com for more information.",
    ]

    filepath = FIXTURES_DIR / "sample_manheim_invoice.pdf"
    create_pdf(str(filepath), lines, "Manheim - Bill of Sale")
    print(f"Created: {filepath}")


def generate_minimal_pdf():
    """Generate a minimal valid PDF for basic validation tests."""
    lines = [
        "Test Document",
        "",
        "This is a minimal valid PDF file.",
        "It contains basic text content.",
        "",
        "Generated for testing purposes.",
    ]

    filepath = FIXTURES_DIR / "minimal_valid.pdf"
    create_pdf(str(filepath), lines, "Minimal Test PDF")
    print(f"Created: {filepath}")


def main():
    """Generate all test PDF fixtures."""
    print("Generating test PDF fixtures...")
    print(f"Using: {'reportlab' if USE_REPORTLAB else 'fpdf2'}")
    print(f"Output directory: {FIXTURES_DIR}")
    print()

    generate_iaa_invoice()
    generate_copart_invoice()
    generate_manheim_invoice()
    generate_minimal_pdf()

    print()
    print("Done! Test PDFs generated successfully.")


if __name__ == "__main__":
    main()
