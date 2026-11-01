from django.core.management.base import BaseCommand,CommandError
from django.core.management import call_command
from django.db import connections
from config.tenant_registry import resolve_tenant

class Command(BaseCommand):
    help="Inspect or migrate an explicitly configured tenant PostgreSQL database"

    def add_arguments(self,parser):
        parser.add_argument("tenant_id",help="Configured tenant key, not a URL")
        parser.add_argument("--migrate",action="store_true",help="Apply existing schema migrations to this tenant")
        parser.add_argument("--confirm",action="store_true",help="Required with --migrate")

    def handle(self,*args,**options):
        try: tenant=resolve_tenant(options["tenant_id"])
        except (LookupError,ValueError) as exc:raise CommandError(str(exc))
        db=connections[tenant.alias]
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT current_database(),current_user")
                name,user=cursor.fetchone()
        except Exception as exc:raise CommandError("Tenant connection failed: "+str(exc))
        self.stdout.write(f"Tenant: {tenant.tenant_id} | Database: {name} | Role: {user}")
        if name!=tenant.database_name:
            raise CommandError("Database name mismatch; refusing to continue")
        if options["migrate"]:
            if not options["confirm"]:
                raise CommandError("Use --migrate --confirm to apply schema migrations")
            call_command("migrate",database=tenant.alias,interactive=False)
            self.stdout.write(self.style.SUCCESS("Migrations complete for "+tenant.tenant_id))
        else:
            self.stdout.write("Read-only inspection complete. Add --migrate --confirm to apply schema.")
