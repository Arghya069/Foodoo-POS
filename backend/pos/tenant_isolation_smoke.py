"""Run only after provisioning and migrating tenant_first and tenant_second."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.db import connections
from pos.models import Restaurant,Membership,MenuItem,Order
from decimal import Decimal

for key,alias in (("first","tenant_first"),("second","tenant_second")):
    user=User.objects.db_manager(alias).create_user(username="cashier",password="ci-tenant-password")
    restaurant=Restaurant.objects.using(alias).create(name="Tenant "+key)
    Membership.objects.using(alias).create(user_id=user.pk,restaurant_id=restaurant.pk,role="cashier")
    MenuItem.objects.using(alias).create(restaurant_id=restaurant.pk,name=key+" rice",price=Decimal("80"))
    assert User.objects.using(alias).count()==1

clients={}
for key in ("first","second"):
    client=Client(HTTP_HOST=f"{key}.example.test")
    csrf=client.get("/api/auth/csrf/")
    assert csrf.status_code==200,(key,csrf.status_code)
    login=client.post("/api/auth/login/",data={"username":"cashier","password":"ci-tenant-password"},content_type="application/json")
    assert login.status_code==200,(key,login.status_code,login.content)
    menu=client.get("/api/menu/")
    assert menu.status_code==200,(key,menu.status_code,menu.content)
    assert len(menu.json())==1
    assert menu.json()[0]["name"]==key+" rice"
    clients[key]=client

first_menu=clients["first"].get("/api/menu/").json()[0]
paid=clients["first"].post("/api/orders/",data={"items":[{"id":first_menu["id"],"quantity":1}]},content_type="application/json")
assert paid.status_code==201,(paid.status_code,paid.content)
assert Order.objects.using("tenant_first").count()==1
assert Order.objects.using("tenant_second").count()==0

unknown=Client(HTTP_HOST="unknown.example.test").get("/api/me/")
assert unknown.status_code==404,unknown.content
assert connections["tenant_first"].settings_dict["NAME"]!=connections["tenant_second"].settings_dict["NAME"]
print("PASS: separate PostgreSQL tenants, sessions, menus and orders; unknown host denied")
