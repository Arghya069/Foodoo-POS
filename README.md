# Foodoo POS — Sprint 01

Single-restaurant POS MVP. Future-ready for separate organization databases, with an independently deployable POS service.

**Sunday goal:** Admin configures restaurant details (GSTIN, contact, address), menu prices and separate CGST/SGST rates (defaults 2.5% each). Cashier creates an order, records customer name/phone, views server-calculated tax and total, manually confirms payment, and prints a receipt.

WhatsApp Cloud API remains a **non-blocking follow-up** while sender/template approval is in progress. Kitchen, sales analytics, meal plans and multi-tenancy onboarding are out of scope.

## Development

Backend: Python 3.12+, Django/DRF; deployment target: Google Cloud Run, PostgreSQL in production. Frontend: React/Vite.

```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=true DJANGO_SECRET_KEY=local-only-change-me
python manage.py makemigrations pos
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Run `python manage.py test` after installing dependencies. Create first restaurant/admin membership using the Django shell. Local SQLite is a development shortcut, **not** the deployment architecture.

**Important:** This is a work-in-progress foundation, not production-ready. Authentication, migration files, deployment secrets, WhatsApp verification, receipt printing and end-to-end acceptance tests require completion. Never deploy with development credentials or expose Basic auth over plain HTTP.

See the project task sheet for Sprint 01 acceptance criteria.
