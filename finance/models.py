from django.db import models
from clients.models import Client
from clients.models import CustomUser
import os

class MovementCategory(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="movement_categories")
    name = models.CharField(max_length=100)
    type = models.CharField(
        max_length=10,
        choices=[
            ("expense", "Gasto"),
            ("income", "Ingreso"),
            ("investment", "Inversión"),
            ("loan", "Prestamo"),
        ]
    )
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        unique_together = ("client", "name", "type")
        ordering = ["type", "name"]

    def __str__(self):
        return f"{self.client.name} - {self.name}"

class FinancialMovement(models.Model):
    PAYMENT_CHOICES = [
        ("cash", "Efectivo"),
        ("transfer", "Transferencia"),
        ("check", "Cheque"),
        ("credit_card", "Tarjeta de Credito"),
        ("debit_card", "Tarjeta de Debito"),
        ("bizum", "Bizum"),
    ]

    def payment_icon(self):
        icons = {
            "cash": "fa-money-bill-wave",
            "transfer": "fa-building-columns",
            "check": "fa-file-invoice-dollar",
            "credit_card": "fa-credit-card",
            "debit_card": "fa-credit-card",
            "bizum": "fa-mobile-screen",
        }
        return icons.get(self.payment_method)

    @property
    def has_receipt(self):
        return bool(self.receipt)
    
    @property
    def has_payment_method(self):
        return bool(self.payment_method)
    
    def save(self, *args, **kwargs):
        if self.receipt and not self.receipt_name:
            self.receipt_name = os.path.basename(self.receipt.name)

        if self.category:
            self.movement_type = self.category.type
        super().save(*args, **kwargs)

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="movements")
    movement_type = models.CharField(max_length=10, choices=[("expense", "Gasto"), ("income", "Ingreso")], db_index=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="created_movements")
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.ForeignKey(MovementCategory, on_delete=models.PROTECT, related_name="movements")
    description = models.CharField(max_length=255, blank=True, verbose_name="Concepto")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt = models.FileField(upload_to="finance/receipts/", blank=True, null=True,verbose_name="Recibo")
    receipt_name = models.CharField(max_length=255, blank=True, null=True)
    payment_method = models.CharField(max_length=20, blank=True, null=True, choices=PAYMENT_CHOICES)
    is_conciled = models.BooleanField(default=False)
    is_recurrent = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date = models.DateField(db_index=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["client", "date"]),
            models.Index(fields=["client", "movement_type"]),
            models.Index(fields=["client", "category"]),
        ]

    def __str__(self):
        return f"{self.category.name} - {self.amount} ({self.date})"