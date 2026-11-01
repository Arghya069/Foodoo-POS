from decimal import Decimal
from io import BytesIO
from pypdf import PdfReader
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Membership, MenuItem, Order, Restaurant

class PosFlowTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="First Restaurant", cgst_rate=Decimal("2.50"), sgst_rate=Decimal("2.50"))
        self.other = Restaurant.objects.create(name="Other Restaurant")
        self.admin = User.objects.create_user("owner", password="test-password")
        self.staff = User.objects.create_user("cashier", password="test-password")
        self.outsider = User.objects.create_user("other-cashier", password="test-password")
        Membership.objects.create(user=self.admin, restaurant=self.restaurant, role="admin")
        Membership.objects.create(user=self.staff, restaurant=self.restaurant, role="staff")
        Membership.objects.create(user=self.outsider, restaurant=self.other, role="staff")
        self.item = MenuItem.objects.create(restaurant=self.restaurant, name="Thali", price=Decimal("200.00"))
        self.client = APIClient()

    def login(self, user):
        self.client.force_authenticate(user=user)

    def create_order(self):
        return self.client.post("/api/orders/", {"items": [{"id": self.item.id, "quantity": 1}], "customer_name": "Guest", "customer_phone": "9999999999"}, format="json")

    def test_admin_can_configure_tax_and_staff_cannot(self):
        self.login(self.staff)
        self.assertEqual(self.client.patch("/api/restaurant/", {"cgst_rate": "9.00"}, format="json").status_code, 403)
        self.login(self.admin)
        response = self.client.patch("/api/restaurant/", {"cgst_rate": "3.00", "sgst_rate": "3.00"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.cgst_rate, Decimal("3.00"))

    def test_staff_cannot_add_menu_items(self):
        self.login(self.staff)
        response = self.client.post("/api/menu/", {"name": "Extra", "price": "20.00"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_order_tax_paid_receipt_and_idempotent_payment(self):
        self.login(self.staff)
        response = self.create_order()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["subtotal"]), Decimal("200.00"))
        self.assertEqual(Decimal(response.data["cgst"]), Decimal("5.00"))
        self.assertEqual(Decimal(response.data["sgst"]), Decimal("5.00"))
        self.assertEqual(Decimal(response.data["total"]), Decimal("210.00"))
        order_id = response.data["id"]
        self.assertEqual(self.client.get(f"/api/orders/{order_id}/receipt/").status_code, 404)
        first = self.client.post(f"/api/orders/{order_id}/pay/", {"payment_method":"cash"}, format="json")
        second = self.client.post(f"/api/orders/{order_id}/pay/", {}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["receipt_number"], second.data["receipt_number"])
        self.assertEqual(Order.objects.get(pk=order_id).status, "paid")
        receipt = self.client.get(f"/api/orders/{order_id}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt["Content-Type"], "application/pdf")
        pdf_bytes=b"".join(receipt.streaming_content)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        pdf=PdfReader(BytesIO(pdf_bytes))
        self.assertAlmostEqual(float(pdf.pages[0].mediabox.width), 57*72/25.4, delta=0.1)
        self.assertIn("Powered by foodoo", pdf.pages[0].extract_text())

    def test_cannot_order_item_from_another_restaurant(self):
        self.login(self.outsider)
        response = self.create_order()
        self.assertEqual(response.status_code, 400)

    def test_cannot_view_other_restaurant_receipt(self):
        self.login(self.staff)
        order_id = self.create_order().data["id"]
        self.client.post(f"/api/orders/{order_id}/pay/", {}, format="json")
        self.login(self.outsider)
        self.assertEqual(self.client.get(f"/api/orders/{order_id}/receipt/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/orders/{order_id}/pay/", {}, format="json").status_code, 404)

    def test_server_uses_menu_price_not_client_price(self):
        self.login(self.staff)
        response = self.client.post("/api/orders/", {"items": [{"id": self.item.id, "quantity": 1, "price": "0.01"}]}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data["subtotal"]), Decimal("200.00"))

    def test_menu_description_image_and_tenant_scoped_edit(self):
        self.login(self.admin)
        created = self.client.post("/api/menu/", {"name": "Paneer Roll", "price": "80.00", "description": "Fresh paneer in a wrap", "image_url": "https://example.com/roll.jpg"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        item_id = created.data["id"]
        self.assertEqual(created.data["description"], "Fresh paneer in a wrap")
        self.assertEqual(created.data["image_url"], "https://example.com/roll.jpg")
        self.assertEqual(self.client.patch(f"/api/menu/{item_id}/", {"price": "85.00"}, format="json").status_code, 200)
        self.login(self.outsider)
        self.assertEqual(self.client.patch(f"/api/menu/{item_id}/", {"price": "1.00"}, format="json").status_code, 403)
        self.assertNotIn(item_id, [i["id"] for i in self.client.get("/api/menu/").data])

    def test_menu_classification(self):
        self.login(self.admin)
        created = self.client.post("/api/menu/", {"name":"Paneer Tikka", "price":"190.00","food_type":"veg","food_subtype":"paneer","category":"starter"},format="json")
        self.assertEqual(created.status_code,201,created.data)
        self.assertEqual(created.data["food_type"],"veg")
        self.assertEqual(created.data["food_subtype"],"paneer")
        self.assertEqual(created.data["category"],"starter")
        invalid = self.client.post("/api/menu/", {"name":"Invalid","price":"100.00","food_type":"unknown"},format="json")
        self.assertEqual(invalid.status_code,400)

    def test_restaurant_logo_setting_is_admin_only(self):
        self.login(self.staff)
        self.assertEqual(self.client.patch("/api/restaurant/",{"logo_data":"data:image/png;base64,YWJj"},format="json").status_code,403)
        self.login(self.admin)
        self.assertEqual(self.client.patch("/api/restaurant/",{"logo_data":"data:image/png;base64,YWJj"},format="json").status_code,200)
        self.assertEqual(self.client.get("/api/restaurant/").data["logo_data"],"data:image/png;base64,YWJj")

    def test_payment_method_required_and_customer_lookup_tenant_scoped(self):
        self.login(self.staff)
        order_id=self.create_order().data["id"]
        self.assertEqual(self.client.post(f"/api/orders/{order_id}/pay/", {},format="json").status_code,400)
        paid=self.client.post(f"/api/orders/{order_id}/pay/",{"payment_method":"upi"},format="json")
        self.assertEqual(paid.status_code,200)
        self.assertEqual(paid.data["payment_method"],"upi")
        self.assertEqual(self.client.get("/api/customers/lookup/?phone=9999999999").data["customer_name"],"Guest")
        self.login(self.outsider)
        self.assertEqual(self.client.get("/api/customers/lookup/?phone=9999999999").data["customer_name"],"")

    def test_whatsapp_consent_is_saved_but_not_sent(self):
        self.login(self.staff)
        response=self.client.post("/api/orders/",{"items":[{"id":self.item.id,"quantity":1}],"customer_phone":"9999999999","whatsapp_consent":True},format="json")
        self.assertEqual(response.status_code,201)
        self.assertTrue(Order.objects.get(pk=response.data["id"]).whatsapp_consent)

    def test_menu_subtype_consistency(self):
        self.login(self.admin)
        bad=self.client.post("/api/menu/",{"name":"Fish curry","price":"100.00","food_type":"veg","food_subtype":"fish"},format="json")
        self.assertEqual(bad.status_code,400)
        good=self.client.post("/api/menu/",{"name":"Fish curry","price":"100.00","food_type":"non_veg","food_subtype":"fish"},format="json")
        self.assertEqual(good.status_code,201,good.data)

    def test_image_upload_saved_and_returned_for_cashier(self):
        import base64
        self.login(self.admin)
        sample="data:image/png;base64,"+base64.b64encode(b"sample-photo").decode()
        response=self.client.post("/api/menu/",{"name":"Biryani","price":"200.00","image_data":sample},format="json")
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data["image_data"],sample)
        self.login(self.staff)
        items=self.client.get("/api/menu/").data
        self.assertEqual(next(x for x in items if x["name"]=="Biryani")["image_data"],sample)

    def test_phone_suggestions_paid_and_restaurant_scoped(self):
        self.login(self.staff)
        order_id=self.create_order().data["id"]
        self.assertEqual(self.client.get("/api/customers/suggest/?q=999").data,[])
        self.client.post(f"/api/orders/{order_id}/pay/",{"payment_method":"cash"},format="json")
        result=self.client.get("/api/customers/suggest/?q=999").data
        self.assertEqual(result,[{"customer_phone":"9999999999","customer_name":"Guest","whatsapp_consent":False}])
        self.login(self.outsider)
        self.assertEqual(self.client.get("/api/customers/suggest/?q=999").data,[])

class SessionAuthenticationTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user("session-owner",password="secure-password")
        restaurant=Restaurant.objects.create(name="Session Restaurant")
        Membership.objects.create(user=self.user,restaurant=restaurant,role="admin")

    def test_csrf_login_session_and_logout(self):
        from django.test import Client
        import json
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.get("/api/me/").status_code,403)
        self.assertEqual(client.post("/api/auth/login/",data=json.dumps({"username":"session-owner","password":"secure-password"}),content_type="application/json").status_code,403)
        client.get("/api/auth/csrf/")
        token=client.cookies["csrftoken"].value
        invalid=client.post("/api/auth/login/",data=json.dumps({"username":"session-owner","password":"wrong"}),content_type="application/json",HTTP_X_CSRFTOKEN=token)
        self.assertEqual(invalid.status_code,401)
        response=client.post("/api/auth/login/",data=json.dumps({"username":"session-owner","password":"secure-password"}),content_type="application/json",HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)
        self.assertIn("sessionid",client.cookies)
        self.assertEqual(client.get("/api/me/").status_code,200)
        csrf=client.cookies["csrftoken"].value
        self.assertEqual(client.post("/api/auth/logout/",content_type="application/json",HTTP_X_CSRFTOKEN=csrf).status_code,200)
        self.assertEqual(client.get("/api/me/").status_code,403)

class OrderHistoryReportTests(TestCase):
    def setUp(self):
        self.restaurant=Restaurant.objects.create(name="Sales Restaurant")
        self.other=Restaurant.objects.create(name="Other Sales")
        self.owner=User.objects.create_user("sales-owner",password="pass")
        self.cashier=User.objects.create_user("sales-staff",password="pass")
        self.outsider=User.objects.create_user("other-staff",password="pass")
        Membership.objects.create(user=self.owner,restaurant=self.restaurant,role="admin")
        Membership.objects.create(user=self.cashier,restaurant=self.restaurant,role="staff")
        Membership.objects.create(user=self.outsider,restaurant=self.other,role="staff")
        self.menu_item=MenuItem.objects.create(restaurant=self.restaurant,name="Biryani",price=Decimal("100.00"))
        self.client=APIClient()
        self.client.force_authenticate(user=self.cashier)
        data=self.client.post("/api/orders/",{"items":[{"id":self.menu_item.id,"quantity":2}],"customer_name":"Customer A","customer_phone":"9898988787"},format="json").data
        self.order_id=data["id"]
        self.client.post(f"/api/orders/{self.order_id}/pay/",{"payment_method":"upi"},format="json")

    def test_history_includes_snapshots_and_is_tenant_scoped(self):
        response=self.client.get("/api/orders/history/")
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data["count"],1)
        row=response.data["results"][0]
        self.assertEqual(row["items"][0]["name"],"Biryani")
        self.assertEqual(row["payment_method"],"upi")
        self.assertEqual(self.client.get("/api/orders/history/?q=nonexistent").data["count"],0)
        self.client.force_authenticate(user=self.outsider)
        self.assertEqual(self.client.get("/api/orders/history/").data["count"],0)

    def test_reports_only_for_admin_and_only_paid_tenant_orders(self):
        self.assertEqual(self.client.get("/api/reports/sales/").status_code,403)
        self.client.force_authenticate(user=self.owner)
        report=self.client.get("/api/reports/sales/")
        self.assertEqual(report.status_code,200,report.data)
        self.assertEqual(report.data["orders"],1)
        self.assertEqual(Decimal(report.data["subtotal"]),Decimal("200.00"))
        self.assertEqual(report.data["payment_methods"][0]["method"],"upi")
        self.assertEqual(self.client.get("/api/reports/sales/?start=2026-11-30&end=2026-11-01").status_code,400)

    def test_admin_archive_restore_and_staff_visibility(self):
        self.client.force_authenticate(user=self.owner)
        archive=self.client.patch(f"/api/menu/{self.menu_item.id}/",{"active":False},format="json")
        self.assertEqual(archive.status_code,200,archive.data)
        self.assertFalse(archive.data["active"])
        self.assertIn(self.menu_item.id,[x["id"] for x in self.client.get("/api/menu/").data])
        self.client.force_authenticate(user=self.cashier)
        self.assertNotIn(self.menu_item.id,[x["id"] for x in self.client.get("/api/menu/").data])
        denied=self.client.post("/api/orders/",{"items":[{"id":self.menu_item.id,"quantity":1}]},format="json")
        self.assertEqual(denied.status_code,400)
        self.client.force_authenticate(user=self.owner)
        restored=self.client.patch(f"/api/menu/{self.menu_item.id}/",{"active":True},format="json")
        self.assertEqual(restored.status_code,200,restored.data)
        self.assertTrue(restored.data["active"])
        self.client.force_authenticate(user=self.cashier)
        self.assertIn(self.menu_item.id,[x["id"] for x in self.client.get("/api/menu/").data])

    def test_history_filters_and_report_date_boundaries(self):
        self.client.force_authenticate(user=self.cashier)
        self.assertEqual(self.client.get("/api/orders/history/?status=draft").data["count"],0)
        self.assertEqual(self.client.get("/api/orders/history/?status=paid").data["count"],1)
        self.assertEqual(self.client.get("/api/orders/history/?q=Customer%20A").data["count"],1)
        self.assertEqual(self.client.get("/api/orders/history/?page=abc").status_code,400)
        self.assertEqual(self.client.get("/api/orders/history/?start=2026-12-30&end=2026-11-01").status_code,400)
        self.client.force_authenticate(user=self.owner)
        response=self.client.get("/api/reports/sales/?start=2000-01-01&end=2000-01-02")
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data["orders"],0)
        self.assertEqual(Decimal(response.data["revenue"]),Decimal("0"))

    def test_sales_exports_are_admin_only_tenant_scoped_and_valid(self):
        import csv
        from openpyxl import load_workbook
        from io import BytesIO, StringIO
        self.assertEqual(self.client.get("/api/reports/sales/export/?format=csv").status_code,403)
        self.client.force_authenticate(user=self.owner)
        csv_response=self.client.get("/api/reports/sales/export/?format=csv")
        self.assertEqual(csv_response.status_code,200)
        self.assertIn("text/csv",csv_response["Content-Type"])
        records=list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
        self.assertEqual(len(records),2)
        self.assertEqual(records[1][4],"upi")
        self.assertEqual(records[1][8],"210.00")
        xlsx=self.client.get("/api/reports/sales/export/?format=xlsx")
        self.assertEqual(xlsx.status_code,200)
        sheet=load_workbook(BytesIO(xlsx.content),read_only=True).active
        self.assertEqual(sheet.max_row,2)
        self.assertEqual(sheet["E2"].value,"upi")
        self.client.force_authenticate(user=self.outsider)
        self.assertEqual(len(list(csv.reader(StringIO(self.client.get("/api/reports/sales/export/?format=csv").content.decode("utf-8-sig"))))),1)
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.get("/api/reports/sales/export/?format=pdf").status_code,400)
