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
  fields=["id","name","description","image_url","image_data","food_type","food_subtype","category","price","active"]
  read_only_fields=["id"]
 def validate(self,attrs):
  main=attrs.get("food_type",getattr(self.instance,"food_type","veg"))
  sub=attrs.get("food_subtype",getattr(self.instance,"food_subtype","none"))
  if sub in ("egg","chicken","mutton","fish") and main!="non_veg":raise serializers.ValidationError({"food_subtype":"This subtype requires Non-veg."})
  if sub in ("paneer","mushroom") and main!="veg":raise serializers.ValidationError({"food_subtype":"This subtype requires Veg."})
  return attrs
 def validate_image_data(self,value):
  if value and (len(value)>5592500 or not re.fullmatch(r"data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+",value)):
   raise serializers.ValidationError("Provide a PNG, JPEG or WebP image up to 4 MB.")
  if value:
   try:
    raw=base64.b64decode(value.split(",",1)[1],validate=True)
    if len(raw)>4*1024*1024:raise serializers.ValidationError("Image must be at most 4 MB.")
   except (ValueError,base64.binascii.Error):raise serializers.ValidationError("Invalid encoded image.")
  return value

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

@api_view(["GET"])
def customer_lookup(request):
 m=membership(request)
 if not m:return no_member()
 phone=str(request.query_params.get("phone","")).strip()
 if not re.fullmatch(r"[+0-9 -]{8,20}",phone):return Response({"customer_name":""})
 last=Order.objects.filter(restaurant=m.restaurant,customer_phone=phone,status="paid").exclude(customer_name="").order_by("-paid_at").first()
 return Response({"customer_name":last.customer_name if last else "","whatsapp_consent":bool(last.whatsapp_consent) if last else False})

@api_view(["GET"])
def customer_suggestions(request):
 m=membership(request)
 if not m:return no_member()
 prefix=str(request.query_params.get("q","")).strip()
 if not re.fullmatch(r"[+0-9 -]{3,20}",prefix):return Response([])
 matches=Order.objects.filter(restaurant=m.restaurant,status="paid",customer_phone__startswith=prefix).exclude(customer_name="").exclude(customer_phone="").order_by("-paid_at").values("customer_phone","customer_name","whatsapp_consent")[:100]
 seen=set()
 suggestions=[]
 for x in matches:
  if x["customer_phone"] not in seen:
   seen.add(x["customer_phone"])
   suggestions.append(x)
  if len(suggestions)==8:break
 return Response(suggestions)

@api_view(["GET","POST"])
def orders(request):
 m=membership(request)
 if not m:return no_member()
 if request.method=="GET":return Response([{"id":o.pk,"status":o.status,"total":str(o.total),"receipt_number":o.receipt_number} for o in Order.objects.filter(restaurant=m.restaurant).order_by("-id")[:50]])
 phone=str(request.data.get("customer_phone","")).strip()
 name=str(request.data.get("customer_name","")).strip()
 if phone and not re.fullmatch(r"[+0-9 -]{8,20}",phone):return Response({"customer_phone":"Enter a valid phone number (8–20 characters)."},status=400)
 if len(name)>160:return Response({"customer_name":"Name is too long."},status=400)
 if request.data.get("whatsapp_consent") is True and not phone:return Response({"whatsapp_consent":"Customer phone is required for WhatsApp consent."},status=400)
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
  o=Order.objects.create(restaurant=r,created_by=request.user,customer_name=name,customer_phone=phone,whatsapp_consent=request.data.get("whatsapp_consent") is True,subtotal=subtotal,cgst_rate=r.cgst_rate,sgst_rate=r.sgst_rate,cgst_amount=cgst,sgst_amount=sgst,total=subtotal+cgst+sgst)
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
   method=request.data.get("payment_method")
   if method not in ("cash","card","upi"):return Response({"payment_method":"Choose Cash, Card or UPI."},status=400)
   o.status="paid";o.payment_method=method;o.paid_at=timezone.now();o.receipt_number="FD-"+uuid.uuid4().hex[:12].upper();o.save(update_fields=["status","payment_method","paid_at","receipt_number"])
 return Response({"id":o.pk,"status":o.status,"receipt_number":o.receipt_number,"total":str(o.total),"payment_method":o.payment_method,"whatsapp_consent":o.whatsapp_consent})
