from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_tenant_advanced_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='registration_settings',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
