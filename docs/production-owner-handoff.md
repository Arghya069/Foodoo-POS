# Foodoo POS – production deployment handoff

**Release candidate:** `feat/fastapi-firestore-parity`.
**Launch target:** 6 November 2026.
**Tenant policy:** **one Google Cloud project / Firestore database / Cloud Run
service per restaurant**, one shared versioned application image. No
cross-restaurant data or application super-admin access.

This is an **owner runbook, not proof of production readiness**. The owner
must verify permissions, deployment, backups and payment/receipt flows. The
`invoicing-predev` project already has a default Firestore database and an
admin: **do not run the bootstrap job again** there.

## 0. Prerequisites and inventory

The operator needs project-level deployment and IAM rights, a billing-enabled
project, GitHub repository access, and a working `gcloud` installation or
Google Cloud Shell. At minimum, delegate Cloud Run Admin/Developer,
Service Account User, Service Usage Admin, Artifact Registry Admin/Writer,
Cloud Build build permissions, Secret Manager Admin for creation and binding,
Firestore Admin for TTL/backup administration, and an authorized billing
manager for budgets. Use narrower scope in production where possible.
The **runtime identity** needs only Firestore read/write
(`roles/datastore.user`) and per-secret accessor permissions.

Per restaurant, document **project ID, Cloud Run URL, deployed image digest,
Firestore database, service account, region, release version and owner** in
private operations inventory. Never record passwords, tokens or customer
data in that inventory.

Do not commit `.env` files, service account keys, or API tokens.

## 1. Identify the target project and verify Firestore

Replace the project ID for each restaurant. 1More's existing prototype project
is `invoicing-predev`; the owner decides whether to use it for production
or create a separate production project.

```bash
export PROJECT="invoicing-predev"
export REGION="asia-south1"
export SERVICE="foodoo-pos"
export SA="foodoo-runtime@${PROJECT}.iam.gserviceaccount.com"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/foodoo/foodoo-pos:release-2026-11-06"

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com

gcloud firestore databases list --project="$PROJECT"
```

If the `(default)` Native Firestore database exists, **do not create another**.
For a new GCP project, configure Firestore Native/Standard in `asia-south1`
through the console before continuing.

## 2. Runtime service identity and permissions

Run once per new project; if the account already exists, skip creation:

```bash
gcloud iam service-accounts create foodoo-runtime \
  --display-name="Foodoo POS runtime" --project="$PROJECT"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role="roles/datastore.user"
```

Cloud Run uses its managed service identity; **do not create or deploy
a JSON service-account key**.

## 3. Secret Manager: create and grant access

Use three secrets (a fresh per-restaurant session secret, the Meta access token
and an optional short-lived bootstrap password). The Phone Number ID, approved
template name and template language are not credentials and can be ordinary
configuration variables.

Create only if missing:

```bash
gcloud secrets create foodoo-session-secret --replication-policy=automatic \
  --project="$PROJECT"
gcloud secrets create foodoo-meta-token --replication-policy=automatic \
  --project="$PROJECT"
```

Add the random signing secret as version 1:

```bash
openssl rand -hex 32 | gcloud secrets versions add foodoo-session-secret \
  --data-file=- --project="$PROJECT"
```

Add Meta token **without placing the token in command history or a file**:

```bash
read -rsp "Meta access token: " META_TOKEN; echo
printf '%s' "$META_TOKEN" | gcloud secrets versions add foodoo-meta-token \
  --data-file=- --project="$PROJECT"
unset META_TOKEN
```

Give the runtime access **only to these secrets**:

```bash
for NAME in foodoo-session-secret foodoo-meta-token; do
  gcloud secrets add-iam-policy-binding "$NAME" \
    --member="serviceAccount:$SA" \
    --role="roles/secretmanager.secretAccessor" --project="$PROJECT"
done
```

We pin Secret Manager environment values to explicit version `1` for the
first deployment (see below). When rotating a token, add a new version,
update the Cloud Run secret reference and redeploy. Google recommends
version pinning for secrets exposed as environment variables.

