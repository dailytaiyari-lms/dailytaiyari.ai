"""Map a course onto a shipped exam tree and instantiate its syllabus nodes.

    manage.py map_course_to_exam --course <id> --exam jee_main \
        --subject-map physics=<subject_id>,chemistry=<subject_id>,maths=<subject_id>
"""
import uuid

from django.core.management.base import BaseCommand, CommandError

from exams.models import Course, Subject
from intelligence.services.syllabus import instantiate_exam_tree
from intelligence.services.taxonomy import TaxonomyError


def _uuid(value, label):
    try:
        return uuid.UUID(str(value).strip())
    except ValueError as exc:
        raise CommandError(f'{label} {value!r} is not a valid id.') from exc


class Command(BaseCommand):
    help = 'Map a course onto an exam tree (taxonomy/exams/<exam>.yaml) and build its nodes.'

    def add_arguments(self, parser):
        parser.add_argument('--course', required=True)
        parser.add_argument('--exam', required=True, help='Exam tree key, e.g. jee_main.')
        parser.add_argument('--subject-map', required=True,
                            help='Comma-separated tree_subject=subject_id pairs.')
        parser.add_argument('--audience', default=None, help='Override the tree audience text.')

    def handle(self, *args, **options):
        course = Course.objects.filter(id=_uuid(options['course'], 'Course')).first()
        if course is None:
            raise CommandError('Course not found.')
        mapping = {}
        for part in options['subject_map'].split(','):
            if not part.strip():
                continue
            tree_key, _, subject_id = part.partition('=')
            subject = Subject.objects.filter(id=_uuid(subject_id, 'Subject'), course=course).first()
            if subject is None:
                raise CommandError(f'Subject {subject_id.strip()!r} is not part of this course.')
            mapping[tree_key.strip()] = subject
        if not mapping:
            raise CommandError('--subject-map is empty.')
        try:
            summary = instantiate_exam_tree(course, options['exam'], mapping, audience=options['audience'])
        except TaxonomyError as exc:
            raise CommandError('; '.join(exc.errors)) from exc

        self.stdout.write(
            f'{course.name} → {options["exam"]}: created {summary["created"]}, '
            f'updated {summary["updated"]}, archived {summary["archived"]}, '
            f'linked {summary["linked_topics"]} course topic(s).'
        )
        for line in summary['unmatched_topics']:
            self.stdout.write(f'  unmatched course topic — {line}')
        for line in summary['ambiguous_concepts']:
            self.stdout.write(f'  concept matches several subtopics, left alone — {line}')
        if summary['merged_concepts']:
            self.stdout.write(
                f'{summary["merged_concepts"]} existing concept(s) merged into tree subtopics; '
                'run `manage.py recompute_learner_state` next.'
            )
