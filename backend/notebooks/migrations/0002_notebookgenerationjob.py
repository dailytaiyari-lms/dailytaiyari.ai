import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_tenant_ai_platform_monthly_tokens'),
        ('exams', '0014_course_sequential_chapter_unlock'),
        ('notebooks', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NotebookGenerationJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('kind', models.CharField(choices=[('notebook', 'Interactive notebook (cells + autograder tests)')], default='notebook', max_length=20)),
                ('prompt', models.TextField(blank=True, default='')),
                ('options', models.JSONField(blank=True, default=dict)),
                ('provider', models.CharField(blank=True, default='', max_length=32)),
                ('model', models.CharField(blank=True, default='', max_length=200)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('generating', 'Generating'), ('preview', 'Awaiting review'), ('applied', 'Applied'), ('failed', 'Failed'), ('discarded', 'Discarded')], default='pending', max_length=20)),
                ('draft', models.JSONField(blank=True, default=dict)),
                ('revisions', models.JSONField(blank=True, default=list)),
                ('error', models.TextField(blank=True, default='')),
                ('prompt_tokens', models.PositiveIntegerField(default=0)),
                ('completion_tokens', models.PositiveIntegerField(default=0)),
                ('total_tokens', models.PositiveIntegerField(default=0)),
                ('estimated_cost_usd', models.DecimalField(decimal_places=6, default=0, max_digits=10)),
                ('generation_ms', models.PositiveIntegerField(default=0)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('applied_summary', models.JSONField(blank=True, default=dict)),
                ('applied_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='applied_notebook_generation_jobs', to=settings.AUTH_USER_MODEL)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notebook_generation_jobs', to='exams.course')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notebook_generation_jobs', to=settings.AUTH_USER_MODEL)),
                ('notebook', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generation_jobs', to='notebooks.notebook')),
                ('subject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notebook_generation_jobs', to='exams.subject')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='core.tenant')),
                ('topic', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notebook_generation_jobs', to='exams.topic')),
            ],
            options={
                'verbose_name': 'Notebook Generation Job',
                'verbose_name_plural': 'Notebook Generation Jobs',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['tenant', 'status'], name='nbgen_tenant_status_idx'), models.Index(fields=['topic', 'status'], name='nbgen_topic_status_idx')],
            },
        ),
    ]
