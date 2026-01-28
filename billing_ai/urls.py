from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="login"), name="home"),
    path('login/', LoginView.as_view(template_name='auth/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('documents/', include("documents.urls"))
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)