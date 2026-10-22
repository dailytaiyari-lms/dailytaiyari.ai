"""Serializers for the student-facing practice + mastery APIs."""
from rest_framework import serializers

from .models import LearnerConceptState, PracticeSet, PracticeSetItem


class PracticeItemSerializer(serializers.ModelSerializer):
    """One question inside a set. Never leaks the correct answer before the
    item is answered — grading responses carry the review payload instead."""

    question_id = serializers.UUIDField(source='question.id', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    question_html = serializers.CharField(source='question.question_html', read_only=True)
    difficulty = serializers.CharField(source='question.difficulty', read_only=True)
    options = serializers.SerializerMethodField()
    answered = serializers.SerializerMethodField()

    class Meta:
        model = PracticeSetItem
        fields = [
            'id', 'order', 'role', 'question_id', 'question_type',
            'question_text', 'question_html', 'difficulty', 'options',
            'answered', 'is_correct', 'time_taken_seconds',
        ]
        read_only_fields = fields

    def get_options(self, item):
        return [
            {'index': i, 'text': option.option_text}
            for i, option in enumerate(item.question.options.order_by('order'))
        ]

    def get_answered(self, item):
        return item.answered_at is not None


class PracticeSetSerializer(serializers.ModelSerializer):
    reason_text = serializers.SerializerMethodField()
    concepts = serializers.SerializerMethodField()
    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    ladder = serializers.SerializerMethodField()

    class Meta:
        model = PracticeSet
        fields = [
            'id', 'status', 'deficit_kind', 'reason_text', 'concepts',
            'course', 'course_name', 'item_count', 'score_correct',
            'score_total', 'xp_awarded', 'ladder', 'created_at',
            'started_at', 'completed_at', 'expires_at',
        ]
        read_only_fields = fields

    def get_reason_text(self, practice_set):
        return (practice_set.reason or {}).get('text', '')

    def get_concepts(self, practice_set):
        return [concept.name for concept in practice_set.target_concepts.all()]

    def get_ladder(self, practice_set):
        counts = {}
        for role in practice_set.items.values_list('role', flat=True):
            counts[role] = counts.get(role, 0) + 1
        return counts


class PracticeSetDetailSerializer(PracticeSetSerializer):
    items = PracticeItemSerializer(many=True, read_only=True)

    class Meta(PracticeSetSerializer.Meta):
        fields = PracticeSetSerializer.Meta.fields + ['items']
        read_only_fields = fields


class MasteryRowSerializer(serializers.ModelSerializer):
    concept_id = serializers.UUIDField(source='concept.id', read_only=True)
    concept = serializers.CharField(source='concept.name', read_only=True)
    subject = serializers.CharField(source='concept.subject.name', read_only=True)

    class Meta:
        model = LearnerConceptState
        fields = [
            'concept_id', 'concept', 'subject', 'mastery', 'retention',
            'confidence', 'evidence_count', 'transfer_gap', 'flags',
            'last_seen_at',
        ]
        read_only_fields = fields