**Do not rotate the session secret casually**: a change will invalidate
CSRF tokens and can affect active sessions. Arrange a maintenance window
or implement key rotation first.

## 4. Image build

From a clean checkout of the reviewed release commit:

```bash
git fetch origin
git switch feat/fastapi-firestore-parity
git pull --ff-only origin feat/fastapi-firestore-parity

gcloud artifacts repositories create foodoo --repository-format=docker \
  --location="$REGION" --project="$PROJECT"

gcloud builds submit . --config deploy/cloudbuild.foodoo.yaml \
  --substitutions="_IMAGE=$IMAGE" --project="$PROJECT"
```

Only create the Artifact Registry repository if missing. The **single**
`Dockerfile.foodoo` bundles React, FastAPI, Pydantic schemas, receipt,
WhatsApp sender, audit modules and the one-time CLI bootstrap. The same
image digest should later be promoted to other restaurant projects.

## 5. Configure non-secret environment variables

The owner should create a local configuration file in Cloud Shell
**outside Git**. Replace all placeholder values:

```bash
cat > /tmp/foodoo-runtime.yaml <<EOF
FOODOO_FIRESTORE_PROJECT: "$PROJECT"
FOODOO_FIRESTORE_DATABASE: "(default)"
FOODOO_COOKIE_SECURE: "true"
FOODOO_ALLOWED_ORIGINS: "https://placeholder.invalid"
WHATSAPP_PHONE_NUMBER_ID: "REPLACE_WITH_META_PHONE_NUMBER_ID"
WHATSAPP_TEMPLATE_NAME: "REPLACE_WITH_APPROVED_TEMPLATE_NAME"
WHATSAPP_TEMPLATE_LANGUAGE: "en_US"
WHATSAPP_TEMPLATE_BODY_FIELDS: "customer_name,receipt_number"
WHATSAPP_GRAPH_VERSION: "v26.0"
EOF
```

Use the real template language and a currently supported Meta Graph API
version. The approved WhatsApp document template must match exactly:
`Hello {{1}}` = customer name; `order {{2}}` = receipt number.

## 6. Deploy and set the actual HTTPS origin

```bash
gcloud run deploy "$SERVICE" --image="$IMAGE" \
  --region="$REGION" --project="$PROJECT" \
  --service-account="$SA" --allow-unauthenticated \
  --min-instances=0 --max-instances=3 \
  --env-vars-file=/tmp/foodoo-runtime.yaml \
  --set-secrets="FOODOO_SESSION_SECRET=foodoo-session-secret:1,WHATSAPP_ACCESS_TOKEN=foodoo-meta-token:1"

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" \
  --project="$PROJECT" --format='value(status.url)')"

gcloud run services update "$SERVICE" --region="$REGION" \
  --project="$PROJECT" \
  --update-env-vars="FOODOO_ALLOWED_ORIGINS=$URL"

printf 'Foodoo URL: %s\n' "$URL"
curl -fsS "$URL/healthz"
```

The service deliberately exposes the **login page publicly**, with application
authentication protecting order/customer endpoints. Before opening to real
users, test CSRF, account disable, session logout, 403 protections and
login-rate limiting. Cloud Run public ingress is not staff authorization.

Use the actual HTTPS origin (no trailing slash) in
`FOODOO_ALLOWED_ORIGINS`, and `FOODOO_COOKIE_SECURE=true`.

## 7. Bootstrap a brand-new restaurant (skip on 1More)

The existing 1More administrator and Firestore records should be preserved.
For a **new** tenant, use a short-lived Cloud Run Job with the **same image**
and service identity; never expose a bootstrap API to the internet.
See [one-project-per-restaurant-deployment.md](./one-project-per-restaurant-deployment.md)
for Cloud Run Job commands.

Bootstrap must create the restaurant and first admin **once**. It refuses
to overwrite either record and creates both transactionally. Remove the
temporary admin-password secret after a successful bootstrap. The account
must immediately change the initial password.

## 8. Set data retention and backups

