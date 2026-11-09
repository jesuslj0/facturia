from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from billing_ai.storage import HashedImageField, logo_upload_to

# Create your models here.
class Client(models.Model):
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    logo = HashedImageField(upload_to=logo_upload_to, blank=True, null=True)
    primary_color = models.CharField(max_length=7, default="#2563eb")
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
    
class CustomUserManager(UserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        # createsuperuser pasa el id del Client (no la instancia) para las FK
        # de REQUIRED_FIELDS; lo convertimos a client_id.
        client = extra_fields.get("client")
        if client is not None and not isinstance(client, Client):
            extra_fields["client_id"] = extra_fields.pop("client")
        return super()._create_user_object(username, email, password, **extra_fields)


class CustomUser(AbstractUser):
    objects = CustomUserManager()

    client = models.ForeignKey(
        Client, 
        on_delete=models.CASCADE, 
        related_name="users"
    )
    roles = models.ManyToManyField(Role, blank=True)

    # createsuperuser pedirá el id del Client (FK obligatoria)
    REQUIRED_FIELDS = ["email", "client"]

    def has_role(self, code):
        return self.roles.filter(code=code).exists()
    
    def has_any_role(self, *codes):
        return self.roles.filter(code__in=codes).exists()
    
    def is_owner(self):
        return self.has_role("owner")
    def clean(self):
        super().clean()
        if not self.client_id:
            raise ValidationError("User must have a client assigned.")
        
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
@receiver(m2m_changed, sender=CustomUser.roles.through)
def validate_roles_client(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action in ["pre_add", "pre_set"]:
        for role_id in pk_set:
            role = model.objects.get(pk=role_id)
            if role.client_id != instance.client_id:
                raise ValidationError(
                    f"Role '{role}' does not belong to the same client as the user '{instance.username}'."
                )
