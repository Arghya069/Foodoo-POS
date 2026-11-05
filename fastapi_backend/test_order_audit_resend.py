"""Policy and privacy unit tests: no network or Firestore required."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
from starlette.requests import Request

from order_audit import actor_details, device_details, peer_address
from whatsapp_policy import SendDenied, authorize_receipt_send


NOW=datetime(2026,11,5,8,0,tzinfo=timezone.utc)


@pytest.mark.parametrize("record,resend,expected",[
    ({},False,1),
    ({"state":"failed","attempt_count":1},False,2),
    ({"state":"submitted","attempt_count":1,"last_sent_at":NOW-timedelta(minutes=3)},True,2),
])
def test_allowed_receipt_sends(record,resend,expected):
    assert authorize_receipt_send(record,resend,at=NOW)==expected


@pytest.mark.parametrize("record,resend,status",[
    ({"state":"submitted"},False,409),
    ({"state":"sending"},True,409),
    ({"state":"review_required"},False,409),
    ({"state":"not_sent"},True,409),
    ({"state":"submitted","last_sent_at":NOW-timedelta(seconds=30)},True,429),
    ({"state":"submitted","attempt_count":3},True,429),
])
def test_resend_guards(record,resend,status):
    with pytest.raises(SendDenied) as error:
        authorize_receipt_send(record,resend,at=NOW)
    assert error.value.status_code==status


def request(ip="203.0.113.44",headers=None):
    values=[(k.encode(),v.encode()) for k,v in (headers or {}).items()]
    scope={"type":"http","method":"POST","path":"/api/orders/",
           "headers":values,"client":(ip,54321),"server":("app",8001),"scheme":"https"}
    return Request(scope)


def test_device_and_authenticated_actor_capture():
    browser_id=str(uuid.uuid4())
    req=request(headers={"x-foodoo-device-id":browser_id,
                         "x-foodoo-device-label":"Cash Counter 1",
                         "user-agent":"Foodoo-Test Browser",
                         "x-forwarded-for":"8.8.8.8"})
    recorded=actor_details(req,{"id":"admin","username":"cashier1",
                                "role":"cashier","_session_id":"opaque-hash"})
    assert recorded["username"]=="cashier1"
    assert recorded["device"]["browser_device_id"]==browser_id
    assert recorded["device"]["device_label"]=="Cash Counter 1"
    assert recorded["device"]["observed_ip"]=="203.0.113.44"
    assert recorded["device"]["user_agent"]=="Foodoo-Test Browser"
    # Never accept the caller's arbitrary X-Forwarded-For as authoritative.
    assert recorded["device"]["observed_ip"]!="8.8.8.8"


@pytest.mark.parametrize("id_value",["not-a-uuid","",str(uuid.uuid4())+"evil"])
def test_invalid_browser_identifier_is_discarded(id_value):
    details=device_details(request(headers={"x-foodoo-device-id":id_value}))
    assert details["browser_device_id"] is None


def test_unavailable_network_address_is_not_invented():
    assert peer_address(request("not-an-ip")) is None


def test_device_label_sanitized():
    req=request(headers={"x-foodoo-device-label":"Counter<script>alert(1)</script>"})
    assert "<" not in (device_details(req)["device_label"] or "")