Order records keep the staff username that created the sale.
Network and browser audit details live in separate
`restaurants/{restaurant_id}/order_audit/{order_id}` documents with
an `expires_at` timestamp 30 days after creation/payment.

Enable a **Firestore TTL policy** for these records:

```bash
gcloud firestore fields ttls update expires_at \
  --collection-group=order_audit --enable-ttl --project="$PROJECT"
```

Firestore TTL deletion is asynchronous and can be delayed; the application
also hides expired audit data. Note that backups/exports may separately
retain data beyond operational TTL and require their own retention policy.

Create and test Firestore backup/restore procedures with the owner. An empty
backup policy is a **go-live blocker**.

## 9. Verify in deployed production-like environment

These must be actual test results, not assumptions from a passing build:

- [ ] `npm run build`, `python -m pytest -v`, Docker build and startup.
- [ ] `/healthz` returns 200, UI loads over HTTPS, login and session cookies work.
- [ ] Create an order as cashier, pay via Cash/UPI, verify token issued once.
- [ ] Try duplicate payment: no double charge/paid transition.
- [ ] Download receipt; check four-column layout, 14-digit FSSAI and taxes.
- [ ] In **Sessions**, save a counter label, create an order; verify Order
      History displays creator and admin can inspect label/browser/peer IP.
- [ ] Confirm the network peer IP matches available infrastructure evidence;
      the browser-reported device ID is NOT proof of a physical terminal.
- [ ] Send a consented WhatsApp PDF; view it on recipient device.
- [ ] Resend deliberately after 2 minutes; verify 3-attempt cap and audit.
- [ ] Check no-consent, nonpaid, concurrent resend, spoofed device ID and
      user/role restrictions.
- [ ] Confirm Meta webhook security, message status tracking and failure handling.
- [ ] Inspect Firestore backup, TTL status, logs, error/uptime alerts,
      cost/billing budgets and response to an outage.
- [ ] Run multiple simultaneous orders and verify unique token sequence.
- [ ] Prepare a paper/manual billing fallback and rollback image digest.
- [ ] Get explicit go/no-go approval from restaurant owner.

## 10. Device/IP and privacy limits

- **Actor identity:** server-validated staff ID/username, role and session.
- **Device:** staff-defined local counter label (configure under **Sessions**),
  browser-generated UUID stored locally, and browser/user agent. Counter
  labels and UUIDs can be changed or reset, and are not hardware attestation.
- **IP:** socket peer observed by ASGI. Behind Cloud Run, load balancers,
  Vite or reverse proxies, this may be an intermediary IP, not the staff
  terminal's public address. We intentionally do not trust arbitrary
  client-supplied `X-Forwarded-For` headers. Use Cloud Run/load-balancer
  request logs and configured trusted-proxy infrastructure for deeper tracing.
- **MAC and private LAN IP:** web browsers cannot reliably or safely
  disclose them. Use an optional managed POS hardware-agent/kiosk enrollment
  if hardware-level attestation becomes a real requirement.
- **Access/retention:** order audit endpoint is admin-only; IP and user-agent
  are not sent to the customer. Notify staff about security/audit collection,
  restrict Firestore IAM, and enable the TTL policy.

## Operational ownership

GCP projects, IAM, billing, logs and Cloud Run services can be centrally
administered by the owner's organization. Google Cloud does not automatically
provide Foodoo's business-level multi-restaurant dashboard. Treat releases
and project inventories as a separate operations process; each restaurant
continues to manage its own cashiers/menus/accounts in its own app.

## Official references

- Cloud Run secrets: https://docs.cloud.google.com/run/docs/configuring/services/secrets
- Deploy an image: https://docs.cloud.google.com/run/docs/deploying
- Firestore TTL: https://firebase.google.com/docs/firestore/ttl

## 11. Meta WhatsApp callbacks (delivery status, replies and feedback)

**New integrated FastAPI webhook:** `GET/POST /webhooks/meta` on the same
Cloud Run service as Foodoo. It verifies the Meta challenge and signs POST
requests with `WHATSAPP_APP_SECRET`. This does **not** require a separate
Flask/PubSub deployment for initial single-restaurant operations.

