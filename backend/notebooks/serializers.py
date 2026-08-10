"""Student-facing serializers for notebooks."""
from rest_framework import serializers

from .models import Notebook, NotebookDataset, NotebookSubmission, NotebookTest


class NotebookDatasetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    size_bytes = serializers.SerializerMethodField()

    class Meta:
        model = NotebookDataset
        fields = ['id', 'filename', 'description', 'url', 'size_bytes', 'order']

    def get_url(self, obj):
        if not obj.file:
            return ''
        url = obj.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def get_size_bytes(self, obj):
        try:
            return obj.file.size if obj.file else 0
        except (OSError, ValueError):
            return 0


class VisibleTestSerializer(serializers.ModelSerializer):
    """A non-hidden test. Source is included so the browser kernel can run it."""

    class Meta:
        model = NotebookTest
        fields = ['id', 'name', 'grade_id', 'source', 'points', 'is_hidden', 'order']


class TestSummarySerializer(serializers.ModelSerializer):
    """Hidden tests, described but never revealed (no `source`)."""

    class Meta:
        model = NotebookTest
        fields = ['id', 'name', 'grade_id', 'points', 'is_hidden', 'order']


class MySubmissionSummarySerializer(serializers.ModelSerializer):
    all_passed = serializers.BooleanField(read_only=True)
    final_marks = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    score_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = NotebookSubmission
        fields = [
            'id', 'attempt_number', 'status', 'passed_count', 'total_count',
            'passed_points', 'total_points', 'marks', 'override_marks',
            'final_marks', 'score_percent', 'all_passed', 'is_late',
            'submitted_at', 'graded_at',
        ]


class SubmissionResultSerializer(serializers.ModelSerializer):
    """Result of a submission as shown to its owner.

    Hidden-test *sources* are never included, and when the notebook is
    configured with show_results_to_students=False the per-test breakdown is
    withheld entirely (only the aggregate score is shown).
    """
    results = serializers.SerializerMethodField()
    all_passed = serializers.BooleanField(read_only=True)
    final_marks = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    score_percent = serializers.IntegerField(read_only=True)
    notebook_max_marks = serializers.IntegerField(source='notebook.max_marks', read_only=True)

    class Meta:
        model = NotebookSubmission
        fields = [
            'id', 'notebook', 'notebook_max_marks', 'attempt_number', 'status',
            'results', 'execution_error', 'passed_count', 'total_count',
            'passed_points', 'total_points', 'marks', 'override_marks',
            'final_marks', 'score_percent', 'all_passed', 'feedback',
            'is_late', 'submitted_at', 'graded_at',
        ]

    def get_results(self, obj):
        if not obj.notebook.show_results_to_students:
            return []
        # `results` already carries only verdicts/points/messages — never test
        # source — but strip defensively so a future field can't leak.
        return [
            {
                'index': r.get('index'),
                'name': r.get('name'),
                'grade_id': r.get('grade_id'),
                'is_hidden': r.get('is_hidden'),
                'passed': r.get('passed'),
                'points': r.get('points'),
                'max_points': r.get('max_points'),
                'error': r.get('error'),
            }
            for r in (obj.results or [])
        ]


class MyStatusMixin:
    """Shared helpers for exposing the student's own state on a notebook."""

    def get_my_best(self, obj):
        best = getattr(obj, '_my_best', None)
        return MySubmissionSummarySerializer(best).data if best else None

    def get_attempts_used(self, obj):
        return getattr(obj, '_attempts_used', 0)

    def get_attempts_remaining(self, obj):
        return obj.attempts_remaining(getattr(obj, '_attempts_used', 0))

    def get_is_complete(self, obj):
        completion = getattr(obj, '_my_completion', None)
        return bool(completion and completion.is_complete)

    def get_can_submit(self, obj):
        if not obj.is_open:
            return False
        remaining = obj.attempts_remaining(getattr(obj, '_attempts_used', 0))
        return remaining is None or remaining > 0


