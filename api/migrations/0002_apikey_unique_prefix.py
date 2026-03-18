from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="apikey",
            constraint=models.UniqueConstraint(fields=("prefix",), name="unique_api_key_prefix"),
        ),
    ]
