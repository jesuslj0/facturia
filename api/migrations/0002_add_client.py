# Añadir Client a ApiKey
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0001_initial'),
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='apikey',
            name='client',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='api_keys', to='clients.client'),
        ),
    ]