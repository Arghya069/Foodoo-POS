"""Meta WhatsApp Cloud API callbacks for a single Foodoo restaurant/project.

GET verifies the callback subscription. POST requires the Meta app secret
HMAC-SHA256 over RAW request bytes (not JSON re-serialization).

Verified messages, button replies and statuses are stored in restaurant-
project Firestore. The application never auto-replies or changes POS orders.
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

logger=logging.getLogger("foodoo.meta_webhook")
MAX_BYTES=1024*1024
router=APIRouter(tags=["Meta WhatsApp webhook"])


def event_id(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def verify_signature(body:bytes,header:str,secret:str)->bool:
    if not secret or not header.startswith("sha256="):
        return False
    expected="sha256="+hmac.new(secret.encode("utf-8"),body,hashlib.sha256).hexdigest()
    return hmac.compare_digest(header,expected)


def parse_meta_time(value):
    try:
        if value is not None:
            return datetime.fromtimestamp(int(value),timezone.utc)
    except (TypeError,ValueError,OverflowError):
        pass
    return datetime.now(timezone.utc)


def extract_reply(message):
    """Untrusted inbound content; limit text and never interpret as a command."""
    kind=str(message.get("type") or "unknown")[:40]
    detail=message.get(kind)
    if not isinstance(detail,dict):
        detail={}
    if kind=="text":
        text=detail.get("body") or ""
    elif kind=="button":
        text=detail.get("text") or detail.get("payload") or ""
    elif kind=="interactive":
        interactive=detail.get("button_reply") or detail.get("list_reply") or {}
        text=interactive.get("title") or interactive.get("id") or ""
    elif kind=="reaction":
        text=detail.get("emoji") or ""
    else:
        text="[Received "+kind+" message]"
    return kind,str(text)[:4000]


def merge_status(db,status):
    message_id=status.get("id")
    if not isinstance(message_id,str) or not message_id:
        return False
    timestamp=parse_meta_time(status.get("timestamp"))
    new_status=str(status.get("status") or "unknown")[:32]
    errors=status.get("errors") or []
    error_codes=[str(x.get("code")) for x in errors[:3] if isinstance(x,dict)]
    ref=db.collection("whatsapp_status").document(event_id(message_id))
    tx=db.transaction()
    @firestore.transactional
    def persist(transaction):
        prior=ref.get(transaction=transaction)
        old=prior.to_dict() if prior.exists else {}
        previous=old.get("event_at")
        # Old or duplicated webhooks must not roll back a delivered/read state.
        if previous and previous>timestamp:
            return False
        rank={"failed":0,"sent":1,"delivered":2,"read":3,"played":4}
        if previous==timestamp and rank.get(new_status,-1)<rank.get(old.get("status"),-1):
            return False
        transaction.set(ref,{
            "meta_message_id":message_id,
            "status":new_status,
            "recipient":str(status.get("recipient_id") or "")[:30],
            "event_at":timestamp,
            "updated_at":firestore.SERVER_TIMESTAMP,
            "error_codes":error_codes
        },merge=True)
        return True
    return persist(tx)


def persist_meta_events(db,payload,expected_phone_id=None):
    if not isinstance(payload,dict) or payload.get("object")!="whatsapp_business_account":
        raise ValueError("Unsupported WhatsApp event object")
    entries=payload.get("entry")
    if not isinstance(entries,list):
        raise ValueError("Missing WhatsApp event entries")
    result={"incoming":0,"statuses":0,"changes":0}
    for entry in entries:
        if not isinstance(entry,dict):
            continue
        for change in entry.get("changes",[]):
            if not isinstance(change,dict):
                continue
            value=change.get("value")
            if not isinstance(value,dict):
                continue
            phone_id=str((value.get("metadata") or {}).get("phone_number_id") or "")
            if expected_phone_id and phone_id and phone_id!=expected_phone_id:
                logger.warning("Ignoring event from different WhatsApp phone number ID")
                continue
            field=str(change.get("field") or "unknown")[:60]
            for message in value.get("messages",[]):
                if not isinstance(message,dict) or not message.get("id"):
                    continue
                mid=str(message["id"])
                kind,body=extract_reply(message)
                doc={
                    "message_id":mid,
                    "sender":str(message.get("from") or "")[:30],
                    "message_type":kind,
                    "body":body,
                    "context_message_id":str((message.get("context") or {}).get("id") or "")[:150],
                    "received_at":parse_meta_time(message.get("timestamp")),
                    "recorded_at":firestore.SERVER_TIMESTAMP
                }
                try:
                    db.collection("whatsapp_inbox").document(event_id(mid)).create(doc)
                    result["incoming"]+=1
                except AlreadyExists:
                    pass
            for status in value.get("statuses",[]):
                if isinstance(status,dict) and merge_status(db,status):
                    result["statuses"]+=1
            # Track feedback/quality/account changes without storing raw PII.
            if field!="messages":
                descriptor=json.dumps({"field":field,"entry":entry.get("id"),
                                       "event":value},sort_keys=True,default=str)
                fingerprint=event_id(descriptor)
                try:
                    db.collection("whatsapp_events").document(fingerprint).create({
                        "event_type":field,
                        "received_at":firestore.SERVER_TIMESTAMP,
                        "payload":value
                    })
                    result["changes"]+=1
                except AlreadyExists:
                    pass
    return result


@router.get("/webhooks/meta")
def meta_verify(request:Request):
    verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN","")
    supplied=request.query_params.get("hub.verify_token","")
    challenge=request.query_params.get("hub.challenge","")
    if (verify_token and request.query_params.get("hub.mode")=="subscribe" and
            challenge and hmac.compare_digest(supplied,verify_token)):
        return Response(content=challenge,media_type="text/plain")
    raise HTTPException(status_code=403,detail="Webhook verification failed")


def create_webhook_receiver(db):
    """Register the secured POST handler against the app's existing Firestore client."""
    @router.post("/webhooks/meta")
    async def meta_receive(request:Request):
        size=request.headers.get("content-length")
        if size:
            try:
                if int(size)>MAX_BYTES:
                    raise HTTPException(413,"Webhook body too large")
            except ValueError:
                raise HTTPException(400,"Invalid content length")
        raw=await request.body()
        if len(raw)>MAX_BYTES:
            raise HTTPException(413,"Webhook body too large")
        secret=os.getenv("WHATSAPP_APP_SECRET","")
        if not secret:
            raise HTTPException(503,"Webhook signature verification not configured")
        if not verify_signature(raw,request.headers.get("x-hub-signature-256",""),secret):
            raise HTTPException(403,"Invalid Meta signature")
        try:
            payload=json.loads(raw)
        except (UnicodeDecodeError,json.JSONDecodeError):
            raise HTTPException(400,"Invalid JSON")
        try:
            counts=persist_meta_events(db,payload,os.getenv("WHATSAPP_PHONE_NUMBER_ID") or None)
        except ValueError:
            raise HTTPException(400,"Invalid WhatsApp payload")
        except Exception:
            logger.exception("Failed to persist verified Meta webhook event")
            # Meta retries non-2xx delivery; do not acknowledge lost data.
            raise HTTPException(503,"Webhook persistence temporarily unavailable")
        logger.info("WhatsApp verified webhook persisted events: %s",counts)
        return {"ok":True}
    return router
