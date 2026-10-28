"""Diagnosis view switches: opt-in, and only on while Answer Diagnosis is on."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from users.models import User

VIEW_KEYS = ('diagnosis_teacher_view', 'diagnosis_student_view')


class SwitchDependencyTests(TestCase):
    def test_view_switches_are_off_by_default(self):
        features = Tenant.objects.create(name='Default Academy').get_features()
        for key in VIEW_KEYS:
            self.assertIs(features[key], False)

    def test_view_switch_is_off_while_requirement_is_off(self):
        tenant = Tenant.objects.create(
            name='Half Academy',
            features={'diagnosis_teacher_view': True, 'diagnosis_student_view': True},
        )
        features = tenant.get_features()
        for key in VIEW_KEYS:
            self.assertIs(features[key], False)

    def test_view_switch_is_on_with_requirement(self):
        tenant = Tenant.objects.create(
            name='Full Academy',
            features={'response_diagnosis': True, 'diagnosis_teacher_view': True},
        )
        features = tenant.get_features()
        self.assertIs(features['diagnosis_teacher_view'], True)
        self.assertIs(features['diagnosis_student_view'], False)

    def test_force_on_lock_still_needs_requirement(self):
        tenant = Tenant.objects.create(
            name='Locked Academy', feature_locks={'diagnosis_teacher_view': True},
        )
        self.assertIs(tenant.get_features()['diagnosis_teacher_view'], False)
        tenant.feature_locks = {'diagnosis_teacher_view': True, 'response_diagnosis': True}
        self.assertIs(tenant.get_features()['diagnosis_teacher_view'], True)

    def test_requirement_map_names_known_keys(self):
        for key, required in Tenant.FEATURE_REQUIRES.items():
            self.assertIn(key, Tenant.FEATURE_CHOICES)
            self.assertIn(required, Tenant.FEATURE_CHOICES)
            self.assertIn(key, Tenant.OPT_IN_FEATURES)


class SettingsPayloadTests(TestCase):
    def test_tenant_settings_mark_the_dependency(self):
        tenant = Tenant.objects.create(name='Payload Academy', is_active=True)
        admin = User.objects.create_user(
            email='payload-admin@example.com', password='pw-payload-1',
            tenant=tenant, role='admin',
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}',
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        response = client.get('/api/v1/tenant-admin/settings/')
        self.assertEqual(response.status_code, 200, response.content)
        by_key = {row['key']: row for row in response.json()['available_features']}
        self.assertEqual(by_key['diagnosis_teacher_view']['requires'], 'response_diagnosis')
        self.assertEqual(by_key['diagnosis_student_view']['requires_label'], 'Answer Diagnosis')
        self.assertIsNone(by_key['quiz']['requires'])
