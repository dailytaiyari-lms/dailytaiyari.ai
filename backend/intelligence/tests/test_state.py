"""The learner-state algorithm, tested as the pure function it is,
plus one integration pass through real events and concept links."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, ConceptLink, LearnerConceptState
from intelligence.services import itemstats
from intelligence.services.events import record_attempt_events
from intelligence.services.state import (
    _Observation, compute_state_fields, recompute_state, update_for_attempt,
)
from quiz.models import MockTest, MockTestAnswer, MockTestAttempt, MockTestItem
from users.models import User

NOW = timezone.now()


def obs(days_ago, score, *, weight=1.0, multi=False, item='item1', selected=None):
    return _Observation(
        occurred_at=NOW - timedelta(days=days_ago),
        score=score, link_weight=weight, is_multi=multi,
        item_ref=item, selected=selected or [],
    )


class StateAlgorithmTests(TestCase):
    def test_no_observations_returns_none(self):
        self.assertIsNone(compute_state_fields([], now=NOW))

    def test_prior_blocks_one_lucky_answer(self):
        fields = compute_state_fields([obs(0, 1.0)], now=NOW)
        # (1·1 + 3·0.5) / (1 + 3) — far from certainty.
        self.assertAlmostEqual(fields['mastery'], 0.625, places=3)
        self.assertEqual(fields['confidence'], 'low')

    def test_recent_evidence_outweighs_old(self):
        improving = compute_state_fields([obs(60, 0.0), obs(0, 1.0)], now=NOW)
        declining = compute_state_fields([obs(60, 1.0), obs(0, 0.0)], now=NOW)
        self.assertGreater(improving['mastery'], declining['mastery'])

    def test_fading_retention_flag(self):
        history = [obs(40, 1.0), obs(30, 1.0), obs(20, 1.0)]
        fields = compute_state_fields(history, now=NOW)
        self.assertGreaterEqual(fields['mastery'], 0.6)
        self.assertLess(fields['retention'], 0.7)
        self.assertIn('fading_retention', fields['flags'])
        # Practising today resets the countdown.
        fields = compute_state_fields(history + [obs(0, 1.0)], now=NOW)
        self.assertNotIn('fading_retention', fields['flags'])

    def test_spacing_grows_stability_more_than_cramming(self):
        spaced = compute_state_fields(
            [obs(30, 1.0), obs(20, 1.0), obs(10, 1.0), obs(0, 1.0)], now=NOW,
        )
        crammed = compute_state_fields(
            [obs(0.3, 1.0), obs(0.2, 1.0), obs(0.1, 1.0), obs(0, 1.0)], now=NOW,
        )
        self.assertGreater(spaced['stability_days'], crammed['stability_days'])

    def test_weak_transfer_flag(self):
        history = [obs(1, 1.0, item=f's{i}') for i in range(15)]
        history += [obs(1, 0.0, multi=True, item=f'm{i}') for i in range(5)]
        fields = compute_state_fields(history, now=NOW)
        self.assertGreaterEqual(fields['mastery'], 0.7)
        self.assertGreaterEqual(fields['transfer_gap'], 0.25)
        self.assertIn('weak_transfer', fields['flags'])

    def test_transfer_gap_needs_evidence_in_both_buckets(self):
        history = [obs(1, 1.0, item=f's{i}') for i in range(10)]
        history += [obs(1, 0.0, multi=True, item='m1')]  # only one multi item
        fields = compute_state_fields(history, now=NOW)
        self.assertIsNone(fields['transfer_gap'])
        self.assertNotIn('weak_transfer', fields['flags'])

    def test_repeat_misconception_flag(self):
        history = [
            obs(3, 0.0, item='q7', selected=[2]),
            obs(1, 0.0, item='q7', selected=[2]),
        ]
        fields = compute_state_fields(history, now=NOW)
        self.assertEqual(fields['misconception_counts'].get('q7:2'), 2)
        self.assertIn('repeat_misconception', fields['flags'])

    def test_confidence_tiers(self):
        self.assertEqual(compute_state_fields([obs(0, 1.0)], now=NOW)['confidence'], 'low')
        many = [obs(1, 1.0, item=f'i{n}') for n in range(12)]
        self.assertEqual(compute_state_fields(many, now=NOW)['confidence'], 'high')


class StateIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='State Academy', is_active=True)
        cls.user = User.objects.create_user(
            email='learner@example.com', password='pw-learner-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kin',
        )
        cls.concept_a = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Velocity', slug='velocity',
        )
        cls.concept_b = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Vectors', slug='vector',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, course=cls.course, title='Paper',
            duration_minutes=60, total_marks=8,
        )

    def make_answered_item(self, *, concepts, correct, selected=None):
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq',
            question_text=f'Q {len(concepts)} {correct}?', marks=4,
            topic=self.topic, subject=self.subject,
            options=[{'text': 'A', 'is_correct': True}, {'text': 'B', 'is_correct': False},
                     {'text': 'C', 'is_correct': False}],
        )
        for position, concept in enumerate(concepts):
            ConceptLink.objects.create(
                tenant=self.tenant, concept=concept, mock_item=item,
                is_primary=position == 0, weight=1.0 if position == 0 else 0.5,
                source='generator',
            )
        attempt = MockTestAttempt.objects.create(
            student=self.student, mock_test=self.mock_test, status='completed',
            completed_at=timezone.now(), percentage=50,
        )
        MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item,
            selected_options=selected if selected is not None else ([0] if correct else [1]),
            is_correct=correct, marks_obtained=4 if correct else 0, max_marks=4,
            time_taken_seconds=42,
        )
        record_attempt_events(attempt)
        return attempt, item

    def test_update_for_attempt_builds_states_for_touched_concepts(self):
        attempt, _item = self.make_answered_item(concepts=[self.concept_a], correct=True)
        touched = update_for_attempt('mock', str(attempt.id))
        self.assertEqual(touched, 1)
        state_row = LearnerConceptState.objects.get(student=self.student, concept=self.concept_a)
        self.assertEqual(state_row.tenant, self.tenant)
        self.assertEqual(state_row.evidence_count, 1)
        self.assertAlmostEqual(state_row.mastery, 0.625, places=2)

    def test_multi_concept_item_counts_in_multi_bucket_for_both_concepts(self):
        attempt, _item = self.make_answered_item(
            concepts=[self.concept_a, self.concept_b], correct=False,
        )
        update_for_attempt('mock', str(attempt.id))
        for concept in (self.concept_a, self.concept_b):
            state_row = LearnerConceptState.objects.get(student=self.student, concept=concept)
            self.assertEqual(state_row.multi_attempts, 1)
            self.assertEqual(state_row.single_attempts, 0)

    def test_recompute_is_idempotent(self):
        attempt, _item = self.make_answered_item(concepts=[self.concept_a], correct=True)
        update_for_attempt('mock', str(attempt.id))
        first = LearnerConceptState.objects.get(student=self.student, concept=self.concept_a)
        recompute_state(self.student, self.concept_a, now=first.computed_at)
        again = LearnerConceptState.objects.get(student=self.student, concept=self.concept_a)
        self.assertEqual(first.mastery, again.mastery)
        self.assertEqual(first.evidence_count, again.evidence_count)

    def test_item_stats_distractor_distribution(self):
        _attempt, item = self.make_answered_item(
            concepts=[self.concept_a], correct=False, selected=[2],
        )
        stats = itemstats.recompute_for_item(item)
        self.assertEqual(stats.attempts_count, 1)
        self.assertEqual(stats.correct_count, 0)
        self.assertEqual(stats.option_distribution, {'2': 1})
        self.assertIsNone(stats.discrimination)      # n < 30
        self.assertFalse(stats.difficulty_divergence)  # n < 20
        self.assertEqual(stats.observed_difficulty, 'hard')
