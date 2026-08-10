from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0008_seed_tenant_ai_allocations'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aiusagerecord',
            name='feature',
            field=models.CharField(
                choices=[
                    ('chat', 'Doubt solver'),
                    ('quiz', 'AI quiz'),
                    ('coursegen', 'Course builder'),
                    ('notebookgen', 'Notebook builder'),
                    ('other', 'Other'),
                ],
                default='chat',
                max_length=20,
            ),
        ),
    ]
