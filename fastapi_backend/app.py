"""Foodoo alternative API: FastAPI + Firestore.

Proof-of-architecture implementation. Never point the production frontend at
this API until the parity and migration checklist is completed.
"""
import os
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
    allowed={"name","address","contact_phone","gstin","logo_data","branch_type","branch_name","branch_code","cgst_rate","sgst_rate"}
    if set(changes)-allowed:
        raise HTTPException(400,"Unknown restaurant settings")
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
