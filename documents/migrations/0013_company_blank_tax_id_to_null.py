from django.db import migrations


def blank_to_null(apps, schema_editor):
    Company = apps.get_model("documents", "Company")
    # Si varias empresas del mismo cliente tienen NIF "" solo una puede quedar con
    # NULL-único; NULL no colisiona, así que todas pasan a NULL sin conflicto.
    Company.objects.filter(tax_id="").update(tax_id=None)


class Migration(migrations.Migration):
    dependencies = [("documents", "0012_h1_models")]
    operations = [migrations.RunPython(blank_to_null, migrations.RunPython.noop)]
