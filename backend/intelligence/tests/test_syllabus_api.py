"""Syllabus tools API: switch, scope, and each operation end to end."""
from unittest.mock import patch

from intelligence.models import SyllabusNode, TaggingRun, TreeBuildJob
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
