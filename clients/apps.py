from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = 'clients'

    def ready(self):
        # Django 6.1 añade la opción vacía «- Select an option -» a los selectores y aún no está
        # traducida al español. Es un punto de extensión documentado de Django.
        from django.db.models import fields
        fields.BLANK_CHOICE_LABEL = "Selecciona una opción"
