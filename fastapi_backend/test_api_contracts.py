"""FastAPI request/response contracts, PDF and Meta template unit tests."""
from datetime import datetime, timezone
from io import BytesIO

import pytest
from pydantic import ValidationError
from pypdf import PdfReader
from reportlab.lib.units import mm

from receipt_pdf import build_receipt_pdf
from schemas import (Credentials, MenuInput, MenuPatch, OrderInput, RestaurantResponse,
                     RestaurantUpdate, StaffCreate, StaffPatch, TokenResponse, PaidResponse)
from sessions import document_id
from whatsapp_send import build_template, normalize_phone


@pytest.fixture
def receipt_data():
    restaurant = {"name": "1More", "address": "Infocity, Bhubaneswar",
                  "fssai_license_number": "12345678901234"}
    order = {"status": "paid", "receipt_number": "FD-001", "token_number": 7,
             "paid_at": datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc),
             "payment_method": "upi", "customer_name": "Test Customer",
             "lines": [{"name": "Chicken Biryani", "quantity": 2,
                        "unit_price_paise": 20000, "line_total_paise": 40000},
                       {"name": "Mutton Rogan Josh", "quantity": 1,
                        "unit_price_paise": 30000, "line_total_paise": 30000}],
             "subtotal_paise": 70000, "cgst_paise": 1750, "sgst_paise": 1750,
             "total_paise": 73500}
    return restaurant, order


def test_receipt_57mm_columns_fssai_and_totals(receipt_data):
    raw = build_receipt_pdf(*receipt_data)
    page = PdfReader(BytesIO(raw)).pages[0]
    assert abs(float(page.mediabox.width) - 57 * mm) <= 1
    text = page.extract_text()
    for part in ("ITEM", "QTY", "UNIT", "TOTAL", "Chicken Biryani",
                 "Mutton Rogan", "Josh", "FSSAI Lic. No.: 12345678901234",
                 "735.00", "TOKEN #7", "Thank you!"):
        assert part in text


def test_meta_document_template_shape():
    payload = build_template("918249672385", "media-123", "receipt.pdf",
                             {"template_name": "foodoo_receipt", "language": "en_US"},
                             ["Customer", "735.00"])
    assert payload["template"]["components"][0]["parameters"][0]["document"]["id"] == "media-123"
    assert payload["template"]["components"][1]["parameters"][0]["text"] == "Customer"


@pytest.mark.parametrize("phone,normalized", [("8249672385","918249672385"),
                                                  ("+91 82496 72385","918249672385")])
def test_normalize_phone(phone, normalized):
    assert normalize_phone(phone) == normalized


@pytest.mark.parametrize("invalid", ["not a phone", "", "123"])
def test_reject_invalid_phone(invalid):
    with pytest.raises(ValueError):
        normalize_phone(invalid)


def test_session_doc_id_does_not_include_raw_cookie():
    assert len(document_id("test-cookie")) == 64
    assert "test-cookie" not in document_id("test-cookie")


@pytest.mark.parametrize("invalid", ["1234", "abc12345678901", "123456789012345"])
def test_fssai_validation_rejects_malformed_license(invalid):
    with pytest.raises(ValidationError):
        RestaurantUpdate(fssai_license_number=invalid)


def test_patch_omits_unset_fields():
    data = RestaurantUpdate(fssai_license_number="12345678901234")
    assert data.model_dump(exclude_unset=True) == {"fssai_license_number":"12345678901234"}
    assert MenuPatch(active=False).model_dump(exclude_unset=True) == {"active":False}
    assert StaffPatch(role="chef").model_dump(exclude_unset=True) == {"role":"chef"}


def test_unknown_restaurant_field_rejected():
    with pytest.raises(ValidationError):
        RestaurantUpdate(id="server-owned-doc-id")


def test_request_validation():
    with pytest.raises(ValidationError):
        OrderInput(items=[{"id": "item1", "quantity": 0}])
    with pytest.raises(ValidationError):
        StaffCreate(username="joe", password="short", role="cashier")
    with pytest.raises(ValidationError):
        MenuInput(name="", price="10.00")


def test_response_models_retain_frontend_contract():
    restaurant = RestaurantResponse(id="one-more", name="1More")
    assert restaurant.cgst_rate == "2.50"
    token = TokenResponse(date="2026-11-04",last_issued=2,currently_serving=1)
    assert token.model_dump()["last_issued"] == 2
    paid = PaidResponse(id="o",status="paid",receipt_number="FD-1",
                        payment_method="upi",total="210.00",
                        whatsapp_consent=True,token_number=9)
    assert paid.model_dump()["token_number"] == 9


def test_login_request_redacts_unknown_fields():
    with pytest.raises(ValidationError):
        Credentials(username="admin",password="strong",admin=True)


def test_fastapi_openapi_documents_request_and_response_models(monkeypatch):
    monkeypatch.setenv("FOODOO_SESSION_SECRET", "test-secret-longer-than-thirty-two-characters")
    monkeypatch.setenv("FOODOO_FIRESTORE_PROJECT", "foodoo-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8089")
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    client = TestClient(fastapi_app)
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    routes = spec.json()["paths"]
    update = routes["/api/restaurant/"]["patch"]
    assert update["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("RestaurantUpdate")
    assert update["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("RestaurantResponse")
    assert routes["/api/orders/"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("OrderCreatedResponse")
