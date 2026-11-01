import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator,MaxValueValidator
class Restaurant(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
 name=models.CharField(max_length=200)
 branch_code=models.SlugField(max_length=48,default="main")
 branch_name=models.CharField(max_length=120,default="Main")
 branch_type=models.CharField(max_length=12,choices=[("main","Main"),("branch","Branch")],default="main")
 address=models.TextField(blank=True)
 contact_phone=models.CharField(max_length=25,blank=True)
 gstin=models.CharField(max_length=15,blank=True)
 logo_data=models.TextField(blank=True)
 cgst_rate=models.DecimalField(max_digits=5,decimal_places=2,default=Decimal("2.50"),validators=[MinValueValidator(0),MaxValueValidator(100)])
 sgst_rate=models.DecimalField(max_digits=5,decimal_places=2,default=Decimal("2.50"),validators=[MinValueValidator(0),MaxValueValidator(100)])
class Membership(models.Model):
 user=models.OneToOneField(User,on_delete=models.CASCADE,related_name="pos_membership")
 restaurant=models.ForeignKey(Restaurant,on_delete=models.PROTECT)
 role=models.CharField(max_length=10,choices=[("admin","Admin"),("staff","Cashier (legacy)"),("cashier","Cashier"),("chef","Chef"),("partner","Partner / guest")])
class MenuItem(models.Model):
 restaurant=models.ForeignKey(Restaurant,on_delete=models.PROTECT)
 name=models.CharField(max_length=160)
 food_type=models.CharField(max_length=20,choices=[("veg","Veg"),("non_veg","Non Veg")],default="veg")
 food_subtype=models.CharField(max_length=20,choices=[("none","None"),("egg","Egg"),("chicken","Chicken"),("mutton","Mutton"),("fish","Fish"),("paneer","Paneer"),("mushroom","Mushroom"),("other","Other")],default="none")
 image_data=models.TextField(blank=True)
 category=models.CharField(max_length=24,choices=[("snack","Snack"),("beverage","Beverage"),("combo","Combo"),("main_course","Main Course"),("starter","Starter"),("dessert","Dessert"),("breakfast","Breakfast"),("other","Other")],default="main_course")
 description=models.TextField(blank=True)
 image_url=models.URLField(max_length=1000,blank=True)
 price=models.DecimalField(max_digits=12,decimal_places=2,validators=[MinValueValidator(Decimal("0"))])
 active=models.BooleanField(default=True)
class DailyTokenCounter(models.Model):
 restaurant=models.ForeignKey(Restaurant,on_delete=models.PROTECT)
 service_date=models.DateField()
 last_number=models.PositiveIntegerField(default=0)
 serving_number=models.PositiveIntegerField(default=0)
 class Meta:
  constraints=[models.UniqueConstraint(fields=["restaurant","service_date"],name="unique_daily_token_counter")]

class Order(models.Model):
 restaurant=models.ForeignKey(Restaurant,on_delete=models.PROTECT)
 created_by=models.ForeignKey(User,on_delete=models.PROTECT)
 customer_name=models.CharField(max_length=160,blank=True)
 customer_phone=models.CharField(max_length=20,blank=True)
 status=models.CharField(max_length=10,choices=[("draft","Draft"),("paid","Paid")],default="draft")
 payment_method=models.CharField(max_length=10,choices=[("cash","Cash"),("card","Card"),("upi","UPI")],blank=True)
 whatsapp_consent=models.BooleanField(default=False)
 subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
 cgst_rate=models.DecimalField(max_digits=5,decimal_places=2,default=0)
 sgst_rate=models.DecimalField(max_digits=5,decimal_places=2,default=0)
 cgst_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
 sgst_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
 total=models.DecimalField(max_digits=12,decimal_places=2,default=0)
 token_date=models.DateField(null=True,blank=True)
 token_number=models.PositiveIntegerField(null=True,blank=True)
 receipt_number=models.CharField(max_length=40,unique=True,null=True,blank=True)
 paid_at=models.DateTimeField(null=True,blank=True)
 created_at=models.DateTimeField(auto_now_add=True)
 class Meta:
  constraints=[models.UniqueConstraint(fields=["restaurant","token_date","token_number"],name="unique_restaurant_daily_order_token")]
class OrderLine(models.Model):
 order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name="lines")
 menu_item=models.ForeignKey(MenuItem,on_delete=models.PROTECT)
 name_snapshot=models.CharField(max_length=160)
 unit_price=models.DecimalField(max_digits=12,decimal_places=2)
 quantity=models.PositiveIntegerField()
 line_total=models.DecimalField(max_digits=12,decimal_places=2)
