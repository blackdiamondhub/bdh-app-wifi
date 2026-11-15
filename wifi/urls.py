from django.urls import path
from . import views

urlpatterns = [
    path('', views.wifi_qr, name='wifi_qr'),
    path('settings/networks/', views.networks_page, name='wifi_networks'),
]
