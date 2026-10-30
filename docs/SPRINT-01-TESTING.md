# Sprint 01 verification checklist

Current PR is a **draft**. These commands must run before sign-off:

```bash
cd backend
python -m pip install -r requirements.txt
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test
python manage.py createsuperuser
python manage.py bootstrap_restaurant --admin-username YOUR_USERNAME --restaurant-name "First Restaurant"
python manage.py runserver
```

In a second terminal:

```bash
cd frontend
npm install
npm run build
npm run dev
```

Verify admin restaurant details/GSTIN/tax settings, add menu items, create a separate staff account and membership, then sign in as staff to create an order. Verify totals, mark paid once, print a receipt, and confirm that WhatsApp is disabled until approved.

## Release blockers
- Do not expose development HTTP Basic credentials to a public deployment.
- Confirm GST applicability and required invoice details for the first restaurant.
- Ensure Django `DEBUG=false` in production, configure allowed hosts/HTTPS, secure secrets and database.
- Verify that every database query is scoped to the restaurant.
- Confirm runtime migrations, frontend build and end-to-end flow; they have **not** been executed in this environment.
- Meta WhatsApp callback integration remains out of Sunday release scope.
