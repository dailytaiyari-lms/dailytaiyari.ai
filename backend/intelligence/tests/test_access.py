"""Who sees which students and courses (spec 2B §3.2), and the narrowing of
the existing Insights views for faculty."""
from intelligence.access import (
    can_manage_course, can_view_student, diagnosis_scope_q, teachable_course_ids,
)
from intelligence.models import ResponseDiagnosis
from intelligence.tests.visibility_fixtures import VisibilityTestCase
from quiz.models import Quiz

INSIGHTS = '/api/v1/tenant-admin/intelligence'


class HelperTests(VisibilityTestCase):
    def test_teachable_course_ids(self):
        self.assertEqual(teachable_course_ids(self.admin), {self.course.id, self.other_course.id})
        self.assertEqual(teachable_course_ids(self.faculty), {self.course.id})
        self.assertEqual(teachable_course_ids(self.student_user), set())

    def test_can_view_student(self):
        self.assertTrue(can_view_student(self.admin, self.outsider))
        self.assertTrue(can_view_student(self.faculty, self.student))
        self.assertFalse(can_view_student(self.faculty, self.outsider))
        self.assertFalse(can_view_student(self.student_user, self.student))

    def test_pending_enrollment_is_not_in_scope(self):
        enrollment = self.student.enrollments.get(course=self.course)
        enrollment.status = 'pending'
        enrollment.save()
        self.assertFalse(can_view_student(self.faculty, self.student))

    def test_can_manage_course(self):
        self.assertTrue(can_manage_course(self.admin, self.other_course))
        self.assertTrue(can_manage_course(self.faculty, self.course))
        self.assertFalse(can_manage_course(self.faculty, self.other_course))
        self.assertFalse(can_manage_course(self.student_user, self.course))

    def test_diagnosis_scope_limits_faculty_to_their_courses(self):
        question = self.make_question(1)
        mine = self.diagnose(self.quiz_attempt(self.student), question, 'guess')
        other_quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.other_course, title='Chem quiz',
            quiz_type='topic', duration_minutes=10,
        )
        theirs = self.diagnose(
            self.quiz_attempt(self.student, quiz=other_quiz),
            self.make_question(2, quiz=other_quiz), 'guess',
        )
        rows = ResponseDiagnosis.objects.filter(student=self.student)
        self.assertEqual(
            set(rows.filter(diagnosis_scope_q(self.faculty, self.student))
                .values_list('id', flat=True)),
            {mine.id},
        )
        self.assertEqual(
            set(rows.filter(diagnosis_scope_q(self.admin, self.student))
                .values_list('id', flat=True)),
            {mine.id, theirs.id},
        )


class ExistingViewNarrowingTests(VisibilityTestCase):
    def test_overview_refuses_unassigned_course_for_faculty(self):
        client = self.client_for(self.faculty)
        self.assertEqual(
            client.get(f'{INSIGHTS}/overview/', {'course': str(self.course.id)}).status_code, 200)
        self.assertEqual(
            client.get(f'{INSIGHTS}/overview/', {'course': str(self.other_course.id)}).status_code,
            403)
        self.assertEqual(
            self.client_for(self.admin).get(
                f'{INSIGHTS}/overview/', {'course': str(self.other_course.id)}).status_code,
            200)

    def test_assessment_report_refuses_unassigned_course_for_faculty(self):
        url = f'{INSIGHTS}/assessments/quiz/{self.quiz.id}/report/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 403)

    def test_student_diagnosis_refuses_out_of_scope_student(self):
        client = self.client_for(self.faculty)
        self.assertEqual(
            client.get(f'{INSIGHTS}/students/{self.student.id}/diagnosis/').status_code, 200)
        self.assertEqual(
            client.get(f'{INSIGHTS}/students/{self.outsider.id}/diagnosis/').status_code, 403)

    def test_practice_config_refuses_unassigned_course_for_faculty(self):
        url = f'{INSIGHTS}/courses/{self.other_course.id}/practice-config/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 200)

    def test_generation_jobs_are_filtered_for_faculty(self):
        from intelligence.models import PracticeGenerationJob

        PracticeGenerationJob.objects.create(
            tenant=self.tenant, course=self.other_course, deficit_kind='low_mastery',
            deficit_signature='sig',
        )
        self.assertEqual(self.client_for(self.faculty).get(f'{INSIGHTS}/generation-jobs/').json(), [])
        self.assertEqual(len(self.client_for(self.admin).get(f'{INSIGHTS}/generation-jobs/').json()), 1)
