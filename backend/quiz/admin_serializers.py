"""
Writable serializers for the admin Quiz Builder.

These power full CRUD over Quizzes and their Questions (with options) from the
Course Content Builder. Question correctness is stored in the same format the quiz
player submits: for ``mcq``/``true_false`` the ``correct_answer`` is the string
index of the correct option (matching ``Answer.selected_option``); for
``fill_blank`` it is the expected text; for ``numerical`` the answer lives in
``numerical_answer`` (with ``correct_answer`` mirrored as a string for display).
"""
from rest_framework import serializers

from core.serializer_fields import Base64ImageField
from .models import (
    Quiz, Question, QuestionOption, QuizQuestion,
    MockTest, MockTestItem, MockTestQuestion,
)
from coding.languages import LANGUAGE_KEYS


class AdminQuestionOptionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    option_image = Base64ImageField(required=False, allow_null=True)

    class Meta:
        model = QuestionOption
        fields = ['id', 'option_text', 'is_correct', 'option_image', 'order']
        extra_kwargs = {'order': {'required': False}}


class AdminQuestionSerializer(serializers.ModelSerializer):
    """Writable serializer for Question with nested options and quiz linking."""
    options = AdminQuestionOptionSerializer(many=True, required=False)
    question_image = Base64ImageField(required=False, allow_null=True)
    explanation_image = Base64ImageField(required=False, allow_null=True)
    quiz = serializers.PrimaryKeyRelatedField(
        queryset=Quiz.objects.all(), required=False, allow_null=True, write_only=True
    )
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'question_text', 'question_html', 'question_image', 'question_type',
            'difficulty', 'status', 'topic', 'topic_name', 'subject',
            'subject_name', 'courses', 'correct_answer', 'explanation',
            'explanation_image', 'numerical_answer', 'numerical_tolerance',
            'marks', 'negative_marks',
            'source', 'year', 'tags', 'options', 'quiz',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'courses': {'required': False},
            'correct_answer': {'required': False, 'allow_blank': True},
        }

    def _tenant(self):
        request = self.context.get('request')
        return getattr(request, 'tenant', None)

    def validate(self, attrs):
        """Reject relations that belong to another tenant (cross-tenant linking)."""
        tenant = self._tenant()
        if tenant is not None:
            quiz = attrs.get('quiz')
            if quiz is not None and getattr(quiz.course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'quiz': 'Quiz not found for this tenant.'})
            topic = attrs.get('topic')
            if topic is not None and getattr(topic.subject.course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'topic': 'Topic not found for this tenant.'})
            subject = attrs.get('subject')
            if subject is not None and getattr(subject.course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'subject': 'Subject not found for this tenant.'})
        return attrs

    def _sync_options(self, question, options):
        """
        Reconcile the question's options against the supplied list.

        Options are matched by ``id`` so that existing images (which the client
        round-trips as URLs, not base64) are preserved when untouched. Options
        missing from the payload are deleted.
        """
        existing = {str(o.id): o for o in question.options.all()}
        seen = set()
        for index, opt in enumerate(options):
            oid = str(opt['id']) if opt.get('id') else None
            values = {
                'option_text': opt.get('option_text', ''),
                'is_correct': opt.get('is_correct', False),
                'order': opt.get('order', index),
            }
            # 'option_image' is only present when a new base64 image (ContentFile)
            # or an explicit null (clear) was sent; URLs raise SkipField upstream.
            has_image = 'option_image' in opt

            if oid and oid in existing:
                obj = existing[oid]
                for attr, value in values.items():
                    setattr(obj, attr, value)
                if has_image:
                    obj.option_image = opt['option_image']
                obj.save()
                seen.add(oid)
            else:
                obj = QuestionOption(question=question, **values)
                if has_image:
                    obj.option_image = opt['option_image']
                obj.save()

        for oid, obj in existing.items():
            if oid not in seen:
                obj.delete()

    def _link_quiz(self, question, quiz):
        if quiz is None:
            return
        if QuizQuestion.objects.filter(quiz=quiz, question=question).exists():
            return
        next_order = QuizQuestion.objects.filter(quiz=quiz).count()
        QuizQuestion.objects.create(quiz=quiz, question=question, order=next_order)

    def create(self, validated_data):
        options = validated_data.pop('options', None)
        quiz = validated_data.pop('quiz', None)
        courses = validated_data.pop('courses', None)
        subject = validated_data.get('subject')

        question = Question.objects.create(**validated_data)

        if courses:
            question.courses.set(courses)
        elif subject is not None and getattr(subject, 'course_id', None):
            question.courses.set([subject.course])

        if options is not None:
            self._sync_options(question, options)
        self._link_quiz(question, quiz)
        return question

    def update(self, instance, validated_data):
        options = validated_data.pop('options', None)
        quiz = validated_data.pop('quiz', None)
        courses = validated_data.pop('courses', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if courses is not None:
            instance.courses.set(courses)
        if options is not None:
            self._sync_options(instance, options)
        self._link_quiz(instance, quiz)

        # A content edit invalidates the item's concept/difficulty tags.
        from intelligence import api as intelligence_api
        intelligence_api.mark_item_stale_if_changed(instance)
        return instance


class AdminQuizSerializer(serializers.ModelSerializer):
    """Writable serializer for Quiz; derives course/subject from topic when omitted."""
    questions_count = serializers.IntegerField(source='questions.count', read_only=True)
    course_name = serializers.CharField(source='course.name', read_only=True)

    class Meta:
        model = Quiz
        fields = [
            'id', 'title', 'description', 'quiz_type', 'status',
            'course', 'course_name', 'subject', 'topic',
            'duration_minutes', 'total_marks', 'passing_marks',
            'shuffle_questions', 'shuffle_options', 'show_answer_after_each',
            'allow_skip', 'is_free', 'questions_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'course': {'required': False},
            'quiz_type': {'required': False},
        }

    def validate(self, attrs):
        topic = attrs.get('topic')
        if topic is not None:
            attrs.setdefault('subject', topic.subject)
            if not attrs.get('course'):
                attrs['course'] = topic.subject.course
        subject = attrs.get('subject')
        if subject is not None and not attrs.get('course'):
            attrs['course'] = subject.course
        if not attrs.get('quiz_type'):
            if topic is not None:
                attrs['quiz_type'] = 'topic'
            elif subject is not None:
                attrs['quiz_type'] = 'subject'
            else:
                attrs['quiz_type'] = 'custom'

        # Reject relations that belong to another tenant.
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None)
        if tenant is not None:
            course = attrs.get('course')
            if course is not None and getattr(course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'course': 'Course not found for this tenant.'})
            if attrs.get('subject') is not None and getattr(attrs['subject'].course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'subject': 'Subject not found for this tenant.'})
            if topic is not None and getattr(topic.subject.course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'topic': 'Topic not found for this tenant.'})
        return attrs