class NotebookListSerializer(MyStatusMixin, serializers.ModelSerializer):
    """Compact list view; includes the student's best-so-far status."""
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    my_best = serializers.SerializerMethodField()
    attempts_used = serializers.SerializerMethodField()
    attempts_remaining = serializers.SerializerMethodField()
    is_complete = serializers.SerializerMethodField()
    can_submit = serializers.SerializerMethodField()
    is_open = serializers.BooleanField(read_only=True)
    is_past_due = serializers.BooleanField(read_only=True)
    test_count = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'title', 'description', 'difficulty', 'max_marks', 'status', 'order',
            'topic', 'topic_name', 'subject', 'subject_name',
            'estimated_time_minutes', 'is_timed', 'due_at', 'is_open', 'is_past_due',
            'allow_resubmission', 'max_attempts',
            'my_best', 'attempts_used', 'attempts_remaining', 'is_complete',
            'can_submit', 'test_count',
        ]

    def get_test_count(self, obj):
        return obj.tests.count()


class NotebookDetailSerializer(MyStatusMixin, serializers.ModelSerializer):
    """Full notebook for the work page.

    ``notebook_json`` is the student's own working copy: their autosaved draft
    if they have one, otherwise a fresh copy of the template. Only *visible*
    test sources are exposed (plus hidden ones when the notebook opts into
    ``provisional_grading='all'``); hidden tests are otherwise described by
    name and points only.
    """
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    notebook_json = serializers.SerializerMethodField()
    template_json = serializers.SerializerMethodField()
    datasets = NotebookDatasetSerializer(many=True, read_only=True)
    packages = serializers.SerializerMethodField()
    tests = serializers.SerializerMethodField()
    hidden_test_count = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    my_best = serializers.SerializerMethodField()
    my_submissions = serializers.SerializerMethodField()
    attempts_used = serializers.SerializerMethodField()
    attempts_remaining = serializers.SerializerMethodField()
    is_complete = serializers.SerializerMethodField()
    can_submit = serializers.SerializerMethodField()
    is_open = serializers.BooleanField(read_only=True)
    is_past_due = serializers.BooleanField(read_only=True)
    draft_saved_at = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'title', 'description', 'difficulty', 'max_marks', 'status',
            'topic', 'topic_name', 'subject', 'subject_name',
            'notebook_json', 'template_json', 'datasets', 'packages',
            'tests', 'hidden_test_count', 'total_points',
            'time_limit_ms', 'memory_limit_mb', 'estimated_time_minutes',
            'is_timed', 'due_at', 'is_open', 'is_past_due',
            'allow_resubmission', 'max_attempts', 'provisional_grading',
            'show_results_to_students',
            'my_best', 'my_submissions', 'attempts_used', 'attempts_remaining',
            'is_complete', 'can_submit', 'draft_saved_at',
        ]

    def get_notebook_json(self, obj):
        draft = getattr(obj, '_my_draft', None)
        if draft and draft.notebook_json:
            return draft.notebook_json
        return obj.template_json

    def get_template_json(self, obj):
        return obj.template_json

    def get_packages(self, obj):
        return obj.normalized_packages()

    def get_tests(self, obj):
        """Tests the browser kernel is allowed to see.

        Hidden test sources stay on the server unless the notebook explicitly
        opts into full in-browser provisional grading.
        """
        tests = list(obj.tests.all().order_by('order', 'created_at'))
        if obj.provisional_grading == Notebook.PROVISIONAL_ALL:
            return VisibleTestSerializer(tests, many=True).data
        payload = []
        for test in tests:
            if test.is_hidden:
                payload.append(TestSummarySerializer(test).data)
            else:
                payload.append(VisibleTestSerializer(test).data)
        return payload

    def get_hidden_test_count(self, obj):
        return sum(1 for t in obj.tests.all() if t.is_hidden)

    def get_total_points(self, obj):
        return sum(t.points for t in obj.tests.all())

    def get_my_submissions(self, obj):
        subs = getattr(obj, '_my_submissions', None) or []
        return MySubmissionSummarySerializer(subs, many=True).data

    def get_draft_saved_at(self, obj):
        draft = getattr(obj, '_my_draft', None)
        return draft.updated_at if draft else None
