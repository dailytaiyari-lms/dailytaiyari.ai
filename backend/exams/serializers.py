"""
Serializers for Courses app.
"""
from rest_framework import serializers
from .models import Course, Subject, Topic, TopicCourseRelevance, Chapter


class CourseSerializer(serializers.ModelSerializer):
    """Serializer for Course model."""
    subjects_count = serializers.SerializerMethodField()
    mock_tests_count = serializers.SerializerMethodField()
    quizzes_count = serializers.SerializerMethodField()
    discount_percent = serializers.ReadOnlyField()
    is_free = serializers.ReadOnlyField()
    instructors = serializers.SerializerMethodField()
    enroll_mode = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'name', 'code', 'description', 'course_type',
            'icon', 'color', 'status', 'is_featured', 'thumbnail',
            'duration_minutes', 'total_marks', 'negative_marking',
            'negative_marking_ratio', 'total_students', 'total_questions',
            'subjects_count', 'mock_tests_count', 'quizzes_count',
            'pricing_type', 'price', 'original_price', 'currency',
            'is_free', 'discount_percent', 'subtitle', 'highlights',
            'refund_policy', 'certificate_enabled', 'certificate_template',
            'instructors', 'enroll_mode', 'created_at'
        ]

    def get_enroll_mode(self, obj):
        """How a student joins this course: 'request', 'self' or 'payment'."""
        tenant = getattr(obj, 'tenant', None)
        if tenant is None:
            return 'request'
        return tenant.enroll_mode_for(obj)

    def get_subjects_count(self, obj):
        return obj.subjects.count()

    def get_mock_tests_count(self, obj):
        return obj.mock_tests.count()

    def get_quizzes_count(self, obj):
        return obj.quizzes.count()

    def get_instructors(self, obj):
        return [
            {'id': str(u.id), 'name': u.full_name or u.first_name or u.email}
            for u in obj.instructors.all()
        ]


class CourseListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for course listings.

    Includes the handful of display fields course cards need (thumbnail,
    short description, type and pricing) so listings — including the public
    landing page carousel — can render rich tiles without a detail fetch.
    """
    is_free = serializers.ReadOnlyField()
    discount_percent = serializers.ReadOnlyField()

    class Meta:
        model = Course
        fields = [
            'id', 'name', 'code', 'icon', 'color', 'status', 'is_featured',
            'thumbnail', 'subtitle', 'description', 'course_type',
            'total_students', 'pricing_type', 'price', 'original_price',
            'currency', 'is_free', 'discount_percent',
        ]


class TopicSerializer(serializers.ModelSerializer):
    """Serializer for Topic model."""
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    subtopics_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Topic
        fields = [
            'id', 'name', 'code', 'description', 'subject', 'subject_name',
            'parent_topic', 'difficulty', 'importance',
            'estimated_study_hours', 'total_questions', 'total_content',
            'subtopics_count', 'order'
        ]
    
    def get_subtopics_count(self, obj):
        return obj.subtopics.count()


class TopicDetailSerializer(TopicSerializer):
    """Detailed serializer with subtopics."""
    subtopics = TopicSerializer(many=True, read_only=True)
    
    class Meta(TopicSerializer.Meta):
        fields = TopicSerializer.Meta.fields + ['subtopics']


class SubjectSerializer(serializers.ModelSerializer):
    """Serializer for Subject model."""
    topics_count = serializers.SerializerMethodField()
    quizzes_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Subject
        fields = [
            'id', 'name', 'code', 'description', 'icon', 'color', 'course',
            'weightage', 'total_topics', 'total_questions',
            'topics_count', 'quizzes_count', 'order'
        ]
    
    def get_topics_count(self, obj):
        return obj.topics.count()

    def get_quizzes_count(self, obj):
        return obj.quizzes.count()


class SubjectDetailSerializer(SubjectSerializer):
    """Detailed serializer with topics."""
    topics = TopicSerializer(many=True, read_only=True)
    
    class Meta(SubjectSerializer.Meta):
        fields = SubjectSerializer.Meta.fields + ['topics']


class ChapterSerializer(serializers.ModelSerializer):
    """Serializer for Chapter model."""
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    topics_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Chapter
        fields = [
            'id', 'name', 'code', 'description', 'subject', 'subject_name',
            'grade', 'book_reference', 'estimated_hours', 'topics_count', 'order'
        ]
    
    def get_topics_count(self, obj):
        return obj.topics.count()


class ChapterDetailSerializer(ChapterSerializer):
    """Detailed serializer with topics in chapter order (via ChapterTopic)."""
    topics = serializers.SerializerMethodField()

    class Meta(ChapterSerializer.Meta):
        fields = ChapterSerializer.Meta.fields + ['topics']

    def get_topics(self, obj):
        qs = obj.chapter_topics.select_related('topic').order_by('order')
        return TopicSerializer([ct.topic for ct in qs], many=True).data


def chapter_content_type_counts(topic_ids):
    """Published content grouped by student-facing type for a set of topics.

    Mirrors the taxonomy used by the study flow (reading / videos / quizzes /
    assignments / coding / labs) so the pre-enrollment curriculum preview
    matches what an enrolled student actually sees. Returns an ordered list of
    {key, label, count}, only including non-zero buckets.
    """
    from content.models import Content
    from quiz.models import Quiz
    from assignments.models import Assignment
    from coding.models import CodingProblem
    from notebooks.models import Notebook

    if not topic_ids:
        return []

    published_content = Content.objects.filter(topic_id__in=topic_ids, status='published')
    reading = published_content.filter(
        content_type__in=['notes', 'pdf', 'revision', 'formula']
    ).count()
    videos = published_content.filter(content_type='video').count()
    quizzes = Quiz.objects.filter(topic_id__in=topic_ids, status='published').count()
    assignments = Assignment.objects.filter(topic_id__in=topic_ids, status='published').count()
    coding = CodingProblem.objects.filter(topic_id__in=topic_ids, status='published').count()
    labs = Notebook.objects.filter(topic_id__in=topic_ids, status='published').count()

    buckets = [
        ('reading', 'Reading material', reading),
        ('videos', 'Videos', videos),
        ('quizzes', 'Quizzes', quizzes),
        ('assignments', 'Assignments', assignments),
        ('coding', 'Coding problems', coding),
        ('labs', 'Labs', labs),
    ]
    return [
        {'key': key, 'label': label, 'count': count}
        for key, label, count in buckets if count
    ]


class CurriculumChapterSerializer(serializers.ModelSerializer):
    """Chapter with a per-type breakdown of the content it contains."""
    topics_count = serializers.SerializerMethodField()
    content_types = serializers.SerializerMethodField()
    content_total = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = [
            'id', 'name', 'code', 'description', 'order',
            'estimated_hours', 'topics_count', 'content_types', 'content_total',
        ]

    def _topic_ids(self, obj):
        return list(obj.chapter_topics.values_list('topic_id', flat=True))

    def get_topics_count(self, obj):
        return obj.chapter_topics.count()

    def get_content_types(self, obj):
        return chapter_content_type_counts(self._topic_ids(obj))

    def get_content_total(self, obj):
        return sum(b['count'] for b in chapter_content_type_counts(self._topic_ids(obj)))


class CurriculumSubjectSerializer(SubjectSerializer):
    """Subject with nested chapters + their content breakdown for the
    course-details curriculum preview."""
    chapters = serializers.SerializerMethodField()

    class Meta(SubjectSerializer.Meta):
        fields = SubjectSerializer.Meta.fields + ['chapters']

    def get_chapters(self, obj):
        qs = obj.chapters.all().order_by('order', 'name').prefetch_related('chapter_topics')
        return CurriculumChapterSerializer(qs, many=True).data


class CourseDetailSerializer(CourseSerializer):
    """Detailed course serializer with curriculum (subjects -> chapters)."""
    subjects = serializers.SerializerMethodField()

    class Meta(CourseSerializer.Meta):
        fields = CourseSerializer.Meta.fields + ['subjects']

    def get_subjects(self, obj):
        qs = obj.subjects.all().order_by('order', 'name')
        return CurriculumSubjectSerializer(qs, many=True, context=self.context).data


class SubjectWithChaptersSerializer(SubjectSerializer):
    """Subject serializer with nested chapters."""
    chapters = ChapterSerializer(many=True, read_only=True)
    
    class Meta(SubjectSerializer.Meta):
        fields = SubjectSerializer.Meta.fields + ['chapters']


class CourseContentExplorerSerializer(CourseSerializer):
    """Hierarchical serializer for admin content explorer: Course -> Subject -> Chapter."""
    subjects = SubjectWithChaptersSerializer(many=True, read_only=True)
    
    class Meta(CourseSerializer.Meta):
        fields = CourseSerializer.Meta.fields + ['subjects']

