# Rehearse Foodooo against a fresh Firestore project before publishing

**Goal:** use the existing Cloud Shell React/FastAPI development setup
with a completely new restaurant project and empty Firestore database.
Leave `invoicing-predev` untouched.

## 1. New GCP project + database (preferred tenant isolation)

Create a unique project ID, or ask the owner to create the project and
attach billing through the Google Cloud Console. Each restaurant should
own its own project, Firestore database, secrets, runtime identity, and
billing/backup policies.

```bash
export NEW_PROJECT="REPLACE_WITH_UNIQUE_PROJECT_ID"
export REGION="asia-south1"
gcloud projects create "$NEW_PROJECT" --name="Foodooo 1More rehearsal"
# The owner must link the new project to a valid billing account in
# Google Cloud Console > Billing > My projects before deployment.
gcloud services enable firestore.googleapis.com \
  --project="$NEW_PROJECT"

gcloud firestore databases list --project="$NEW_PROJECT"
```

Only if no default database exists:

```bash
gcloud firestore databases create \
  --project="$NEW_PROJECT" \
  --database='(default)' \
  --location="$REGION" \
  --edition=standard \
  --type=firestore-native \
  --delete-protection
```

Check created database:

```bash
gcloud firestore databases describe \
  --project="$NEW_PROJECT" --database='(default)'
```

The Firestore location is normally irreversible; verify `asia-south1`
is the desired region before running create. Create exactly one database
for a new project, and do not overwrite existing records.

**Alternative (testing only):** A second named Firestore database may
be created in `invoicing-predev` with `--database=foodooo-test`.
Then set `FOODOO_FIRESTORE_PROJECT=invoicing-predev` and
`FOODOO_FIRESTORE_DATABASE=foodooo-test`. This keeps data in separate
databases but does **not** give per-project isolation, IAM or billing.
Use the new-project approach for restaurant tenants.

## 2. Cloud Shell app: connect to the NEW Firestore

Ensure your Cloud Shell Google account has permission to read/write
Firestore in the new project, and that Application Default Credentials
are available. Do not set a service-account JSON key in Git.
The application gets credentials from ADC in development, and from the
Cloud Run runtime service account after deployment.

```bash
cd ~/Foodoo-FastAPI
git pull origin feat/fastapi-firestore-parity

export FOODOO_FIRESTORE_PROJECT="$NEW_PROJECT"
export FOODOO_FIRESTORE_DATABASE='(default)'
export FOODOO_COOKIE_SECURE=false
# Keep the secure session secret used by your existing Cloud Shell
# environment, or set a DIFFERENT 32+ character secret temporarily.
# FOODOO_ALLOWED_ORIGINS must contain your actual Cloud Shell Vite URL.
# Avoid pasting secrets into chat or committing any .env file.
```

The app loads `fastapi_backend/.env` but shell-exported values take
precedence. Confirm which terminal starts Uvicorn; these exported
variables need to exist in **that same terminal**.

## 3. One-time bootstrap in the NEW empty database

```bash
cd ~/Foodoo-FastAPI/fastapi_backend
source .venv/bin/activate
read -rsp "Initial admin password (12+ characters): " FOODOO_INITIAL_ADMIN_PASSWORD; echo
export FOODOO_INITIAL_ADMIN_PASSWORD

python bootstrap.py \
  --restaurant-id one-more \
  --restaurant-name "1More" \
  --admin-username admin

unset FOODOO_INITIAL_ADMIN_PASSWORD
```

The transaction refuses to overwrite an existing restaurant or
username. Do not rerun this in the populated `invoicing-predev`
default database. The newly bootstrapped admin should use
**Account & security → Change password** after signing in.

## 4. Start the same development application

```bash
cd ~/Foodoo-FastAPI/fastapi_backend
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8001
```

Keep Vite serving port 5173 in its own terminal. Its `/api` proxy
continues to target port 8001. Refresh the browser, sign in with the
new admin and verify the new restaurant starts with an empty menu and
empty order history.

**Do not run both the old and new projects on the same port at once.**
Changing `FOODOO_FIRESTORE_PROJECT` in a running shell does nothing;
the API process must be restarted.

## 5. Rebuild and publish only after verification

```bash
cd ~/Foodoo-FastAPI
cd fastapi_backend && python -m pytest -v && cd ..
cd frontend && npm install && npm run build && cd ..
docker build -f Dockerfile.foodoo -t foodooo:release-candidate .
```

Next, use [production-owner-handoff.md](./production-owner-handoff.md)
to provision a dedicated runtime service account, Secret Manager
secrets, Artifact Registry, production Cloud Run HTTPS origin, backups,
alerts and a versioned image. The local image build does **not** create
a cloud service or persist an image in Artifact Registry.

## Password change behavior

Any authenticated administrator, cashier, chef, partner or legacy staff
role can open **Account & security**, enter their current password and
a new password of at least 12 characters, confirm it, and submit.

The backend verifies the current Argon2 password hash, updates only the
caller’s identity, and revokes all sessions. It also rejects sessions
created before the password change, even if revocation cleanup is
interrupted. The user signs in again with the new password.

## Troubleshooting

- `403` from Firestore: your Cloud Shell user or runtime identity lacks
  appropriate IAM access in `$NEW_PROJECT`.
- `403 Untrusted origin`: set `FOODOO_ALLOWED_ORIGINS` to the exact
  HTTPS Vite Cloud Shell preview URL and restart Uvicorn.
- `401` after password change: expected; sign in again.
- Firestore bootstrap refuses to overwrite: verify
  `FOODOO_FIRESTORE_PROJECT` and database selection; never delete
  production collections to make bootstrap succeed.
