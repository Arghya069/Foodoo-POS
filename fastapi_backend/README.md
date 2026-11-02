# Foodoo FastAPI + Firestore migration branch

This is a **parallel prototype**, not a production replacement for the Django POS.
The existing React application remains in `frontend/`; **do not migrate or delete
the PostgreSQL data** and do not deploy this service over the live API yet.

## Run locally

Use Application Default Credentials via `gcloud auth application-default login`
or the Firestore emulator. Create a Firestore Native-mode database in your
project before using real cloud credentials.

```sh
cd fastapi_backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# replace session secret
uvicorn app:app --reload --port 8000
```

The new API deliberately has separate Firestore collection paths
`restaurants/{restaurant_id}/...`, and restaurant identity is derived from the
signed-in session, not a request-provided tenant ID. Date-scoped token counters
will use Firestore transactions.

The frontend is **not yet switched**: run it against Django until the parity
matrix, real integration tests, and data migration are finished.

## Required before production cutover

- Import current 1More restaurant, menu, staff, orders and their immutable
  price/tax snapshots, with reconciliation by order ID and money totals.
- Add Firestore indexes for the real search/order-history queries.
- Verify transactional order creation, retries and daily tokens with concurrent
  clients. All money stored as integer paise, never floating-point values.
- Test session expiry, CSRF, role restrictions, cross-restaurant isolation and
  PDF/Excel exports. Password hashes cannot simply be reused between algorithms;
  use password reset or a verified compatibility migration.
- Evaluate read/write costs and backups, retention, security rules/IAM and
  Firestore query constraints before selecting this as the production backend.

**Important:** A lighter framework does not guarantee lower total database
cost or development complexity. Firestore is a viable option; this branch lets
us prove parity and performance before replacing the existing system.
