# Foodoo POS — Sprint 01

Single-restaurant POS MVP. Future-ready for separate organization databases, with an independently deployable POS service.

**Sunday goal:** Admin configures restaurant details (GSTIN, contact, address), menu prices and separate CGST/SGST rates (defaults 2.5% each). Cashier creates an order, records customer name/phone, views server-calculated tax and total, manually confirms payment, and prints a receipt.

WhatsApp Cloud API remains a **non-blocking follow-up** while sender/template approval is in progress. Kitchen, sales analytics, meal plans and multi-tenancy onboarding are out of scope.

## Local development

Backend: Python 3.12+, Django/DRF, PostgreSQL. Frontend: React/Vite.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
chmod 600 .env
```

Edit `backend/.env` with your local PostgreSQL credentials, Django secret key,
debug mode, allowed hosts and trusted origins. The file is ignored by Git.
Generate a Django secret using:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Then run:

```bash
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

In a separate terminal, run `cd frontend && npm install && npm run dev`.
Use `http://localhost:5173`; Vite proxies requests to Django for session auth.

**Configuration precedence:** existing shell/process environment variables override
values from `backend/.env`. This allows cloud/CI secret injection without local
settings overriding it. If you previously exported `DATABASE_URL` or other
variables, `unset` them before checking whether the `.env` file is effective.

**Security:** never commit or share `.env`, keep `DJANGO_DEBUG=false` outside
development, and use a dedicated PostgreSQL role rather than the `postgres`
superuser. Changes to the Django secret key invalidate existing sessions.
The local `.env` is for development, not a production secret manager.

See the project task sheet for Sprint 01 acceptance criteria.
