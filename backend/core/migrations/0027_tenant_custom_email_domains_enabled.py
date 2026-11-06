from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_tenantemaildomain'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='custom_email_domains_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
