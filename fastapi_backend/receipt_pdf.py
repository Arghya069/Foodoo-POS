"""Thermal (57 mm) PDF receipts for Foodoo POS."""
from datetime import timezone
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

RUPEE_PREFIX = "Rs. "
WIDTH = 57 * mm
LEFT = 3 * mm
RIGHT = WIDTH - 3 * mm
IST = ZoneInfo("Asia/Kolkata")


def _as_amount(paise):
    return f"{int(paise) / 100:.2f}"


def _wrapped(value, max_width, font="Helvetica", font_size=7.5):
    """Wrap text using actual PDF font widths, not character-count guesses."""
    words = str(value or "").split()
    result = []
    current = ""
    for word in words:
        probe = (current + " " + word).strip()
        if current and stringWidth(probe, font, font_size) > max_width:
            result.append(current)
            current = word
        else:
            current = probe
        while stringWidth(current, font, font_size) > max_width and len(current) > 1:
            split = len(current) - 1
            while split > 1 and stringWidth(current[:split], font, font_size) > max_width:
                split -= 1
            result.append(current[:split])
            current = current[split:]
    if current:
        result.append(current)
    return result or [""]


def build_receipt_pdf(restaurant, order):
    """Render a readable 57mm receipt with Item / Qty / Unit / Total columns."""
    rows = []
    for item in order.get("lines", []):
        name_lines = _wrapped(item.get("name", ""), 21 * mm)
        rows.append((item, name_lines))

    address = _wrapped(restaurant.get("address", ""), 48 * mm, font_size=7)
    # Reserve generous space for ALL headers, multi-line item names, taxes and
    # the mandatory footer. A fixed minimum alone can clip longer receipts.
    customer_lines = _wrapped("Customer: " + order.get("customer_name", ""), 49 * mm, font_size=7) if order.get("customer_name") else []
    fixed_mm = (6 + 5 + 4 + 5 + 5 + 4 + 2 + 4.5 + 2 + 2 +
                3 * 4.7 + 2 + 4.7 + 5 + 4 + 5 + 6)
    optional_mm = (len(address) * 3.5 +
                   (4 if restaurant.get("contact_phone") else 0) +
                   (4 if restaurant.get("gstin") else 0) +
                   (4 if (order.get("paid_at") or order.get("created_at")) else 0) +
                   len(customer_lines) * 3.6)
    item_mm = sum(max(1, len(lines)) * 4.2 + 1.5 for _, lines in rows)
    # 8 mm safety buffer to protect the last line on narrow thermal printers.
    height_mm = max(118, fixed_mm + optional_mm + item_mm + 8)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(WIDTH, height_mm * mm), pageCompression=1)
    y = height_mm * mm - 6 * mm

    def centered(text, size=8, bold=False, step=5):
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawCentredString(WIDTH / 2, y, str(text))
        y -= step * mm

    def pair(label, amount, bold=False):
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 8)
        pdf.drawString(LEFT, y, label)
        pdf.drawRightString(RIGHT, y, _as_amount(amount))
        y -= 4.7 * mm

    def rule():
        nonlocal y
        pdf.setLineWidth(.3)
        pdf.line(LEFT, y + 1 * mm, RIGHT, y + 1 * mm)
        y -= 2 * mm

    centered(restaurant.get("name", "Foodoo"), 10.5, True, 5)
    for line in address:
        centered(line, 7, False, 3.5)
    if restaurant.get("contact_phone"):
        centered("Tel: " + str(restaurant["contact_phone"]), 7, False, 4)
    if restaurant.get("gstin"):
        centered("GSTIN: " + str(restaurant["gstin"]), 7, False, 4)

    centered("TAX INVOICE / RECEIPT", 8.5, True, 5)
    centered("TOKEN #" + str(order.get("token_number", "-")), 12, True, 5)
    centered(str(order.get("receipt_number", "")), 7.5, False, 4)
    timestamp = order.get("paid_at") or order.get("created_at")
    if timestamp:
        if isinstance(timestamp, str):
            from datetime import datetime
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        centered(timestamp.astimezone(IST).strftime("%d-%m-%Y %H:%M IST"), 7, False, 4)
    if order.get("customer_name"):
        for line in _wrapped("Customer: " + order["customer_name"], 49 * mm, font_size=7):
            centered(line, 7, False, 3.6)
    rule()

    # Four fixed columns in 57mm paper width.
    # Right-align money columns; keep names within first column.
    x_qty = 29 * mm
    x_unit = 41.5 * mm
    x_total = RIGHT
    pdf.setFont("Helvetica-Bold", 6.9)
    pdf.drawString(LEFT, y, "ITEM")
    pdf.drawRightString(x_qty, y, "QTY")
    pdf.drawRightString(x_unit, y, "UNIT")
    pdf.drawRightString(x_total, y, "TOTAL")
    y -= 4.5 * mm
    rule()

    for item, name_lines in rows:
        item_y = y
        pdf.setFont("Helvetica", 7)
        pdf.drawRightString(x_qty, item_y, str(item["quantity"]))
        pdf.drawRightString(x_unit, item_y, _as_amount(item["unit_price_paise"]))
        pdf.drawRightString(x_total, item_y, _as_amount(item["line_total_paise"]))
        for idx, line in enumerate(name_lines):
            pdf.drawString(LEFT, item_y - idx * 4.2 * mm, line)
        y -= max(1, len(name_lines)) * 4.2 * mm + 1.5 * mm

    rule()
    pair("Subtotal", order["subtotal_paise"])
    pair("CGST", order["cgst_paise"])
    pair("SGST", order["sgst_paise"])
    rule()
    pair("TOTAL", order["total_paise"], True)
    centered("PAID - " + str(order.get("payment_method", "")).upper(), 7, False, 5)
    centered("Powered by foodoo", 7, True, 4)
    # GSTIN and FSSAI are optional: include each only when actually configured.
    # FSSAI sits immediately above the thank-you line as requested.
    license_number = str(restaurant.get("fssai_license_number") or "").strip()
    if license_number:
        centered("FSSAI Lic. No.: " + license_number, 6.8, True, 4.6)
    centered("Thank you!", 8, False, 5)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
