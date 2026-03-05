from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from documents.views import DashboardView, MetricsDashboardView
from debug_toolbar.toolbar import debug_toolbar_urls
from django.urls import re_path
from django.views.static import serve

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard"), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path('login/', LoginView.as_view(template_name='public/auth/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('documents/', include("documents.urls")),
    path('dashboard/metrics/', MetricsDashboardView.as_view(), name='metrics'),
]

if settings.DEBUG:
    urlpatterns += debug_toolbar_urls()

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

from django.core.management import call_command
from django.http import FileResponse

def download_backup(request):
    with open("backup_docs.json", "w", encoding="utf-8") as f:
        call_command(
            "dumpdata",
            "clients.Client",
            "documents.Company",
            "documents.Document",
            indent=2,
            natural_foreign=True,
            natural_primary=True,
            stdout=f
        )

    return FileResponse(
        open("backup_docs.json", "rb"),
        as_attachment=True,
        filename="backup_docs.json"
    )

urlpatterns += [
    path("download-backup/", download_backup)
]