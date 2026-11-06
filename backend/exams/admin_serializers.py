"""
Writable serializers for the admin Course Content Builder.

These power full CRUD over the content hierarchy:
Course -> Subject -> Chapter -> Topic -> Content.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Course, Subject, Topic, Chapter, ChapterTopic

User = get_user_model()


class AdminCourseSerializer(serializers.ModelSerializer):
    """Writable serializer for Course in the content builder."""
    subjects_count = serializers.IntegerField(source='subjects.count', read_only=True)
    discount_percent = serializers.ReadOnlyField()
    instructors = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=User.objects.filter(role='instructor'),
    )
    instructors_detail = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'name', 'code', 'description', 'course_type',
            'color', 'status', 'is_featured', 'is_hidden', 'thumbnail',
            'duration_minutes', 'total_marks', 'negative_marking',
            'negative_marking_ratio', 'total_students', 'total_questions',
            'pricing_type', 'price', 'original_price', 'currency',
            'discount_percent', 'subtitle', 'highlights', 'refund_policy',
            'certificate_enabled', 'certificate_template',
            'sequential_chapter_unlock',
            'subjects_count', 'instructors', 'instructors_detail',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'total_students', 'total_questions', 'created_at', 'updated_at']

    def get_instructors_detail(self, obj):
        return [
            {'id': str(u.id), 'name': u.full_name or u.email, 'email': u.email}
            for u in obj.instructors.all()
        ]


class AdminSubjectSerializer(serializers.ModelSerializer):
    """Writable serializer for Subject."""
    course_name = serializers.CharField(source='course.name', read_only=True)
    topics_count = serializers.IntegerField(source='topics.count', read_only=True)
    chapters_count = serializers.IntegerField(source='chapters.count', read_only=True)

    class Meta:
        model = Subject
        fields = [
            'id', 'name', 'code', 'description', 'icon', 'color',
            'course', 'course_name', 'weightage', 'order',
            'topics_count', 'chapters_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AdminChapterSerializer(serializers.ModelSerializer):
    """Writable serializer for Chapter."""
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    topics_count = serializers.IntegerField(source='topics.count', read_only=True)

    class Meta:
        model = Chapter
        fields = [
            'id', 'name', 'code', 'description', 'subject', 'subject_name',
            'grade', 'book_reference', 'estimated_hours', 'order',
            'topics_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AdminTopicSerializer(serializers.ModelSerializer):
    """Writable serializer for Topic.

    Supports an optional ``chapter`` write field so admins can create a topic
    directly inside a chapter (a ChapterTopic link is created/maintained).
    """
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    content_count = serializers.IntegerField(source='contents.count', read_only=True)
    chapter = serializers.PrimaryKeyRelatedField(
        queryset=Chapter.objects.all(), required=False, allow_null=True, write_only=True
    )
    chapter_ids = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            'id', 'name', 'code', 'description', 'subject', 'subject_name',
            'parent_topic', 'difficulty', 'importance', 'estimated_study_hours',
            'order', 'total_questions', 'content_count', 'chapter', 'chapter_ids',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'total_questions', 'created_at', 'updated_at']

    def get_chapter_ids(self, obj):
        return [str(ct.chapter_id) for ct in obj.chapter_topics.all()]

    def _link_chapter(self, topic, chapter):
        if not chapter:
            return
        last = ChapterTopic.objects.filter(chapter=chapter).order_by('-order').first()
        ChapterTopic.objects.get_or_create(
            chapter=chapter,
            topic=topic,
            defaults={
                'order': (last.order + 1) if last else 0,
                'tenant': getattr(topic, 'tenant', None),
            },
        )

    def create(self, validated_data):
        chapter = validated_data.pop('chapter', None)
        topic = super().create(validated_data)
        self._link_chapter(topic, chapter)
        return topic

    def update(self, instance, validated_data):
        chapter = validated_data.pop('chapter', None)
        topic = super().update(instance, validated_data)
        self._link_chapter(topic, chapter)
        return topic
