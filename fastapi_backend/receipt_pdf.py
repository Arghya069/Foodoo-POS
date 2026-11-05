"""Foodooo 57mm thermal receipts: automatic height and safe page continuation.

A physical receipt has fixed paper width. The PDF is one tall page for normal
orders; extremely long orders continue on another 57mm page to stay inside the
PDF page-size limit. Totals and optional tax identifiers print only at the end.
"""
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

WIDTH=57*mm
LEFT=3*mm
RIGHT=WIDTH-3*mm
IST=ZoneInfo("Asia/Kolkata")
MAX_PAGE_MM=4500


def _as_amount(paise):
    return f"{int(paise)/100:.2f}"


def _wrapped(value,max_width,font="Helvetica",font_size=7.5):
    """Wrap words by their actual PDF font width, splitting very long words."""
    words=str(value or "").split()
    result=[]
    current=""
    for word in words:
        probe=(current+" "+word).strip()
        if current and stringWidth(probe,font,font_size)>max_width:
            result.append(current)
            current=word
        else:
            current=probe
        while stringWidth(current,font,font_size)>max_width and len(current)>1:
            split=len(current)-1
            while split>1 and stringWidth(current[:split],font,font_size)>max_width:
                split-=1
            result.append(current[:split])
            current=current[split:]
    if current:
        result.append(current)
    return result or [""]


def _receipt_time(value):
    if not value:
        return None
    if isinstance(value,str):
        value=datetime.fromisoformat(value.replace("Z","+00:00"))
    if value.tzinfo is None:
        value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).strftime("%d-%m-%Y %H:%M IST")


