"""Build (or extend) syllabus trees for a custom course.

    manage.py build_course_tree --course <id> --model gpt-6-luna [--packs programming] [--dry-run]

Only question text, topic names and objectives are sent to the model.
"""
import uuid

from django.core.management.base import BaseCommand, CommandError

from exams.models import Course
from intelligence.services.course_tree import build_course_tree
from intelligence.services.llm import platform_call, tenant_tagging_call


class Command(BaseCommand):
    help = 'Build syllabus trees (sub-subjects, topics, subtopics, skill packs) for a custom course.'

    def add_arguments(self, parser):
        parser.add_argument('--course', required=True)
        parser.add_argument('--model', default=None,
                            help='Platform model name (default: the tenant tagging model).')
        parser.add_argument('--packs', default=None,
                            help='Comma-separated skill pack keys for every subject (skips the LLM choice).')
        parser.add_argument('--dry-run', action='store_true', help='Roll back at the end (LLM calls still run).')

    def handle(self, *args, **options):
        try:
            course = Course.objects.filter(id=uuid.UUID(options['course'])).first()
        except ValueError as exc:
            raise CommandError('--course is not a valid id.') from exc
        if course is None:
            raise CommandError('Course not found.')
        call = (platform_call(options['model'], course.tenant) if options['model']
                else tenant_tagging_call(course.tenant))
        packs = ([key.strip() for key in options['packs'].split(',') if key.strip()]
                 if options['packs'] is not None else None)
        summary = build_course_tree(course, call=call, packs=packs, dry_run=options['dry_run'])
        self.stdout.write(
            f'{course.name}: subjects {summary["subjects"]}, '
            f'sub-subjects created: {summary["sub_subjects_created"]}, '
            f'topics created: {summary["topics_created"]}, seeded subtopics: {summary["seeded_subtopics"]}, '
            f'proposed subtopics: {summary["proposed_subtopics"]}, LLM calls: {summary["llm_calls"]}'
            + (' (dry run — rolled back)' if summary['dry_run'] else '')
        )
        for name, keys in summary['packs'].items():
            self.stdout.write(f'  packs — {name}: {", ".join(keys)}')
