"""Meta WhatsApp Cloud API receiver. Publish before acknowledging delivery."""
import hashlib
import hmac
import json
import os
from concurrent.futures import TimeoutError as FutureTimeout

from flask import Flask, Response, request
from google.cloud import pubsub_v1

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
publisher = pubsub_v1.PublisherClient()

def required(name):
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Missing environment variable {name}")
    return value

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    expected = required("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and hmac.compare_digest(token, expected) and challenge:
        return Response(challenge, status=200, content_type="text/plain")
    return {"error": "verification failed"}, 403

@app.post("/webhook")
def receive():
    raw = request.get_data(cache=False)
    secret = required("WHATSAPP_APP_SECRET").encode("utf-8")
    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        return {"error": "invalid signature"}, 403
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"error": "invalid JSON"}, 400
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return {"error": "unsupported event object"}, 400
    topic = required("WHATSAPP_EVENTS_TOPIC")
    try:
        # Preserve raw Meta payload and let the processor apply idempotency.
        message_id = publisher.publish(topic, raw, source="meta-whatsapp").result(timeout=10)
    except (Exception, FutureTimeout):
        app.logger.exception("WhatsApp event publish failed")
        return {"error": "temporary delivery failure"}, 503
    app.logger.info("WhatsApp webhook accepted Pub/Sub id %s", message_id)
    return {"ok": True}, 200
