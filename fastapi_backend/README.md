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

The React frontend is now wired through Vite to FastAPI on port **8001** on this branch. It still needs real integration testing with Firestore before we can call it feature-parity or production-ready.

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

## Run both locally in the new clone

Terminal A (from the project root):
```sh
cd fastapi_backend
source .venv/bin/activate
# Firestore emulator is safest for development. If you use it:
# export FIRESTORE_EMULATOR_HOST=127.0.0.1:8089
# export FOODOO_FIRESTORE_PROJECT=foodoo-local
uvicorn app:app --reload --host 127.0.0.1 --port 8001
```

Terminal B (from the project root):
```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies /api to http://127.0.0.1:8001.
Never run Django on port 8001 or use the other clone's frontend against
the Firestore API by mistake. To point Vite at a different server, set
`FOODOO_API_TARGET=http://127.0.0.1:PORT` before `npm run dev`.

To create a fresh Firestore test tenant, set
`FOODOO_INITIAL_ADMIN_PASSWORD` in your shell and run:
```sh
python bootstrap.py --restaurant-id one-more --restaurant-name 1More --admin-username admin
```

Use a **new emulator database or disposable Firestore project** for this bootstrap.
Do not overwrite the existing production users or records.

Current gaps: manual/integration verification against a Firestore emulator,
historical order and customer import, high-volume indexed history and reports,
production-grade account provisioning, full receipt visual parity, and
security review. Keep Django as the baseline until these are resolved.


## API contracts and unit tests

FastAPI request and response schemas are defined in `schemas.py` using
**Pydantic v2**. They document the main API contracts in `/docs`,
reject unknown writable fields, and prevent internal Firestore properties
from leaking into public API responses.

Tests use **pytest** rather than unittest:

```bash
cd fastapi_backend
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q -v
```

The test suite covers schema validation, receipt rendering, WhatsApp template
payloads, session ID hashing, and OpenAPI request/response documentation.
These are not a replacement for end-to-end Firestore integration tests.

The React navigation syntax fix is on this branch; run
`cd frontend && npm install && npm run build` before starting Vite.
