"""Recompute LearnerConceptState rows from the event log.

Run after a backfill, a tagging pass, a concept merge, or a
STATE_MODEL_VERSION bump. Idempotent by construction.
Also recomputes My Progress facets (tenants with it on) unless --no-facets.
"""
from argparse import BooleanOptionalAction

from django.core.management.base import BaseCommand

from intelligence.models import ConceptLink, LearningEvent
from intelligence.services import state


class Command(BaseCommand):
    help = 'Recompute learner concept states from LearningEvents (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id (default: all).')
        parser.add_argument('--student', help='StudentProfile id (default: all).')
        parser.add_argument(
            '--facets', action=BooleanOptionalAction, default=True,
            help='Also recompute skill / thinking-level facets for tenants with My Progress on '
                 '(default: on).',
        )

    def handle(self, *args, **options):
        events = LearningEvent.objects.all()
        if options.get('tenant'):
            events = events.filter(tenant_id=options['tenant'])
        if options.get('student'):
            events = events.filter(student_id=options['student'])

        # Every (student, concept) pair with any evidence, via the item links.
        pairs = set()
        for arm in ('question', 'mock_item'):
            rows = (
                events.filter(**{f'{arm}__isnull': False})
                .values_list('student_id', f'{arm}_id').distinct()
            )
            by_item = {}
            for student_id, item_id in rows:
                by_item.setdefault(item_id, set()).add(student_id)
            links = ConceptLink.objects.filter(
                **{f'{arm}_id__in': by_item.keys()}
            ).values_list(f'{arm}_id', 'concept_id')
            for item_id, concept_id in links:
                for student_id in by_item.get(item_id, ()):
                    pairs.add((student_id, concept_id))

        from intelligence.models import Concept
        from users.models import StudentProfile

        students = StudentProfile.objects.in_bulk({s for s, _ in pairs})
        concepts = Concept.objects.in_bulk({c for _, c in pairs})

        done = 0
        for student_id, concept_id in sorted(pairs, key=str):
            student = students.get(student_id)
            concept = concepts.get(concept_id)
            if student and concept:
                state.recompute_state(student, concept)
                done += 1
                if done % 500 == 0:
                    self.stdout.write(f'  … {done} states recomputed')
        self.stdout.write(self.style.SUCCESS(f'{done} learner concept states recomputed.'))
        if not options['facets']:
            return
        from intelligence.services import facets

        profiled = 0
        student_ids = set(events.values_list('student_id', flat=True).distinct())
        for student in StudentProfile.objects.filter(id__in=student_ids).select_related('user__tenant'):
            if facets.facets_enabled(student.user.tenant):
                facets.recompute_facets(student)
                profiled += 1
        self.stdout.write(self.style.SUCCESS(f'{profiled} student facet profiles recomputed.'))
