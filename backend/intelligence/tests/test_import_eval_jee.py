"""JEE Lab importer: guards, structure, type mapping, idempotency, no gold leak."""
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import Tenant
from exams.models import Course
from intelligence.models import SyllabusNode
from quiz.models import Question

FIXTURE = Path(__file__).parent / 'fixtures' / 'eval_jee_sample.jsonl'


def run(*args):
    out = StringIO()
    call_command('import_eval_jee', '--file', str(FIXTURE), *args, stdout=out)
    return out.getvalue()


@override_settings(DEBUG=True)
class ImportEvalJeeTests(TestCase):
    def test_import_builds_the_lab_course(self):
        output = run('--tenant', 'lab-jee')
        self.assertIn('4 question(s) created', output)
        tenant = Tenant.objects.get(subdomain='lab-jee')
        course = Course.objects.get(code='lab-jee-jee-main')
        self.assertEqual((course.tenant, course.name), (tenant, 'JEE Main (Lab)'))
        self.assertEqual(course.syllabus.exam_tree, 'jee_main')
        self.assertEqual(sorted(course.subjects.values_list('code', flat=True)), ['chemistry', 'maths', 'physics'])
        self.assertTrue(SyllabusNode.objects.filter(
            subject__course=course, level='topic', course_topic__isnull=False).exists())

        questions = Question.objects.filter(tenant=tenant)
        self.assertEqual(sorted(questions.values_list('question_type', flat=True)),
                         ['mcq', 'mcq', 'mcq_multi', 'numerical'])
        # JSONField __contains is unsupported on SQLite, so match in Python.
        friction = next(q for q in questions if 'eval_jee:fx-1' in q.tags)
        self.assertEqual(friction.topic.name, 'Laws of Motion')
        self.assertEqual(friction.correct_answer, '1')
        self.assertEqual(list(friction.options.order_by('order').values_list('is_correct', flat=True)),
                         [False, True, False, False])
        self.assertTrue(friction.question_text.startswith('A 2 kg block rests on a rough floor'))
        self.assertIn('<p>', friction.question_html)
        self.assertEqual(friction.status, 'published')
        self.assertIn(course, friction.courses.all())
        multi = questions.get(question_type='mcq_multi')
        self.assertEqual(multi.correct_answer, '0,2')
        numerical = questions.get(question_type='numerical')
        self.assertEqual(numerical.numerical_answer, Decimal('12'))
        self.assertFalse(numerical.options.exists())
        # The dataset's subtopic labels never reach the database.
        for question in questions:
            self.assertFalse(any('-drill' in tag for tag in question.tags))

    def test_rerun_is_idempotent(self):
        run('--tenant', 'lab-jee')
        output = run('--tenant', 'lab-jee')
        self.assertIn('0 question(s) created', output)
        self.assertEqual(Question.objects.filter(tenant__subdomain='lab-jee').count(), 4)

    def test_limit_samples_the_pool(self):
        run('--tenant', 'lab-small', '--limit', '2')
        self.assertEqual(Question.objects.filter(tenant__subdomain='lab-small').count(), 2)

    def test_guards(self):
        with self.assertRaises(CommandError):
            run('--tenant', 'jee')  # not lab-
        with patch('intelligence.management.commands.import_eval_jee.database_is_local', return_value=False), \
                self.assertRaises(CommandError):
            run('--tenant', 'lab-jee')
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            run('--tenant', 'lab-jee')
        self.assertFalse(Tenant.objects.filter(subdomain__startswith='lab-').exists())
