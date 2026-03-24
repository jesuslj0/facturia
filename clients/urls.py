from django.urls import path
from clients.views import ClientDetailView

app_name = 'clients'

urlpatterns = [
    path('detail/', ClientDetailView.as_view(), name='detail'),
]
