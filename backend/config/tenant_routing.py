"""Opt-in database-per-tenant routing.

Tenant identity comes only from a server-configured hostname mapping, never a
client supplied tenant ID or a database URL in a request.
"""
import json
from contextvars import ContextVar
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from .tenant_registry import resolve_tenant

_active_db=ContextVar("foodoo_tenant_db",default=None)

def current_database():
    return _active_db.get()

def tenant_host_mapping():
    mapping=settings.FOODOO_TENANT_HOSTS
    if not isinstance(mapping,dict):
        raise ImproperlyConfigured("FOODOO_TENANT_HOSTS must be a dictionary")
    return mapping

class TenantHostMiddleware:
    """MUST be installed before Django SessionMiddleware."""
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        if not settings.FOODOO_TENANT_ROUTING:
            return self.get_response(request)
        host=request.get_host().split(":")[0].lower()
        tenant_id=tenant_host_mapping().get(host)
        if not tenant_id:
            return JsonResponse({"detail":"Unknown tenant hostname"},status=404)
        try: tenant=resolve_tenant(tenant_id)
        except (LookupError,ValueError):
            return JsonResponse({"detail":"Tenant unavailable"},status=503)
        token=_active_db.set(tenant.alias)
        try:
            request.tenant_id=tenant.tenant_id
            return self.get_response(request)
        finally:
            _active_db.reset(token)

    async def __acall__(self,request):
        return self.__call__(request)

class TenantDatabaseRouter:
    def db_for_read(self,model,**hints):
        return current_database()
    def db_for_write(self,model,**hints):
        return current_database()
    def allow_relation(self,obj1,obj2,**hints):
        if obj1._state.db and obj2._state.db:
            return obj1._state.db==obj2._state.db
        return None
    def allow_migrate(self,db,app_label,model_name=None,**hints):
        return True
