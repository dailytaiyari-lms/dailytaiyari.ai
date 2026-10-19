"""
Signals for the content app.

Watches uploaded lecture videos so a newly attached file is queued for
faststart optimisation (see ``content.tasks``) without any caller having to
remember to do it.
"""
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from content.models import Content
from content.tasks import enqueue_video_optimization

_ORIGINAL = '_original_video_file'


@receiver(post_init, sender=Content)
def remember_video_file(sender, instance, **kwargs):
    instance.__dict__[_ORIGINAL] = instance.video_file.name if instance.video_file else ''


@receiver(post_save, sender=Content)
def optimize_new_video(sender, instance, created, **kwargs):
    current = instance.video_file.name if instance.video_file else ''
    previous = instance.__dict__.get(_ORIGINAL, '')
    instance.__dict__[_ORIGINAL] = current

    if not current or current == previous:
        return
    # The task writes back a "-faststart" copy; don't chase our own tail.
    if current.endswith('-faststart.mp4'):
        return

    # A replacement upload must not inherit the previous file's progress.
    Content.objects.filter(pk=instance.pk).update(
        video_status='pending', video_progress=0,
    )
    enqueue_video_optimization(instance)
