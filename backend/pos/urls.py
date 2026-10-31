from django.urls import path
from . import views
urlpatterns=[path("me/",views.me),path("restaurant/",views.restaurant),path("menu/",views.menu),path("menu/<int:pk>/",views.menu_detail),path("orders/",views.orders),path("orders/<int:pk>/pay/",views.pay),path("orders/<int:pk>/receipt/",views.receipt)]
