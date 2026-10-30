from decimal import Decimal
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
        first = self.client.post(f"/api/orders/{order_id}/pay/", {}, format="json")
        second = self.client.post(f"/api/orders/{order_id}/pay/", {}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["receipt_number"], second.data["receipt_number"])
        self.assertEqual(Order.objects.get(pk=order_id).status, "paid")
        receipt = self.client.get(f"/api/orders/{order_id}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn("210.00", receipt.content.decode())

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