Two additional secrets are required:

- `WHATSAPP_APP_SECRET`: Meta **App Settings → Basic → App Secret**.
  This is distinct from the `WHATSAPP_ACCESS_TOKEN` used for sending.
- `WHATSAPP_VERIFY_TOKEN`: a random token we generate; enter the same
  string in the Meta Webhooks form.

Create the secrets in the **restaurant's** GCP project:

```bash
gcloud secrets create foodoo-meta-app-secret --replication-policy=automatic --project="$PROJECT"
read -rsp "Meta App Secret: " META_APP_SECRET; echo
printf %s "$META_APP_SECRET" | gcloud secrets versions add foodoo-meta-app-secret \
  --data-file=- --project="$PROJECT"
unset META_APP_SECRET

gcloud secrets create foodoo-meta-verify-token --replication-policy=automatic --project="$PROJECT"
openssl rand -hex 32 | gcloud secrets versions add foodoo-meta-verify-token \
  --data-file=- --project="$PROJECT"

for NAME in foodoo-meta-app-secret foodoo-meta-verify-token; do
  gcloud secrets add-iam-policy-binding "$NAME" \
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT"
done

gcloud run services update "$SERVICE" --region="$REGION" --project="$PROJECT" \
  --update-secrets="WHATSAPP_APP_SECRET=foodoo-meta-app-secret:1,WHATSAPP_VERIFY_TOKEN=foodoo-meta-verify-token:1"
```

Retrieve the verify token **only while configuring the Meta developer portal**:

```bash
gcloud secrets versions access 1 --secret=foodoo-meta-verify-token --project="$PROJECT"
```

Keep this token private. In Meta for Developers → your App → WhatsApp →
**Configuration** → Webhooks, enter:

- Callback URL: `https://YOUR-FOODOO-CLOUD-RUN-URL/webhooks/meta`
  (replace with the actual deployed `$URL`).
- Verify token: the exact secret value created above.
- Click **Verify and Save**.
- Subscribe to the `messages` webhook field; that carries customer replies
  and outgoing delivery statuses. Subscribe additional fields for template
  quality/account events only if they are useful.

The same app secret must match the Meta app that owns the WhatsApp number.
Meta must be able to access this HTTPS endpoint publicly. Request signature
validation makes the endpoint different from authenticated POS routes: the
CSRF middleware exempts **only** this exact webhook path; the receiver
validates `X-Hub-Signature-256` over the raw bytes and refuses unsigned POSTs.

### What is stored

- `whatsapp_inbox`: inbound text, button replies, quick-reply feedback and
  bounded metadata. Admin sees the 50 newest in **WhatsApp activity**.
- `whatsapp_status`: latest sent/delivered/read/failed state per Meta message
  ID, ordered by event timestamp; stale updates cannot overwrite newer status.
- `whatsapp_events`: other subscribed Meta feedback/account events.
- `whatsapp_message_links`: connects each sent receipt's Meta message ID
  back to the Foodoo order, including resends.

Messages are deduplicated by Meta message ID; account events by fingerprint.
No auto-reply is sent, and incoming text does not change orders or payments.
The webhook returns 503 when Firestore cannot persist an event so Meta can
retry rather than having us falsely acknowledge delivery.

### Retention

The inbox and other events have a 90-day `expires_at` value; status events
have 180 days. Configure Firestore TTL for each collection group:

```bash
gcloud firestore fields ttls update expires_at --collection-group=whatsapp_inbox \
  --enable-ttl --project="$PROJECT"
gcloud firestore fields ttls update expires_at --collection-group=whatsapp_events \
  --enable-ttl --project="$PROJECT"
gcloud firestore fields ttls update expires_at --collection-group=whatsapp_status \
  --enable-ttl --project="$PROJECT"
```

TTL only applies after the policy is enabled and deletes asynchronously.
Review access, backup retention, and customer privacy before production.

### Acceptance test

1. Confirm Meta webhook verification succeeds.
2. Send a new PDF receipt to a consented test customer.
3. Verify Meta sends `sent`/`delivered`/`read` status events.
4. Reply from the customer's WhatsApp number; check the admin
   **WhatsApp activity** view and linked order.
