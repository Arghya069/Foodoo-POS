# Foodoo: one container image, one GCP project per restaurant

**Model:** one Git branch/codebase and immutable image release; each restaurant gets
its own Google Cloud project, default Firestore (Native/Standard), Cloud Run
service, runtime service account, secrets, monitoring, and administrator.
No central restaurant database registry or cross-restaurant application admin.

**IMPORTANT:** These steps prepare a deployable image and a repeatable setup.
They have NOT yet been run end-to-end on a real GCP project. Do not use a
production deployment without acceptance testing, backup setup and rate limits.

## Build and run

The multi-stage `Dockerfile.foodoo` builds the React Vite UI then copies
it into a Python FastAPI image. `fastapi_backend/server.py` serves the UI
and API at the same origin. The image also includes `bootstrap.py`, used
only via CLI/Cloud Run Job. Nothing sensitive is baked into the image.

```bash
docker build -f Dockerfile.foodoo -t foodoo:dev .
docker run --rm -p 8080:8080 \
  --env-file fastapi_backend/.env \
  -e GOOGLE_APPLICATION_CREDENTIALS=/credentials/adc.json \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/credentials/adc.json:ro" \
  foodoo:dev
```

The above is for a local workstation with Google ADC. On Cloud Run, do NOT
mount service-account JSON keys; use a per-project service identity instead.

For an empty, separately configured Firestore project, local CLI bootstrap:

```bash
read -rsp "New admin password: " FOODOO_INITIAL_ADMIN_PASSWORD; echo
export FOODOO_INITIAL_ADMIN_PASSWORD
docker run --rm \
  --env-file fastapi_backend/.env \
  -e FOODOO_INITIAL_ADMIN_PASSWORD \
  -e GOOGLE_APPLICATION_CREDENTIALS=/credentials/adc.json \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/credentials/adc.json:ro" \
  foodoo:dev python bootstrap.py --restaurant-id one-more \
    --restaurant-name "1More" --admin-username admin
unset FOODOO_INITIAL_ADMIN_PASSWORD
```

Bootstrap is atomic across restaurant+identity documents and refuses to
overwrite an existing restaurant or username. **Do not bootstrap 1More again
in the existing `invoicing-predev` project if that admin already exists.**

## Per-project GCP Cloud Run deployment (example, NOT executed)

You need billing, Cloud Run/Build/Artifact Registry/Secret Manager APIs
enabled, rights to configure IAM and deploy, and a Firestore database.
Use unique PROJECT values per restaurant; this is the isolation boundary.

```bash
export PROJECT="REPLACE_WITH_DEDICATED_RESTAURANT_PROJECT"
export REGION="asia-south1"
export RESTAURANT_ID="one-more"
export RESTAURANT_NAME="1More"
export ADMIN_USERNAME="admin"
export SERVICE="foodoo-pos"
export SERVICE_ACCOUNT="foodoo-runtime@${PROJECT}.iam.gserviceaccount.com"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/foodoo/foodoo-pos:release-2026-11-06"

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
    iam.googleapis.com

# Only for a NEW project without a Firestore database.
# Always inspect databases before attempting create.
gcloud firestore databases list --project="$PROJECT"
# gcloud firestore databases create --database='(default)' \
#    --location="$REGION" --edition=standard --type=firestore-native \
#    --delete-protection --project="$PROJECT"

gcloud iam service-accounts create foodoo-runtime \
    --display-name="Foodoo POS runtime" --project="$PROJECT"

gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SERVICE_ACCOUNT" --role="roles/datastore.user"

# Create an independent session secret for EACH restaurant.
openssl rand -hex 32 | gcloud secrets create foodoo-session-secret \
    --replication-policy=automatic --data-file=- --project="$PROJECT"
gcloud secrets add-iam-policy-binding foodoo-session-secret \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" --project="$PROJECT"

gcloud artifacts repositories create foodoo --repository-format=docker \
    --location="$REGION" --description="Foodoo POS images" --project="$PROJECT"

# From the Foodoo repository root.
gcloud builds submit . --config deploy/cloudbuild.foodoo.yaml \
    --substitutions="_IMAGE=$IMAGE" --project="$PROJECT"

# Start with a placeholder allowed origin. Set it to actual URL after deploy.
gcloud run deploy "$SERVICE" --image="$IMAGE" --region="$REGION" \
    --project="$PROJECT" --service-account="$SERVICE_ACCOUNT" \
    --allow-unauthenticated --min-instances=0 --max-instances=3 \
    --set-env-vars="FOODOO_FIRESTORE_PROJECT=$PROJECT,FOODOO_FIRESTORE_DATABASE=(default),FOODOO_COOKIE_SECURE=true,FOODOO_ALLOWED_ORIGINS=https://placeholder.invalid" \
    --set-secrets="FOODOO_SESSION_SECRET=foodoo-session-secret:latest"

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" \
   --project="$PROJECT" --format='value(status.url)')"
gcloud run services update "$SERVICE" --region="$REGION" --project="$PROJECT" \
    --update-env-vars="FOODOO_ALLOWED_ORIGINS=$URL"
echo "Foodoo URL: $URL"
```

