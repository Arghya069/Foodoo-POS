import unittest
from datetime import datetime, timezone

from reportlab.lib.units import mm
from pypdf import PdfReader
from io import BytesIO

from receipt_pdf import build_receipt_pdf
from whatsapp_send import normalize_phone, build_template
from sessions import document_id


class ReceiptTests(unittest.TestCase):
    def test_thermal_columns_fssai_and_totals(self):
        restaurant={"name":"1More","address":"Infocity, Bhubaneswar","fssai_license_number":"12345678901234"}
        order={"status":"paid","receipt_number":"FD-001","token_number":7,
               "paid_at":datetime(2026,11,4,16,0,tzinfo=timezone.utc),
               "payment_method":"upi","customer_name":"Arghya",
               "lines":[{"name":"Chicken Biryani","quantity":2,"unit_price_paise":20000,"line_total_paise":40000},
                        {"name":"Mutton Rogan Josh","quantity":1,"unit_price_paise":30000,"line_total_paise":30000}],
               "subtotal_paise":70000,"cgst_paise":1750,"sgst_paise":1750,"total_paise":73500}
        raw=build_receipt_pdf(restaurant,order)
        reader=PdfReader(BytesIO(raw))
        self.assertEqual(len(reader.pages),1)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width),57*mm,delta=1)
        text=reader.pages[0].extract_text()
        for part in ("ITEM","QTY","UNIT","TOTAL","Chicken Biryani",
                     "Mutton Rogan Josh","FSSAI Lic. No.: 12345678901234",
                     "735.00","TOKEN #7","Thank you!"):
            self.assertIn(part,text)


class WhatsAppTests(unittest.TestCase):
    def test_template_document_and_body_parameters(self):
        config={"template_name":"foodoo_receipt","language":"en_US"}
        payload=build_template("918249672385","abc-media","receipt.pdf",config,["Arghya","735.00"])
        self.assertEqual(payload["template"]["components"][0]["parameters"][0]["document"]["id"],"abc-media")
        self.assertEqual(payload["template"]["components"][1]["parameters"][0]["text"],"Arghya")
        self.assertEqual(normalize_phone("8249672385"),"918249672385")
        with self.assertRaises(ValueError):
            normalize_phone("not a phone")

    def test_session_document_does_not_expose_cookie_token(self):
        self.assertEqual(len(document_id("test-cookie")),64)
        self.assertNotIn("test-cookie",document_id("test-cookie"))


if __name__=="__main__":
    unittest.main()
