from django.http import Http404
import os
from django.conf import settings

class MediaSecurityMiddleware:
    """
    Bloquea el acceso a directorios dentro de /media/ y permite solo archivos existentes.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(settings.MEDIA_URL):
            # Ruta física del archivo
            file_path = os.path.join(settings.MEDIA_ROOT, path[len(settings.MEDIA_URL):])
            if os.path.isdir(file_path) or not os.path.exists(file_path):
                raise Http404("Archivo no encontrado")
        return self.get_response(request)
