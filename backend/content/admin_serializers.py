"""
Writable serializer for admin content management in the Content Builder.
"""
from django.utils.text import slugify
from rest_framework import serializers

from .models import Content
from exams.models import Course


class AdminContentSerializer(serializers.ModelSerializer):
    """Full CRUD serializer for Content with automatic slug handling."""
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    courses = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), many=True, required=False
    )

    class Meta:
        model = Content
        fields = [
            'id', 'title', 'slug', 'description', 'content_type', 'material_kind',
            'topic', 'topic_name', 'subject', 'subject_name', 'courses',
            'content_html', 'video_url', 'video_file', 'video_duration_minutes',
            'video_duration_seconds', 'video_status', 'hls_status', 'pdf_file',
            'difficulty', 'status', 'is_free', 'is_premium',
            'estimated_time_minutes', 'order', 'author_name',
            'views_count', 'likes_count', 'bookmarks_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'slug', 'views_count', 'likes_count', 'bookmarks_count',
            'created_at', 'updated_at',
        ]

    def _unique_slug(self, title, instance=None):
        base = slugify(title) or 'content'
        slug = base
        i = 1
        qs = Content.objects.all()
        if instance is not None:
            qs = qs.exclude(pk=instance.pk)
        while qs.filter(slug=slug).exists():
            i += 1
            slug = f"{base}-{i}"
        return slug

    def _default_courses(self, validated_data):
        """If no courses supplied, inherit from the subject's course."""
        subject = validated_data.get('subject')
        if subject and getattr(subject, 'course_id', None):
            return [subject.course]
        return []

    def create(self, validated_data):
        courses = validated_data.pop('courses', None)
        validated_data['slug'] = self._unique_slug(validated_data.get('title', ''))
        content = super().create(validated_data)
        content.courses.set(courses if courses else self._default_courses(validated_data))
        return content

    def update(self, instance, validated_data):
        courses = validated_data.pop('courses', None)
        if 'title' in validated_data and validated_data['title'] != instance.title:
            validated_data['slug'] = self._unique_slug(validated_data['title'], instance)
        content = super().update(instance, validated_data)
        if courses is not None:
            content.courses.set(courses)
        return content
