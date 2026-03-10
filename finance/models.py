from django.db import models
from clients.models import Client
from clients.models import CustomUser

class MovementCategory(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="movement_categories")
    name = models.CharField(max_length=100)
    type = models.CharField(
        max_length=10,
        choices=[
            ("expense", "Gasto"),
            ("income", "Ingreso")
        ]
    )

    class Meta:
        unique_together = ("client", "name")
        ordering = ["type", "name"]

    def __str__(self):
        return f"{self.client.name} - {self.name}"

class FinancialMovement(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="movements")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="created_movements")
    category = models.ForeignKey(MovementCategory, on_delete=models.PROTECT, related_name="movements")
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt = models.FileField(upload_to="finance/receipts/", blank=True, null=True)
    date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.category.name} - {self.amount} ({self.date})"