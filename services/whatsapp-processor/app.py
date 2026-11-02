"""Private Pub/Sub push processor: persist Meta event payloads in Firestore."""
import base64
import hashlib
import json
import os

from flask import Flask, request
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
db = firestore.Client()

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.post("/pubsub")
def persist():
    # Cloud Run IAM must enforce authenticated invocations for this service.
    envelope = request.get_json(silent=True)
    message = envelope.get("message") if isinstance(envelope, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("data"), str):
        return {"error": "missing Pub/Sub message"}, 400
    try:
        payload = json.loads(base64.b64decode(message["data"], validate=True))
    except (ValueError, UnicodeDecodeError):
        return {"error": "malformed event"}, 400
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return {"error": "unsupported event"}, 400
    # The same Meta retry produces the same canonical fingerprint.
    # A repeated identical payload is deliberately stored only once.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    collection = os.getenv("WHATSAPP_EVENTS_COLLECTION", "whatsapp_events")
    doc = {
        "source": "meta_whatsapp",
        "payload": payload,
        "payload_sha256": fingerprint,
        "pubsub_message_id": str(message.get("messageId", "")),
        "received_at": firestore.SERVER_TIMESTAMP,
        "processing_state": "received",
    }
    try:
        db.collection(collection).document(fingerprint).create(doc)
    except AlreadyExists:
        return {"ok": True, "duplicate": True}, 200
    except Exception:
        app.logger.exception("Firestore event persistence failed")
        return {"error": "storage unavailable"}, 503
    return {"ok": True}, 200
