"""Admin/instructor authoring + submission review serializers for notebooks."""
from rest_framework import serializers

from .models import (
    Notebook, NotebookDataset, NotebookSubmission, NotebookTest,
)
from .nbformat_utils import (
    KNOWN_PACKAGES, NotebookFormatError, answer_grade_ids, normalize_notebook,
)


class AdminNotebookTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotebookTest
        fields = [
            'id', 'grade_id', 'name', 'source', 'points', 'is_hidden',
            'failure_hint', 'order',
        ]


class AdminNotebookDatasetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    size_bytes = serializers.SerializerMethodField()

    class Meta:
        model = NotebookDataset
        fields = ['id', 'notebook', 'filename', 'file', 'description', 'order',
                  'url', 'size_bytes']
        read_only_fields = ['url', 'size_bytes']

    def get_url(self, obj):
        if not obj.file:
            return ''
        request = self.context.get('request')
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url

    def get_size_bytes(self, obj):
        try:
            return obj.file.size if obj.file else 0
        except (OSError, ValueError):
            return 0

    def validate_filename(self, value):
        name = (value or '').strip()
        if not name:
            raise serializers.ValidationError('A filename is required.')
        if '/' in name or '\\' in name or name.startswith('.'):
            raise serializers.ValidationError(
                'Use a plain filename with no path separators, e.g. "data.csv".'
            )
        return name


class AdminNotebookSerializer(serializers.ModelSerializer):
    tests = AdminNotebookTestSerializer(many=True, required=False)
    datasets = AdminNotebookDatasetSerializer(many=True, read_only=True)
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    course_name = serializers.CharField(source='course.name', read_only=True)
    submission_count = serializers.SerializerMethodField()
    test_count = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    answer_cells = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'course', 'course_name', 'subject', 'subject_name', 'topic', 'topic_name',
            'title', 'description', 'difficulty', 'template_json', 'packages',
            'time_limit_ms', 'memory_limit_mb', 'max_marks', 'status', 'order',
            'estimated_time_minutes', 'is_timed', 'due_at',
            'allow_resubmission', 'max_attempts', 'provisional_grading',
            'show_results_to_students',
            'tests', 'datasets', 'submission_count', 'test_count', 'total_points',
            'answer_cells', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_submission_count(self, obj):
        return obj.submissions.count()

    def get_test_count(self, obj):
        return obj.tests.count()

    def get_total_points(self, obj):
        return sum(t.points for t in obj.tests.all())

    def get_answer_cells(self, obj):
        """grade_ids declared by the template's answer cells, for the test editor."""
        return answer_grade_ids(obj.template_json)

    def validate_template_json(self, value):
        try:
            return normalize_notebook(value)
        except NotebookFormatError as exc:
            raise serializers.ValidationError(str(exc))

    def validate_packages(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Must be a list of package names.')
        cleaned = []
        for item in value:
            name = str(item).strip()
            if not name:
                continue
            if not all(ch.isalnum() or ch in '-_.' for ch in name):
                raise serializers.ValidationError(f'Invalid package name: {item}')
            cleaned.append(name)
        return cleaned

    def validate(self, attrs):
        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default)

        if current('is_timed', False) and not current('due_at'):
            raise serializers.ValidationError({
                'due_at': 'A due date is required for a timed notebook.',
            })
        if current('allow_resubmission', True):
            max_attempts = current('max_attempts')
            if max_attempts is not None and max_attempts < 1:
                raise serializers.ValidationError({
                    'max_attempts': 'Leave blank for unlimited attempts, or set at least 1.',
                })
        return attrs

    def _write_tests(self, notebook, tests):
        notebook.tests.all().delete()
        for i, t in enumerate(tests):
            NotebookTest.objects.create(
                notebook=notebook,
                grade_id=(t.get('grade_id') or '').strip(),
                name=t.get('name') or f'Test {i + 1}',
                source=t.get('source', ''),
                points=t.get('points', 1),
                is_hidden=t.get('is_hidden', True),
                failure_hint=t.get('failure_hint', ''),
                order=t.get('order', i),
            )

    def create(self, validated_data):
        tests = validated_data.pop('tests', None)
        notebook = super().create(validated_data)
        if tests is not None:
            self._write_tests(notebook, tests)
        return notebook

    def update(self, instance, validated_data):
        tests = validated_data.pop('tests', None)
        notebook = super().update(instance, validated_data)
        if tests is not None:
            self._write_tests(notebook, tests)
        return notebook


