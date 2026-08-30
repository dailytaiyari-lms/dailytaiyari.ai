"""Tests for the dedicated Hackathon section.

These pin the promises the feature makes to its two audiences:

*Students* — a hackathon page is readable by anyone, registering is not; a round
you were not shortlisted for stays shut; and a score stays hidden until the
organiser publishes results.

*Organisers* — the registration count can be switched off; qualification works by
cut-off, by top-N and by hand; and declaring winners is idempotent.
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from users.models import User

from . import grading
from .models import (
    Hackathon,
    HackathonRegistration,
    HackathonStage,
    HackathonStageItem,
    StageItemAnswer,
    StageParticipation,
)

BASE = '/api/v1/hackathons'
ADMIN = '/api/v1/hackathons/admin'
AI = '/api/v1/tenant-admin/hackathon-ai'


class HackathonTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Test Academy', is_active=True)
        cls.other_tenant = Tenant.objects.create(name='Rival Academy', is_active=True)

        cls.admin = User.objects.create_user(
            email='hack-admin@example.com', password='pw-admin-123',
            tenant=cls.tenant, role='admin',
        )
        cls.student = User.objects.create_user(
            email='hack-student@example.com', password='pw-stud-123',
            tenant=cls.tenant, role='student', first_name='Asha', last_name='Rao',
        )
        cls.student2 = User.objects.create_user(
            email='hack-student2@example.com', password='pw-stud-123',
            tenant=cls.tenant, role='student', first_name='Bilal', last_name='Khan',
        )
        cls.student3 = User.objects.create_user(
            email='hack-student3@example.com', password='pw-stud-123',
            tenant=cls.tenant, role='student', first_name='Chitra', last_name='Iyer',
        )

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_TENANT_ID=str(self.tenant.id))

    def auth(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(
            HTTP_X_TENANT_ID=str(self.tenant.id),
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

    def anon(self):
        self.client.credentials(HTTP_X_TENANT_ID=str(self.tenant.id))

    def make_hackathon(self, **kwargs):
        now = timezone.now()
        defaults = {
            'tenant': self.tenant,
            'title': 'AI Build Sprint',
            'tagline': 'Ship something real in 48 hours',
            'description': '<p>Build with AI.</p>',
            'status': 'published',
            'registration_deadline': now + timedelta(days=7),
            'starts_at': now + timedelta(days=8),
            'ends_at': now + timedelta(days=10),
        }
        defaults.update(kwargs)
        return Hackathon.objects.create(**defaults)

    def make_stage(self, hackathon, **kwargs):
        defaults = {
            'tenant': self.tenant,
            'hackathon': hackathon,
            'title': 'Screening Quiz',
            'stage_type': 'quiz',
            'status': 'published',
            'max_score': Decimal('10'),
        }
        defaults.update(kwargs)
        return HackathonStage.objects.create(**defaults)

    def register(self, hackathon, user, **kwargs):
        defaults = {
            'tenant': self.tenant,
            'hackathon': hackathon,
            'participant': user.profile,
            'full_name': user.full_name,
            'email': user.email,
        }
        defaults.update(kwargs)
        return HackathonRegistration.objects.create(**defaults)


class PublicAccessTests(HackathonTestBase):
    """"Anyone can read it, only members can enter it."""

    def test_anonymous_can_list_and_read_a_published_hackathon(self):
        hackathon = self.make_hackathon()
        self.anon()

        listing = self.client.get(f'{BASE}/')
        self.assertEqual(listing.status_code, 200)
        titles = [row['title'] for row in listing.data['results']]
        self.assertIn('AI Build Sprint', titles)

        detail = self.client.get(f'{BASE}/{hackathon.id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['title'], 'AI Build Sprint')
        self.assertIsNone(detail.data.get('my_registration'))

    def test_draft_hackathons_are_never_listed_publicly(self):
        self.make_hackathon(title='Secret Sprint', status='draft')
        self.anon()
        listing = self.client.get(f'{BASE}/')
        self.assertNotIn('Secret Sprint', [row['title'] for row in listing.data['results']])

    def test_anonymous_cannot_register(self):
        hackathon = self.make_hackathon()
        self.anon()
        response = self.client.post(f'{BASE}/{hackathon.id}/register/', {}, format='json')
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(hackathon.registrations.count(), 0)

    def test_logged_in_student_can_register_once(self):
        hackathon = self.make_hackathon()
        self.auth(self.student)

        first = self.client.post(
            f'{BASE}/{hackathon.id}/register/',
            {'full_name': 'Asha Rao', 'email': 'hack-student@example.com',
             'institution': 'NIT'},
            format='json',
        )
        self.assertIn(first.status_code, (200, 201))
        self.assertEqual(hackathon.registrations.count(), 1)

        again = self.client.post(
            f'{BASE}/{hackathon.id}/register/', {'full_name': 'Asha Rao'}, format='json',
        )
        self.assertIn(again.status_code, (200, 400, 409))
        self.assertEqual(hackathon.registrations.count(), 1)

    def test_registration_closes_after_the_deadline(self):
        hackathon = self.make_hackathon(
            registration_deadline=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(hackathon.registration_state, 'closed')
        self.auth(self.student)
        response = self.client.post(f'{BASE}/{hackathon.id}/register/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(hackathon.registrations.count(), 0)

    def test_other_tenants_hackathons_are_invisible(self):
        Hackathon.objects.create(
            tenant=self.other_tenant, title='Rival Sprint', status='published',
        )
        self.anon()
        listing = self.client.get(f'{BASE}/')
        self.assertNotIn('Rival Sprint', [row['title'] for row in listing.data['results']])


class RegistrationCountVisibilityTests(HackathonTestBase):
    """The organiser's switch actually hides the number, not just the label."""

    def test_count_is_returned_when_enabled(self):
        hackathon = self.make_hackathon(show_registration_count=True)
        self.register(hackathon, self.student)
        self.anon()
        detail = self.client.get(f'{BASE}/{hackathon.id}/')
        self.assertEqual(detail.data['registration_count'], 1)

    def test_count_is_withheld_when_disabled(self):
        hackathon = self.make_hackathon(show_registration_count=False)
        self.register(hackathon, self.student)
        self.anon()

        detail = self.client.get(f'{BASE}/{hackathon.id}/')
        self.assertIsNone(detail.data['registration_count'])

        listing = self.client.get(f'{BASE}/')
        row = next(r for r in listing.data['results'] if r['id'] == str(hackathon.id))
        self.assertIsNone(row['registration_count'])


class StageGatingTests(HackathonTestBase):
    """A round only opens for someone who earned their way into it."""

    def setUp(self):
        super().setUp()
        self.hackathon = self.make_hackathon()
        self.round1 = self.make_stage(self.hackathon, title='Round 1', order=0)
        self.round2 = self.make_stage(self.hackathon, title='Round 2', order=1)
        self.registration = self.register(self.hackathon, self.student)

    def test_unregistered_student_cannot_open_a_round(self):
        self.auth(self.student2)
        response = self.client.get(
            f'{BASE}/{self.hackathon.id}/stages/{self.round1.id}/'
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get('code'), 'not_registered')

    def test_first_round_is_open_to_every_registrant(self):
        self.auth(self.student)
        response = self.client.get(
            f'{BASE}/{self.hackathon.id}/stages/{self.round1.id}/'
        )
        self.assertEqual(response.status_code, 200)

    def test_second_round_is_shut_until_round_one_results_exist(self):
        self.auth(self.student)
        response = self.client.get(
            f'{BASE}/{self.hackathon.id}/stages/{self.round2.id}/'
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get('code'), 'awaiting_results')

    def test_a_student_who_was_not_shortlisted_is_told_so(self):
        StageParticipation.objects.create(
            tenant=self.tenant, stage=self.round1, registration=self.registration,
            status='evaluated', qualification='not_qualified',
        )
        self.round1.results_published = True
        self.round1.save()

        self.auth(self.student)
        response = self.client.get(
            f'{BASE}/{self.hackathon.id}/stages/{self.round2.id}/'
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get('code'), 'not_qualified')

    def test_a_shortlisted_student_gets_into_the_next_round(self):
        StageParticipation.objects.create(
            tenant=self.tenant, stage=self.round1, registration=self.registration,
            status='evaluated', qualification='qualified',
        )
        self.round1.results_published = True
        self.round1.save()

        self.auth(self.student)
        response = self.client.get(
            f'{BASE}/{self.hackathon.id}/stages/{self.round2.id}/'
        )
        self.assertEqual(response.status_code, 200)


class QualificationTests(HackathonTestBase):
    """Cut-off, top-N and a hand-picked shortlist all produce the same shape."""

    def setUp(self):
        super().setUp()
        self.hackathon = self.make_hackathon()
        self.stage = self.make_stage(self.hackathon, max_score=Decimal('10'))
        self.parts = []
        for user, score in ((self.student, 9), (self.student2, 5), (self.student3, 2)):
            registration = self.register(self.hackathon, user)
            self.parts.append(StageParticipation.objects.create(
                tenant=self.tenant, stage=self.stage, registration=registration,
                status='submitted', score=Decimal(score), max_score=Decimal('10'),
            ))

    def test_cutoff_shortlists_everyone_at_or_above_the_bar(self):
        self.stage.qualification_mode = 'cutoff'
        self.stage.cutoff_score = Decimal('5')
        self.stage.save()

        result = grading.apply_qualification(self.stage, publish_results=True)
        self.assertEqual(result['qualified'], 2)
        self.assertEqual(result['not_qualified'], 1)

        self.parts[2].refresh_from_db()
        self.assertEqual(self.parts[2].qualification, 'not_qualified')
        self.stage.refresh_from_db()
        self.assertTrue(self.stage.results_published)

    def test_top_n_shortlists_exactly_n(self):
        self.stage.qualification_mode = 'top_n'
        self.stage.top_n = 1
        self.stage.save()

        result = grading.apply_qualification(self.stage, publish_results=True)
        self.assertEqual(result['qualified'], 1)
        self.parts[0].refresh_from_db()
        self.assertEqual(self.parts[0].qualification, 'qualified')
        self.assertEqual(self.parts[0].rank, 1)

    def test_manual_selection_overrides_the_scores(self):
        self.stage.qualification_mode = 'manual'
        self.stage.save()

        # The organiser picks the lowest scorer on purpose.
        result = grading.apply_qualification(
            self.stage, qualified_ids=[str(self.parts[2].id)], publish_results=True,
        )
        self.assertEqual(result['qualified'], 1)
        self.parts[2].refresh_from_db()
        self.parts[0].refresh_from_db()
        self.assertEqual(self.parts[2].qualification, 'qualified')
        self.assertEqual(self.parts[0].qualification, 'not_qualified')

    def test_qualifying_opens_the_next_round_for_the_shortlist_only(self):
        next_stage = self.make_stage(self.hackathon, title='Round 2', order=1)
        self.stage.qualification_mode = 'top_n'
        self.stage.top_n = 2
        self.stage.save()

        grading.apply_qualification(self.stage, publish_results=True)
        opened = StageParticipation.objects.filter(stage=next_stage)
        self.assertEqual(opened.count(), 2)
        self.assertTrue(all(p.status == 'pending' for p in opened))

    def test_scores_stay_hidden_until_results_are_published(self):
        self.auth(self.student)
        response = self.client.get(f'{BASE}/{self.hackathon.id}/my-progress/')
        self.assertEqual(response.status_code, 200)
        stage_row = response.data['stages'][0]
        self.assertIsNone(stage_row['score'])

        grading.apply_qualification(self.stage, publish_results=True)
        response = self.client.get(f'{BASE}/{self.hackathon.id}/my-progress/')
        stage_row = response.data['stages'][0]
        self.assertEqual(float(stage_row['score']), 9.0)


class AutoGradingTests(HackathonTestBase):
    """Marking behaves exactly like the rest of the platform."""

    def setUp(self):
        super().setUp()
        self.hackathon = self.make_hackathon()
        self.stage = self.make_stage(self.hackathon)
        self.mcq = HackathonStageItem.objects.create(
            tenant=self.tenant, stage=self.stage, item_type='mcq', order=0,
            question_text='What is 2 + 2?', marks=Decimal('4'),
            negative_marks=Decimal('1'),
            options=[{'text': '3', 'is_correct': False}, {'text': '4', 'is_correct': True}],
        )
        self.numerical = HackathonStageItem.objects.create(
            tenant=self.tenant, stage=self.stage, item_type='numerical', order=1,
            question_text='Average speed of 100 m in 10 s?', marks=Decimal('4'),
            numerical_answer=Decimal('10'), numerical_tolerance=Decimal('0.1'),
        )

    def _graded(self, item, **fields):
        answer = StageItemAnswer(item=item, **fields)
        grading.grade_answer(item, answer)
        return answer

    def test_correct_mcq_scores_full_marks(self):
        answer = self._graded(self.mcq, selected_options=[1])
        self.assertTrue(answer.is_correct)
        self.assertEqual(float(answer.marks_obtained), 4.0)

    def test_wrong_mcq_is_penalised(self):
        answer = self._graded(self.mcq, selected_options=[0])
        self.assertFalse(answer.is_correct)
        self.assertEqual(float(answer.marks_obtained), -1.0)

    def test_unattempted_mcq_is_never_penalised(self):
        answer = self._graded(self.mcq, selected_options=[])
        self.assertEqual(float(answer.marks_obtained), 0.0)

    def test_numerical_answer_respects_tolerance(self):
        close = self._graded(self.numerical, numerical_answer=Decimal('10.05'))
        far = self._graded(self.numerical, numerical_answer=Decimal('11'))
        self.assertTrue(close.is_correct)
        self.assertFalse(far.is_correct)

    def test_a_paper_never_leaks_the_answer_key(self):
        paper = grading.build_paper(self.stage)
        serialised = json.dumps(paper)
        self.assertNotIn('is_correct', serialised)
        self.assertNotIn('numerical_answer', serialised)

    def test_computed_max_score_sums_the_items(self):
        self.assertEqual(float(self.stage.computed_max_score()), 8.0)


class AdminApiTests(HackathonTestBase):
    """The organiser's console: only admins, and only their own tenant."""

    def test_students_cannot_reach_the_admin_api(self):
        self.auth(self.student)
        self.assertEqual(self.client.get(f'{ADMIN}/hackathons/').status_code, 403)

    def test_admin_can_create_a_hackathon(self):
        self.auth(self.admin)
        response = self.client.post(
            f'{ADMIN}/hackathons/',
            {'title': 'Winter Code Jam', 'tagline': 'Two days, one build',
             'description': '<p>Come build.</p>', 'status': 'published'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        hackathon = Hackathon.objects.get(id=response.data['id'])
        self.assertEqual(hackathon.tenant, self.tenant)
        self.assertEqual(hackathon.created_by, self.admin)
        self.assertTrue(hackathon.slug)

    def test_admin_can_add_and_reorder_rounds(self):
        hackathon = self.make_hackathon()
        self.auth(self.admin)

        first = self.client.post(
            f'{ADMIN}/hackathons/{hackathon.id}/stages/',
            {'title': 'Round 1', 'stage_type': 'quiz', 'max_score': 10},
            format='json',
        )
        second = self.client.post(
            f'{ADMIN}/hackathons/{hackathon.id}/stages/',
            {'title': 'Round 2', 'stage_type': 'submission', 'max_score': 100,
             'allowed_file_types': ['pdf', 'zip']},
            format='json',
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)

        reordered = self.client.post(
            f'{ADMIN}/hackathons/{hackathon.id}/stages/reorder/',
            {'ids': [second.data['id'], first.data['id']]}, format='json',
        )
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual(reordered.data[0]['title'], 'Round 2')

    def test_declaring_winners_is_idempotent(self):
        hackathon = self.make_hackathon()
        winner = self.register(hackathon, self.student)
        runner_up = self.register(hackathon, self.student2)
        self.auth(self.admin)

        payload = {
            'winners': [
                {'registration_id': str(winner.id), 'rank': 1, 'title': 'Champion',
                 'prize': '₹50,000'},
                {'registration_id': str(runner_up.id), 'rank': 2, 'title': 'Runner-up'},
            ],
            'announce': True,
        }
        first = self.client.post(
            f'{ADMIN}/hackathons/{hackathon.id}/declare-winners/', payload, format='json',
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.data['winners']), 2)

        # Re-declaring with only one winner must clear the other's badge.
        second = self.client.post(
            f'{ADMIN}/hackathons/{hackathon.id}/declare-winners/',
            {'winners': [payload['winners'][0]], 'announce': True}, format='json',
        )
        self.assertEqual(second.status_code, 200)
        runner_up.refresh_from_db()
        self.assertFalse(runner_up.is_winner)
        self.assertEqual(hackathon.registrations.filter(is_winner=True).count(), 1)

        hackathon.refresh_from_db()
        self.assertTrue(hackathon.results_announced)

    def test_winners_are_public(self):
        hackathon = self.make_hackathon(results_announced=True)
        registration = self.register(hackathon, self.student)
        registration.is_winner = True
        registration.final_rank = 1
        registration.winner_title = 'Champion'
        registration.save()

        self.anon()
        response = self.client.get(f'{BASE}/{hackathon.id}/winners/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['winners']), 1)
        self.assertEqual(response.data['winners'][0]['winner_title'], 'Champion')

    def test_qualifying_blocks_while_submissions_await_review(self):
        hackathon = self.make_hackathon()
        stage = self.make_stage(hackathon, qualification_mode='manual')
        registration = self.register(hackathon, self.student)
        participation = StageParticipation.objects.create(
            tenant=self.tenant, stage=stage, registration=registration,
            status='submitted', needs_manual_grading=True,
        )
        self.auth(self.admin)

        blocked = self.client.post(
            f'{ADMIN}/stages/{stage.id}/qualify/',
            {'mode': 'manual', 'participation_ids': [str(participation.id)]},
            format='json',
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['code'], 'pending_review')

        forced = self.client.post(
            f'{ADMIN}/stages/{stage.id}/qualify/',
            {'mode': 'manual', 'participation_ids': [str(participation.id)],
             'force': True},
            format='json',
        )
        self.assertEqual(forced.status_code, 200)
        self.assertEqual(forced.data['qualified'], 1)


AI_EVENT_RESPONSE = json.dumps({
    'hackathon': {
        'title': 'Climate Code Sprint',
        'tagline': 'Code for a cooler planet',
        'description': '<p>Build climate tools.</p><script>alert(1)</script>',
        'rules': '<ol><li>Original work only.</li></ol>',
        'prizes_description': '<p>₹1,00,000 pool.</p>',
        'eligibility': '<p>Open to all students.</p>',
        'faqs': [{'question': 'Team size?', 'answer': 'Individual entries only.'}],
        'tags': ['climate', 'ai'],
        'difficulty': 'intermediate',
        'mode': 'online',
        'theme_color': '#10b981',
    },
    'stages': [
        {'title': 'Screening Quiz', 'stage_type': 'quiz', 'max_score': 40,
         'qualification_mode': 'cutoff', 'cutoff_score': 20, 'duration_minutes': 30,
         'blueprint': [{'item_type': 'mcq', 'count': 10, 'marks': 4}]},
        {'title': 'Final Build', 'stage_type': 'submission', 'max_score': 100,
         'qualification_mode': 'manual', 'allowed_file_types': ['zip', 'mp4'],
         'submission_instructions': '<p>Upload your repo and a demo video.</p>'},
    ],
})


class AIStudioTests(HackathonTestBase):
    """The AI proposes; the admin disposes. Nothing is written until confirmed."""

    def _generate(self, **payload):
        with patch('hackathons.generation._call', return_value=AI_EVENT_RESPONSE), \
             patch('hackathons.generation._check_budget'), \
             patch('hackathons.generation.resolve_for_admin') as resolve:
            resolve.return_value = type(
                'R', (), {'provider': 'openai', 'model': 'gpt-4o-mini', 'source': 'tenant'},
            )()
            return self.client.post(f'{AI}/jobs/', payload, format='json')

    def test_generation_creates_a_draft_and_writes_nothing(self):
        self.auth(self.admin)
        response = self._generate(
            kind='event', prompt='A climate-tech hackathon for engineering students',
            options={'stage_count': 2},
        )
        self.assertIn(response.status_code, (201, 202))
        self.assertEqual(Hackathon.objects.filter(tenant=self.tenant).count(), 0)

    def test_draft_html_is_sanitised(self):
        from .schema import normalize_draft

        draft = normalize_draft(json.loads(AI_EVENT_RESPONSE), 'event')
        self.assertNotIn('<script>', draft['hackathon']['description'])
        self.assertIn('<p>', draft['hackathon']['description'])
        self.assertEqual(len(draft['stages']), 2)
        self.assertEqual(draft['stages'][0]['qualification_mode'], 'cutoff')

    def test_apply_requires_confirmation_and_then_writes_once(self):
        from .models import HackathonGenerationJob
        from .schema import normalize_draft

        job = HackathonGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='event',
            status='preview', prompt='Climate hackathon',
            draft=normalize_draft(json.loads(AI_EVENT_RESPONSE), 'event'),
        )
        self.auth(self.admin)

        refused = self.client.post(
            f'{AI}/jobs/{job.id}/apply/', {'confirm': False}, format='json',
        )
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(Hackathon.objects.filter(tenant=self.tenant).count(), 0)

        applied = self.client.post(
            f'{AI}/jobs/{job.id}/apply/', {'confirm': True}, format='json',
        )
        self.assertEqual(applied.status_code, 200)
        hackathon = Hackathon.objects.get(tenant=self.tenant)
        self.assertEqual(hackathon.title, 'Climate Code Sprint')
        self.assertEqual(hackathon.status, 'draft')  # never auto-published
        self.assertEqual(hackathon.stages.count(), 2)

        # A second apply must not duplicate anything.
        repeat = self.client.post(
            f'{AI}/jobs/{job.id}/apply/', {'confirm': True}, format='json',
        )
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(Hackathon.objects.filter(tenant=self.tenant).count(), 1)

    def test_students_cannot_use_the_studio(self):
        self.auth(self.student)
        self.assertEqual(self.client.get(f'{AI}/options/').status_code, 403)
