"""Validated public API request/response contracts.

Keep Firestore document shape private: these models describe the HTTP API,
not the database persistence representation.
"""
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
    name: str | None = None
    address: str | None = None
    contact_phone: str | None = None
    gstin: str | None = None
    fssai_license_number: str | None = None
    logo_data: str | None = None
    branch_type: Literal["main","branch"] | None = None
    branch_name: str | None = None
    branch_code: str | None = None
    cgst_rate: str | None = None
    sgst_rate: str | None = None

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
    price: str
    description: str = ""
    food_type: str = "veg"
    food_subtype: str = "none"
    category: str = "main_course"
    image_url: str = ""
    image_data: str = ""
    active: bool = True

class MenuPatch(StrictRequest):
    name: str | None = None
    price: str | None = None
    description: str | None = None
    food_type: str | None = None
    food_subtype: str | None = None
    category: str | None = None
    image_url: str | None = None
    image_data: str | None = None
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
    items: list[LineInput] = Field(min_length=1)
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

class WhatsAppSendResponse(BaseModel):
    status: str
    message_id: str
