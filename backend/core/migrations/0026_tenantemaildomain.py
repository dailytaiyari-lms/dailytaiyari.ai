import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_tenant_registration_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantEmailDomain',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('domain', models.CharField(max_length=253, unique=True)),
                ('sender_username', models.CharField(default='notifications', max_length=64)),
                ('sender_name', models.CharField(blank=True, default='', max_length=255)),
                ('is_active', models.BooleanField(default=False)),
                ('azure_resource_id', models.TextField(blank=True, default='')),
                ('provisioning_state', models.CharField(blank=True, default='', max_length=32)),
                ('verification_records', models.JSONField(blank=True, default=dict)),
                ('verification_states', models.JSONField(blank=True, default=dict)),
                ('sender_provisioned', models.BooleanField(default=False)),
                ('is_linked', models.BooleanField(default=False)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='email_domain', to='core.tenant')),
            ],
            options={
                'verbose_name': 'Tenant Email Domain',
                'verbose_name_plural': 'Tenant Email Domains',
            },
        ),
    ]
