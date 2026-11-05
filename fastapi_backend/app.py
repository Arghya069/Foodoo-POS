"""Foodoo alternative API: FastAPI + Firestore.

Proof-of-architecture implementation. Never point the production frontend at
this API until the parity and migration checklist is completed.
"""
import os
import re
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from google.cloud import firestore
from sessions import new_session,validate_session,revoke_session,revoke_user_sessions,user_sessions
from order_audit import actor_details
from whatsapp_policy import authorize_receipt_send,SendDenied
from meta_webhook import create_webhook_receiver,event_id
from pwdlib import PasswordHash
from schemas import (Credentials, LoginResponse, MeResponse, RestaurantUpdate, RestaurantResponse,
    MenuInput, MenuPatch, MenuResponse, LineInput, OrderInput, OrderCreatedResponse,
    Payment, PaidResponse, ServingUpdate, TokenResponse, StaffCreate, StaffPatch,
    StaffResponse, ReceiptSendRequest, WhatsAppStatusResponse, WhatsAppSendResponse,
    SuccessResponse, OrderListRow, OrderHistoryResponse, SalesReportResponse,
    KitchenOrder, CustomerSuggestion, CustomerLookupResponse, SessionResponse, OrderAuditResponse,
    WhatsAppInboxItem,WhatsAppDeliveryItem)

load_dotenv(Path(__file__).resolve().parent / ".env")
PROJECT = os.getenv("FOODOO_FIRESTORE_PROJECT")
if not PROJECT:
    raise RuntimeError("FOODOO_FIRESTORE_PROJECT must be explicitly configured for tenant isolation")
DATABASE = os.getenv("FOODOO_FIRESTORE_DATABASE", "(default)")
SECRET = os.getenv("FOODOO_SESSION_SECRET", "")
if len(SECRET) < 32 or SECRET == "replace-with-a-long-random-secret":
    raise RuntimeError("FOODOO_SESSION_SECRET must contain at least 32 characters")
db = firestore.Client(project=PROJECT, database=DATABASE)
password_hash = PasswordHash.recommended()
COOKIE_SECURE = os.getenv("FOODOO_COOKIE_SECURE", "true").lower() == "true"
app = FastAPI(title="Foodooo FastAPI + Firestore", version="0.1.0")
app.include_router(create_webhook_receiver(db))

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
    session = validate_session(db, request.cookies.get("foodoo_session"))
    if not session:
        raise HTTPException(401,"Session expired or revoked; sign in again")
    user_ref = db.collection("identities").document(session["user_id"])
    user = user_ref.get()
    if not user.exists or not user.to_dict().get("active", True):
        raise HTTPException(401, "Account unavailable")
    data = user.to_dict()
    if data["restaurant_id"] != session["restaurant_id"]:
        raise HTTPException(401, "Invalid membership")
    return {"id":user.id, **data, "_session_id":session["id"]}

