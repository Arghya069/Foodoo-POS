# Deploying Foodoo and receiving Meta WhatsApp webhooks (GCP)

This is deployment scaffolding, **not** an automatic rollout. Run commands only
after project/billing setup and review. Never paste secrets into git.

## 1. GCP project and APIs

Use Cloud Shell or a terminal with the Google Cloud CLI.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
export PROJECT_ID="$(gcloud config get-value project)"
export REGION=asia-south1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com pubsub.googleapis.com \
  firestore.googleapis.com iam.googleapis.com
```

Configure a billing budget and email alerts before creating Cloud SQL.

## 2. Database, secrets and service accounts

Create a Cloud SQL PostgreSQL instance in the same region using the console,
with private connection controls appropriate for your network. Create a
`foodoo_pos_restaurant_001` database and a least-privileged application user.
Cloud SQL instances are charged even with zero Cloud Run instances.

Use Secret Manager for `DJANGO_SECRET_KEY`, `DATABASE_URL`,
`WHATSAPP_VERIFY_TOKEN` (arbitrary long random shared verification string)
and `WHATSAPP_APP_SECRET` (Meta **App Secret**, not WhatsApp access token).

The Django `DATABASE_URL` may use the Cloud SQL Unix socket syntax described
by Google's Django-on-Cloud-Run guide, e.g.:
`postgresql://DB_USER:URL_ENCODED_PASSWORD@//cloudsql/PROJECT:REGION:INSTANCE/foodoo_pos_restaurant_001`.

Create dedicated service identities and grant **only**:
- Foodoo API: Cloud SQL Client and Secret Manager access to its own secrets
- Webhook receiver: Pub/Sub Publisher on topic `foodoo-whatsapp-events` and access
  to Meta verification/app secrets
- Event processor: Cloud Datastore User (Firestore native mode)
- Pub/Sub push identity: Cloud Run Invoker on the private processor

Do not grant owner/editor permissions to these service accounts.

## 3. Deploy the POS backend

The Django backend has a Dockerfile under `backend/`.

```bash
gcloud run deploy foodoo-api --source backend --region "$REGION" \
  --service-account "YOUR_API_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --add-cloudsql-instances "$PROJECT_ID:$REGION:YOUR_CLOUD_SQL_INSTANCE" \
  --set-secrets "DJANGO_SECRET_KEY=foodoo-django-key:latest,DATABASE_URL=foodoo-db-url:latest" \
  --set-env-vars "DJANGO_DEBUG=false,DJANGO_ALLOWED_HOSTS=YOUR_HOST_NAMES,CSRF_TRUSTED_ORIGINS=https://YOUR_FIREBASE_SITE.web.app" \
  --min-instances=0 --allow-unauthenticated
```

Public invocation is required for Django's own session login endpoints when
the app is accessed through the browser. Require authentication on protected
Django API views and restrict all backend mutations by role.

Run Django migrations **before** enabling traffic. Use a separate Cloud Run
Job from the same image with the same secrets/Cloud SQL attachment, command
`python manage.py migrate --noinput`. Prefer a controlled job to `migrate`
at every web instance startup.

Important: do **not** enable `FOODOO_TENANT_ROUTING` on the live 1More
database until the platform registry/migration plan is finished.

## 4. Frontend on Firebase Hosting

`firebase.json` rewrites same-origin `/api/**` to Cloud Run service
`foodoo-api` in `asia-south1`. This avoids cross-site Django session
cookie problems. Build assets at `frontend/dist`.

```bash
npm install -g firebase-tools
firebase login
firebase use --add
cd frontend && npm ci && npm run build && cd ..
firebase deploy --only hosting
```

Set the Firebase Hosting site and verify the app URL in Django
`DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` before users log in.
Make sure no old `VITE_API_URL` overrides the production relative `/api`
endpoint.

## 5. Pub/Sub and Firestore

Create Firestore in **Native mode**, selecting its location before creating
it; choose data residency and retention appropriate for customer messages.
Create a Pub/Sub topic:

```bash
gcloud pubsub topics create foodoo-whatsapp-events
```

Deploy the webhook receiver using its Dockerfile:

```bash
gcloud run deploy foodoo-whatsapp-webhook \
  --source services/whatsapp-webhook --region "$REGION" \
  --service-account "YOUR_WEBHOOK_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --set-env-vars "WHATSAPP_EVENTS_TOPIC=projects/$PROJECT_ID/topics/foodoo-whatsapp-events" \
  --set-secrets "WHATSAPP_VERIFY_TOKEN=foodoo-whatsapp-verify:latest,WHATSAPP_APP_SECRET=foodoo-meta-app-secret:latest" \
  --min-instances=0 --allow-unauthenticated
```

Deploy the **private** processor:

```bash
gcloud run deploy foodoo-whatsapp-processor \
  --source services/whatsapp-processor --region "$REGION" \
  --service-account "YOUR_PROCESSOR_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --min-instances=0 --no-allow-unauthenticated
```

Grant the dedicated push service account `roles/run.invoker` on
`foodoo-whatsapp-processor`, then create a Pub/Sub push subscription:

```bash
gcloud pubsub subscriptions create foodoo-whatsapp-events-push \
  --topic=foodoo-whatsapp-events \
  --push-endpoint="https://YOUR_PROCESSOR_URL/pubsub" \
  --push-auth-service-account="YOUR_PUBSUB_PUSH_SA@$PROJECT_ID.iam.gserviceaccount.com"
```

Cloud Run IAM rejects unauthenticated requests to the processor. The
processor persists each **canonical payload** to Firestore with its SHA-256
fingerprint as the document ID; this makes repeated delivery idempotent.
A message is acknowledged only after the write succeeds, so failed writes
are retried. Configure a dead-letter topic, maximum retries and retention
for production; monitor dead letters and delivery failures.

## 6. Configure Meta

In the Meta Developer dashboard, WhatsApp configuration / Webhooks:
- Callback URL: `https://YOUR_WEBHOOK_RUN_URL/webhook`
- Verify token: the value of `WHATSAPP_VERIFY_TOKEN`
- Subscribe to `messages` and any other approved events you need.

GET verification checks the token and returns `hub.challenge`.
POST verifies the raw request using HMAC-SHA256 and the Meta app secret,
publishes the raw event to Pub/Sub, and acknowledges only after publication.

**This only receives/stores WhatsApp events.** It does not send receipts or
customer WhatsApp messages; sending requires Meta authorization,
approved templates and the WhatsApp Cloud API. Do not log raw customer
messages, and restrict Firestore access to staff who need it.

## 7. Smoke and security tests

Verify: invalid verify token → 403; valid verification → challenge text;
invalid/missing POST signature → 403; signed POST → 200 only after Pub/Sub
acceptance; Firestore records created once on repeated delivery; Pub/Sub
retry on write error; anonymous processor invocation denied.

Before live usage check HTTPS, production Django secret, sessions/CSRF,
CORS/host configuration, tenant isolation, data backups, retention,
privacy notices and cost alerts.
