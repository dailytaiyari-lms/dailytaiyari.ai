from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.models import Tenant
from users.models import CourseEnrollment, StudentProfile, User

from .models import Chapter, Course, Subject, Topic
from .views import (
    AvailableCoursesForEnrollmentView,
    ChapterViewSet,
    CourseViewSet,
    StudyChaptersView,
    SubjectViewSet,
    TopicViewSet,
)
from users.views import CourseEnrollmentListView


class HiddenCourseVisibilityTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Academy', subdomain='academy')
        self.public_course = Course.objects.create(
            tenant=self.tenant,
            name='Public Course',
            code='public-course',
            course_type='skill',
        )
        self.hidden_course = Course.objects.create(
            tenant=self.tenant,
            name='Hidden Course',
            code='hidden-course',
            course_type='skill',
            is_hidden=True,
        )
        self.subject = Subject.objects.create(
            course=self.hidden_course, name='Hidden Subject', code='hidden-subject'
        )
        self.topic = Topic.objects.create(
            subject=self.subject, name='Hidden Topic', code='hidden-topic'
        )
        self.chapter = Chapter.objects.create(
            subject=self.subject, name='Hidden Chapter', code='hidden-chapter'
        )
        self.student = User.objects.create_user(
            email='student@example.com', tenant=self.tenant, password='password'
        )
        self.profile, _ = StudentProfile.objects.get_or_create(user=self.student)
        self.outsider = User.objects.create_user(
            email='outsider@example.com', tenant=self.tenant, password='password'
        )
        self.outsider_profile, _ = StudentProfile.objects.get_or_create(user=self.outsider)
        CourseEnrollment.objects.create(
            student=self.profile,
            course=self.hidden_course,
            status='approved',
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def request(self, path, user=None):
        request = self.factory.get(path)
        if user is not None:
            force_authenticate(request, user=user)
        else:
            request.user = AnonymousUser()
        request.tenant = self.tenant
        return request

    def post_request(self, path, data, user):
        request = self.factory.post(path, data, format='json')
        force_authenticate(request, user=user)
        request.tenant = self.tenant
        return request

    def ids(self, response):
        data = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        return {str(item['id']) for item in data}

    def test_catalog_hides_course_from_anonymous_and_non_enrolled_students(self):
        view = AvailableCoursesForEnrollmentView.as_view()

        anonymous = view(self.request('/courses/available-for-enrollment/'))
        outsider = view(self.request('/courses/available-for-enrollment/', self.outsider))

        self.assertNotIn(str(self.hidden_course.id), self.ids(anonymous))
        self.assertNotIn(str(self.hidden_course.id), self.ids(outsider))
        self.assertIn(str(self.public_course.id), self.ids(anonymous))

    def test_catalog_and_detail_include_hidden_course_for_enrolled_student(self):
        catalog = AvailableCoursesForEnrollmentView.as_view()
        detail = CourseViewSet.as_view({'get': 'retrieve'})

        catalog_response = catalog(
            self.request('/courses/available-for-enrollment/', self.student)
        )
        detail_response = detail(
            self.request(f'/courses/{self.hidden_course.id}/', self.student),
            pk=str(self.hidden_course.id),
        )

        self.assertIn(str(self.hidden_course.id), self.ids(catalog_response))
        self.assertEqual(detail_response.status_code, 200)

    def test_direct_course_and_child_urls_hide_course_from_outsider(self):
        cases = [
            (
                CourseViewSet.as_view({'get': 'retrieve'}),
                f'/courses/{self.hidden_course.id}/',
                self.hidden_course.id,
            ),
            (
                SubjectViewSet.as_view({'get': 'retrieve'}),
                f'/courses/subjects/{self.subject.id}/',
                self.subject.id,
            ),
            (
                TopicViewSet.as_view({'get': 'retrieve'}),
                f'/courses/topics/{self.topic.id}/',
                self.topic.id,
            ),
            (
                ChapterViewSet.as_view({'get': 'retrieve'}),
                f'/courses/chapters/{self.chapter.id}/',
                self.chapter.id,
            ),
        ]

        for view, path, pk in cases:
            with self.subTest(path=path):
                response = view(self.request(path, self.outsider), pk=str(pk))
                self.assertEqual(response.status_code, 404)

    def test_study_chapters_requires_active_approved_enrollment(self):
        view = StudyChaptersView.as_view()

        denied = view(
            self.request(f'/courses/study/chapters/{self.subject.id}/', self.outsider),
            subject_id=self.subject.id,
        )
        allowed = view(
            self.request(f'/courses/study/chapters/{self.subject.id}/', self.student),
            subject_id=self.subject.id,
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_non_enrolled_student_cannot_request_hidden_course(self):
        response = CourseEnrollmentListView.as_view()(
            self.post_request(
                '/auth/enrollments/',
                {'course': str(self.hidden_course.id)},
                self.outsider,
            )
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CourseEnrollment.objects.filter(
                student=self.outsider_profile,
                course=self.hidden_course,
            ).exists()
        )