def roles(*allowed):
    def authorize(user=Depends(require_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Insufficient privileges")
        return user
    return authorize

def issue_csrf_token():
    nonce=secrets.token_urlsafe(32)
    signature=hmac.new(SECRET.encode(),nonce.encode(),"sha256").hexdigest()
    return nonce+"."+signature

def valid_csrf_token(value):
    if not isinstance(value,str) or "." not in value:
        return False
    nonce,sig=value.rsplit(".",1)
    if len(nonce)>100 or not re.fullmatch(r"[a-zA-Z0-9_-]+",nonce):
        return False
    expected=hmac.new(SECRET.encode(),nonce.encode(),"sha256").hexdigest()
    return hmac.compare_digest(sig,expected)

@app.middleware("http")
async def protect_mutations(request: Request, call_next):
    # Meta signs webhook requests with the App Secret, not the browser CSRF token.
    if request.url.path=="/webhooks/meta":
        return await call_next(request)
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        cookie=request.cookies.get("foodoo_csrf")
        header=request.headers.get("x-csrftoken")
        if not cookie or not header or not hmac.compare_digest(cookie,header) or not valid_csrf_token(cookie):
            return JSONResponse({"detail":"CSRF verification failed"},status_code=403)
        origin=request.headers.get("origin")
        allowed=[x.strip() for x in os.getenv("FOODOO_ALLOWED_ORIGINS","http://localhost:5173").split(",") if x.strip()]
        if origin and origin not in allowed:
            return JSONResponse({"detail":"Untrusted origin"},status_code=403)
    return await call_next(request)

@app.get("/healthz")
def health():
    return {"ok":True}

@app.get("/api/auth/csrf/")
def csrf(response: Response):
    token = issue_csrf_token()
    response.set_cookie("foodoo_csrf", token, secure=COOKIE_SECURE, httponly=False, samesite="lax", path="/")
    return {"ok":True}

@app.post("/api/auth/login/",response_model=LoginResponse)
def login(payload: Credentials, response: Response):
    # Username is globally unique; resolve membership server-side.
    results = list(db.collection("identities").where("username", "==", payload.username).limit(1).stream())
    if not results or not results[0].to_dict().get("active", True):
        raise HTTPException(401, "Invalid username or password")
    user = results[0].to_dict()
    if not password_hash.verify(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    response.set_cookie("foodoo_session", new_session(db, results[0].id, user["restaurant_id"]),
                        max_age=8*60*60, secure=COOKIE_SECURE, httponly=True, samesite="lax", path="/")
    return {"username":payload.username}

@app.post("/api/auth/logout/")
def logout(request:Request,response: Response):
    token=request.cookies.get("foodoo_session")
    if token:
        # Old stateless cookies are ignored after this migration.
        from google.api_core.exceptions import NotFound
        try:revoke_session(db,token)
        except NotFound:pass
    response.delete_cookie("foodoo_session", path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return {"ok":True}

@app.get("/api/auth/sessions/",response_model=list[SessionResponse])
def list_sessions(user=Depends(require_user)):
    entries=user_sessions(db,user["id"])
    return [{"id":item["id"],"current":item["id"]==user["_session_id"],
             "created_at":item["created_at"],"last_seen_at":item["last_seen_at"],
             "expires_at":item["expires_at"]} for item in entries]

@app.delete("/api/auth/sessions/{session_id}/",response_model=SuccessResponse)
def end_session(session_id:str,request:Request,response:Response,user=Depends(require_user)):
    if not re.fullmatch(r"[a-f0-9]{64}",session_id):raise HTTPException(400,"Invalid session")
    ref=db.collection("sessions").document(session_id)
    snap=ref.get()
    if not snap.exists or snap.to_dict().get("user_id")!=user["id"]:
        raise HTTPException(404,"Session not found")
    ref.update({"revoked":True})
    if session_id==user["_session_id"]:
        response.delete_cookie("foodoo_session",path="/",secure=COOKIE_SECURE,httponly=True,samesite="lax")
    return {"ok":True}

@app.post("/api/auth/logout-all/",response_model=SuccessResponse)
def logout_all(response:Response,user=Depends(require_user)):
    revoke_user_sessions(db,user["id"])
    response.delete_cookie("foodoo_session",path="/",secure=COOKIE_SECURE,httponly=True,samesite="lax")
    return {"ok":True}

@app.get("/api/me/",response_model=MeResponse)
def me(user=Depends(require_user)):
    return {"username":user["username"],"role":user["role"],"restaurant_id":user["restaurant_id"]}

@app.get("/api/restaurant/",response_model=RestaurantResponse)
def restaurant(user=Depends(require_user)):
    doc=restaurant_root(user["restaurant_id"]).get()
    if not doc.exists:
        raise HTTPException(404, "Restaurant missing")
    return {"id":doc.id,**doc.to_dict()}

@app.patch("/api/restaurant/",response_model=RestaurantResponse)
def update_restaurant(payload: RestaurantUpdate, user=Depends(roles("admin"))):
    changes=payload.model_dump(exclude_unset=True)
    allowed={"name","address","contact_phone","gstin","fssai_license_number","logo_data","branch_type","branch_name","branch_code","cgst_rate","sgst_rate"}
    unknown=sorted(set(changes)-allowed)
    if unknown:
        raise HTTPException(400,{"message":"Unknown restaurant settings","fields":unknown})
    if "fssai_license_number" in changes:
        fssai=str(changes["fssai_license_number"]).strip()
        if fssai and not re.fullmatch(r"\d{14}",fssai):
            raise HTTPException(422,"FSSAI license number must be 14 digits")
        changes["fssai_license_number"]=fssai
    restaurant_root(user["restaurant_id"]).update(changes)
    return restaurant(user)

def menu_docs(user, active_only=False):
    docs=restaurant_root(user["restaurant_id"]).collection("menu").stream()
    items=[{"id":snap.id,**snap.to_dict()} for snap in docs]
    return [x for x in items if x.get("active",True)] if active_only else items

@app.get("/api/menu/",response_model=list[MenuResponse])
def menu(user=Depends(roles("admin","cashier","staff"))):
    return sorted(menu_docs(user,active_only=user["role"]!="admin"),key=lambda x:x["name"].lower())

@app.post("/api/menu/",status_code=201,response_model=MenuResponse)
def create_menu(item: MenuInput,user=Depends(roles("admin"))):
    data=item.model_dump()
    data["price_paise"]=as_paise(data.pop("price"))
    data["price"]=money(data["price_paise"])
    ref=restaurant_root(user["restaurant_id"]).collection("menu").document()
    ref.set(data)
    return {"id":ref.id,**data}

@app.patch("/api/menu/{item_id}/",response_model=MenuResponse)
def update_menu(item_id: str, payload: MenuPatch,user=Depends(roles("admin"))):
    changes=payload.model_dump(exclude_unset=True)
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

@app.post("/api/orders/",status_code=201,response_model=OrderCreatedResponse)
def create_order(payload: OrderInput,request:Request,user=Depends(roles("admin","cashier","staff"))):
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
           "created_by":user["id"],"created_by_username":user.get("username",""),"customer_name":payload.customer_name,"customer_phone":payload.customer_phone,
           "whatsapp_consent":payload.whatsapp_consent,"lines":lines,
           "subtotal_paise":subtotal,"cgst_paise":cgst,"sgst_paise":sgst,"total_paise":subtotal+cgst+sgst,
           "cgst_rate":config.get("cgst_rate","2.50"),"sgst_rate":config.get("sgst_rate","2.50")})
        tx.create(root.collection("order_audit").document(order.id),{"created_at":now(),
           "creation":actor_details(request,user),"expires_at":now()+timedelta(days=30)})
        return number
    number=persist(transaction)
    return {"id":order.id,"status":"draft","token_number":number,"token_date":day,
            "subtotal":money(subtotal),"cgst":money(cgst),"sgst":money(sgst),"total":money(subtotal+cgst+sgst)}

@app.post("/api/orders/{order_id}/pay/",response_model=PaidResponse)
def pay(order_id: str,payload: Payment,request:Request,user=Depends(roles("admin","cashier","staff"))):
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
        transaction.set(restaurant_root(user["restaurant_id"]).collection("order_audit").document(order_id),
                        {"payment":actor_details(request,user),"expires_at":now()+timedelta(days=30)},merge=True)
        return {**data,**updated}
    data=commit(tx)
    return {"id":order_id,"status":data["status"],"receipt_number":data["receipt_number"],
            "payment_method":data["payment_method"],"total":money(data["total_paise"]),
            "whatsapp_consent":data.get("whatsapp_consent",False),"token_number":data["token_number"]}

@app.get("/api/tokens/today/",response_model=TokenResponse)
def tokens(user=Depends(roles("admin","cashier","staff"))):
    day=now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    snap=restaurant_root(user["restaurant_id"]).collection("daily_counters").document(day).get()
    data=snap.to_dict() if snap.exists else {}
    return {"date":day,"last_issued":data.get("last_number",0),"currently_serving":data.get("currently_serving",0)}

@app.post("/api/tokens/today/",response_model=TokenResponse)
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
            "created_by_username":o.get("created_by_username") or o.get("created_by","Unknown"),
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

@app.get("/api/orders/",response_model=list[OrderListRow])
def list_orders(user=Depends(roles("admin","cashier","staff"))):
    return [{"id":d.id,"status":d.to_dict()["status"],"total":money(d.to_dict()["total_paise"]),
             "receipt_number":d.to_dict().get("receipt_number")} for d in orders_query(user)[:50]]

@app.get("/api/orders/{order_id}/audit/",response_model=OrderAuditResponse)
def order_audit(order_id:str,user=Depends(roles("admin"))):
    doc=restaurant_root(user["restaurant_id"]).collection("orders").document(order_id).get()
    if not doc.exists:
        raise HTTPException(404,"Order not found")
    data=doc.to_dict()
    audit_doc=restaurant_root(user["restaurant_id"]).collection("order_audit").document(order_id).get()
    audit=audit_doc.to_dict() if audit_doc.exists else {}
    if audit.get("expires_at") and audit["expires_at"]<=now():
        audit={}
    return {"order_id":doc.id,"created_at":data["created_at"],
            "created_by":data.get("created_by_username") or data.get("created_by") or "Unknown",
            "creation":audit.get("creation"),
            "payment":audit.get("payment")}

@app.get("/api/orders/history/",response_model=OrderHistoryResponse)
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

@app.get("/api/reports/sales/",response_model=SalesReportResponse)
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

@app.get("/api/kitchen/",response_model=list[KitchenOrder])
def kitchen(user=Depends(roles("admin","chef"))):
    results=[]
    for doc in orders_query(user):
        row=doc.to_dict()
        if row["status"]=="paid":
            results.append({"id":doc.id,"token_number":row.get("token_number"),"token_date":row.get("token_date"),
                "paid_at":row.get("paid_at").isoformat() if row.get("paid_at") else None,
                "items":[{"name":x["name"],"quantity":x["quantity"]} for x in row["lines"]]})
    return results[:50]

@app.get("/api/staff/",response_model=list[StaffResponse])
def staff(user=Depends(roles("admin"))):
    return [{"id":s.id,**{k:v for k,v in s.to_dict().items() if k in ("username","first_name","role","active")}}
            for s in db.collection("identities").where("restaurant_id","==",user["restaurant_id"]).stream()]

@app.post("/api/staff/",status_code=201,response_model=StaffResponse)
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

@app.patch("/api/staff/{staff_id}/",response_model=StaffResponse)
def staff_change(staff_id:str,payload:StaffPatch,user=Depends(roles("admin"))):
    changes=payload.model_dump(exclude_unset=True)
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
    if changes.get("active") is False or "password_hash" in changes or "role" in changes:
        revoke_user_sessions(db,staff_id)
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
                    headers={"Content-Disposition":f'attachment; filename="foodoo-{order_id}.pdf"',"Cache-Control":"no-store"})

@app.get("/api/orders/{order_id}/whatsapp/",response_model=WhatsAppStatusResponse)
def whatsapp_receipt_status(order_id:str,user=Depends(roles("admin","cashier","staff"))):
    # Verify restaurant ownership before looking up any send-status records.
    ref=restaurant_root(user["restaurant_id"]).collection("orders").document(order_id)
    if not ref.get().exists:
        raise HTTPException(404,"Order not found")
    record=restaurant_root(user["restaurant_id"]).collection("whatsapp_receipts").document(order_id).get()
    if not record.exists:
        return {"status":"not_sent"}
    data=record.to_dict()
    response={"status":data.get("state","unknown"),"message_id":data.get("message_id")}
    mid=data.get("message_id")
    if mid:
        status_doc=db.collection("whatsapp_status").document(event_id(mid)).get()
        if status_doc.exists:
            report=status_doc.to_dict()
            response["delivery_status"]=report.get("status")
            response["delivery_timestamp"]=report.get("event_at")
            response["error_codes"]=report.get("error_codes",[])
    return response

@app.post("/api/orders/{order_id}/whatsapp/",response_model=WhatsAppSendResponse)
def send_receipt_whatsapp(order_id:str,payload:ReceiptSendRequest,
                          request:Request,user=Depends(roles("admin","cashier","staff"))):
    return perform_whatsapp_send(order_id,payload,request,user,resend=False)

@app.post("/api/orders/{order_id}/whatsapp/resend/",response_model=WhatsAppSendResponse)
def resend_receipt_whatsapp(order_id:str,payload:ReceiptSendRequest,
                            request:Request,user=Depends(roles("admin","cashier","staff"))):
    return perform_whatsapp_send(order_id,payload,request,user,resend=True)

def perform_whatsapp_send(order_id,payload,request,user,resend=False):
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
    ref=restaurant_root(user["restaurant_id"]).collection("whatsapp_receipts").document(order_id)
    tx=db.transaction()
    @firestore.transactional
    def claim(transaction):
        snap=ref.get(transaction=transaction)
        data=snap.to_dict() if snap.exists else {}
        try:
            next_count=authorize_receipt_send(data,resend=resend,at=now())
        except SendDenied as failure:
            raise HTTPException(failure.status_code,failure.detail)
        transaction.set(ref,{"state":"sending","claimed_at":now(),
                             "created_by":user["id"],"attempt_count":next_count,
                             "last_attempt_by":actor_details(request,user)},merge=True)
    claim(tx)
    try:
        fields=[x.strip() for x in os.getenv("WHATSAPP_TEMPLATE_BODY_FIELDS","").split(",") if x.strip()]
        values={"customer_name":order.get("customer_name") or "Customer",
                "receipt_number":order.get("receipt_number") or order_id,
                "total":money(order["total_paise"]),
                "token_number":str(order.get("token_number","")),
                "restaurant_name":restaurant.get("name","Foodooo")}
        if any(field not in values for field in fields):
            raise WhatsAppConfigError("Unsupported template body field")
        filename="foodoo-"+str(order.get("receipt_number") or order_id)+".pdf"
        result=send_receipt_pdf(phone,build_receipt_pdf(restaurant,order),filename,
                                body_parameters=[values[field] for field in fields])
    except WhatsAppConfigError:
        ref.update({"state":"failed","updated_at":now(),"reason":"configuration"})
        raise HTTPException(503,"WhatsApp configuration is incomplete or invalid")
    except WhatsAppSendError:
        ref.update({"state":"review_required","updated_at":now(),"reason":"upstream_error"})
        raise HTTPException(502,"Meta did not confirm receipt submission; administrator review required before retrying")
    sent_at=now()
    batch=db.batch()
    batch.update(ref,{"state":"submitted","updated_at":sent_at,"last_sent_at":sent_at,
                "message_id":result["message_id"],"recipient":result["recipient"],"reason":None})
    batch.set(db.collection("whatsapp_message_links").document(event_id(result["message_id"])),{
        "order_id":order_id,"restaurant_id":user["restaurant_id"],
        "recipient":result["recipient"],"sent_at":sent_at})
    batch.commit()
    return {"status":"submitted","message_id":result["message_id"]}

@app.get("/api/whatsapp/statuses/",response_model=list[WhatsAppDeliveryItem])
def whatsapp_delivery_statuses(user=Depends(roles("admin"))):
    """Recent outbound Meta status events; read-only admin visibility."""
    docs=db.collection("whatsapp_status").order_by(
        "event_at",direction=firestore.Query.DESCENDING).limit(50).stream()
    return [{"id":doc.id,**doc.to_dict()} for doc in docs]


@app.get("/api/whatsapp/inbox/",response_model=list[WhatsAppInboxItem])
def whatsapp_inbox(user=Depends(roles("admin"))):
    """Authenticated admin read-only inbound messages; no automatic replies."""
    docs=db.collection("whatsapp_inbox").order_by(
        "received_at",direction=firestore.Query.DESCENDING).limit(50).stream()
    items=[]
    for doc in docs:
        item={"id":doc.id,**doc.to_dict()}
        if not item.get("order_id") and item.get("context_message_id"):
            link=db.collection("whatsapp_message_links").document(event_id(item["context_message_id"])).get()
            if link.exists:
                item["order_id"]=link.to_dict().get("order_id")
        items.append(item)
    return items


@app.get("/api/customers/lookup/",response_model=CustomerLookupResponse)
def lookup_customer(phone:str="",user=Depends(roles("admin","cashier","staff"))):
    if not phone or len(phone)>25:raise HTTPException(400,"Invalid phone number")
    orders=restaurant_root(user["restaurant_id"]).collection("orders").where("customer_phone","==",phone).limit(100).stream()
    paid=[x.to_dict() for x in orders if x.to_dict().get("status")=="paid"]
    if not paid:return {"customer_name":"","whatsapp_consent":False}
    recent=max(paid,key=lambda o:o.get("paid_at") or datetime.min.replace(tzinfo=timezone.utc))
    return {"customer_name":recent.get("customer_name",""),"whatsapp_consent":recent.get("whatsapp_consent",False)}

@app.get("/api/customers/suggest/",response_model=list[CustomerSuggestion])
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
