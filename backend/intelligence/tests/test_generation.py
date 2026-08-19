"""Practice-question generation: caps, strict normalization, applied output."""
import json
from unittest.mock import patch

from django.test import TestCase

from chatbot.providers import ResolvedProvider, Usage
from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, GeneratedItem, PracticeGenerationJob
from intelligence.services import practice_generation
from quiz.models import Question


def option(text, correct=False):
    return {'text': text, 'is_correct': correct}


GOOD_ITEM = {
    'question_text': 'A ball is thrown at 45°; which quantity stays constant in flight?',
    'options': [
        option('Horizontal velocity', True), option('Vertical velocity'),
        option('Speed'), option('Kinetic energy'),
    ],
    'explanation': 'Gravity only acts vertically, so horizontal velocity is unchanged. '
                   'Vertical velocity changes under g; speed and KE follow from it.',
    'difficulty': 'medium',
    'concepts': ['Projectile Motion'],
    'cognitive_type': 'application',
    'misconception_targeted': 'thinking speed stays constant in projectile flight',
}


class GenerationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Gen Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kin',
        )
        cls.concept = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Projectile Motion',
            slug='projectile-motion',
        )
        cls.concept.topics.add(cls.topic)

    def make_deficit(self, signature='mastery:c=X'):
        return {
            'kind': 'low_mastery', 'signature': signature, 'concept': self.concept,
            'severity': 1.0, 'slots': {'concept': self.concept.name, 'n': 6, 'pct': 30},
        }

    def make_job(self):
        job = PracticeGenerationJob.objects.create(
            tenant=self.tenant, course=self.course, deficit_kind='low_mastery',
            deficit_signature='mastery:c=X', status='generating',
            options={'count': 8, 'slots': {'pct': 30}},
        )
        job.target_concepts.add(self.concept)
        return job

    def stub_provider(self):
        return patch(
            'intelligence.services.practice_generation.resolve_for_admin',
            return_value=ResolvedProvider(provider='openai', api_key='k', model='gpt-4o'),
        )

    def stub_llm(self, payload):
        return patch(
            'coursegen.generation.complete',
            return_value=(json.dumps(payload), Usage(200, 400, 600), 900),
        )


class RequestGenerationTests(GenerationTestCase):
    def test_signature_cooldown_prevents_duplicates(self):
        with patch('intelligence.tasks.run_practice_generation.delay'):
            first = practice_generation.request_generation(self.course, self.make_deficit())
            second = practice_generation.request_generation(self.course, self.make_deficit())
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(PracticeGenerationJob.objects.count(), 1)

    def test_daily_job_cap(self):
        with patch('intelligence.tasks.run_practice_generation.delay'):
            for n in range(practice_generation.MAX_JOBS_PER_TENANT_PER_DAY):
                PracticeGenerationJob.objects.create(
                    tenant=self.tenant, course=self.course, deficit_kind='low_mastery',
                    deficit_signature=f'mastery:c={n}',
                )
            refused = practice_generation.request_generation(self.course, self.make_deficit())
        self.assertIsNone(refused)


class RunJobTests(GenerationTestCase):
    def test_run_job_applies_clean_items_and_drops_bad_ones(self):
        bad_three_options = dict(GOOD_ITEM, question_text='Short but only 3 options?',
                                 options=GOOD_ITEM['options'][:3])
        bad_no_correct = dict(GOOD_ITEM, question_text='A question where nothing is correct?',
                              options=[option('a'), option('b'), option('c'), option('d')])
        bad_no_concepts = dict(GOOD_ITEM, question_text='A question missing its concepts entirely?',
                               concepts=[])
        duplicate = dict(GOOD_ITEM)  # same stem as GOOD_ITEM — dropped

        job = self.make_job()
        payload = {'items': [GOOD_ITEM, bad_three_options, bad_no_correct,
                             bad_no_concepts, duplicate]}
        with self.stub_provider(), self.stub_llm(payload):
            practice_generation.run_job(job)

        job.refresh_from_db()
        self.assertEqual(job.status, PracticeGenerationJob.STATUS_APPLIED)
        self.assertEqual(job.applied_summary['created'], 1)

        question = Question.objects.get(source='AI Practice')
        self.assertEqual(question.status, 'published')
        self.assertEqual(question.subject, self.subject)
        self.assertEqual(question.topic, self.topic)
        self.assertEqual(question.options.count(), 4)
        self.assertEqual(question.correct_answer, '0')
        link = question.concept_links.get()
        self.assertEqual(link.concept, self.concept)

        provenance = GeneratedItem.objects.get()
        self.assertEqual(provenance.question, question)
        self.assertEqual(provenance.deficit_kind, 'low_mastery')
        self.assertIn('speed stays constant', provenance.target_misconception)

    def test_run_job_fails_cleanly_when_nothing_survives(self):
        job = self.make_job()
        with self.stub_provider(), self.stub_llm({'items': [{'question_text': 'x'}]}):
            practice_generation.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, PracticeGenerationJob.STATUS_FAILED)
        self.assertEqual(Question.objects.filter(source='AI Practice').count(), 0)

    def test_existing_stem_is_not_regenerated(self):
        # A bank question with the identical stem already linked to the concept.
        existing = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text=GOOD_ITEM['question_text'], question_type='mcq',
            correct_answer='0', status='published',
        )
        from intelligence.models import ConceptLink
        ConceptLink.objects.create(
            tenant=self.tenant, concept=self.concept, question=existing,
            is_primary=True, source='manual',
        )
        job = self.make_job()
        with self.stub_provider(), self.stub_llm({'items': [GOOD_ITEM]}):
            practice_generation.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, PracticeGenerationJob.STATUS_FAILED)
        self.assertEqual(GeneratedItem.objects.count(), 0)
