from django.db.models.signals import post_save
from django.dispatch import receiver
from clients.models import Client
from .models import MovementCategory

DEFAULT_CATEGORIES = [
    ("expense", "Gastos de personal"),
    ("expense", "Alquiler"),
    ("expense", "Servicios"),
    ("expense", "Impuestos"),
    ("expense", "Préstamos"),
    ("expense", "Otros gastos"),
    ("income", "Otros ingresos"),
]


@receiver(post_save, sender=Client)
def create_default_categories(sender, instance, created, **kwargs):

    if not created:
        return

    categories = [
        MovementCategory.objects.get_or_create(
            client=instance,
            name=name,
            type=type_
        )
        for type_, name in DEFAULT_CATEGORIES
    ]

    MovementCategory.objects.bulk_create(categories)