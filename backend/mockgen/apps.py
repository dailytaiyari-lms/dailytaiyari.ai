from django.apps import AppConfig


class MockGenConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mockgen'
    verbose_name = 'AI Mock Test Builder'
