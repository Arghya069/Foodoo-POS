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
- [ ] In Order History, inspect creator; admin can inspect separate audit detail.
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
- **Device:** browser-generated UUID stored locally; browser/user agent.
  UUID can reset when local storage is cleared and can be impersonated.
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
