import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_tenant_registration_settings'),
        ('users', '0014_remove_studentprofile_primary_course'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='guardian_consent_granted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='guardian_consent_required',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='admission_number',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='batch_section',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='gender',
            field=models.CharField(blank=True, choices=[('female', 'Female'), ('male', 'Male'), ('non_binary', 'Non-binary'), ('prefer_not_to_say', 'Prefer not to say'), ('other', 'Other')], max_length=32),
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='stream',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.CreateModel(
            name='GuardianConsent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('guardian_name', models.CharField(max_length=200)),
                ('guardian_email', models.EmailField(max_length=254)),
                ('guardian_phone', models.CharField(blank=True, max_length=15)),
                ('relationship', models.CharField(max_length=50)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('granted', 'Granted'), ('withdrawn', 'Withdrawn')], default='pending', max_length=20)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('email_verified_at', models.DateTimeField(blank=True, null=True)),
                ('granted_at', models.DateTimeField(blank=True, null=True)),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('consent_version', models.CharField(default='1.0', max_length=50)),
                ('consent_text_hash', models.CharField(blank=True, max_length=64)),
                ('verification_method', models.CharField(default='verified_email_declaration', max_length=50)),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='core.tenant')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='guardian_consent', to='users.user')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
