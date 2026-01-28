from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Client(models.Model):
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    

class ClientUser(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE)