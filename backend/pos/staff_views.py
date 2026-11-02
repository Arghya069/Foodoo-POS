from django.contrib.auth import get_user_model
from django.db import transaction,router as django_router
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Membership,Order

User=get_user_model()
ROLES=("admin","cashier","chef","partner")

def admin_membership(request):
    return Membership.objects.filter(user=request.user,role="admin").first()

def public_member(m):
    u=m.user
    return {"id":m.id,"username":u.username,"first_name":u.first_name,
            "last_name":u.last_name,"role":m.role,"active":u.is_active}

@api_view(["GET","POST"])
def staff_directory(request):
    admin=admin_membership(request)
    if not admin:return Response({"detail":"Admin only"},status=403)
    if request.method=="GET":
        return Response([public_member(m) for m in Membership.objects.filter(restaurant=admin.restaurant).select_related("user").order_by("user__username")])
    username=str(request.data.get("username","")).strip()
    password=request.data.get("password","")
    role=request.data.get("role")
    if not username or len(username)>150 or not username.replace("_","").replace("-","").replace(".","").isalnum():
        return Response({"username":"Use letters, digits, dots, underscores or hyphens."},status=400)
    if role not in ROLES:return Response({"role":"Select admin, cashier, chef or partner."},status=400)
    if not isinstance(password,str) or len(password)<10 or password.lower()==username.lower():
        return Response({"password":"Use a password of at least 10 characters, different from username."},status=400)
    if User.objects.filter(username__iexact=username).exists():
        return Response({"username":"Username is already taken."},status=400)
    with transaction.atomic(using=django_router.db_for_write(Membership)):
        user=User.objects.create_user(username=username,password=password,first_name=str(request.data.get("first_name","")).strip()[:150])
        m=Membership.objects.create(user=user,restaurant=admin.restaurant,role=role)
    return Response(public_member(m),status=201)

@api_view(["PATCH"])
def staff_detail(request,pk):
    admin=admin_membership(request)
    if not admin:return Response({"detail":"Admin only"},status=403)
    with transaction.atomic(using=django_router.db_for_write(Membership)):
        try:m=Membership.objects.select_for_update().select_related("user").get(pk=pk,restaurant=admin.restaurant)
        except Membership.DoesNotExist:return Response({"detail":"Not found"},status=404)
        user=m.user
        new_role=request.data.get("role",m.role)
        active=request.data.get("active",user.is_active)
        if new_role not in ROLES:return Response({"role":"Invalid role."},status=400)
        if not isinstance(active,bool):return Response({"active":"Must be true or false."},status=400)
        if user.pk==request.user.pk and (new_role!="admin" or not active):
            return Response({"detail":"You cannot deactivate or demote your own account."},status=400)
        if m.role=="admin" and (new_role!="admin" or not active):
            remaining=Membership.objects.filter(restaurant=admin.restaurant,role="admin",user__is_active=True).exclude(pk=m.pk).exists()
            if not remaining:return Response({"detail":"A restaurant must retain an active admin."},status=400)
        password=request.data.get("password")
        if password is not None and (not isinstance(password,str) or len(password)<10 or password.lower()==user.username.lower()):
            return Response({"password":"Use at least 10 characters, different from username."},status=400)
        if password:user.set_password(password)
        if "first_name" in request.data:user.first_name=str(request.data["first_name"]).strip()[:150]
        user.is_active=active
        user.save()
        m.role=new_role;m.save(update_fields=["role"])
    return Response(public_member(m))

@api_view(["GET"])
def kitchen_queue(request):
    m=Membership.objects.filter(user=request.user).first()
    if not m:return Response({"detail":"No membership"},status=403)
    if m.role not in ("admin","chef"):return Response({"detail":"Kitchen access only"},status=403)
    orders=Order.objects.filter(restaurant=m.restaurant,status="paid").select_related("restaurant").prefetch_related("lines").order_by("-paid_at")[:50]
    return Response([{"id":o.id,"token_number":o.token_number,"token_date":o.token_date,
                      "paid_at":o.paid_at,"items":[{"name":line.name_snapshot,"quantity":line.quantity} for line in o.lines.all()]} for o in orders])
