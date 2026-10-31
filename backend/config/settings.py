import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
BASE_DIR=Path(__file__).resolve().parent.parent
DEBUG=os.getenv("DJANGO_DEBUG","false").lower()=="true"
SECRET_KEY=os.getenv("DJANGO_SECRET_KEY","unsafe-development-placeholder")
if not DEBUG and SECRET_KEY=="unsafe-development-placeholder": raise ImproperlyConfigured("DJANGO_SECRET_KEY required")
ALLOWED_HOSTS=[s.strip() for s in os.getenv("DJANGO_ALLOWED_HOSTS","localhost,127.0.0.1").split(",") if s.strip()]
INSTALLED_APPS=["django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.staticfiles","rest_framework","corsheaders","pos"]
MIDDLEWARE=["django.middleware.security.SecurityMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","corsheaders.middleware.CorsMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware"]
ROOT_URLCONF="config.urls"
TEMPLATES=[]
WSGI_APPLICATION="config.wsgi.application"
DATABASES={"default":dj_database_url.parse(os.getenv("DATABASE_URL",f"sqlite:///{BASE_DIR/'db.sqlite3'}"),conn_max_age=60,conn_health_checks=True)}
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
