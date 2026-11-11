from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import RedirectView
from django.conf import settings
from documents.views import DashboardView, MetricsDashboardView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard"), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path('login/', LoginView.as_view(template_name='public/auth/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('documents/', include("documents.urls")),
    path('metrics/dashboard/', MetricsDashboardView.as_view(), name='metrics'),
    path('finance/', include("finance.urls")),
    path('clients/', include("clients.urls")),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    from debug_toolbar.toolbar import debug_toolbar_urls
    urlpatterns += debug_toolbar_urls()



