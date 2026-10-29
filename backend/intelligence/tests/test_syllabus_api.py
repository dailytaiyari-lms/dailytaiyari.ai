"""Syllabus tools API: switch, scope, and each operation end to end."""
from unittest.mock import patch

from intelligence.models import ItemTagging, SyllabusNode, TaggingRun, TreeBuildJob
from intelligence.tests.syllabus_fixtures import SyllabusTestCase
from intelligence.tests.test_course_tree import FakeCall as BuildCall

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

    def test_retag_queues(self):
        with patch('intelligence.syllabus_views._enqueue_retag') as queued:
            response = self.client_for(self.admin).post(f'{BASE}/review/{self.tagging.id}/retag/')
        self.assertEqual(response.json(), {'queued': True})
        queued.assert_called_once_with('bank', str(self.item.id))

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
