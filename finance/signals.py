from django.db.models.signals import post_save
from django.dispatch import receiver
from clients.models import Client
from .models import MovementCategory

DEFAULT_CATEGORIES = [
    # GASTOS
    ("expense", "Gastos de personal", "fa-solid fa-users", "#ef4444"),
    ("expense", "Alquiler", "fa-solid fa-building", "#f97316"),
    ("expense", "Servicios (luz, agua, internet)", "fa-solid fa-bolt", "#f59e0b"),
    ("expense", "Impuestos y tasas", "fa-solid fa-receipt", "#dc2626"),
    ("expense", "Marketing", "fa-solid fa-bullhorn", "#facc15"),
    ("expense", "Transporte y viajes", "fa-solid fa-car", "#22d3ee"),
    ("expense", "Comidas", "fa-solid fa-utensils", "#10b981"),
    ("expense", "Otros", "fa-solid fa-ellipsis", "#64748b"),

    # INGRESOS
    ("income", "Ventas", "fa-solid fa-cart-shopping", "#16a34a"),
    ("income", "Servicios prestados", "fa-solid fa-briefcase", "#22c55e"),
    ("income", "Ingresos financieros", "fa-solid fa-money-bill-trend-up", "#4ade80"),
    ("income", "Subvenciones y ayudas", "fa-solid fa-hand-holding-heart", "#14b8a6"),
    ("income", "Otros ingresos", "fa-solid fa-plus", "#22c55e"),

    # INVERSIONES / AHORROS
    ("investment", "Ahorro", "fa-solid fa-piggy-bank", "#3b82f6"),
    ("investment", "Inversiones", "fa-solid fa-chart-line", "#6366f1"),

    # PRÉSTAMOS / DEUDAS
    ("loan", "Préstamos personales", "fa-solid fa-hand-holding-dollar", "#a855f7"),
    ("loan", "Créditos", "fa-solid fa-file-invoice-dollar", "#8b5cf6"),
]


@receiver(post_save, sender=Client)
def create_default_categories(sender, instance, created, **kwargs):

    if not created:
        return

    for type_, name, icon, color in DEFAULT_CATEGORIES:
        MovementCategory.objects.get_or_create(
            client=instance, 
            type=type_, 
            name=name,
            defaults={
                "icon": icon,
                "color": color
            }
        )