5. Send a button/interactive feedback reply (if the approved template
   includes one), and verify readable feedback appears.
6. Confirm a forged/unsigned webhook POST returns 403 and does not write.
7. Test Meta retries and duplicate events; no duplicate inbox rows.
8. Confirm only admins can use `/api/whatsapp/inbox/` and
   `/api/whatsapp/statuses/`.

Production phone subscriptions must be associated with the correct Meta WABA.
The webhook callback cannot be registered until the Cloud Run service has a
public HTTPS URL.

Official Meta docs:
- https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview
- https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages

## 12. Final application security/receipt audit (5 November 2026)

The connected repository was inspected and patched on
`feat/fastapi-firestore-parity`. Cloud Shell's temporary port-5173 preview
URL was **not externally reachable for independent HTTP/browser testing**.
It remains a development server, not a security-approved production endpoint.

### Safeguards added during the final review

- Explicit `FOODOO_FIRESTORE_PROJECT` is now required on API startup to
  prevent accidental data writes to an implicit GCP project.
- Login failures are limited to eight attempts within five minutes for the
  same username and server-observed network peer. Use Cloud Armor / edge
  rate limiting as well; Cloud Run may report a shared proxy peer address.
- API responses disable caching and include anti-framing, MIME sniffing and
  conservative browser permissions headers. Enforce HTTPS in Cloud Run.
- The UI no longer reuses WhatsApp consent saved for an earlier order;
  staff must confirm consent for every new order.
- Menu-upload field sizes and tax-rate inputs are validated, and extremely
  large unit prices are rejected.
- Sales reports and order history no longer silently exclude everything
  beyond the most recent 1,000 orders. **However, unbounded Firestore scans
  are not scalable**: implement date-indexed cursor pagination as restaurants
  grow and measure query/read costs.
- Receipt pages remain 57mm wide. Height is calculated from wrapped content,
  and huge receipts are automatically continued onto another 57mm page
  (rather than silently clipping due to the PDF viewer's page-size limit).
  GSTIN/FSSAI print only if configured; tax totals appear on the final page.

### Configure expiry for transient login throttle records

```bash
gcloud firestore fields ttls update expires_at \
  --collection-group=login_attempts --enable-ttl --project="$PROJECT"
```

Verify the TTL policy and Firestore indexes in the **correct restaurant
project**. The five-minute throttle expires logically even before TTL
deletion occurs.

### Validate before production build

```bash
cd ~/Foodoo-FastAPI
git pull origin feat/fastapi-firestore-parity
cd fastapi_backend
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q -v
cd ../frontend
npm install
npm run build
cd ..
docker build -f Dockerfile.foodoo -t foodooo:release-candidate .
```

Stress receipt testing includes 1, 30, 100, 250, 400 and 1,000 items,
including long wrapped names, continuation pages, footer placement and
variable-height PDF assertions. These tests must pass in the owner's
Cloud Shell environment before release; code commits alone are not evidence
that the tests passed.

**Additional release blockers/decisions:** independent Firestore backup and
restore drill; session/CSRF role checks; production Cloud Run HTTPS and exact
origin; Secret Manager references; printer paper-driver test (actual 57mm
roll, no scaling); two-cashier concurrent checkout; a review of login
rate-limit behavior behind the production load balancer; a dependency
vulnerability scan; and staff rehearsal.

Run these security/dependency checks on an internet-enabled build host:

```bash
cd frontend && npm audit --omit=dev && cd ..
cd fastapi_backend
python -m pip install pip-audit
python -m pip_audit -r requirements.txt
```

The project currently has no committed `frontend/package-lock.json`; use
`npm install` to generate one and commit the reviewed lockfile before
treating builds as reproducible. Do not make `npm ci` mandatory until
the lockfile exists.

**No security certification is implied.** The live temporary Cloud Shell
URL could not be inspected directly; perform authorized, non-disruptive
runtime checks with a test account and deployed staging environment.