The Cloud Run service is publicly reachable for its login page, but the
backend protects restaurant data using session authentication and roles.
Review login brute-force protection before enabling public production traffic.

### Initial administrator on Cloud Run (ONE TIME PER NEW PROJECT)

Do not run an internet-exposed bootstrap endpoint; use a private Cloud Run
**Job** using the same image and service account. The password should be a
temporary Secret Manager secret (not a CLI argument and not committed).

```bash
read -rsp "Initial Foodoo admin password: " ADMIN_PASSWORD; echo
printf %s "$ADMIN_PASSWORD" | gcloud secrets create foodoo-bootstrap-password \
  --replication-policy=automatic --data-file=- --project="$PROJECT"
unset ADMIN_PASSWORD

gcloud secrets add-iam-policy-binding foodoo-bootstrap-password \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor" --project="$PROJECT"

gcloud run jobs create foodoo-bootstrap --image="$IMAGE" \
  --region="$REGION" --project="$PROJECT" --service-account="$SERVICE_ACCOUNT" \
  --tasks=1 --max-retries=0 \
  --command=python \
  --args=bootstrap.py,--restaurant-id,"$RESTAURANT_ID",--restaurant-name,"$RESTAURANT_NAME",--admin-username,"$ADMIN_USERNAME" \
  --set-env-vars="FOODOO_FIRESTORE_PROJECT=$PROJECT,FOODOO_FIRESTORE_DATABASE=(default)" \
  --set-secrets="FOODOO_INITIAL_ADMIN_PASSWORD=foodoo-bootstrap-password:latest"

gcloud run jobs execute foodoo-bootstrap --region="$REGION" \
  --project="$PROJECT" --wait

# After verifying the administrator can sign in, delete the one-time job
# and temporary password secret (not the permanent Foodoo session secret):
# gcloud run jobs delete foodoo-bootstrap --region="$REGION" --project="$PROJECT"
# gcloud secrets delete foodoo-bootstrap-password --project="$PROJECT"
```

For `invoicing-predev`, the existing bootstrapped account should remain;
skip the job and use existing Firestore data.

## Administration and rollout policy

- Google Cloud **Organization and Folders** can group restaurants;
  IAM governs who can administer each GCP project, budgets and services.
  It does not provide a Foodoo cross-restaurant business dashboard.
- One Artifact Registry source image should be built once and promoted
  by digest to projects (with appropriate cross-project Artifact Registry IAM),
  avoiding per-restaurant builds or code forks. A simple first release can
  build separately per project while the registry-sharing policy is set up.
- Every project gets its own Firestore backup/export policy, runtime service
  account, Secret Manager entries, log/uptime alerts and billing budget.
- Store inventory of project ID, restaurant ID, deployed image digest,
  URL, release version and operator in a **separate ops-only inventory**.
  No customer's orders or credentials belong in that inventory.
- Application staff and roles remain managed inside each Foodoo instance.
  No global user should automatically have access to every restaurant's data.
- Update rollout: publish the image once, deploy to a staging restaurant,
  validate receipts/payments/session flows, then update the per-project Cloud
  Run image digests in controlled batches.
- Confirm the GCP per-project Firestore billing/free-tier limitations.
  Project isolation is operationally strong, but scales costs and maintenance.

## Go-live checklist

1. In target project, verify Firestore and IAM, configure backups.
2. Validate image build, Cloud Run root page, `/healthz`, and `/docs`.
3. Bootstrap once only if no restaurant/admin data exists.
4. Configure secure cookies and exact HTTPS allowed origin.
5. Validate all roles, CSRF, taxes, double-payment and concurrent token issue.
6. Test PDF thermal printing, GST/FSSAI, history and sales report export.
7. Verify real 1More data migration or inventory, monitoring, billing alerts,
   rollback, emergency manual billing process and staff rehearsal.
8. Keep WhatsApp disabled until Meta credentials/template and delivery
   testing pass; Meta API approval is independent of core POS readiness.
