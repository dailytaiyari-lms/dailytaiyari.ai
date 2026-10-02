from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quiz', '0011_mocktest_max_attempts'),
    ]

    operations = [
        migrations.AddField(
            model_name='quizattempt',
            name='fullscreen_exit_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='last_proctoring_event_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='proctoring_violations',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='restricted_shortcut_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='tab_switch_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
