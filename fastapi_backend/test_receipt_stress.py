"""Stress tests for variable-length 57mm thermal receipt PDFs."""
from datetime import datetime, timezone
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm

from receipt_pdf import build_receipt_pdf


def make_order(count, long_names=False):
    lines=[]
    for i in range(count):
        name=(f"Order item {i:04d} " +
              ("Super long speciality tandoori chicken platter with biryani rice and extras " * 2
               if long_names else ""))
        lines.append({"name":name.strip(),"quantity":1,
                      "unit_price_paise":10000,"line_total_paise":10000})
    return {
        "status":"paid", "receipt_number":"FD-STRESS-001", "token_number":982,
        "customer_name":"Stress Test Customer",
        "paid_at":datetime(2026,11,5,12,30,tzinfo=timezone.utc),
        "payment_method":"upi","lines":lines,
        "subtotal_paise":count*10000,
        "cgst_paise":0,"sgst_paise":0,"total_paise":count*10000
    }


@pytest.mark.parametrize("count,long_names",[(1,False),(30,False),(100,False),
                                              (250,False),(400,False),
                                              (50,True),(100,True)])
def test_all_items_and_footer_fit_without_height_clipping(count,long_names):
    restaurant={"name":"1More","address":"Infocity, Bhubaneswar",
                "gstin":"22AAAAA0000A1Z5","fssai_license_number":"12345678901234"}
    raw=build_receipt_pdf(restaurant,make_order(count,long_names))
    reader=PdfReader(BytesIO(raw))
    assert len(reader.pages)==1
    page=reader.pages[0]
    assert abs(float(page.mediabox.width)-57*mm)<1
    assert float(page.mediabox.height)>118*mm
    content=page.extract_text()
    for i in range(count):
        assert f"Order item {i:04d}" in content
    assert "FSSAI Lic. No.: 12345678901234" in content
    assert "GSTIN: 22AAAAA0000A1Z5" in content
    assert content.index("FSSAI Lic. No.: 12345678901234")<content.index("Thank you!")
    # ReportLab sets line origins using PDF's bottom-up coordinates. Confirm
    # the final baseline stays well above the physical printable bottom.
    assert float(page.mediabox.height)>=count*4.2*mm


def test_height_grows_with_more_items():
    profile={"name":"1More","fssai_license_number":""}
    small=PdfReader(BytesIO(build_receipt_pdf(profile,make_order(2)))).pages[0]
    big=PdfReader(BytesIO(build_receipt_pdf(profile,make_order(50)))).pages[0]
    assert float(big.mediabox.height)>float(small.mediabox.height)+200*mm
    assert "FSSAI" not in small.extract_text()


def test_extreme_order_continues_without_cutting_items_or_duplicating_totals():
    # Larger than a PDF single-page height. The receipt must continue instead
    # of dropping lines or silently truncating the PDF.
    restaurant={"name":"1More","fssai_license_number":"12345678901234"}
    count=1000
    reader=PdfReader(BytesIO(build_receipt_pdf(restaurant,make_order(count))))
    assert len(reader.pages)>=2
    all_text="\n".join(page.extract_text() for page in reader.pages)
    for i in range(count):
        assert f"Order item {i:04d}" in all_text
    assert all_text.count("Thank you!")==1
    assert all_text.count("FSSAI Lic. No.: 12345678901234")==1
    assert "Continued on next page" in all_text
    for page in reader.pages:
        assert abs(float(page.mediabox.width)-57*mm)<1
        assert float(page.mediabox.height)<14000
