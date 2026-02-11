from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from documents.views import DashboardView
from debug_toolbar.toolbar import debug_toolbar_urls

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard"), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path('login/', LoginView.as_view(template_name='auth/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('documents/', include("documents.urls"))
]

if settings.DEBUG:
    urlpatterns += debug_toolbar_urls()

urlpatterns += static(
    settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
)