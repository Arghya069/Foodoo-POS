# FastAPI / Firestore: WhatsApp PDF, FSSAI, sessions and Docker

Branch: `feat/fastapi-firestore-parity`. Not yet a production rollout.

## What works

- Restaurant settings include an optional **14-digit FSSAI license number**.
- Paid receipt PDFs are rendered on **57 mm paper**, with four columns:
  Item | Qty | Unit (price per serving) | Total. Long item names wrap.
- FSSAI number prints at the bottom, immediately before “Thank you!”.
- Staff with cashier access can request sending a **paid** receipt through
  an **approved WhatsApp document-header template**, only if the order's
  WhatsApp consent flag is true and a valid customer phone is recorded.
- FastAPI sessions use opaque random cookies, hashed Firestore session IDs,
  an 8-hour absolute limit, 60-minute inactivity limit, last-active tracking,
  logout, per-device revocation and logout-all.
- CSRF tokens are server-signed and must be supplied on login and mutations.
- A separate frontend image serves React through Nginx, proxying /api to
  the FastAPI service in the local Docker Compose stack.

## Meta WhatsApp Cloud API setup

The `WHATSAPP_ACCESS_TOKEN` is a **Meta Cloud API access token**, NOT a
random API key from a third-party messaging provider.
You also need your WhatsApp Business **phone number ID**,
an **approved template NAME** (not the template's numeric management ID),
and exact template language code.

Keep these in `fastapi_backend/.env` locally or Secret Manager in GCP.
Never commit tokens, copy them into chat, or put them in the frontend.

```ini
WHATSAPP_ACCESS_TOKEN=SECRET
WHATSAPP_PHONE_NUMBER_ID=12345678901234
WHATSAPP_TEMPLATE_NAME=receipt_pdf
WHATSAPP_TEMPLATE_LANGUAGE=en_US
WHATSAPP_GRAPH_VERSION=v26.0
# Optional: comma-separated positional body parameters matching the approved template
WHATSAPP_TEMPLATE_BODY_FIELDS=customer_name,receipt_number,total
```

The approved template must have a DOCUMENT header. If its body has
placeholders, set `WHATSAPP_TEMPLATE_BODY_FIELDS` to the exact ordered
sequence (supported: `customer_name`, `receipt_number`, `total`,
`token_number`, `restaurant_name`). A mismatch causes Meta to reject the
message. The backend uploads the generated PDF as Meta media and sends a
template using the resulting media ID.

On the POS, a **Send receipt on WhatsApp** button appears on a paid order.
Sending is manual to avoid accidental costs or unexpected messages. A
message-ID response means **submitted to Meta**, not delivered or read.
The existing webhook receiver/processor stores delivery events separately;
matching them to the receipt-send records is a follow-up enhancement.
Failed/ambiguous upstream attempts are marked `review_required` to avoid
blind duplicate sends; inspect Meta event logs before manually retrying.

### Provider difference

If the product owner's “API key + template ID” belongs to a third-party
provider rather than Meta Cloud API, adapt `whatsapp_send.py` to that
provider's API instead of using these Meta credentials. Do not assume the
APIs are interchangeable.

## Session management and migration

On first deployment of the new session manager, older stateless cookies
become invalid and users must sign in again. This is expected.

`GET /api/auth/sessions/` lists the current user's sessions.
`DELETE /api/auth/sessions/{session_id}/` revokes one.
`POST /api/auth/logout-all/` revokes every session.
The React navbar has a Sessions screen.

For production, configure Firestore TTL on the `sessions` collection's
`expires_at` field to remove expired records (expiry is also checked
in application code). Add session audit monitoring, rate limiting for
login attempts, persistent secret management, and integration security
tests before rollout.

## Local Docker Compose (Ubuntu with ADC)

After installing Docker, Docker Compose, and configuring local
Application Default Credentials:

```sh
cd ~/Personal/foodoo-pos/Foodoo-FastAPI
cp fastapi_backend/.env.example fastapi_backend/.env
# Set FOODOO_SESSION_SECRET to a random 32+ character value,
# Firestore project, and if desired the WhatsApp settings.
docker compose -f compose.fastapi.yml up --build
```

Open **http://localhost:8088**, which is same-origin with the API proxy.
The FastAPI port is also exposed on localhost:8001 for diagnostics.
The Compose stack mounts **existing local** ADC credentials read-only.
If `~/.config/gcloud/application_default_credentials.json` is absent
(as may happen in Cloud Shell), use managed Cloud Run identity instead or
set up a local Firestore emulator. Do not put a service-account key in Git.

For Cloud Run: deploy the FastAPI container with a least-privileged service
account that has Firestore read/write permissions; set `FOODOO_COOKIE_SECURE=true`,
`FOODOO_ALLOWED_ORIGINS` to the exact HTTPS frontend origin, and
`FOODOO_SESSION_SECRET` and WhatsApp token through Secret Manager.
Containerization alone does not deploy or provision Firestore access.

## Acceptance checks

1. Save a real 14-digit FSSAI license; invalid lengths return HTTP 422.
2. Complete a test checkout; verify quantity, unit price and line total
   in the PDF as well as FSSAI and tax totals.
3. Verify WhatsApp send is disabled if consent was not granted.
4. After Meta credentials/template are configured, send to an authorized
   test recipient and check the Meta message ID and webhook status.
5. Verify logout, logout-all, individual session revocation, inactive
   session timeout, password reset and disabling staff access.
6. Build both containers, and test login + checkout through the reverse proxy.

**No real WhatsApp send or cloud deployment has been attempted by these commits.**
