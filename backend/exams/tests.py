from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.models import Tenant
from users.models import CourseEnrollment, StudentProfile, User
from content.models import Content
from content.views import ContentViewSet

from .models import Chapter, Course, Subject, Topic
from .views import (
    AvailableCoursesForEnrollmentView,
    ChapterViewSet,
    CourseViewSet,
    StudyChapterDetailView,
    StudyChaptersView,
    StudyCoursesView,
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
        self.admin = User.objects.create_user(
            email='admin@example.com',
            tenant=self.tenant,
            password='password',
            role='admin',
        )
        self.instructor = User.objects.create_user(
            email='instructor@example.com',
            tenant=self.tenant,
            password='password',
            role='instructor',
        )
        self.hidden_course.instructors.add(self.instructor)
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

    def test_admin_and_assigned_instructor_can_open_hidden_course_chapters(self):
        view = StudyChaptersView.as_view()

        for user in (self.admin, self.instructor):
            with self.subTest(role=user.role):
                response = view(
                    self.request(
                        f'/courses/study/chapters/{self.subject.id}/',
                        user,
                    ),
                    subject_id=self.subject.id,
                )
                self.assertEqual(response.status_code, 200)

    def test_admin_cannot_open_another_tenants_subject_or_chapter(self):
        other_tenant = Tenant.objects.create(name='Other Academy', subdomain='other-academy')
        other_course = Course.objects.create(
            tenant=other_tenant,
            name='Other Tenant Course',
            code='other-tenant-course',
            course_type='skill',
            is_hidden=True,
        )
        other_subject = Subject.objects.create(
            course=other_course,
            name='Other Subject',
            code='other-subject',
        )
        other_chapter = Chapter.objects.create(
            subject=other_subject,
            name='Other Chapter',
            code='other-chapter',
        )

        subject_response = StudyChaptersView.as_view()(
            self.request(
                f'/courses/study/chapters/{other_subject.id}/',
                self.admin,
            ),
            subject_id=other_subject.id,
        )
        chapter_response = StudyChapterDetailView.as_view()(
            self.request(
                f'/courses/study/chapter/{other_chapter.id}/',
                self.admin,
            ),
            chapter_id=other_chapter.id,
        )

        self.assertEqual(subject_response.status_code, 404)
        self.assertEqual(chapter_response.status_code, 404)

    def test_hidden_pending_and_inactive_enrollments_are_absent_from_study(self):
        inactive_course = Course.objects.create(
            tenant=self.tenant,
            name='Inactive Hidden Course',
            code='inactive-hidden-course',
            course_type='skill',
            is_hidden=True,
        )
        CourseEnrollment.objects.create(
            student=self.outsider_profile,
            course=self.hidden_course,
            status='pending',
            is_active=True,
        )
        CourseEnrollment.objects.create(
            student=self.outsider_profile,
            course=inactive_course,
            status='approved',
            is_active=False,
        )

        response = StudyCoursesView.as_view()(
            self.request('/courses/study/courses/', self.outsider)
        )

        returned_ids = {
            str(course['id'])
            for course in response.data['courses'] + response.data['pending']
        }
        self.assertNotIn(str(self.hidden_course.id), returned_ids)
        self.assertNotIn(str(inactive_course.id), returned_ids)

    def test_student_with_no_enrollment_cannot_retrieve_hidden_course_content(self):
        content = Content.objects.create(
            title='Private Lesson',
            slug='private-lesson',
            content_type='notes',
            topic=self.topic,
            subject=self.subject,
            status='published',
        )
        content.courses.add(self.hidden_course)
        view = ContentViewSet.as_view({'get': 'retrieve'})

        denied = view(
            self.request(f'/content/{content.id}/', self.outsider),
            pk=str(content.id),
        )
        allowed = view(
            self.request(f'/content/{content.id}/', self.student),
            pk=str(content.id),
        )

        self.assertEqual(denied.status_code, 404)
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
