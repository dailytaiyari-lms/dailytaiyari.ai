"""Tests for admin-provisioned student accounts and course assignment."""
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from core.models import Tenant
from exams.models import Course
from users.models import CourseEnrollment, StudentProfile, User


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminStudentProvisioningTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Test Academy')
        self.admin = User.objects.create_user(
            email='admin@test.com', tenant=self.tenant, password='adminpass123',
            first_name='Ada', last_name='Admin', role='admin',
        )
        self.course = Course.objects.create(name='JEE Main', code='JEE', tenant=self.tenant, status='active')
        self.other_tenant = Tenant.objects.create(name='Other')
        self.other_course = Course.objects.create(
            name='Foreign', code='FGN', tenant=self.other_tenant, status='active',
        )
        self.client.force_authenticate(user=self.admin)
        self.headers = {'HTTP_X_TENANT_ID': str(self.tenant.id)}

    def test_create_student_generates_password_and_emails_credentials(self):
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'Student@Test.com',
            'first_name': 'Sam',
            'last_name': 'Student',
            'course_ids': [str(self.course.id)],
            'grade': '12',
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['email_sent'])
        self.assertNotIn('temporary_password', resp.data)

        user = User.objects.get(email='student@test.com', tenant=self.tenant)
        self.assertEqual(user.role, 'student')
        self.assertTrue(user.is_email_verified)
        self.assertEqual(user.profile.grade, '12')

        enrollment = CourseEnrollment.objects.get(student=user.profile, course=self.course)
        self.assertEqual(enrollment.status, 'approved')

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('student@test.com', body)
        self.assertIn('JEE Main', body)
        # The generated password must actually authenticate.
        pwd = None
        for line in body.splitlines():
            if 'Temporary' in line:
                pwd = line.split(':', 1)[1].strip()
        self.assertTrue(pwd)
        self.assertTrue(user.check_password(pwd))

    def test_create_student_rejects_duplicate_email(self):
        User.objects.create_user(email='dupe@test.com', tenant=self.tenant, password='x1234567')
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'dupe@test.com', 'first_name': 'Dupe',
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('email', resp.data)

    def test_create_student_rejects_cross_tenant_course(self):
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'x@test.com', 'first_name': 'X',
            'course_ids': [str(self.other_course.id)],
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(User.objects.filter(email='x@test.com').exists())

    def test_create_student_without_email_returns_password(self):
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'quiet@test.com', 'first_name': 'Quiet', 'send_email': False,
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertFalse(resp.data['email_sent'])
        self.assertIn('temporary_password', resp.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_assign_courses_enrols_and_emails(self):
        user = User.objects.create_user(
            email='existing@test.com', tenant=self.tenant, password='pass12345',
            first_name='Ex', last_name='Isting',
        )
        profile = StudentProfile.objects.get(user=user)
        mail.outbox = []

        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/assign-courses/',
            {'course_ids': [str(self.course.id)]}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data['assigned']), 1)
        enrollment = CourseEnrollment.objects.get(student=profile, course=self.course)
        self.assertEqual(enrollment.status, 'approved')
        self.assertEqual(enrollment.reviewed_by, self.admin)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('JEE Main', mail.outbox[0].subject)

        # Re-assigning the same course is a no-op and sends no further email.
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/assign-courses/',
            {'course_ids': [str(self.course.id)]}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['assigned'], [])
        self.assertEqual(len(mail.outbox), 1)

    def test_assign_course_approves_a_pending_request(self):
        user = User.objects.create_user(
            email='pending@test.com', tenant=self.tenant, password='pass12345', first_name='P',
        )
        profile = StudentProfile.objects.get(user=user)
        CourseEnrollment.objects.create(student=profile, course=self.course, status='pending')
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/assign-courses/',
            {'course_ids': [str(self.course.id)]}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            CourseEnrollment.objects.get(student=profile, course=self.course).status, 'approved',
        )

    def test_non_admin_cannot_create_students(self):
        student = User.objects.create_user(
            email='nobody@test.com', tenant=self.tenant, password='pass12345', first_name='N',
        )
        self.client.force_authenticate(user=student)
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'new@test.com', 'first_name': 'New',
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_reset_password_emails_new_credentials(self):
        user = User.objects.create_user(
            email='reset@test.com', tenant=self.tenant, password='oldpass12345', first_name='R',
        )
        profile = StudentProfile.objects.get(user=user)
        mail.outbox = []
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/reset-password/', {}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['email_sent'])
        user.refresh_from_db()
        self.assertFalse(user.check_password('oldpass12345'))
        self.assertEqual(len(mail.outbox), 1)

    def test_cannot_reset_another_admins_password(self):
        other_admin = User.objects.create_user(
            email='admin2@test.com', tenant=self.tenant, password='adminpass123',
            first_name='Bob', role='admin',
        )
        profile = StudentProfile.objects.get(user=other_admin)
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/reset-password/', {}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 403)
        other_admin.refresh_from_db()
        self.assertTrue(other_admin.check_password('adminpass123'))

    def test_cannot_touch_students_from_another_tenant(self):
        outsider = User.objects.create_user(
            email='out@test.com', tenant=self.other_tenant, password='pass12345', first_name='O',
        )
        profile = StudentProfile.objects.get(user=outsider)
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/assign-courses/',
            {'course_ids': [str(self.course.id)]}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(CourseEnrollment.objects.filter(student=profile).count(), 0)

    def test_cannot_create_an_admin_account(self):
        resp = self.client.post('/api/v1/auth/tenant-students/', {
            'email': 'sneaky@test.com', 'first_name': 'Sneaky', 'role': 'admin',
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('role', resp.data)

    def test_remove_course_deletes_enrollment(self):
        user = User.objects.create_user(
            email='drop@test.com', tenant=self.tenant, password='pass12345', first_name='D',
        )
        profile = StudentProfile.objects.get(user=user)
        CourseEnrollment.objects.create(student=profile, course=self.course, status='approved')
        resp = self.client.post(
            f'/api/v1/auth/tenant-students/{profile.id}/remove-course/',
            {'course_id': str(self.course.id)}, format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(CourseEnrollment.objects.filter(student=profile).count(), 0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RosterCourseProgressTests(APITestCase):
    """The roster progress endpoint must be correct and query-bounded."""

    def setUp(self):
        from exams.models import Subject, Topic
        from content.models import Content

        self.tenant = Tenant.objects.create(name='Progress Academy')
        self.admin = User.objects.create_user(
            email='padmin@test.com', tenant=self.tenant, password='adminpass123',
            first_name='P', role='admin',
        )
        self.course = Course.objects.create(
            name='Python', code='PY', tenant=self.tenant, status='active',
        )
        subject = Subject.objects.create(course=self.course, name='Basics', tenant=self.tenant)
        topic = Topic.objects.create(subject=subject, name='Vars', tenant=self.tenant)
        self.contents = [
            Content.objects.create(
                title=f'Note {i}', subject=subject, topic=topic, tenant=self.tenant,
                content_type='notes', status='published', slug=f'progress-note-{i}',
            )
            for i in range(4)
        ]
        self.client.force_authenticate(user=self.admin)
        self.headers = {'HTTP_X_TENANT_ID': str(self.tenant.id)}

    def _make_student(self, email):
        user = User.objects.create_user(
            email=email, tenant=self.tenant, password='pass12345', first_name='S',
        )
        profile = StudentProfile.objects.get(user=user)
        CourseEnrollment.objects.create(
            student=profile, course=self.course, status='approved',
        )
        return profile

    def test_reports_percent_complete_per_course(self):
        from content.models import ContentProgress

        profile = self._make_student('p1@test.com')
        for content in self.contents[:1]:
            ContentProgress.objects.create(
                student=profile, content=content, is_completed=True, tenant=self.tenant,
            )

        resp = self.client.get('/api/v1/auth/tenant-students/course-progress/', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        row = next(r for r in resp.data['results'] if r['student_id'] == str(profile.id))
        self.assertEqual(row['courses'][0]['total'], 4)
        self.assertEqual(row['courses'][0]['completed'], 1)
        self.assertEqual(row['courses'][0]['percent'], 25)

    def test_query_count_does_not_grow_with_roster_size(self):
        """The whole point of the bulk endpoint: cost stays flat as students are added."""
        for i in range(2):
            self._make_student(f'few{i}@test.com')
        few = len(self._capture_queries())

        for i in range(8):
            self._make_student(f'many{i}@test.com')
        many = len(self._capture_queries())

        self.assertEqual(few, many)

    def _capture_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(
                '/api/v1/auth/tenant-students/course-progress/', **self.headers)
        self.assertEqual(resp.status_code, 200)
        return ctx.captured_queries

    def test_progress_endpoint_is_tenant_scoped(self):
        other_tenant = Tenant.objects.create(name='Other')
        outsider = User.objects.create_user(
            email='out2@test.com', tenant=other_tenant, password='pass12345', first_name='O',
        )
        other_course = Course.objects.create(
            name='Foreign', code='F2', tenant=other_tenant, status='active',
        )
        CourseEnrollment.objects.create(
            student=StudentProfile.objects.get(user=outsider), course=other_course,
            status='approved',
        )
        mine = self._make_student('mine@test.com')

        resp = self.client.get('/api/v1/auth/tenant-students/course-progress/', **self.headers)
        ids = {r['student_id'] for r in resp.data['results']}
        self.assertEqual(ids, {str(mine.id)})