class AdminNotebookListSerializer(serializers.ModelSerializer):
    """Compact list row for the course builder."""
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    submission_count = serializers.SerializerMethodField()
    test_count = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'title', 'difficulty', 'status', 'order', 'max_marks',
            'course', 'subject', 'topic', 'topic_name', 'is_timed', 'due_at',
            'submission_count', 'test_count', 'created_at', 'updated_at',
        ]

    def get_submission_count(self, obj):
        return obj.submissions.count()

    def get_test_count(self, obj):
        return obj.tests.count()


class AdminSubmissionSerializer(serializers.ModelSerializer):
    """Full submission view for admins/instructors (includes everything)."""
    student_name = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    all_passed = serializers.BooleanField(read_only=True)
    final_marks = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    score_percent = serializers.IntegerField(read_only=True)
    notebook_title = serializers.CharField(source='notebook.title', read_only=True)
    notebook_max_marks = serializers.IntegerField(source='notebook.max_marks', read_only=True)
    graded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = NotebookSubmission
        fields = [
            'id', 'notebook', 'notebook_title', 'notebook_max_marks',
            'student', 'student_name', 'student_email', 'attempt_number',
            'notebook_json', 'status', 'results', 'execution_error',
            'passed_count', 'total_count', 'passed_points', 'total_points',
            'marks', 'override_marks', 'final_marks', 'score_percent',
            'provisional_passed_points', 'provisional_total_points',
            'provisional_results', 'all_passed', 'feedback', 'is_late',
            'submitted_at', 'graded_at', 'graded_by', 'graded_by_name',
        ]
        read_only_fields = [
            'notebook', 'student', 'attempt_number', 'notebook_json', 'status',
            'results', 'execution_error', 'passed_count', 'total_count',
            'passed_points', 'total_points', 'marks',
            'provisional_passed_points', 'provisional_total_points',
            'provisional_results', 'is_late', 'submitted_at', 'graded_at',
            'graded_by',
        ]

    def _user(self, obj):
        return getattr(obj.student, 'user', None)

    def get_student_name(self, obj):
        u = self._user(obj)
        if not u:
            return ''
        return (getattr(u, 'full_name', '') or u.email or '').strip()

    def get_student_email(self, obj):
        u = self._user(obj)
        return u.email if u else ''

    def get_graded_by_name(self, obj):
        u = obj.graded_by
        if not u:
            return ''
        return (getattr(u, 'full_name', '') or u.email or '').strip()


class AdminSubmissionListSerializer(AdminSubmissionSerializer):
    """List row: same as the full view minus the heavy notebook document."""

    class Meta(AdminSubmissionSerializer.Meta):
        fields = [f for f in AdminSubmissionSerializer.Meta.fields
                  if f not in ('notebook_json', 'provisional_results')]


class NotebookMetaSerializer(serializers.Serializer):
    """Static authoring metadata for the admin UI."""
    packages = serializers.ListField(child=serializers.CharField(), read_only=True)

    @staticmethod
    def payload():
        return {
            'packages': KNOWN_PACKAGES,
            'cell_roles': [
                {'key': 'readonly', 'label': 'Locked (students can read, not edit)'},
                {'key': 'editable', 'label': 'Scratch (students can edit, not graded)'},
                {'key': 'answer', 'label': 'Answer (students edit, graded)'},
            ],
            'provisional_modes': [
                {'key': k, 'label': v} for k, v in Notebook.PROVISIONAL_CHOICES
            ],
            'difficulties': [{'key': k, 'label': v} for k, v in Notebook.DIFFICULTY_CHOICES],
        }
