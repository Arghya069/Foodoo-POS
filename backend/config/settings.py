import os
import json
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
from dotenv import load_dotenv
BASE_DIR=Path(__file__).resolve().parent.parent
# OS environment takes priority over local .env values (CI / cloud deployments).
load_dotenv(BASE_DIR / '.env', override=False)
DEBUG=os.getenv("DJANGO_DEBUG","false").lower()=="true"
SECRET_KEY=os.getenv("DJANGO_SECRET_KEY","unsafe-development-placeholder")
if not DEBUG and SECRET_KEY=="unsafe-development-placeholder": raise ImproperlyConfigured("DJANGO_SECRET_KEY required")
ALLOWED_HOSTS=[s.strip() for s in os.getenv("DJANGO_ALLOWED_HOSTS","localhost,127.0.0.1").split(",") if s.strip()]
INSTALLED_APPS=["django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.staticfiles","rest_framework","corsheaders","pos"]
MIDDLEWARE=["django.middleware.security.SecurityMiddleware","config.tenant_routing.TenantHostMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","corsheaders.middleware.CorsMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware"]
ROOT_URLCONF="config.urls"
TEMPLATES=[]
WSGI_APPLICATION="config.wsgi.application"
DATABASES={"default":dj_database_url.parse(os.getenv("DATABASE_URL",f"sqlite:///{BASE_DIR/'db.sqlite3'}"),conn_max_age=60,conn_health_checks=True)}
# Optional named tenant databases. This does not yet activate request routing.
# Example TENANT_DATABASE_URLS={"one_more":"postgresql://user:pass@localhost/db"}
try:
 TENANT_DATABASE_URLS=json.loads(os.getenv("TENANT_DATABASE_URLS","{}"))
 if not isinstance(TENANT_DATABASE_URLS,dict):raise ValueError()
except (ValueError,TypeError):
 raise ImproperlyConfigured("TENANT_DATABASE_URLS must be a JSON object")
for tenant_id,url in TENANT_DATABASE_URLS.items():
 if not isinstance(tenant_id,str) or not __import__("re").fullmatch(r"[a-z][a-z0-9_-]{1,47}",tenant_id):
  raise ImproperlyConfigured("Invalid tenant database alias")
 if not isinstance(url,str) or not url.startswith(("postgresql://","postgres://")):
  raise ImproperlyConfigured("Tenant database URLs must use PostgreSQL")
 DATABASES["tenant_"+tenant_id]=dj_database_url.parse(url,conn_max_age=60,conn_health_checks=True)
DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"
REST_FRAMEWORK={"DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],"DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"]}
CORS_ALLOWED_ORIGINS=[x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS","http://localhost:5173").split(",") if x.strip()]
LANGUAGE_CODE="en-in"
TIME_ZONE="Asia/Kolkata"
USE_TZ=True
STATIC_URL="static/"
STATIC_ROOT=BASE_DIR/"staticfiles"
SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")
SESSION_COOKIE_SECURE=not DEBUG
CSRF_COOKIE_SECURE=not DEBUG

# Base64-encoded 4 MiB menu images require ~5.6 MiB JSON requests in local MVP.
DATA_UPLOAD_MAX_MEMORY_SIZE=8*1024*1024

SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE="Lax"
SESSION_COOKIE_AGE=8*60*60
SESSION_SAVE_EVERY_REQUEST=True

CSRF_TRUSTED_ORIGINS=[x.strip() for x in os.getenv("CSRF_TRUSTED_ORIGINS","http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]

# Opt-in database-per-tenant routing: OFF until multiple databases have been
# provisioned and isolated login flows have passed acceptance tests.
FOODOO_TENANT_ROUTING=os.getenv("FOODOO_TENANT_ROUTING","false").lower()=="true"
try:
 FOODOO_TENANT_HOSTS=json.loads(os.getenv("FOODOO_TENANT_HOSTS","{}"))
 if not isinstance(FOODOO_TENANT_HOSTS,dict):raise ValueError()
except (ValueError,TypeError):
 raise ImproperlyConfigured("FOODOO_TENANT_HOSTS must be a JSON object")
if FOODOO_TENANT_ROUTING and not FOODOO_TENANT_HOSTS:
 raise ImproperlyConfigured("At least one tenant hostname is required with tenant routing")
DATABASE_ROUTERS=["config.tenant_routing.TenantDatabaseRouter"]
