"""Foodoo alternative API: FastAPI + Firestore.

Proof-of-architecture implementation. Never point the production frontend at
this API until the parity and migration checklist is completed.
"""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from google.cloud import firestore
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pwdlib import PasswordHash
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent / ".env")
PROJECT = os.getenv("FOODOO_FIRESTORE_PROJECT")
DATABASE = os.getenv("FOODOO_FIRESTORE_DATABASE", "(default)")
SECRET = os.getenv("FOODOO_SESSION_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("FOODOO_SESSION_SECRET must contain at least 32 characters")
db = firestore.Client(project=PROJECT, database=DATABASE)
signer = URLSafeTimedSerializer(SECRET, salt="foodoo-auth-v1")
password_hash = PasswordHash.recommended()
COOKIE_SECURE = os.getenv("FOODOO_COOKIE_SECURE", "true").lower() == "true"
app = FastAPI(title="Foodoo FastAPI + Firestore", version="0.1.0")

def now():
    return datetime.now(timezone.utc)

def as_paise(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError()
        paise = amount * 100
        if paise != paise.to_integral_value():
            raise ValueError()
        return int(paise)
    except (ValueError, ArithmeticError):
        raise HTTPException(422, "Use a nonnegative amount with at most 2 decimal places")

def money(paise):
    return str((Decimal(paise) / 100).quantize(Decimal("0.01")))

def tax(paise, rate):
    return int((Decimal(paise) * Decimal(str(rate)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def restaurant_root(tenant):
    return db.collection("restaurants").document(tenant)

def require_user(request: Request):
    token = request.cookies.get("foodoo_session")
    try:
        claims = signer.loads(token or "", max_age=8*60*60)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Login required")
    user_ref = db.collection("identities").document(claims["uid"])
    user = user_ref.get()
    if not user.exists or not user.to_dict().get("active", True):
        raise HTTPException(401, "Account unavailable")
    data = user.to_dict()
    if data["restaurant_id"] != claims["rid"]:
        raise HTTPException(401, "Invalid membership")
    return {"id":user.id, **data}

def roles(*allowed):
    def authorize(user=Depends(require_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Insufficient privileges")
        return user
    return authorize

class Credentials(BaseModel):
    username: str
    password: str

class MenuInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    price: str
    description: str = ""
    food_type: str = "veg"
    food_subtype: str = "none"
    category: str = "main_course"
    image_url: str = ""
    image_data: str = ""
    active: bool = True

class LineInput(BaseModel):
    id: str
    quantity: int = Field(ge=1, le=999)

class OrderInput(BaseModel):
    items: list[LineInput]
    customer_name: str = ""
    customer_phone: str = ""
    whatsapp_consent: bool = False

class Payment(BaseModel):
    payment_method: str

@app.middleware("http")
async def protect_mutations(request: Request, call_next):
    # Explicit CSRF token check for cookie-authenticated API mutations.
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.url.path not in ("/api/auth/login/",):
        cookie = request.cookies.get("foodoo_csrf")
        header = request.headers.get("x-csrftoken")
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return JSONResponse({"detail":"CSRF verification failed"}, status_code=403)
        origin = request.headers.get("origin")
        allowed = os.getenv("FOODOO_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
        if origin and origin not in allowed:
            return JSONResponse({"detail":"Untrusted origin"}, status_code=403)
    return await call_next(request)

@app.get("/healthz")
def health():
    return {"ok":True}

@app.get("/api/auth/csrf/")
def csrf(response: Response):
    token = secrets.token_urlsafe(32)
    response.set_cookie("foodoo_csrf", token, secure=COOKIE_SECURE, httponly=False, samesite="lax", path="/")
    return {"ok":True}

@app.post("/api/auth/login/")
def login(payload: Credentials, response: Response):
    # Username is globally unique; resolve membership server-side.
    results = list(db.collection("identities").where("username", "==", payload.username).limit(1).stream())
    if not results or not results[0].to_dict().get("active", True):
        raise HTTPException(401, "Invalid username or password")
    user = results[0].to_dict()
    if not password_hash.verify(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    response.set_cookie("foodoo_session", signer.dumps({"uid":results[0].id,"rid":user["restaurant_id"]}),
                        max_age=8*60*60, secure=COOKIE_SECURE, httponly=True, samesite="lax", path="/")
    return {"username":payload.username}

@app.post("/api/auth/logout/")
def logout(response: Response):
    response.delete_cookie("foodoo_session", path="/")
    return {"ok":True}

@app.get("/api/me/")
def me(user=Depends(require_user)):
    return {"username":user["username"],"role":user["role"],"restaurant_id":user["restaurant_id"]}

@app.get("/api/restaurant/")
def restaurant(user=Depends(require_user)):
    doc=restaurant_root(user["restaurant_id"]).get()
    if not doc.exists:
        raise HTTPException(404, "Restaurant missing")
    return {"id":doc.id,**doc.to_dict()}

@app.patch("/api/restaurant/")
def update_restaurant(changes: dict, user=Depends(roles("admin"))):
    allowed={"name","address","contact_phone","gstin","fssai_license_number","logo_data","branch_type","branch_name","branch_code","cgst_rate","sgst_rate"}
    unknown=sorted(set(changes)-allowed)
    if unknown:
        raise HTTPException(400,{"message":"Unknown restaurant settings","fields":unknown})
    if "fssai_license_number" in changes:
        fssai=str(changes["fssai_license_number"]).strip()
        if fssai and not re.fullmatch(r"\\d{14}",fssai):
            raise HTTPException(422,"FSSAI license number must be 14 digits")
        changes["fssai_license_number"]=fssai
    restaurant_root(user["restaurant_id"]).update(changes)
    return restaurant(user)

def menu_docs(user, active_only=False):
    docs=restaurant_root(user["restaurant_id"]).collection("menu").stream()
    items=[{"id":snap.id,**snap.to_dict()} for snap in docs]
    return [x for x in items if x.get("active",True)] if active_only else items

@app.get("/api/menu/")
def menu(user=Depends(roles("admin","cashier","staff"))):
    return sorted(menu_docs(user,active_only=user["role"]!="admin"),key=lambda x:x["name"].lower())

@app.post("/api/menu/",status_code=201)
def create_menu(item: MenuInput,user=Depends(roles("admin"))):
    data=item.model_dump()
    data["price_paise"]=as_paise(data.pop("price"))
    data["price"]=money(data["price_paise"])
    ref=restaurant_root(user["restaurant_id"]).collection("menu").document()
    ref.set(data)
    return {"id":ref.id,**data}

@app.patch("/api/menu/{item_id}/")
def update_menu(item_id: str, changes: dict,user=Depends(roles("admin"))):
    ref=restaurant_root(user["restaurant_id"]).collection("menu").document(item_id)
    original=ref.get()
    if not original.exists:raise HTTPException(404,"Dish missing")
    allowed=set(MenuInput.model_fields)
    if set(changes)-allowed:raise HTTPException(400,"Invalid menu fields")
    if "price" in changes:
        changes["price_paise"]=as_paise(changes["price"])
        changes["price"]=money(changes["price_paise"])
    ref.update(changes)
    return {"id":ref.id,**ref.get().to_dict()}

@app.post("/api/orders/",status_code=201)
def create_order(payload: OrderInput,user=Depends(roles("admin","cashier","staff"))):
    if not payload.items:raise HTTPException(400,"At least one item required")
    root=restaurant_root(user["restaurant_id"])
    restaurant=root.get()
    if not restaurant.exists:raise HTTPException(404,"Restaurant missing")
    config=restaurant.to_dict()
    qty={}
    for line in payload.items:qty[line.id]=qty.get(line.id,0)+line.quantity
    lines=[]
    for item_id,count in qty.items():
        snap=root.collection("menu").document(item_id).get()
        if not snap.exists or not snap.to_dict().get("active",True):
            raise HTTPException(400,"Invalid or archived menu item")
        item=snap.to_dict()
        lines.append({"menu_item_id":item_id,"name":item["name"],"quantity":count,
                      "unit_price_paise":int(item["price_paise"]),
                      "line_total_paise":int(item["price_paise"])*count})
    subtotal=sum(line["line_total_paise"] for line in lines)
    cgst=tax(subtotal,config.get("cgst_rate","2.50"))
    sgst=tax(subtotal,config.get("sgst_rate","2.50"))
    day=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    counter=root.collection("daily_counters").document(day)
    order=root.collection("orders").document()
    transaction=db.transaction()
    @firestore.transactional
    def persist(tx):
        snap=counter.get(transaction=tx)
        number=(snap.to_dict().get("last_number",0) if snap.exists else 0)+1
        tx.set(counter,{"last_number":number,"currently_serving":snap.to_dict().get("currently_serving",0) if snap.exists else 0})
        tx.create(order,{"created_at":now(),"status":"draft","token_number":number,"token_date":day,
           "created_by":user["id"],"customer_name":payload.customer_name,"customer_phone":payload.customer_phone,
           "whatsapp_consent":payload.whatsapp_consent,"lines":lines,
           "subtotal_paise":subtotal,"cgst_paise":cgst,"sgst_paise":sgst,"total_paise":subtotal+cgst+sgst,
           "cgst_rate":config.get("cgst_rate","2.50"),"sgst_rate":config.get("sgst_rate","2.50")})
        return number
    number=persist(transaction)
    return {"id":order.id,"status":"draft","token_number":number,"token_date":day,
            "subtotal":money(subtotal),"cgst":money(cgst),"sgst":money(sgst),"total":money(subtotal+cgst+sgst)}

@app.post("/api/orders/{order_id}/pay/")
def pay(order_id: str,payload: Payment,user=Depends(roles("admin","cashier","staff"))):
    if payload.payment_method not in ("cash","card","upi"):
        raise HTTPException(400,"Invalid payment method")
    order=restaurant_root(user["restaurant_id"]).collection("orders").document(order_id)
    tx=db.transaction()
    @firestore.transactional
    def commit(transaction):
        snap=order.get(transaction=transaction)
        if not snap.exists:raise HTTPException(404,"Order missing")
        data=snap.to_dict()
        if data["status"]=="paid":return data
        updated={"status":"paid","payment_method":payload.payment_method,"paid_at":now(),
                 "receipt_number":"FD-"+now().strftime("%Y%m%d")+"-"+order_id[:12].upper()}
        transaction.update(order,updated)
        return {**data,**updated}
    data=commit(tx)
    return {"id":order_id,"status":data["status"],"receipt_number":data["receipt_number"],
            "payment_method":data["payment_method"],"total":money(data["total_paise"]),
            "whatsapp_consent":data.get("whatsapp_consent",False),"token_number":data["token_number"]}

@app.get("/api/tokens/today/")
def tokens(user=Depends(roles("admin","cashier","staff"))):
    day=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    snap=restaurant_root(user["restaurant_id"]).collection("daily_counters").document(day).get()
    data=snap.to_dict() if snap.exists else {}
    return {"date":day,"last_issued":data.get("last_number",0),"currently_serving":data.get("currently_serving",0)}

class ServingUpdate(BaseModel):
    currently_serving: int = Field(ge=0)

@app.post("/api/tokens/today/")
def set_serving(payload:ServingUpdate,user=Depends(roles("admin","cashier","staff"))):
    day=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    ref=restaurant_root(user["restaurant_id"]).collection("daily_counters").document(day)
    tx=db.transaction()
    @firestore.transactional
    def update(transaction):
        snap=ref.get(transaction=transaction)
        data=snap.to_dict() if snap.exists else {}
        if payload.currently_serving<data.get("currently_serving",0) or payload.currently_serving>data.get("last_number",0):
            raise HTTPException(400,"Token cannot go backwards or exceed issued tokens")
        transaction.set(ref,{"currently_serving":payload.currently_serving},merge=True)
        return data.get("last_number",0)
    issued=update(tx)
    return {"date":day,"last_issued":issued,"currently_serving":payload.currently_serving}

def order_view(doc):
    o=doc.to_dict()
    return {"id":doc.id,"status":o["status"],"receipt_number":o.get("receipt_number"),
            "token_number":o.get("token_number"),"token_date":o.get("token_date"),
            "customer_name":o.get("customer_name",""),"customer_phone":o.get("customer_phone",""),
            "payment_method":o.get("payment_method",""),"whatsapp_consent":o.get("whatsapp_consent",False),
            "subtotal":money(o["subtotal_paise"]),"cgst":money(o["cgst_paise"]),
            "sgst":money(o["sgst_paise"]),"total":money(o["total_paise"]),
            "created_at":o["created_at"].isoformat(),"paid_at":o.get("paid_at").isoformat() if o.get("paid_at") else None,
            "items":[{"name":x["name"],"quantity":x["quantity"],"unit_price":money(x["unit_price_paise"]),
                      "total":money(x["line_total_paise"])} for x in o.get("lines",[])]}

def orders_query(user):
    # Bounded Firestore scan for prototype. Replace with indexed cursor queries.
    return [d for d in restaurant_root(user["restaurant_id"]).collection("orders").order_by("created_at",direction=firestore.Query.DESCENDING).limit(1000).stream()]

@app.get("/api/orders/")
def list_orders(user=Depends(roles("admin","cashier","staff"))):
    return [{"id":d.id,"status":d.to_dict()["status"],"total":money(d.to_dict()["total_paise"]),
             "receipt_number":d.to_dict().get("receipt_number")} for d in orders_query(user)[:50]]

@app.get("/api/orders/history/")
def history(start:str|None=None,end:str|None=None,status:str="all",q:str="",page:int=1,
            user=Depends(roles("admin","cashier","staff"))):
    from datetime import date
    today=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()
    try:
        lower=date.fromisoformat(start) if start else today-timedelta(days=29)
        upper=date.fromisoformat(end) if end else today
    except ValueError:raise HTTPException(400,"Invalid date")
    if lower>upper or (upper-lower).days>366 or status not in ("all","paid","draft") or page<1:
        raise HTTPException(400,"Invalid filter")
    matches=[]
    for doc in orders_query(user):
        data=doc.to_dict()
        if not lower<=data["created_at"].astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()<=upper:continue
        if status!="all" and data["status"]!=status:continue
        if q and not any(q.lower() in str(data.get(key,"")).lower() for key in ("customer_phone","customer_name","receipt_number")):continue
        matches.append(order_view(doc))
    return {"count":len(matches),"page":page,"page_size":25,"results":matches[(page-1)*25:page*25]}

def paid_report_rows(user,start=None,end=None):
    from datetime import date
    today=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()
    try:
        lower=date.fromisoformat(start) if start else today-timedelta(days=29)
        upper=date.fromisoformat(end) if end else today
    except ValueError:raise HTTPException(400,"Invalid date")
    if lower>upper or (upper-lower).days>366:raise HTTPException(400,"Invalid date range")
    paid=[]
    for doc in orders_query(user):
        record=doc.to_dict()
        if record["status"]!="paid" or not record.get("paid_at"):continue
        day=record["paid_at"].astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()
        if lower<=day<=upper:paid.append((doc.id,record,day))
    return lower,upper,paid

@app.get("/api/reports/sales/")
def sales_report(start:str|None=None,end:str|None=None,user=Depends(roles("admin","partner"))):
    lower,upper,paid=paid_report_rows(user,start,end)
    sums={key:sum(row[1][key] for row in paid) for key in ("subtotal_paise","cgst_paise","sgst_paise","total_paise")}
    methods={};daily={}
    for _,r,day in paid:
        method=r.get("payment_method","unknown")
        for group,key in ((methods,method),(daily,day.isoformat())):
            value=group.setdefault(key,{"orders":0,"revenue_paise":0})
            value["orders"]+=1;value["revenue_paise"]+=r["total_paise"]
    return {"start":lower.isoformat(),"end":upper.isoformat(),"orders":len(paid),
            "subtotal":money(sums["subtotal_paise"]),"cgst":money(sums["cgst_paise"]),
            "sgst":money(sums["sgst_paise"]),"revenue":money(sums["total_paise"]),
            "payment_methods":[{"method":k,"orders":v["orders"],"revenue":money(v["revenue_paise"])} for k,v in sorted(methods.items())],
            "daily":[{"date":k,"orders":v["orders"],"revenue":money(v["revenue_paise"])} for k,v in sorted(daily.items())]}

@app.get("/api/reports/sales/export/")
def sales_export(start:str|None=None,end:str|None=None,file_type:str="csv",user=Depends(roles("admin","partner"))):
    import csv
    from io import BytesIO,StringIO
    from fastapi.responses import StreamingResponse
    lower,upper,paid=paid_report_rows(user,start,end)
    if file_type not in ("csv","xlsx"):raise HTTPException(400,"Unknown export type")
    headers=["Receipt","Paid at (IST)","Customer name","Customer phone","Payment method","Subtotal","CGST","SGST","Total"]
    def safe_text(s):
        value=str(s or "")
        return "'"+value if value.startswith(("=","+","-","@")) else value
    rows=[[safe_text(r.get("receipt_number")),day.isoformat(),safe_text(r.get("customer_name")),
           safe_text(r.get("customer_phone")),safe_text(r.get("payment_method")),
           *[money(r[k]) for k in ("subtotal_paise","cgst_paise","sgst_paise","total_paise")]] for _,r,day in paid]
    filename=f"foodoo-sales-{lower}-to-{upper}.{file_type}"
    if file_type=="csv":
        out=StringIO();writer=csv.writer(out);writer.writerow(headers);writer.writerows(rows)
        return Response(content="\ufeff"+out.getvalue(),media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":f'attachment; filename="{filename}"'})
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active;ws.title="Sales";ws.append(headers)
    for row in rows:ws.append(row)
    ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
    out=BytesIO();wb.save(out)
    return Response(content=out.getvalue(),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":f'attachment; filename="{filename}"'})

@app.get("/api/kitchen/")
def kitchen(user=Depends(roles("admin","chef"))):
    results=[]
    for doc in orders_query(user):
        row=doc.to_dict()
        if row["status"]=="paid":
            results.append({"id":doc.id,"token_number":row.get("token_number"),"token_date":row.get("token_date"),
                "paid_at":row.get("paid_at").isoformat() if row.get("paid_at") else None,
                "items":[{"name":x["name"],"quantity":x["quantity"]} for x in row["lines"]]})
    return results[:50]

class StaffCreate(BaseModel):
    username: str = Field(min_length=2,max_length=150)
    first_name: str = ""
    password: str = Field(min_length=10)
    role: str

@app.get("/api/staff/")
def staff(user=Depends(roles("admin"))):
    return [{"id":s.id,**{k:v for k,v in s.to_dict().items() if k in ("username","first_name","role","active")}}
            for s in db.collection("identities").where("restaurant_id","==",user["restaurant_id"]).stream()]

@app.post("/api/staff/",status_code=201)
def create_staff(payload:StaffCreate,user=Depends(roles("admin"))):
    if payload.role not in ("admin","cashier","chef","partner"):
        raise HTTPException(400,"Invalid staff role")
    # Claim the username using the normalized username as the document ID.
    username=payload.username.casefold()
    if not all(c.isalnum() or c in "._-" for c in username):
        raise HTTPException(400,"Invalid username")
    ref=db.collection("identities").document(username)
    try:
        ref.create({"username":payload.username,"first_name":payload.first_name,
                    "password_hash":password_hash.hash(payload.password),
                    "restaurant_id":user["restaurant_id"],"role":payload.role,"active":True})
    except __import__("google.api_core.exceptions",fromlist=["AlreadyExists"]).AlreadyExists:
        raise HTTPException(409,"Username is already taken")
    return {"id":ref.id,"username":payload.username,"first_name":payload.first_name,"role":payload.role,"active":True}

@app.patch("/api/staff/{staff_id}/")
def staff_change(staff_id:str,changes:dict,user=Depends(roles("admin"))):
    ref=db.collection("identities").document(staff_id)
    snap=ref.get()
    if not snap.exists or snap.to_dict().get("restaurant_id")!=user["restaurant_id"]:
        raise HTTPException(404,"Staff member not found")
    allowed={"role","active","password","first_name"}
    if not changes or set(changes)-allowed:raise HTTPException(400,"Invalid staff fields")
    if "role" in changes and changes["role"] not in ("admin","cashier","chef","partner"):
        raise HTTPException(400,"Invalid role")
    if "active" in changes and not isinstance(changes["active"],bool):
        raise HTTPException(400,"Invalid active status")
    if staff_id==user["id"] and (changes.get("active") is False or changes.get("role","admin")!="admin"):
        raise HTTPException(400,"Cannot disable or demote your own account")
    existing=snap.to_dict()
    if existing["role"]=="admin" and (changes.get("role") not in (None,"admin") or changes.get("active") is False):
        admins=[m for m in db.collection("identities").where("restaurant_id","==",user["restaurant_id"]).stream()
                if m.to_dict().get("role")=="admin" and m.to_dict().get("active",True) and m.id!=staff_id]
        if not admins:raise HTTPException(400,"At least one active admin is required")
    if "password" in changes:
        if not isinstance(changes["password"],str) or len(changes["password"])<10:
            raise HTTPException(400,"Password must be at least 10 characters")
        changes["password_hash"]=password_hash.hash(changes.pop("password"))
    ref.update(changes)
    data=ref.get().to_dict()
    return {"id":staff_id,**{k:data[k] for k in ("username","first_name","role","active")}}

def order_receipt_data(order_id,user):
    order_ref=restaurant_root(user["restaurant_id"]).collection("orders").document(order_id)
    order_doc=order_ref.get()
    if not order_doc.exists:raise HTTPException(404,"Order not found")
    order=order_doc.to_dict()
    if order.get("status")!="paid":raise HTTPException(409,"Order not paid yet")
    restaurant_doc=restaurant_root(user["restaurant_id"]).get()
    if not restaurant_doc.exists:raise HTTPException(404,"Restaurant missing")
    return order,restaurant_doc.to_dict()

@app.get("/api/orders/{order_id}/receipt/")
def receipt(order_id:str,user=Depends(roles("admin","cashier","staff"))):
    from receipt_pdf import build_receipt_pdf
    order,restaurant=order_receipt_data(order_id,user)
    pdf=build_receipt_pdf(restaurant,order)
    return Response(content=pdf,media_type="application/pdf",
                    headers={"Content-Disposition":f'attachment; filename="foodoo-{order_id}.pdf"'})

class ReceiptSendRequest(BaseModel):
    confirm: bool = True

@app.post("/api/orders/{order_id}/whatsapp/")
def send_receipt_whatsapp(order_id:str,payload:ReceiptSendRequest,user=Depends(roles("admin","cashier","staff"))):
    from receipt_pdf import build_receipt_pdf
    from whatsapp_send import send_receipt_pdf,WhatsAppConfigError,WhatsAppSendError,normalize_phone
    if not payload.confirm:
        raise HTTPException(400,"Confirm the WhatsApp receipt request")
    order,restaurant=order_receipt_data(order_id,user)
    if not order.get("whatsapp_consent"):
        raise HTTPException(403,"Customer has not consented to WhatsApp messages")
    phone=order.get("customer_phone")
    try:
        normalize_phone(phone)
    except ValueError:
        raise HTTPException(422,"Customer phone number is invalid")
    # Avoid inadvertent repeated sends. This is a best-effort delivery record,
    # not an exactly-once guarantee across upstream network failures.
    ref=restaurant_root(user["restaurant_id"]).collection("whatsapp_receipts").document(order_id)
    tx=db.transaction()
    @firestore.transactional
    def claim(transaction):
        snap=ref.get(transaction=transaction)
        if snap.exists and snap.to_dict().get("state") in ("sending","submitted"):
            return False
        transaction.set(ref,{"state":"sending","claimed_at":now(),"created_by":user["id"]},merge=True)
        return True
    if not claim(tx):
        raise HTTPException(409,"This receipt is already sending or was submitted")
    try:
        filename="foodoo-"+str(order.get("receipt_number") or order_id)+".pdf"
        result=send_receipt_pdf(phone,build_receipt_pdf(restaurant,order),filename)
    except WhatsAppConfigError:
        ref.update({"state":"failed","updated_at":now(),"reason":"configuration"})
        raise HTTPException(503,"WhatsApp is not configured: set Meta token, phone number ID, template name and language")
    except WhatsAppSendError:
        ref.update({"state":"review_required","updated_at":now(),"reason":"upstream_error"})
        raise HTTPException(502,"Meta did not confirm delivery acceptance. Check status before attempting again")
    ref.update({"state":"submitted","updated_at":now(),"message_id":result["message_id"],
                "recipient":result["recipient"],"reason":None})
    return {"status":"submitted","message_id":result["message_id"]}

@app.get("/api/customers/lookup/")
def lookup_customer(phone:str="",user=Depends(roles("admin","cashier","staff"))):
    if not phone or len(phone)>25:raise HTTPException(400,"Invalid phone number")
    orders=restaurant_root(user["restaurant_id"]).collection("orders").where("customer_phone","==",phone).limit(100).stream()
    paid=[x.to_dict() for x in orders if x.to_dict().get("status")=="paid"]
    if not paid:return {"customer_name":"","whatsapp_consent":False}
    recent=max(paid,key=lambda o:o.get("paid_at") or datetime.min.replace(tzinfo=timezone.utc))
    return {"customer_name":recent.get("customer_name",""),"whatsapp_consent":recent.get("whatsapp_consent",False)}

@app.get("/api/customers/suggest/")
def suggest_customers(q:str="",user=Depends(roles("admin","cashier","staff"))):
    # Temporary bounded lookup until dedicated customer index is added.
    if len(q)<3:return []
    matches={}
    for snapshot in orders_query(user):
        data=snapshot.to_dict()
        phone=data.get("customer_phone","")
        if data.get("status")=="paid" and q in phone and phone not in matches:
            matches[phone]={"customer_phone":phone,"customer_name":data.get("customer_name",""),
                            "whatsapp_consent":data.get("whatsapp_consent",False)}
            if len(matches)>=8:break
    return list(matches.values())
