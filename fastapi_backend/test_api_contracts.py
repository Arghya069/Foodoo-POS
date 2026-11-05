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


def test_optional_fssai_and_gstin_are_omitted_when_blank(receipt_data):
    restaurant,order=receipt_data
    restaurant={**restaurant,"fssai_license_number":"","gstin":""}
    page=PdfReader(BytesIO(build_receipt_pdf(restaurant,order))).pages[0]
    text=page.extract_text()
    assert "FSSAI" not in text
    assert "GSTIN" not in text
    assert "Thank you!" in text


def test_configured_fssai_and_gstin_both_print(receipt_data):
    restaurant,order=receipt_data
    restaurant={**restaurant,"gstin":"22AAAAA0000A1Z5"}
    text=PdfReader(BytesIO(build_receipt_pdf(restaurant,order))).pages[0].extract_text()
    assert "GSTIN: 22AAAAA0000A1Z5" in text
    assert "FSSAI Lic. No.: 12345678901234" in text


def test_long_receipt_still_has_fssai_before_thank_you(receipt_data):
    restaurant,order=receipt_data
    order={**order,"lines":[{
        "name":"Very Long Tandoori Special Chicken Biryani Serving Family Portion",
        "quantity":2,"unit_price_paise":20000,"line_total_paise":40000,
    } for _ in range(15)]}
    page=PdfReader(BytesIO(build_receipt_pdf(restaurant,order))).pages[0]
    words=page.extract_text()
    assert words.index("FSSAI Lic. No.: 12345678901234") < words.index("Thank you!")
    assert float(page.mediabox.height)>118*mm


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


@pytest.mark.parametrize("rate",["-1","101","2.555","NaN","Infinity","abc"])
def test_untrusted_tax_rates_are_rejected(rate):
    with pytest.raises(ValidationError):
        RestaurantUpdate(cgst_rate=rate)


def test_file_upload_and_order_payload_limits():
    with pytest.raises(ValidationError):
        MenuInput(name="Dish",price="10",image_data="a"*210001)
    with pytest.raises(ValidationError):
        OrderInput(items=[{"id":"dish","quantity":1}]*2001)


def test_prod_security_headers_and_api_cache_policy(monkeypatch):
    monkeypatch.setenv("FOODOO_SESSION_SECRET", "test-secret-longer-than-thirty-two-characters")
    monkeypatch.setenv("FOODOO_FIRESTORE_PROJECT", "foodoo-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8089")
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    response=TestClient(fastapi_app).get("/healthz")
    assert response.status_code==200
    assert response.headers["x-content-type-options"]=="nosniff"
    assert response.headers["x-frame-options"]=="DENY"
    protected=TestClient(fastapi_app).get("/api/auth/csrf/")
    assert protected.headers["cache-control"]=="no-store"
