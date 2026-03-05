from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

# Create your models here.
class Client(models.Model):
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Role(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('client', 'code')

    def __str__(self):
        return f"{self.client.name} - {self.name}"
    
class CustomUser(AbstractUser):
    client = models.ForeignKey(
        Client, 
        on_delete=models.CASCADE, 
        related_name="users"
    )
    roles = models.ManyToManyField(Role, blank=True)

    def has_role(self, code):
        return self.roles.filter(code=code).exists()
    
    def has_any_role(self, *codes):
        return self.roles.filter(code__in=codes).exists()
    
    def is_owner(self):
        return self.has_role("owner")
    def clean(self):
        super().clean()
        for role in self.roles.all():
            if role.client_id != self.client_id:
                raise ValidationError("Role must belong to the same client.")