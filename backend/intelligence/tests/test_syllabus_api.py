"""Syllabus tools API: switch, scope, and each operation end to end."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from intelligence.models import (
    STALE_JOB_ERROR, ItemTagging, SyllabusNode, TaggingRun, TreeBuildJob,
)
from intelligence.tasks import recompute_concept_states, run_tagging_run
from intelligence.tests.syllabus_fixtures import SyllabusTestCase
from intelligence.tests.test_course_tree import FakeCall as BuildCall
from intelligence.tests.test_tagging_sweep import FRICTION, patched_tree

BASE = '/api/v1/tenant-admin/intelligence/syllabus'


def fake_call(call):
    call.meter = type('M', (), {'usage': type('U', (), {'total_tokens': 10})()})()
    call.cost_usd = lambda: 0
    return patch('intelligence.services.llm.tenant_tagging_call', return_value=call)


class CourseEndpointTests(SyllabusTestCase):
    def test_tree(self):
        response = self.client_for(self.faculty).get(f'{BASE}/courses/{self.course.id}/tree/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['kind'], 'exam')
        self.assertEqual(data['jobs'], [])
        self.assertIn('budget', data)

    def test_scope_and_switch(self):
        url = f'{BASE}/courses/{self.custom.id}/tree/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 200)
        self.tenant.features = {}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 403)

    def test_build_flow_runs_eagerly_in_tests(self):
        client = self.client_for(self.admin)
        estimate = client.post(f'{BASE}/courses/{self.custom.id}/tree/estimate/', {}, format='json')
        self.assertEqual(estimate.status_code, 200)
        self.assertEqual(estimate.json()['calls']['subtopics'], 1)
        with fake_call(BuildCall(subtopics={'Two Sum': ['Hash map lookup']})):
            response = client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {'packs': []},
                                   format='json')
        self.assertEqual(response.status_code, 202, response.content)
        job = TreeBuildJob.objects.get()
        self.assertEqual(job.status, 'done', job.error)
        status = client.get(f'{BASE}/jobs/{job.id}/').json()
        self.assertEqual(status['summary']['proposed_subtopics'], 1)
        tree = client.get(f'{BASE}/courses/{self.custom.id}/tree/').json()
        self.assertEqual(tree['subjects'][0]['proposed'], 1)
        self.assertEqual(tree['jobs'][0]['id'], str(job.id))

    def test_build_refusals(self):
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post(f'{BASE}/courses/{self.course.id}/tree/build/', {}, format='json').status_code, 400)
        TreeBuildJob.objects.create(tenant=self.tenant, course=self.custom, status='running')
        self.assertEqual(
            client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json').status_code, 409)
        TreeBuildJob.objects.all().delete()
        with patch('intelligence.syllabus_views.budget_status',
                   return_value={'exhausted': True, 'monthly_budget': 10, 'used': 10, 'remaining': 0}):
            response = client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_exam_mapping_refused_for_a_built_course(self):
        client = self.client_for(self.admin)
        with fake_call(BuildCall()):
            client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {'packs': []}, format='json')
        response = client.post(f'{BASE}/courses/{self.custom.id}/tree/exam/',
                               {'exam': 'jee_main', 'subjects': {str(self.arrays.id): 'physics'}},
                               format='json')
        self.assertEqual(response.status_code, 400)

    def test_node_add_patch_merge(self):
        client = self.client_for(self.faculty)
        created = client.post(f'{BASE}/courses/{self.course.id}/nodes/', {
            'subject': str(self.physics.id), 'level': 'subtopic', 'name': 'Static friction',
            'parent': str(self.laws_node.id)}, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        node_id = created.json()['id']
        patched = client.patch(f'{BASE}/nodes/{node_id}/', {'weightage': 0.3}, format='json')
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(len(patched.json()['warnings']), 1)
        refused = client.patch(f'{BASE}/nodes/{self.laws_node.id}/', {'name': 'X'}, format='json')
        self.assertEqual(refused.status_code, 400)
        merged = client.post(f'{BASE}/nodes/{node_id}/merge/', {'into': str(self.friction.id)},
                             format='json')
        self.assertEqual(merged.status_code, 200, merged.content)
        self.assertEqual(SyllabusNode.objects.get(id=node_id).status, 'archived')
        self.assertEqual(
            self.client_for(self.other_faculty).patch(
                f'{BASE}/nodes/{self.friction.id}/', {'weightage': 0.5}, format='json').status_code,
            403)

    def test_skill_packs(self):
        response = self.client_for(self.admin).patch(
            f'{BASE}/courses/{self.course.id}/skill-packs/',
            {'packs': {str(self.physics.id): ['physics']}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['skill_packs'], {str(self.physics.id): ['physics']})

    def test_tagging_estimate_and_refusal_without_tree(self):
        client = self.client_for(self.admin)
        self.question('Friction on a block?')
        estimate = client.post(f'{BASE}/courses/{self.course.id}/tagging/estimate/', {}, format='json')
        self.assertEqual(estimate.status_code, 200, estimate.content)
        self.assertEqual(estimate.json()['questions'], 1)
        refused = client.post(f'{BASE}/courses/{self.custom.id}/tagging/run/', {}, format='json')
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(TaggingRun.objects.exists())


class ReviewEndpointTests(SyllabusTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.question('A block slides down…')
        self.tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=self.item, primary_node=self.friction,
            thinking_level='recall', review_status='needs_review',
            review_reasons=['low_confidence'])
        other = self.question('Two sum?', subject=self.arrays, topic=self.two_sum)
        self.other_tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=other, review_status='needs_review',
            review_reasons=['invalid_key'])

    def test_list_scope_filters_and_pagination(self):
        admin = self.client_for(self.admin).get(f'{BASE}/review/').json()
        self.assertEqual(admin['total'], 2)
        faculty = self.client_for(self.faculty).get(f'{BASE}/review/').json()
        self.assertEqual([r['id'] for r in faculty['results']], [str(self.tagging.id)])
        filtered = self.client_for(self.admin).get(f'{BASE}/review/', {'reason': 'invalid_key'}).json()
        self.assertEqual([r['id'] for r in filtered['results']], [str(self.other_tagging.id)])
        by_course = self.client_for(self.admin).get(f'{BASE}/review/', {'course': str(self.course.id)}).json()
        self.assertEqual(by_course['total'], 1)
        by_topic = self.client_for(self.admin).get(f'{BASE}/review/', {'topic': str(self.laws.id)}).json()
        self.assertEqual(by_topic['total'], 1)

    def test_filters_cannot_widen_a_faculty_scope(self):
        faculty = self.client_for(self.faculty)
        other_course = faculty.get(f'{BASE}/review/', {'course': str(self.custom.id)}).json()
        self.assertEqual(other_course['total'], 0)
        other_topic = faculty.get(f'{BASE}/review/', {'topic': str(self.two_sum.id)}).json()
        self.assertEqual(other_topic['total'], 0)

    def test_pagination(self):
        for number in range(24):
            ItemTagging.objects.create(
                tenant=self.tenant, question=self.question(f'Extra {number}'),
                review_status='needs_review', review_reasons=['low_confidence'])
        client = self.client_for(self.faculty)
        first = client.get(f'{BASE}/review/').json()
        self.assertEqual((first['total'], first['pages'], len(first['results'])), (25, 1, 25))
        ItemTagging.objects.create(
            tenant=self.tenant, question=self.question('One more'),
            review_status='needs_review', review_reasons=['low_confidence'])
        page_one = client.get(f'{BASE}/review/').json()
        page_two = client.get(f'{BASE}/review/', {'page': 2}).json()
        self.assertEqual((page_one['total'], page_one['pages']), (26, 2))
        self.assertEqual(len(page_one['results']), 25)
        self.assertEqual((page_two['page'], len(page_two['results'])), (2, 1))

    def test_accept_bulk_and_scope(self):
        client = self.client_for(self.faculty)
        self.assertEqual(client.post(f'{BASE}/review/{self.other_tagging.id}/accept/').status_code, 403)
        self.assertEqual(client.post(f'{BASE}/review/{self.tagging.id}/accept/').status_code, 200)
        self.tagging.review_status = 'needs_review'
        self.tagging.save()
        response = client.post(f'{BASE}/review/bulk-accept/',
                               {'ids': [str(self.tagging.id), str(self.other_tagging.id)]}, format='json')
        self.assertEqual(response.json(), {'accepted': 1})

    def test_detail_and_edit(self):
        client = self.client_for(self.faculty)
        detail = client.get(f'{BASE}/review/{self.tagging.id}/').json()
        self.assertIn('choices', detail)
        response = client.put(f'{BASE}/review/{self.tagging.id}/', {
            'primary': str(self.newton.id), 'thinking_level': 'conceptual', 'skills': [],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['source'], 'manual')
        bad = client.put(f'{BASE}/review/{self.tagging.id}/', {'primary': 'nope'}, format='json')
        self.assertEqual(bad.status_code, 400)
        for field, value in (('secondary', 5), ('skills', 'free_body_diagram')):
            body = {'primary': str(self.newton.id), 'thinking_level': 'conceptual', 'skills': [],
                    field: value}
            response = client.put(f'{BASE}/review/{self.tagging.id}/', body, format='json')
            self.assertEqual(response.status_code, 400, (field, response.content))
            self.assertIn('error', response.json())

    def test_retag_queues(self):
        self.tagging.source = 'manual'
        self.tagging.save()
        self.item.tagging_status = 'tagged'
        self.item.save()

        at_enqueue = []

        def record_state(kind, item_id):
            # What the database holds the moment the task is queued. Recorded
            # here and asserted below: the view swallows exceptions from this call.
            at_enqueue.append((ItemTagging.objects.get(id=self.tagging.id).source,
                               type(self.item).objects.get(id=self.item.id).tagging_status))

        with patch('intelligence.syllabus_views._enqueue_retag', side_effect=record_state) as queued:
            response = self.client_for(self.admin).post(f'{BASE}/review/{self.tagging.id}/retag/')
        self.assertEqual(response.json(), {'queued': True})
        self.assertEqual(at_enqueue, [('llm_tagger', 'stale')])
        queued.assert_called_once_with('bank', str(self.item.id))
        self.tagging.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.tagging.source, 'llm_tagger')
        self.assertEqual(self.item.tagging_status, 'stale')

    def test_add_to_tree(self):
        self.tagging.primary_node = None
        self.tagging.proposed_subtopic = 'Rolling friction'
        self.tagging.save()
        response = self.client_for(self.admin).post(
            f'{BASE}/review/{self.tagging.id}/add-to-tree/', {'topic': str(self.laws_node.id)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['node']['name'], 'Rolling friction')

    def test_item_tags(self):
        client = self.client_for(self.faculty)
        data = client.get(f'{BASE}/items/bank/{self.item.id}/tags/').json()
        self.assertEqual(data['tagging']['id'], str(self.tagging.id))
        untagged = self.question('Untagged?')
        self.assertIsNone(client.get(f'{BASE}/items/bank/{untagged.id}/tags/').json()['tagging'])


class SyllabusApiGapTests(SyllabusTestCase):
    def test_merge_enqueues_concept_state_recompute(self):
        client = self.client_for(self.faculty)
        created = client.post(f'{BASE}/courses/{self.course.id}/nodes/', {
            'subject': str(self.physics.id), 'level': 'subtopic', 'name': 'Static friction',
            'parent': str(self.laws_node.id)}, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        with patch('intelligence.api.enqueue') as enqueue:
            merged = client.post(f'{BASE}/nodes/{created.json()["id"]}/merge/',
                                 {'into': str(self.friction.id)}, format='json')
        self.assertEqual(merged.status_code, 200, merged.content)
        enqueue.assert_called_once()
        task, concept_id = enqueue.call_args.args
        self.assertEqual(task, recompute_concept_states)
        self.assertEqual(str(concept_id), str(merged.json()['concept_id']))

    def test_exam_mapping_on_a_fresh_course(self):
        client = self.client_for(self.admin)
        url = f'{BASE}/courses/{self.custom.id}/tree/exam/'
        with patched_tree():
            response = client.post(url, {'exam': 'mini', 'subjects': {str(self.arrays.id): 'physics'}},
                                   format='json')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertGreater(data['summary']['created'], 0)
        self.assertTrue(SyllabusNode.objects.filter(subject=self.arrays, key=FRICTION).exists())
        self.assertEqual(data['tree']['kind'], 'exam')

    def test_exam_mapping_refuses_a_foreign_subject(self):
        with patched_tree():
            response = self.client_for(self.admin).post(
                f'{BASE}/courses/{self.custom.id}/tree/exam/',
                {'exam': 'mini', 'subjects': {str(self.physics.id): 'physics'}}, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(SyllabusNode.objects.filter(subject=self.arrays).exists())

    def test_missing_objects_are_404(self):
        client = self.client_for(self.admin)
        missing = uuid.uuid4()
        self.assertEqual(client.get(f'{BASE}/courses/{missing}/tree/').status_code, 404)
        self.assertEqual(client.patch(f'{BASE}/nodes/{missing}/', {'weightage': 0.5}, format='json')
                         .status_code, 404)
        self.assertEqual(client.get(f'{BASE}/jobs/{missing}/').status_code, 404)

    def test_job_out_of_scope_is_403(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.custom)
        url = f'{BASE}/jobs/{job.id}/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 200)

    def test_tagging_run_is_accepted_then_conflicts(self):
        SyllabusNode.objects.create(tenant=self.tenant, subject=self.arrays, level='topic',
                                    key='hashing', name='Hashing', source='course')
        url = f'{BASE}/courses/{self.custom.id}/tagging/run/'
        client = self.client_for(self.admin)
        with patch('intelligence.api.enqueue') as enqueue:
            first = client.post(url, {}, format='json')
            second = client.post(url, {}, format='json')
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(first.json()['status'], 'queued')
        enqueue.assert_called_once_with(run_tagging_run, first.json()['id'])
        self.assertEqual(second.status_code, 409, second.content)
        self.assertEqual(second.json()['job']['id'], first.json()['id'])
        self.assertEqual(TaggingRun.objects.count(), 1)


class OptOutTests(SyllabusTestCase):
    """With every learning-layer switch off: no Part B endpoint is reachable
    and nothing is queued."""

    features = {}

    def test_every_endpoint_is_403_and_nothing_is_queued(self):
        node = self.friction
        urls = [
            ('get', f'{BASE}/courses/{self.course.id}/tree/'),
            ('post', f'{BASE}/courses/{self.course.id}/tree/estimate/'),
            ('post', f'{BASE}/courses/{self.custom.id}/tree/build/'),
            ('post', f'{BASE}/courses/{self.course.id}/tree/exam/'),
            ('post', f'{BASE}/courses/{self.course.id}/nodes/'),
            ('patch', f'{BASE}/nodes/{node.id}/'),
            ('post', f'{BASE}/nodes/{node.id}/merge/'),
            ('patch', f'{BASE}/courses/{self.course.id}/skill-packs/'),
            ('post', f'{BASE}/courses/{self.course.id}/tagging/estimate/'),
            ('post', f'{BASE}/courses/{self.course.id}/tagging/run/'),
            ('get', f'{BASE}/review/'),
            ('post', f'{BASE}/review/bulk-accept/'),
        ]
        client = self.client_for(self.admin)
        with patch('intelligence.api.enqueue') as enqueue:
            for method, url in urls:
                self.assertEqual(getattr(client, method)(url, {}, format='json').status_code, 403, url)
        enqueue.assert_not_called()
        self.assertFalse(TreeBuildJob.objects.exists())
        self.assertFalse(TaggingRun.objects.exists())


class StaleJobTests(SyllabusTestCase):
    """A job whose worker died must not block its course forever."""

    def _aged(self, model, hours, **fields):
        job = model.objects.create(tenant=self.tenant, course=self.custom, **fields)
        when = timezone.now() - timedelta(hours=hours)
        model.objects.filter(id=job.id).update(created_at=when, **(
            {'started_at': when} if fields.get('status') == 'running' else {}))
        return job

    def test_old_running_job_no_longer_blocks_build(self):
        old = self._aged(TreeBuildJob, 3, status='running')
        client = self.client_for(self.admin)
        with patch('intelligence.api.enqueue'):
            response = client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json')
        self.assertEqual(response.status_code, 202, response.content)
        old.refresh_from_db()
        self.assertEqual(old.status, 'failed')
        self.assertEqual(old.error, STALE_JOB_ERROR)
        self.assertIsNotNone(old.finished_at)

    def test_recent_running_job_still_blocks(self):
        self._aged(TreeBuildJob, 0.1, status='running')
        response = self.client_for(self.admin).post(
            f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json')
        self.assertEqual(response.status_code, 409, response.content)

    def test_old_queued_tagging_run_expires(self):
        old = self._aged(TaggingRun, 7)
        recent = self._aged(TaggingRun, 1)
        tree = self.client_for(self.admin).get(f'{BASE}/courses/{self.custom.id}/tree/').json()
        by_id = {job['id']: job for job in tree['jobs']}
        self.assertEqual(by_id[str(old.id)]['status'], 'failed')
        self.assertEqual(by_id[str(old.id)]['error'], STALE_JOB_ERROR)
        self.assertEqual(by_id[str(recent.id)]['status'], 'queued')

    def test_job_detail_returns_the_expired_status(self):
        old = self._aged(TaggingRun, 3, status='running')
        data = self.client_for(self.admin).get(f'{BASE}/jobs/{old.id}/').json()
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(data['error'], STALE_JOB_ERROR)
        self.assertIsNotNone(data['finished_at'])

    def test_finished_jobs_are_left_alone(self):
        done = self._aged(TreeBuildJob, 30, status='done')
        TreeBuildJob.expire_stale(self.custom)
        done.refresh_from_db()
        self.assertEqual(done.status, 'done')
