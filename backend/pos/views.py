from decimal import Decimal,ROUND_HALF_UP
import uuid
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework.decorators import api_view,permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Restaurant,Membership,MenuItem,Order,OrderLine

def membership(request):
 return Membership.objects.select_related("restaurant").filter(user=request.user).first()
def money(v): return Decimal(v).quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
def no_member():return Response({"detail":"No POS membership"},status=403)
@api_view(["GET"])
def me(request):
 m=membership(request)
 return Response({"role":m.role,"restaurant_id":str(m.restaurant_id),"username":request.user.username} if m else {"detail":"No membership"},status=200 if m else 403)
@api_view(["GET","PATCH"])
def restaurant(request):
 m=membership(request)
 if not m:return no_member()
 r=m.restaurant
 if request.method=="PATCH":
  if m.role!="admin":return Response({"detail":"Admin only"},status=403)
  for k in ("name","address","contact_phone","gstin"):
   if k in request.data:setattr(r,k,str(request.data[k]).strip())
  for k in ("cgst_rate","sgst_rate"):
   if k in request.data:
    try:v=Decimal(str(request.data[k]));assert v.is_finite() and Decimal("0")<=v<=Decimal("100") and v.as_tuple().exponent>=-2
    except (Exception):return Response({k:"Invalid percentage"},status=400)
    setattr(r,k,v)
  r.save()
 return Response({"id":str(r.id),"name":r.name,"address":r.address,"contact_phone":r.contact_phone,"gstin":r.gstin,"cgst_rate":str(r.cgst_rate),"sgst_rate":str(r.sgst_rate)})
@api_view(["GET","POST"])
def menu(request):
 m=membership(request)
 if not m:return no_member()
 if request.method=="POST":
  if m.role!="admin":return Response({"detail":"Admin only"},status=403)
  try:
   price=Decimal(str(request.data.get("price")));assert price.is_finite() and price>=0 and price.as_tuple().exponent>=-2
   name=str(request.data.get("name","")).strip();assert name
  except (Exception):return Response({"detail":"Invalid name or price"},status=400)
  obj=MenuItem.objects.create(restaurant=m.restaurant,name=name,price=price)
  return Response({"id":obj.pk,"name":obj.name,"price":str(obj.price)},status=201)
 return Response([{"id":o.pk,"name":o.name,"price":str(o.price)} for o in MenuItem.objects.filter(restaurant=m.restaurant,active=True).order_by("name")])
@api_view(["GET","POST"])
def orders(request):
 m=membership(request)
 if not m:return no_member()
 if request.method=="GET":return Response([{"id":o.pk,"status":o.status,"total":str(o.total),"receipt_number":o.receipt_number} for o in Order.objects.filter(restaurant=m.restaurant).order_by("-id")[:50]])
 entries=request.data.get("items",[])
 if not isinstance(entries,list) or not entries:return Response({"items":"At least one item required"},status=400)
 try:
  quantities={}
  for e in entries:
   ident=int(e["id"]);qty=int(e["quantity"]);assert 1<=qty<=999
   quantities[ident]=quantities.get(ident,0)+qty
  items={x.id:x for x in MenuItem.objects.filter(restaurant=m.restaurant,active=True,id__in=quantities)}
  assert len(items)==len(quantities)
 except (ValueError,TypeError,KeyError,AssertionError):return Response({"items":"Invalid or unavailable items"},status=400)
 subtotal=money(sum((items[k].price*v for k,v in quantities.items()),Decimal(0)))
 r=m.restaurant
 cgst=money(subtotal*r.cgst_rate/100);sgst=money(subtotal*r.sgst_rate/100)
 with transaction.atomic():
  o=Order.objects.create(restaurant=r,created_by=request.user,customer_name=str(request.data.get("customer_name",""))[:160],customer_phone=str(request.data.get("customer_phone",""))[:20],subtotal=subtotal,cgst_rate=r.cgst_rate,sgst_rate=r.sgst_rate,cgst_amount=cgst,sgst_amount=sgst,total=subtotal+cgst+sgst)
  OrderLine.objects.bulk_create([OrderLine(order=o,menu_item=items[k],name_snapshot=items[k].name,unit_price=items[k].price,quantity=q,line_total=money(items[k].price*q)) for k,q in quantities.items()])
 return Response({"id":o.pk,"subtotal":str(subtotal),"cgst":str(cgst),"sgst":str(sgst),"total":str(o.total)},status=201)
@api_view(["POST"])
def pay(request,pk):
 m=membership(request)
 if not m:return no_member()
 with transaction.atomic():
  try:o=Order.objects.select_for_update().get(pk=pk,restaurant=m.restaurant)
  except Order.DoesNotExist:return Response({"detail":"Not found"},status=404)
  if o.status=="draft":
   o.status="paid";o.paid_at=timezone.now();o.receipt_number="FD-"+uuid.uuid4().hex[:12].upper();o.save(update_fields=["status","paid_at","receipt_number"])
 return Response({"id":o.pk,"status":o.status,"receipt_number":o.receipt_number,"total":str(o.total)})
@api_view(["GET"])
def receipt(request,pk):
 m=membership(request)
 if not m:return no_member()
 try:o=Order.objects.select_related("restaurant").prefetch_related("lines").get(pk=pk,restaurant=m.restaurant,status="paid")
 except Order.DoesNotExist:return Response({"detail":"Receipt unavailable"},status=404)
 r=o.restaurant
 lines="".join(f"<tr><td>{escape(x.name_snapshot)}</td><td>{x.quantity}</td><td>₹{x.line_total}</td></tr>" for x in o.lines.all())
 html=f"<html><head><meta charset='utf-8'><title>Receipt {escape(o.receipt_number)}</title></head><body><h2>{escape(r.name)}</h2><p>{escape(r.address)}<br>Phone: {escape(r.contact_phone)}<br>GSTIN: {escape(r.gstin)}</p><p>Receipt {escape(o.receipt_number)}</p><table>{lines}</table><p>Subtotal ₹{o.subtotal}<br>CGST {o.cgst_rate}%: ₹{o.cgst_amount}<br>SGST {o.sgst_rate}%: ₹{o.sgst_amount}</p><h3>Total ₹{o.total}</h3><button onclick='window.print()'>Print</button></body></html>"
 return HttpResponse(html)
