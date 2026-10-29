"""Skill and thinking-level profiles (spec 2B §6.3)."""
import io
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from exams.models import Course, Subject
from intelligence.models import ItemSkillTag, ItemTagging, LearnerFacetState, TagDefinition
from intelligence.services import facets
from intelligence.tasks import diagnose_and_update_state, refresh_learner_state
from intelligence.tests.progress_fixtures import PROGRESS_ON, ProgressTestCase
from users.models import User


class FacetModelTests(TestCase):
    def test_one_row_per_student_subject_kind_key(self):
        tenant = Tenant.objects.create(name='Facet Academy')
        student = User.objects.create_user(
            email='facet@example.com', password='pw-facet-1', tenant=tenant, role='student',
        ).profile
        course = Course.objects.create(tenant=tenant, name='Physics', code='facet-phy',
                                       course_type='competitive')
        subject = Subject.objects.create(tenant=tenant, course=course, name='Mechanics',
                                         code='facet-mech')
        LearnerFacetState.objects.create(
            tenant=tenant, student=student, subject=subject, kind='skill', key='vectors',
            mastery=0.6, evidence_count=2, effective_evidence=2.0, confidence='low',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            LearnerFacetState.objects.create(
                tenant=tenant, student=student, subject=subject, kind='skill', key='vectors',
            )
        self.assertEqual(student.facet_states.get().model_version, '1')



class FacetFixture(ProgressTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.vectors = TagDefinition.objects.create(
            kind='skill', key='vector_resolution', label='Vector resolution', definition='-')
        cls.units = TagDefinition.objects.create(
            kind='skill', key='unit_conversion', label='Unit conversion', definition='-')
        TagDefinition.objects.create(
            kind='thinking_level', key='apply', label='Apply', definition='-', order=2)

    def setUp(self):
        self.now = timezone.now()

    def tagged_question(self, n, *, skills=(), thinking='apply', node=None):
        question = self.make_question(n)
        ItemTagging.objects.create(
            tenant=self.tenant, question=question, primary_node=node or self.velocity,
            thinking_level=thinking, confidence=0.9,
        )
        for skill, role in skills:
            ItemSkillTag.objects.create(tenant=self.tenant, question=question, skill=skill, role=role)
        return question

    def rows(self):
        return {(row.kind, row.key): row for row in self.student.facet_states.all()}


class RecomputeTests(FacetFixture):
    def test_core_supporting_and_thinking_level_weights(self):
        question = self.tagged_question(
            1, skills=[(self.vectors, 'core'), (self.units, 'supporting')])
        self.event(question, score=1.0, now=self.now)
        self.assertEqual(facets.recompute_facets(self.student, now=self.now), 3)
        rows = self.rows()
        # prior 3 pseudo-answers at 0.5: core (1 + 1.5) / (1 + 3) = 0.625
        self.assertAlmostEqual(rows[('skill', 'vector_resolution')].mastery, 0.625, places=4)
        # supporting, weight 0.5: (0.5 + 1.5) / (0.5 + 3) = 0.5714
        self.assertAlmostEqual(rows[('skill', 'unit_conversion')].mastery, 0.5714, places=4)
        self.assertAlmostEqual(rows[('skill', 'unit_conversion')].effective_evidence, 0.5)
        self.assertAlmostEqual(rows[('thinking_level', 'apply')].mastery, 0.625, places=4)
        row = rows[('skill', 'vector_resolution')]
        self.assertEqual((row.subject, row.tenant, row.model_version), (self.subject, self.tenant, '1'))

    def test_diagnosis_down_weights_a_guess(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')], thinking='')
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt, now=self.now)
        self.diagnose(attempt, question, 'correct_lucky')       # weight 0.2
        facets.recompute_facets(self.student, now=self.now)
        # (0.2 + 1.5) / (0.2 + 3) = 0.53125
        self.assertAlmostEqual(self.rows()[('skill', 'vector_resolution')].mastery, 0.53125, places=4)
        self.assertNotIn(('thinking_level', ''), self.rows())

    def test_old_evidence_decays(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, days_ago=60, now=self.now)   # two half-lives: 0.25
        facets.recompute_facets(self.student, now=self.now)
        row = self.rows()[('skill', 'vector_resolution')]
        self.assertAlmostEqual(row.effective_evidence, 0.25, places=4)
        self.assertAlmostEqual(row.mastery, 1.75 / 3.25, places=4)

    def test_practice_answers_count_at_practice_weight(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, source='practice_answer', now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        self.assertAlmostEqual(
            self.rows()[('skill', 'vector_resolution')].effective_evidence, 0.6, places=4)

    def test_recompute_is_idempotent_and_drops_stale_rows(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        first = self.rows()[('skill', 'vector_resolution')].mastery
        facets.recompute_facets(self.student, now=self.now)
        self.assertEqual(self.rows()[('skill', 'vector_resolution')].mastery, first)
        ItemSkillTag.objects.filter(question=question).delete()
        facets.recompute_facets(self.student, now=self.now)
        self.assertNotIn(('skill', 'vector_resolution'), self.rows())

    def test_untagged_items_add_nothing(self):
        self.event(self.make_question(1), score=1.0, now=self.now)
        self.assertEqual(facets.recompute_facets(self.student, now=self.now), 0)

    def test_update_for_attempt_needs_my_progress(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt, now=self.now)
        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 2)
        self.student.facet_states.all().delete()
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 0)
        self.assertFalse(self.student.facet_states.exists())


    def test_recompute_updates_existing_rows_in_place(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        before = self.rows()[('skill', 'vector_resolution')]
        LearnerFacetState.objects.filter(id=before.id).update(model_version='0')
        self.event(question, score=0.0, now=self.now)
        later = self.now + timedelta(hours=1)
        facets.recompute_facets(self.student, now=later)
        after = self.rows()[('skill', 'vector_resolution')]
        self.assertEqual(after.id, before.id)
        self.assertNotEqual(after.mastery, before.mastery)
        self.assertEqual((before.evidence_count, after.evidence_count), (1, 2))
        self.assertEqual(after.model_version, '1')
        self.assertGreater(after.updated_at, before.updated_at)
        self.assertEqual(after.created_at, before.created_at)

    def test_recompute_over_a_row_it_did_not_read_does_not_collide(self):
        # A concurrent recompute that committed first leaves exactly this row behind.
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        racer = LearnerFacetState.objects.create(
            tenant=self.tenant, student=self.student, subject=self.subject,
            kind='skill', key='vector_resolution', mastery=0.1, model_version='0')
        self.assertEqual(facets.recompute_facets(self.student, now=self.now), 2)
        row = self.rows()[('skill', 'vector_resolution')]
        self.assertEqual(row.id, racer.id)
        self.assertAlmostEqual(row.mastery, 0.625, places=4)
        self.assertEqual(row.model_version, '1')
        self.assertEqual(self.student.facet_states.count(), 2)


class ProfileTests(FacetFixture):
    def test_tagged_subject_lists_facets_and_untagged_needs_tagging(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        for _ in range(3):
            self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        mechanics, optics = facets.profile_for(self.student, self.course)
        self.assertEqual(optics, {
            'subject_id': str(self.optics.id), 'subject': 'Optics',
            'status': 'needs_tagging', 'skills': [], 'thinking_levels': [],
        })
        self.assertEqual(mechanics['status'], 'ok')
        skill = mechanics['skills'][0]
        self.assertEqual(skill['label'], 'Vector resolution')
        self.assertEqual(skill['mastery'], 0.75)                # (3 + 1.5) / (3 + 3)
        self.assertEqual(skill['status'], 'in_progress')
        self.assertEqual(mechanics['thinking_levels'][0]['label'], 'Apply')

    def test_thin_facets_show_no_mastery(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        skill = facets.profile_for(self.student, self.course)[0]['skills'][0]
        self.assertIsNone(skill['mastery'])
        self.assertEqual(skill['status'], 'not_enough_data')


class JobTests(FacetFixture):
    def test_diagnosis_job_recomputes_facets(self):
        attempt = self.quiz_attempt(self.student)
        with patch('intelligence.services.facets.update_for_attempt', return_value=1) as hook:
            diagnose_and_update_state('quiz', str(attempt.id))
        hook.assert_called_once_with('quiz', str(attempt.id))

    def test_facet_failure_does_not_break_the_job(self):
        attempt = self.quiz_attempt(self.student)
        with patch('intelligence.services.facets.update_for_attempt', side_effect=RuntimeError):
            self.assertEqual(diagnose_and_update_state('quiz', str(attempt.id)), 0)

    def test_nightly_sweep_fills_facets_only_with_my_progress(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0)
        refresh_learner_state()
        self.assertTrue(self.student.facet_states.exists())

        self.student.facet_states.all().delete()
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        refresh_learner_state()
        self.assertFalse(self.student.facet_states.exists())

    def test_attempt_job_writes_no_facets_with_my_progress_off(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt)
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        diagnose_and_update_state('quiz', str(attempt.id))
        self.assertFalse(self.student.facet_states.exists())

        self.tenant.features = PROGRESS_ON
        self.tenant.save()
        diagnose_and_update_state('quiz', str(attempt.id))
        self.assertTrue(self.student.facet_states.exists())

    def test_command_recomputes_facets_unless_told_not_to(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0)
        call_command('recompute_learner_state', '--no-facets', tenant=str(self.tenant.id),
                     stdout=io.StringIO())
        self.assertFalse(self.student.facet_states.exists())
        call_command('recompute_learner_state', tenant=str(self.tenant.id), stdout=io.StringIO())
        self.assertEqual(self.student.facet_states.count(), 2)

    def test_command_skips_tenants_with_my_progress_off(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0)
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        call_command('recompute_learner_state', tenant=str(self.tenant.id), stdout=io.StringIO())
        self.assertFalse(self.student.facet_states.exists())