# ---------------------------------------------------------------------------
# Rich Mock Test builder (Phase 2)
# ---------------------------------------------------------------------------

class AdminMockTestItemSerializer(serializers.ModelSerializer):
    """Writable serializer for a single inline mock-test item (any type)."""
    id = serializers.UUIDField(required=False)
    question_image = Base64ImageField(required=False, allow_null=True)

    class Meta:
        model = MockTestItem
        fields = [
            'id', 'mock_test', 'item_type', 'section', 'order',
            'question_text', 'question_html', 'question_image', 'explanation',
            'marks', 'negative_marks', 'options',
            'numerical_answer', 'numerical_tolerance',
            'max_words', 'rubric', 'model_answer',
            'allowed_languages', 'starter_code', 'time_limit_ms',
            'memory_limit_mb', 'coding_test_cases',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'mock_test': {'required': False},   # set by the viewset on create
            'order': {'required': False},
        }

    def validate_allowed_languages(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Must be a list of language keys.')
        bad = [v for v in value if v not in LANGUAGE_KEYS]
        if bad:
            raise serializers.ValidationError(f'Unsupported languages: {", ".join(bad)}')
        return value

    def validate_options(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Options must be a list.')
        return value

    def validate_coding_test_cases(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Test cases must be a list.')
        return value

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        # A content edit invalidates the item's concept/difficulty tags.
        from intelligence import api as intelligence_api
        intelligence_api.mark_item_stale_if_changed(instance)
        return instance


class AdminMockTestQuestionSerializer(serializers.ModelSerializer):
    """Read-oriented serializer for a bank question linked into a mock test."""
    question_detail = serializers.SerializerMethodField()
    effective_marks = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    effective_negative_marks = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True,
    )

    class Meta:
        model = MockTestQuestion
        fields = [
            'id', 'question', 'section', 'order',
            'marks_override', 'negative_marks_override',
            'effective_marks', 'effective_negative_marks', 'question_detail',
        ]
        read_only_fields = ['id']

    def get_question_detail(self, obj):
        q = obj.question
        return {
            'id': str(q.id),
            'question_text': q.question_text,
            'question_type': q.question_type,
            'marks': float(q.marks),
            'negative_marks': float(q.negative_marks),
            'topic': str(q.topic_id) if q.topic_id else None,
            'subject': str(q.subject_id) if q.subject_id else None,
        }


class AdminMockTestSerializer(serializers.ModelSerializer):
    """Writable serializer for the rich mock-test builder (scalars + course links).

    Inline items and bank questions are managed via dedicated endpoints; they are
    exposed here read-only for display.
    """
    course_name = serializers.CharField(source='course.name', read_only=True, default=None)
    items = AdminMockTestItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    bank_questions_count = serializers.SerializerMethodField()
    computed_total_marks = serializers.SerializerMethodField()

    class Meta:
        model = MockTest
        fields = [
            'id', 'title', 'description', 'course', 'course_name', 'courses',
            'sections', 'duration_minutes', 'total_marks', 'negative_marking',
            'status', 'is_free', 'result_visibility', 'results_released',
            'start_deadline', 'fullscreen_required', 'max_attempts',
            'available_from', 'available_until',
            'is_pyp', 'pyp_year', 'pyp_shift', 'pyp_session', 'pyp_date',
            'items', 'items_count', 'bank_questions_count', 'computed_total_marks',
            'total_attempts', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'total_attempts', 'created_at', 'updated_at']
        extra_kwargs = {
            'course': {'required': False, 'allow_null': True},
            'courses': {'required': False},
            'total_marks': {'required': False},
            'sections': {'required': False},
        }

    def get_items_count(self, obj):
        return obj.items.count()

    def get_bank_questions_count(self, obj):
        return MockTestQuestion.objects.filter(mock_test=obj).count()

    def get_computed_total_marks(self, obj):
        items_total = sum((i.marks for i in obj.items.all()), 0)
        bank_total = sum(
            (mtq.effective_marks for mtq in
             MockTestQuestion.objects.filter(mock_test=obj).select_related('question')),
            0,
        )
        return float(items_total) + float(bank_total)

    def validate(self, attrs):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None)
        if tenant is not None:
            course = attrs.get('course')
            if course is not None and getattr(course, 'tenant_id', None) != tenant.id:
                raise serializers.ValidationError({'course': 'Course not found for this tenant.'})
            for c in attrs.get('courses', []) or []:
                if getattr(c, 'tenant_id', None) != tenant.id:
                    raise serializers.ValidationError({'courses': 'One or more courses not found for this tenant.'})
        return attrs