def build_receipt_pdf(restaurant,order):
    """Build a 57mm PDF without cutting off rows or the final footer."""
    rows=[(line,_wrapped(line.get("name",""),21*mm,font_size=7))
          for line in order.get("lines",[])]
    name_lines=_wrapped(restaurant.get("name") or "Foodooo",49*mm,font="Helvetica-Bold",font_size=10.5)
    address_lines=(_wrapped(restaurant.get("address"),48*mm,font_size=7)
                   if str(restaurant.get("address") or "").strip() else [])
    phone_lines=(_wrapped("Tel: "+str(restaurant["contact_phone"]).strip(),49*mm,font_size=7)
                 if str(restaurant.get("contact_phone") or "").strip() else [])
    gstin_lines=(_wrapped("GSTIN: "+str(restaurant["gstin"]).strip(),49*mm,font_size=7)
                 if str(restaurant.get("gstin") or "").strip() else [])
    customer_lines=(_wrapped("Customer: "+str(order["customer_name"]),49*mm,font_size=7)
                    if order.get("customer_name") else [])
    license_number=str(restaurant.get("fssai_license_number") or "").strip()
    date_text=_receipt_time(order.get("paid_at") or order.get("created_at"))

    # The measurements here mirror the exact pen movements in render_page.
    header_mm=(len(name_lines)*5+len(address_lines)*3.5+
               (len(phone_lines)+len(gstin_lines))*4+
               5+5+4+(4 if date_text else 0)+
               len(customer_lines)*3.6+2+4.5+2)
    footer_mm=(2+3*4.7+2+4.7+5+4+(4.6 if license_number else 0)+5)
    overflow_text_mm=5
    row_heights=[max(1,len(parts))*4.2+1.5 for _,parts in rows]
    groups=[]
    current=[]
    current_height=0
    for entry,row_height in zip(rows,row_heights):
        # Reserve both the final footer and a continuation label, so any
        # page may safely be selected as the last one.
        would_fit=(6+header_mm+overflow_text_mm+current_height+
                   row_height+footer_mm+8)<=MAX_PAGE_MM
        if current and not would_fit:
            groups.append(current)
            current=[]
            current_height=0
        if (6+header_mm+overflow_text_mm+row_height+footer_mm+8)>MAX_PAGE_MM:
            raise ValueError("One receipt item is too long to fit on a PDF page")
        current.append(entry)
        current_height+=row_height
    groups.append(current)

    stream=BytesIO()
    pdf=canvas.Canvas(stream,pagesize=(WIDTH,118*mm),pageCompression=1)
    for index,group in enumerate(groups):
        continued=index>0
        last=index==len(groups)-1
        item_height=sum(max(1,len(parts))*4.2+1.5 for _,parts in group)
        height_mm=(6+header_mm+(overflow_text_mm if continued else 0)+
                   item_height+(footer_mm if last else 5)+8)
        height_mm=max(90,height_mm)
        if height_mm>MAX_PAGE_MM:
            raise ValueError("Receipt page height exceeds PDF limit")
        pdf.setPageSize((WIDTH,height_mm*mm))
        y=height_mm*mm-6*mm

        def centered(text,size=8,bold=False,step=5):
            nonlocal y
            pdf.setFont("Helvetica-Bold" if bold else "Helvetica",size)
            pdf.drawCentredString(WIDTH/2,y,str(text))
            y-=step*mm

        def rule():
            nonlocal y
            pdf.setLineWidth(.3)
            pdf.line(LEFT,y+1*mm,RIGHT,y+1*mm)
            y-=2*mm

        def pair(label,amount,bold=False):
            nonlocal y
            pdf.setFont("Helvetica-Bold" if bold else "Helvetica",8)
            pdf.drawString(LEFT,y,label)
            pdf.drawRightString(RIGHT,y,_as_amount(amount))
            y-=4.7*mm

        for name in name_lines:
            centered(name,10.5,True,5)
        for line in address_lines:
            centered(line,7,False,3.5)
        for line in phone_lines+gstin_lines:
            centered(line,7,False,4)
        centered("TAX INVOICE / RECEIPT",8.5,True,5)
        centered("TOKEN #"+str(order.get("token_number","-")),12,True,5)
        centered(str(order.get("receipt_number","")),7.5,False,4)
        if date_text:
            centered(date_text,7,False,4)
        for line in customer_lines:
            centered(line,7,False,3.6)
        if continued:
            centered("CONTINUED - PAGE "+str(index+1),7,True,overflow_text_mm)
        rule()

        x_qty=29*mm
        x_unit=41.5*mm
        x_total=RIGHT
        pdf.setFont("Helvetica-Bold",6.9)
        pdf.drawString(LEFT,y,"ITEM")
        pdf.drawRightString(x_qty,y,"QTY")
        pdf.drawRightString(x_unit,y,"UNIT")
        pdf.drawRightString(x_total,y,"TOTAL")
        y-=4.5*mm
        rule()
        for line,name_parts in group:
            row_y=y
            pdf.setFont("Helvetica",7)
            pdf.drawRightString(x_qty,row_y,str(line["quantity"]))
            pdf.drawRightString(x_unit,row_y,_as_amount(line["unit_price_paise"]))
            pdf.drawRightString(x_total,row_y,_as_amount(line["line_total_paise"]))
            for n,name in enumerate(name_parts):
                pdf.drawString(LEFT,row_y-n*4.2*mm,name)
            y-=max(1,len(name_parts))*4.2*mm+1.5*mm

        if not last:
            centered("Continued on next page",7,False,5)
        else:
            rule()
            pair("Subtotal",order["subtotal_paise"])
            pair("CGST",order["cgst_paise"])
            pair("SGST",order["sgst_paise"])
            rule()
            pair("TOTAL",order["total_paise"],True)
            centered("PAID - "+str(order.get("payment_method","")).upper(),7,False,5)
            centered("Powered by foodooo",7,True,4)
            if license_number:
                centered("FSSAI Lic. No.: "+license_number,6.8,True,4.6)
            centered("Thank you!",8,False,5)
        pdf.showPage()
    pdf.save()
    return stream.getvalue()
