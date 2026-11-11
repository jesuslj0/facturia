from django.urls import path
from clients.views import ClientDetailView, ClientLogoView

app_name = 'clients'

urlpatterns = [
    path('detail/', ClientDetailView.as_view(), name='detail'),
    path('logo/', ClientLogoView.as_view(), name='logo'),
]
