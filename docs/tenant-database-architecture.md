# Foodoo database-per-tenant architecture

Status: **design approved as the target; implementation outstanding**.

## Separation of concerns

- **Platform database**: organizations, tenant registry, global identities,
  account-to-organization memberships, entitlements, tenant database connection
  references, tenant lifecycle and provisioning state.
- **Restaurant tenant database**: branch records, POS menu, orders, daily tokens,
  receipts and customer preferences. Meal subscription data can be added as a
  separate service-owned database or schema according to the service boundary.
- **Physical hosting**: PostgreSQL databases may share a managed PostgreSQL
  server. Database-per-tenant does not require one server per tenant.
- **Branch identity**: branch code and main/branch designation currently describe
  this restaurant. Later a tenant-local Branch model should own stable branch IDs,
  with each order/menu/meal-plan referencing the correct branch.

## Why this is not implemented today

Currently Membership and Restaurant are in the same tenant-scoped POS database,
and the application uses one DATABASE_URL. Restaurant ID filtering is a helpful
defense but **is not physical database isolation**. Pointing Django to another
DATABASE_URL alone does not enable multi-tenant routing.

## Migration phases

1. Introduce a separate platform database with stable organization IDs, normalized
   identity/membership models and tenant connection aliases or secret references.
2. Implement authenticated tenant resolution from validated server-side membership
   records, never from a browser-supplied database name or arbitrary header.
3. Add an explicit database router and service/repository boundaries; ensure every
   POS ORM call and transaction uses the resolved tenant database. Keep Django auth,
   session and platform data in the platform database.
4. Define per-tenant migration and provisioning commands with idempotency,
   health checks and rollback paths. Database credentials must remain in the
   environment/secret manager, not in API responses or user-controlled fields.
5. Migrate the existing `foodoo_pos_restaurant_001` data to the new model only
   after verified backups; preserve original user IDs and historical receipts.
6. Validate with at least two restaurant databases and two users, including
   cross-tenant attempts at reading and modifying orders, customers, reports and
   staff; check that schema migration failures isolate the affected tenant.
7. Only then mark Sprint S1-002 fully Done.

## Non-negotiable testing requirements

- Requests to tenant A never access tenant B's connection even when IDs coincide.
- Tenant resolution fails closed if membership or database configuration is missing.
- Admin/partner/cashier/chef permissions work in every tenant database.
- Provisioning is repeatable and never drops or overwrites an existing tenant DB.
- A single restaurant's DB outage does not expose another tenant's data.
- Query, transaction and connection routing are verified on PostgreSQL in CI.

A database-per-tenant rollout requires an isolated feature/architecture phase and
should not be mixed into routine cashier UX changes.
