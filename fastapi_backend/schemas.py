"""Validated public API request/response contracts.

Keep Firestore document shape private: these models describe the HTTP API,
not the database persistence representation.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Credentials(StrictRequest):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1)

class LoginResponse(BaseModel):
    username: str

class MeResponse(BaseModel):
    username: str
    role: str
    restaurant_id: str

class RestaurantUpdate(StrictRequest):
    name: str | None = Field(default=None,max_length=160)
    address: str | None = Field(default=None,max_length=500)
    contact_phone: str | None = None
    gstin: str | None = None
    fssai_license_number: str | None = None
    logo_data: str | None = Field(default=None,max_length=210000)
    branch_type: Literal["main","branch"] | None = None
    branch_name: str | None = None
    branch_code: str | None = None
    cgst_rate: str | None = None
    sgst_rate: str | None = None

    @field_validator("cgst_rate","sgst_rate")
    @classmethod
    def validate_tax_rate(cls,value):
        if value is None:
            return value
        try:
            rate=Decimal(value)
            if not rate.is_finite() or rate < 0 or rate > 100 or rate.as_tuple().exponent < -2:
                raise ValueError("Tax rate must be between 0 and 100 with up to two decimals")
        except (InvalidOperation,TypeError):
            raise ValueError("Tax rate must be numeric")
        return value

    @field_validator("fssai_license_number")
    @classmethod
    def validate_fssai(cls, value):
        if value not in (None, "") and (len(value) != 14 or not value.isdigit()):
            raise ValueError("FSSAI license number must be 14 digits")
        return value

class RestaurantResponse(BaseModel):
    id: str
    name: str
    address: str = ""
    contact_phone: str = ""
    gstin: str = ""
    fssai_license_number: str = ""
    logo_data: str = ""
    branch_type: str = "main"
    branch_name: str = "Main"
    branch_code: str = "main"
    cgst_rate: str = "2.50"
    sgst_rate: str = "2.50"

class MenuInput(StrictRequest):
    name: str = Field(min_length=1, max_length=160)
    price: str = Field(min_length=1,max_length=20)
    description: str = Field(default="",max_length=2000)
    food_type: str = "veg"
    food_subtype: str = "none"
    category: str = "main_course"
    image_url: str = Field(default="",max_length=2048)
    image_data: str = Field(default="",max_length=210000)
    active: bool = True

class MenuPatch(StrictRequest):
    name: str | None = None
    price: str | None = Field(default=None,max_length=20)
    description: str | None = Field(default=None,max_length=2000)
    food_type: str | None = None
    food_subtype: str | None = None
    category: str | None = None
    image_url: str | None = Field(default=None,max_length=2048)
    image_data: str | None = Field(default=None,max_length=210000)
    active: bool | None = None

class MenuResponse(BaseModel):
    id: str
    name: str
    price: str
    description: str = ""
    food_type: str = "veg"
    food_subtype: str = "none"
    category: str = "main_course"
    image_url: str = ""
    image_data: str = ""
    active: bool = True
    price_paise: int = 0

class LineInput(StrictRequest):
    id: str
    quantity: int = Field(ge=1, le=999)

class OrderInput(StrictRequest):
    items: list[LineInput] = Field(min_length=1,max_length=2000)
    customer_name: str = Field(default="", max_length=160)
    customer_phone: str = Field(default="", max_length=25)
    whatsapp_consent: bool = False

class OrderCreatedResponse(BaseModel):
    id: str
    status: str
    token_number: int
    token_date: str
    subtotal: str
    cgst: str
    sgst: str
    total: str

class Payment(StrictRequest):
    payment_method: Literal["cash","card","upi"]

class PaidResponse(BaseModel):
    id: str
    status: str
    receipt_number: str
    payment_method: str
    total: str
    whatsapp_consent: bool
    token_number: int

class ServingUpdate(StrictRequest):
    currently_serving: int = Field(ge=0)

class TokenResponse(BaseModel):
    date: str
    last_issued: int
    currently_serving: int

class StaffCreate(StrictRequest):
    username: str = Field(min_length=2,max_length=150)
    first_name: str = ""
    password: str = Field(min_length=10)
    role: Literal["admin","cashier","chef","partner"]

class StaffPatch(StrictRequest):
    role: Literal["admin","cashier","chef","partner"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None,min_length=10)
    first_name: str | None = None

class StaffResponse(BaseModel):
    id: str
    username: str
    first_name: str = ""
    role: str
    active: bool = True

class ReceiptSendRequest(StrictRequest):
    confirm: bool = True

class WhatsAppStatusResponse(BaseModel):
    status: str
    message_id: str | None = None
    delivery_status: str | None = None
    delivery_timestamp: datetime | None = None
    error_codes: list[str] = Field(default_factory=list)

class WhatsAppSendResponse(BaseModel):
    status: str
    message_id: str

class SuccessResponse(BaseModel):
    ok: bool = True

class OrderListRow(BaseModel):
    id: str
    status: str
    total: str
    receipt_number: str | None = None

class OrderItemResponse(BaseModel):
    name: str
    quantity: int
    unit_price: str
    total: str

class OrderHistoryRow(BaseModel):
    id: str
    created_by_username: str = "Unknown"
    status: str
    receipt_number: str | None = None
    token_number: int | None = None
    token_date: str | None = None
    customer_name: str = ""
    customer_phone: str = ""
    payment_method: str = ""
    whatsapp_consent: bool = False
    subtotal: str
    cgst: str
    sgst: str
    total: str
    created_at: str
    paid_at: str | None = None
    items: list[OrderItemResponse]

class OrderHistoryResponse(BaseModel):
    count: int
    page: int
    page_size: int
    results: list[OrderHistoryRow]

class SalesBreakdown(BaseModel):
    method: str
    orders: int
    revenue: str

class SalesByDay(BaseModel):
    date: str
    orders: int
    revenue: str

class SalesReportResponse(BaseModel):
    start: str
    end: str
    orders: int
    subtotal: str
    cgst: str
    sgst: str
    revenue: str
    payment_methods: list[SalesBreakdown]
    daily: list[SalesByDay]

class KitchenItem(BaseModel):
    name: str
    quantity: int

class KitchenOrder(BaseModel):
    id: str
    token_number: int | None = None
    token_date: str | None = None
    paid_at: str | None = None
    items: list[KitchenItem]

class CustomerSuggestion(BaseModel):
    customer_name: str = ""
    customer_phone: str = ""
    whatsapp_consent: bool = False

class CustomerLookupResponse(BaseModel):
    customer_name: str = ""
    whatsapp_consent: bool = False

class SessionResponse(BaseModel):
    id: str
    current: bool
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime

class AuditDevice(BaseModel):
    device_label: str | None = None
    browser_device_id: str | None = None
    observed_ip: str | None = None
    user_agent: str | None = None

class AuditActor(BaseModel):
    user_id: str
    username: str
    role: str
    session_id: str | None = None
    device: AuditDevice

class OrderAuditResponse(BaseModel):
    order_id: str
    created_at: datetime
    created_by: str
    creation: AuditActor | None = None
    payment: AuditActor | None = None

class WhatsAppInboxItem(BaseModel):
    id: str
    order_id: str | None = None
    message_id: str
    sender: str
    message_type: str
    body: str
    context_message_id: str = ""
    received_at: datetime

class WhatsAppDeliveryItem(BaseModel):
    id: str
    meta_message_id: str
    status: str
    recipient: str = ""
    event_at: datetime
    error_codes: list[str] = Field(default_factory=list)
