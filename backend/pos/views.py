from decimal import Decimal,ROUND_HALF_UP
import uuid
import base64
import re
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from django.db import transaction
from django.db.models import F
from django.http import FileResponse
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from rest_framework import serializers
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
  if "logo_data" in request.data:
   logo=request.data["logo_data"]
   if not isinstance(logo,str) or (logo and (not re.match(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$",logo) or len(logo)>220000)):
    return Response({"logo_data":"Use a small PNG or JPEG logo (maximum about 160 KB)."},status=400)
   r.logo_data=logo
  r.save()
 return Response({"id":str(r.id),"name":r.name,"address":r.address,"contact_phone":r.contact_phone,"gstin":r.gstin,"logo_data":r.logo_data,"cgst_rate":str(r.cgst_rate),"sgst_rate":str(r.sgst_rate)})
class MenuItemSerializer(serializers.ModelSerializer):
 class Meta:
  model=MenuItem
  fields=["id","name","description","image_url","food_type","category","price","active"]
  read_only_fields=["id"]

@api_view(["GET","POST"])
def menu(request):
 m=membership(request)
 if not m:return no_member()
 if request.method=="POST":
  if m.role!="admin":return Response({"detail":"Admin only"},status=403)
  serializer=MenuItemSerializer(data=request.data)
  serializer.is_valid(raise_exception=True)
  item=serializer.save(restaurant=m.restaurant)
  return Response(MenuItemSerializer(item).data,status=201)
 items=MenuItem.objects.filter(restaurant=m.restaurant,active=True).order_by("name")
 return Response(MenuItemSerializer(items,many=True).data)

@api_view(["PATCH"])
def menu_detail(request,pk):
 m=membership(request)
 if not m:return no_member()
 if m.role!="admin":return Response({"detail":"Admin only"},status=403)
 try:item=MenuItem.objects.get(pk=pk,restaurant=m.restaurant)
 except MenuItem.DoesNotExist:return Response({"detail":"Not found"},status=404)
 serializer=MenuItemSerializer(item,data=request.data,partial=True)
 serializer.is_valid(raise_exception=True)
 serializer.save()
 return Response(serializer.data)

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
def thermal_receipt_pdf(order):
 from reportlab.pdfbase.pdfmetrics import stringWidth
 width=57*mm
 left=4.5*mm
 usable=48*mm
 entries=[]
 def wrapped(text,size=7,bold=False):
  font="Helvetica-Bold" if bold else "Helvetica"
  for paragraph in str(text or "").splitlines() or [""]:
   words=paragraph.split()
   line=""
   for word in words:
    candidate=(line+" "+word).strip()
    if stringWidth(candidate,font,size)>usable and line:
     entries.append(("text",line,size,bold))
     line=word
    else:line=candidate
   entries.append(("text",line,size,bold))
 def rule():entries.append(("rule",))
 wrapped(order.restaurant.name,10,True)
 wrapped(order.restaurant.address,7)
 if order.restaurant.contact_phone:wrapped("Tel: "+order.restaurant.contact_phone)
 if order.restaurant.gstin:wrapped("GSTIN: "+order.restaurant.gstin)
 entries.append(("gap",5))
 wrapped("TAX INVOICE / RECEIPT",8,True)
 wrapped("No: "+order.receipt_number)
 wrapped("Date: "+timezone.localtime(order.paid_at).strftime("%d-%m-%Y %H:%M"))
 if order.customer_name:wrapped("Customer: "+order.customer_name)
 if order.customer_phone:wrapped("Phone: "+order.customer_phone)
 rule()
 for line in order.lines.all():
  wrapped(line.name_snapshot,8,True)
  wrapped(f"  {line.quantity} x {line.unit_price:.2f}       {line.line_total:.2f}")
 rule()
 wrapped(f"Subtotal: Rs {order.subtotal:.2f}")
 wrapped(f"CGST {order.cgst_rate}%: Rs {order.cgst_amount:.2f}")
 wrapped(f"SGST {order.sgst_rate}%: Rs {order.sgst_amount:.2f}")
 rule()
 wrapped(f"TOTAL: Rs {order.total:.2f}",10,True)
 wrapped("PAID - manually confirmed")
 entries.append(("gap",5))
 wrapped("Powered by foodoo",7,True)
 wrapped("Thank you!")
 logo=None
 if order.restaurant.logo_data:
  try:
   raw=base64.b64decode(order.restaurant.logo_data.split(",",1)[1],validate=True)
   logo=ImageReader(BytesIO(raw))
  except Exception:logo=None
 logo_height=19*mm if logo else 0
 height=max(70*mm,16*mm+logo_height+(3*mm if logo else 0)+sum((entry[2]+4 if entry[0]=="text" else 9 if entry[0]=="rule" else entry[1]) for entry in entries))
 output=BytesIO()
 pdf=canvas.Canvas(output,pagesize=(width,height),pageCompression=1)
 y=height-6*mm
 if logo:
  iw,ih=logo.getSize()
  dw=min(iw/ih*logo_height,usable)
  pdf.drawImage(logo,left+(usable-dw)/2,y-logo_height,width=dw,height=logo_height,preserveAspectRatio=True,mask="auto")
  y-=logo_height+3*mm
 for entry in entries:
  if entry[0]=="text":
   _,value,size,bold=entry
   y-=size+4
   pdf.setFont("Helvetica-Bold" if bold else "Helvetica",size)
   pdf.drawString(left,y,value)
  elif entry[0]=="rule":
   y-=6
   pdf.setLineWidth(.5)
   pdf.line(left,y,left+usable,y)
   y-=3
  else:y-=entry[1]
 pdf.showPage()
 pdf.save()
 output.seek(0)
 return output

@api_view(["GET"])
def receipt(request,pk):
 m=membership(request)
 if not m:return no_member()
 try:o=Order.objects.select_related("restaurant").prefetch_related("lines").get(pk=pk,restaurant=m.restaurant,status="paid")
 except Order.DoesNotExist:return Response({"detail":"Receipt unavailable"},status=404)
 return FileResponse(thermal_receipt_pdf(o),content_type="application/pdf",filename=f"{o.receipt_number}.pdf")