def thermal_receipt_pdf(order):
 from reportlab.pdfbase.pdfmetrics import stringWidth
 width=57*mm
 left=4.5*mm
 usable=48*mm
 entries=[]
 def text(value,size=7,bold=False,center=False):
  font="Helvetica-Bold" if bold else "Helvetica"
  for paragraph in str(value or "").splitlines() or [""]:
   line=""
   for word in paragraph.split():
    candidate=(line+" "+word).strip()
    if stringWidth(candidate,font,size)>usable and line:
     entries.append(("text",line,size,bold,center))
     line=word
    else:line=candidate
   entries.append(("text",line,size,bold,center))
 def rule():entries.append(("rule",))
 text(order.restaurant.name,10,True,True)
 text(order.restaurant.address,7,False,True)
 if order.restaurant.contact_phone:text("Tel: "+order.restaurant.contact_phone,7,False,True)
 if order.restaurant.gstin:text("GSTIN: "+order.restaurant.gstin,7,False,True)
 entries.append(("gap",5))
 text("TAX INVOICE / RECEIPT",8,True,True)
 text("No: "+order.receipt_number)
 text("Date: "+timezone.localtime(order.paid_at).strftime("%d-%m-%Y %H:%M"))
 if order.customer_name:text("Customer: "+order.customer_name)
 if order.customer_phone:text("Phone: "+order.customer_phone)
 rule()
 entries.append(("tablehead",))
 for line in order.lines.all():
  text(line.name_snapshot,7,True)
  entries.append(("itemtotal",str(line.quantity)+" x "+str(line.unit_price),f"{line.line_total:.2f}"))
 rule()
 for label,amount in [("Subtotal",order.subtotal),(f"CGST {order.cgst_rate}%",order.cgst_amount),(f"SGST {order.sgst_rate}%",order.sgst_amount)]:
  entries.append(("amount",label,f"{amount:.2f}",7))
 rule()
 entries.append(("amount","TOTAL",f"{order.total:.2f}",9))
 text("PAID - "+(order.payment_method or "manual").upper())
 entries.append(("gap",6))
 text("Powered by foodoo",7,True,True)
 text("Thank you!",7,False,True)
 logo=None
 if order.restaurant.logo_data:
  try:
   raw=base64.b64decode(order.restaurant.logo_data.split(",",1)[1],validate=True)
   logo=ImageReader(BytesIO(raw))
  except Exception:logo=None
 logo_height=19*mm if logo else 0
 def line_height(entry):
  if entry[0]=="text":return entry[2]+4
  if entry[0] in ("tablehead","itemtotal"):return 14
  if entry[0]=="amount":return entry[3]+6
  if entry[0]=="rule":return 9
  return entry[1]
 height=max(70*mm,16*mm+logo_height+(3*mm if logo else 0)+sum(map(line_height,entries)))
 output=BytesIO()
 pdf=canvas.Canvas(output,pagesize=(width,height),pageCompression=1)
 y=height-6*mm
 if logo:
  iw,ih=logo.getSize()
  dw=min(iw/ih*logo_height,usable)
  pdf.drawImage(logo,left+(usable-dw)/2,y-logo_height,width=dw,height=logo_height,preserveAspectRatio=True,mask="auto")
  y-=logo_height+3*mm
 for entry in entries:
  kind=entry[0]
  if kind=="text":
   _,value,size,bold,center=entry
   y-=size+4
   font="Helvetica-Bold" if bold else "Helvetica"
   pdf.setFont(font,size)
   x=left+(usable-stringWidth(value,font,size))/2 if center else left
   pdf.drawString(x,y,value)
  elif kind=="rule":
   y-=6;pdf.setLineWidth(.5);pdf.line(left,y,left+usable,y);y-=3
  elif kind=="tablehead":
   y-=11;pdf.setFont("Helvetica-Bold",7);pdf.drawString(left,y,"ITEM");pdf.drawRightString(left+usable,y,"PRICE")
  elif kind=="itemtotal":
   y-=11;pdf.setFont("Helvetica",7);pdf.drawString(left,y,entry[1]);pdf.drawRightString(left+usable,y,entry[2])
  elif kind=="amount":
   y-=entry[3]+6;pdf.setFont("Helvetica-Bold" if entry[3]==9 else "Helvetica",entry[3]);pdf.drawString(left,y,entry[1]);pdf.drawRightString(left+usable,y,entry[2])
  else:y-=entry[1]
 pdf.showPage();pdf.save();output.seek(0)
 return output

@api_view(["GET"])
def receipt(request,pk):
 m=membership(request)
 if not m:return no_member()
 try:o=Order.objects.select_related("restaurant").prefetch_related("lines").get(pk=pk,restaurant=m.restaurant,status="paid")
 except Order.DoesNotExist:return Response({"detail":"Receipt unavailable"},status=404)
 return FileResponse(thermal_receipt_pdf(o),content_type="application/pdf",filename=f"{o.receipt_number}.pdf")
