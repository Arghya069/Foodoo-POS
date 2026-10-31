from decimal import Decimal,ROUND_HALF_UP
import uuid
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
  r.save()
 return Response({"id":str(r.id),"name":r.name,"address":r.address,"contact_phone":r.contact_phone,"gstin":r.gstin,"cgst_rate":str(r.cgst_rate),"sgst_rate":str(r.sgst_rate)})
class MenuItemSerializer(serializers.ModelSerializer):
 class Meta:
  model=MenuItem
  fields=["id","name","description","image_url","price","active"]
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
@api_view(["GET"])
def receipt(request,pk):
 m=membership(request)
 if not m:return no_member()
 try:o=Order.objects.select_related("restaurant").prefetch_related("lines").get(pk=pk,restaurant=m.restaurant,status="paid")
 except Order.DoesNotExist:return Response({"detail":"Receipt unavailable"},status=404)
 r=o.restaurant
 output=BytesIO()
 doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=45,leftMargin=45,topMargin=40,bottomMargin=40)
 ss=getSampleStyleSheet()
 ss.add(ParagraphStyle(name="FoodooTitle",parent=ss["Heading1"],fontSize=18,leading=22,textColor=colors.HexColor("#126B5B")))
 safe=lambda value:xml_escape(str(value or ""))
 story=[Paragraph(safe(r.name),ss["FoodooTitle"]),Paragraph(safe(r.address).replace("\\n","<br/>"),ss["Normal"]),Paragraph("Phone: "+safe(r.contact_phone)+" | GSTIN: "+safe(r.gstin),ss["Normal"]),Spacer(1,18),Paragraph("TAX INVOICE / RECEIPT",ss["Heading2"]),Paragraph("Invoice: "+safe(o.receipt_number),ss["Normal"]),Paragraph("Date: "+timezone.localtime(o.paid_at).strftime("%d %b %Y %I:%M %p"),ss["Normal"]),Paragraph("Customer: "+safe(o.customer_name or "Walk-in"),ss["Normal"]),Paragraph("Customer phone: "+safe(o.customer_phone),ss["Normal"]),Spacer(1,18)]
 rows=[["Item","Qty","Rate (INR)","Amount (INR)"]]
 for line in o.lines.all():rows.append([Paragraph(safe(line.name_snapshot),ss["Normal"]),str(line.quantity),str(line.unit_price),str(line.line_total)])
 table=Table(rows,colWidths=[225,45,95,95],repeatRows=1)
 table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DCEFEA")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#0E5448")),("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(1,1),(-1,-1),"RIGHT"),("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9),("LINEBELOW",(0,0),(-1,0),1,colors.HexColor("#126B5B")),("LINEBELOW",(0,1),(-1,-1),0.25,colors.HexColor("#DCEFEA"))]))
 story.extend([table,Spacer(1,18)])
 summary=[["Subtotal",f"INR {o.subtotal:.2f}"],[f"CGST ({o.cgst_rate}%)",f"INR {o.cgst_amount:.2f}"],[f"SGST ({o.sgst_rate}%)",f"INR {o.sgst_amount:.2f}"],["TOTAL",f"INR {o.total:.2f}"]]
 totals=Table(summary,colWidths=[330,130])
 totals.setStyle(TableStyle([("ALIGN",(1,0),(1,-1),"RIGHT"),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,-1),(-1,-1),13),("LINEABOVE",(0,-1),(-1,-1),1,colors.HexColor("#126B5B")),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
 story.extend([totals,Spacer(1,20),Paragraph("Payment status: PAID (manually confirmed)",ss["Normal"]),Paragraph("Thank you for your visit.",ss["Normal"])])
 doc.build(story)
 output.seek(0)
 return FileResponse(output,content_type="application/pdf",filename=f"{o.receipt_number}.pdf")
