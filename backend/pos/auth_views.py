import json
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.http import require_GET, require_POST
from .models import Membership

@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"ok":True})

@require_POST
@csrf_protect
def sign_in(request):
    try:
        data=json.loads(request.body)
    except (ValueError,UnicodeDecodeError):
        return JsonResponse({"detail":"Invalid request"},status=400)
    username=str(data.get("username","")).strip()
    password=data.get("password","")
    if not username or not isinstance(password,str) or not password:
        return JsonResponse({"detail":"Username and password are required"},status=400)
    user=authenticate(request,username=username,password=password)
    if user is None or not user.is_active:
        return JsonResponse({"detail":"Invalid username or password"},status=401)
    if not Membership.objects.filter(user=user).exists():
        return JsonResponse({"detail":"No restaurant membership"},status=403)
    login(request,user)
    request.session.set_expiry(8*60*60)
    return JsonResponse({"username":user.username})

@require_POST
@csrf_protect
def sign_out(request):
    logout(request)
    return JsonResponse({"ok":True})
