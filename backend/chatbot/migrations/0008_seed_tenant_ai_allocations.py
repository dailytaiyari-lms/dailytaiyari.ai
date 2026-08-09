"""Carry legacy platform grants onto the new allocation row.

``Tenant.ai_platform_monthly_tokens`` used to be the whole platform-key story.
Allocations replace it, so every tenant that already had a grant keeps working
without the super admin re-entering anything.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Tenant = apps.get_model('core', 'Tenant')
    Allocation = apps.get_model('chatbot', 'TenantAIAllocation')

    for tenant in Tenant.objects.filter(ai_platform_monthly_tokens__gt=0):
        Allocation.objects.get_or_create(
            tenant=tenant,
            defaults={
                'tenant_id': tenant.id,
                'is_enabled': True,
                'monthly_token_limit': tenant.ai_platform_monthly_tokens,
            },
        )


def backwards(apps, schema_editor):
    """Push the token ceiling back onto the tenant so a downgrade keeps grants."""
    Tenant = apps.get_model('core', 'Tenant')
    Allocation = apps.get_model('chatbot', 'TenantAIAllocation')

    for allocation in Allocation.objects.filter(is_enabled=True).select_related('tenant'):
        Tenant.objects.filter(pk=allocation.tenant_id).update(
            ai_platform_monthly_tokens=allocation.monthly_token_limit
        )


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0007_platformaimodel_platformaiprovider_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
