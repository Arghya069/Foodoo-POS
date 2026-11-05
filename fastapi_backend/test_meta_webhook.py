"""Meta WhatsApp webhook verification and safe event parsing tests."""
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists

from meta_webhook import extract_reply, verify_signature, persist_meta_events, event_id


@pytest.fixture
def signed_client(monkeypatch):
    monkeypatch.setenv("FOODOO_SESSION_SECRET","ci-session-secret-at-least-32-chars")
    monkeypatch.setenv("FOODOO_FIRESTORE_PROJECT","foodoo-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST","127.0.0.1:8089")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN","unit-test-verification-secret")
    monkeypatch.setenv("WHATSAPP_APP_SECRET","unit-test-meta-app-secret")
    from app import app
    return TestClient(app)


def test_meta_verify_callback(signed_client):
    query={"hub.mode":"subscribe","hub.verify_token":"unit-test-verification-secret",
           "hub.challenge":"challenge-8877"}
    response=signed_client.get("/webhooks/meta",params=query)
    assert response.status_code==200
    assert response.text=="challenge-8877"
    query["hub.verify_token"]="wrong"
    assert signed_client.get("/webhooks/meta",params=query).status_code==403


def test_signed_webhook_rejects_missing_or_forged_signature(signed_client):
    body=b'{"object":"whatsapp_business_account","entry":[]}'
    assert signed_client.post("/webhooks/meta",content=body).status_code==403
    assert signed_client.post("/webhooks/meta",content=body,
          headers={"X-Hub-Signature-256":"sha256="+"0"*64}).status_code==403


def test_signed_webhook_accepts_valid_signature(signed_client,monkeypatch):
    import meta_webhook
    stored=[]
    monkeypatch.setattr(meta_webhook,"persist_meta_events",
                        lambda db,payload,phone:stored.append(payload) or {"incoming":1})
    payload={"object":"whatsapp_business_account","entry":[]}
    body=json.dumps(payload).encode()
    signature="sha256="+hmac.new(b"unit-test-meta-app-secret",body,hashlib.sha256).hexdigest()
    response=signed_client.post("/webhooks/meta",content=body,
                                headers={"X-Hub-Signature-256":signature})
    assert response.status_code==200
    assert stored==[payload]


@pytest.mark.parametrize("kind,value,expected",[
    ("text",{"body":"Great food!"},"Great food!"),
    ("button",{"text":"Good"},"Good"),
    ("interactive",{"button_reply":{"title":"Loved it"}},"Loved it"),
    ("reaction",{"emoji":"👍"},"👍")
])
def test_extract_customer_replies(kind,value,expected):
    assert extract_reply({"type":kind,kind:value})==(kind,expected)


def test_signature_comparison():
    payload=b'{"test":true}'
    sig="sha256="+hmac.new(b"secret",payload,hashlib.sha256).hexdigest()
    assert verify_signature(payload,sig,"secret")
    assert not verify_signature(payload+b" ",sig,"secret")
    assert not verify_signature(payload,sig,"other")


class StubDoc:
    def __init__(self,path,store):
        self.path=path
        self.store=store
    def create(self,data):
        if self.path in self.store:
            raise AlreadyExists("duplicate")
        self.store[self.path]=data


class StubCollection:
    def __init__(self,name,store):
        self.name=name
        self.store=store
    def document(self,id):
        return StubDoc(self.name+"/"+id,self.store)


class StubDb:
    def __init__(self):
        self.store={}
    def collection(self,name):
        return StubCollection(name,self.store)


def test_incoming_messages_deduplicated(monkeypatch):
    import meta_webhook
    monkeypatch.setattr(meta_webhook,"merge_status",lambda db,status:True)
    db=StubDb()
    payload={"object":"whatsapp_business_account",
             "entry":[{"id":"WABA","changes":[{"field":"messages",
                "value":{"metadata":{"phone_number_id":"12345"},"messages":[
                    {"id":"wamid.test","from":"919999999999","timestamp":"1790000000",
                     "type":"text","text":{"body":"Thank you!"}}]}}]}]}
    assert persist_meta_events(db,payload,"12345")["incoming"]==1
    assert persist_meta_events(db,payload,"12345")["incoming"]==0
    assert len(db.store)==1
    assert list(db.store.values())[0]["body"]=="Thank you!"


def test_ignore_other_number_payload():
    db=StubDb()
    payload={"object":"whatsapp_business_account",
             "entry":[{"changes":[{"field":"messages","value":{
                 "metadata":{"phone_number_id":"DIFFERENT"},
                 "messages":[{"id":"m","type":"text","text":{"body":"private"}}]}}]}]}
    assert persist_meta_events(db,payload,"OUR_NUMBER")["incoming"]==0
    assert not db.store
