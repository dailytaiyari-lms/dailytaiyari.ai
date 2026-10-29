"""Skill and thinking-level profiles (spec 2B §6.3)."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Tenant
from exams.models import Course, Subject
from intelligence.models import LearnerFacetState
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
