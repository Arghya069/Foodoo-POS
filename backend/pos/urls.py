from django.urls import path
from . import views,auth_views
urlpatterns=[path("auth/csrf/",auth_views.csrf),path("auth/login/",auth_views.sign_in),path("auth/logout/",auth_views.sign_out),path("me/",views.me),path("restaurant/",views.restaurant),path("menu/",views.menu),path("customers/lookup/",views.customer_lookup),path("customers/suggest/",views.customer_suggestions),path("menu/<int:pk>/",views.menu_detail),path("orders/",views.orders),path("orders/<int:pk>/pay/",views.pay),path("orders/<int:pk>/receipt/",views.receipt)]
