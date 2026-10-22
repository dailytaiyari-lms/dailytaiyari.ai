"""Validate intelligence/taxonomy/*.yaml and load the tag vocabulary.

    manage.py sync_taxonomy --check            # validate only (CI)
    manage.py sync_taxonomy                    # load tags.yaml into the DB
    manage.py sync_taxonomy --retag-subjects <id,id>
"""
from django.core.management.base import BaseCommand, CommandError

from intelligence.services.taxonomy import (
    TaxonomyError, load_exam_tree, load_tags, mark_subjects_stale, shipped_exam_keys,
    sync_vocabulary,
)


class Command(BaseCommand):
    help = 'Validate the taxonomy YAML files and load the tag vocabulary into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='Validate only; write nothing.')
        parser.add_argument('--retag-subjects', default='',
                            help='Comma-separated subject ids whose tagged items become stale.')

    def handle(self, *args, **options):
        try:
            tags, sha = load_tags()
            trees = [load_exam_tree(key) for key in shipped_exam_keys()]
        except TaxonomyError as exc:
            raise CommandError('Taxonomy is invalid:\n- ' + '\n- '.join(exc.errors)) from exc
        tree_names = ', '.join(tree['key'] for tree in trees) or 'none'
        self.stdout.write(f'tags.yaml v{tags["version"]} OK; exam trees OK: {tree_names}')
        if options['check']:
            return

        summary = sync_vocabulary(tags, sha)
        release = summary['release']
        self.stdout.write(
            f'{summary["upserted"]} tag(s) upserted, {summary["deactivated"]} deactivated; '
            + (f'new release #{release.sequence}' if release else 'no content change')
        )
        subject_ids = [raw.strip() for raw in options['retag_subjects'].split(',') if raw.strip()]
        if subject_ids:
            try:
                marked = mark_subjects_stale(subject_ids)
            except TaxonomyError as exc:
                raise CommandError('; '.join(exc.errors)) from exc
            self.stdout.write(f'{marked} item(s) marked stale for re-tagging')
        elif release:
            self.stdout.write('To re-tag existing items, run again with --retag-subjects <ids>.')
