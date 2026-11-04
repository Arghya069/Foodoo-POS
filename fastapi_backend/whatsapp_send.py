"""Meta WhatsApp Cloud API PDF template sender.

Credential values only from environment/Secret Manager. Never return tokens
or raw upstream error responses to browser users.
"""
import io
import logging
import os
import re

import httpx

logger = logging.getLogger("foodoo.whatsapp")


class WhatsAppConfigError(Exception):
    pass


class WhatsAppSendError(Exception):
    pass


def settings():
    names = {
        "token": "WHATSAPP_ACCESS_TOKEN",
        "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID",
        "template_name": "WHATSAPP_TEMPLATE_NAME",
        "language": "WHATSAPP_TEMPLATE_LANGUAGE",
    }
    values = {key: os.getenv(env, "").strip() for key, env in names.items()}
    if not all(values.values()):
        raise WhatsAppConfigError("WhatsApp sending has not been configured")
    version = os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0")
    if not re.fullmatch(r"v\d+\.0", version):
        raise WhatsAppConfigError("Invalid Graph API version")
    if not re.fullmatch(r"\d+", values["phone_number_id"]):
        raise WhatsAppConfigError("Invalid WhatsApp phone number ID")
    values["version"] = version
    return values


def normalize_phone(phone, default_country="91"):
    """Accept E.164-ish phone numbers; add +91 to 10-digit Indian numbers."""
    cleaned = re.sub(r"[\s()+-]", "", str(phone or ""))
    if not cleaned.isdigit():
        raise ValueError("Customer phone must contain digits")
    if len(cleaned) == 10:
        cleaned = default_country + cleaned
    if not 8 <= len(cleaned) <= 15:
        raise ValueError("Customer phone must be 8-15 digits including country code")
    return cleaned


def build_template(to, media_id, filename, config, body_parameters=None):
    parts = [{
        "type": "header",
        "parameters": [{
            "type": "document",
            "document": {"id": media_id, "filename": filename},
        }],
    }]
    if body_parameters:
        parts.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in body_parameters],
        })
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": config["template_name"],
            "language": {"code": config["language"]},
            "components": parts,
        },
    }


def send_receipt_pdf(phone, pdf_bytes, filename, body_parameters=None):
    """Upload PDF to Meta media, then send an approved document-header template."""
    config = settings()
    destination = normalize_phone(phone)
    api = f'https://graph.facebook.com/{config["version"]}/{config["phone_number_id"]}'
    headers = {"Authorization": "Bearer " + config["token"]}
    try:
        with httpx.Client(timeout=25.0) as client:
            uploaded = client.post(
                api + "/media",
                headers=headers,
                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                files={"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")},
            )
            uploaded.raise_for_status()
            media_id = uploaded.json()["id"]
            sent = client.post(
                api + "/messages",
                headers=headers,
                json=build_template(destination, media_id, filename, config, body_parameters),
            )
            sent.raise_for_status()
            message_ids = [m.get("id") for m in sent.json().get("messages", [])]
            if not message_ids or not message_ids[0]:
                raise WhatsAppSendError("WhatsApp did not confirm a message ID")
    except httpx.HTTPStatusError as exc:
        # Log the stage/status, never the Authorization header or raw response.
        stage = "media_upload" if exc.request.url.path.endswith("/media") else "template_send"
        logger.warning("Meta WhatsApp %s rejected request with HTTP %s", stage, exc.response.status_code)
        raise WhatsAppSendError("WhatsApp media upload or template send failed") from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Meta WhatsApp request failed: %s", type(exc).__name__)
        raise WhatsAppSendError("WhatsApp media upload or template send failed") from exc
    return {"message_id": message_ids[0], "recipient": destination}
