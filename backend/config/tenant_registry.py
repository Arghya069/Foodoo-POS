"""Tenant database configuration foundation.

This module deliberately does not change the live POS database routing. A
central identity service must be introduced before enabling request routing.
"""
import re
from dataclasses import dataclass
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

SLUG=re.compile(r"^[a-z][a-z0-9_-]{1,47}$")

@dataclass(frozen=True)
class TenantDatabase:
    tenant_id: str
    alias: str
    database_name: str

def validate_tenant_id(tenant_id):
    if not isinstance(tenant_id,str) or not SLUG.fullmatch(tenant_id):
        raise ValueError("Invalid tenant ID")
    return tenant_id

def tenant_alias(tenant_id):
    return "tenant_"+validate_tenant_id(tenant_id)

def configured_tenants():
    """Return only explicitly configured tenant aliases, no user-supplied names."""
    result={}
    for alias, db in settings.DATABASES.items():
        if not alias.startswith("tenant_"):
            continue
        key=alias[7:]
        validate_tenant_id(key)
        if db.get("ENGINE")!="django.db.backends.postgresql":
            raise ImproperlyConfigured("Tenant databases require PostgreSQL")
        if not db.get("NAME"):
            raise ImproperlyConfigured("Tenant database name is required")
        result[key]=TenantDatabase(key,alias,db["NAME"])
    return result

def resolve_tenant(tenant_id):
    """Reject unknown tenants rather than silently using the default database."""
    tenant=configured_tenants().get(validate_tenant_id(tenant_id))
    if tenant is None:
        raise LookupError("Tenant database is not configured")
    return tenant
