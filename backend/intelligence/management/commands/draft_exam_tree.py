"""Dev only: draft taxonomy/exams/jee_main.yaml from the local eval_jee dataset.

    manage.py draft_exam_tree --from-eval-jee ../data_dumps/jee_eval/eval_jee.jsonl

The output holds syllabus names and weights only (no question content). Review
it by hand — labels, merged duplicates, the sub-subject grouping — then run
``sync_taxonomy --check`` and commit it.
"""
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

from intelligence.services.eval_jee import draft_jee_main_tree, read_rows
from intelligence.services.taxonomy import TaxonomyError, flatten_tree, validate_exam_tree
from intelligence.taxonomy import EXAMS_DIR

HEADER = """\
# JEE Main syllabus tree (decision D5): subject → sub-subject → topic → subtopic.
# Drafted by `manage.py draft_exam_tree` from the chapter/topic labels of the
# local-only eval_jee dataset, then reviewed by hand. No question content.
# weightage = share of 2021–2024 JEE Main questions within the parent node.
# in_syllabus: false marks chapters removed from the NTA JEE Main syllabus (2024).
# aliases = the dataset's slugs (used to build gold files and to link course topics).
"""


class Command(BaseCommand):
    help = 'Draft the JEE Main exam tree YAML from the local eval_jee dataset (dev only).'

    def add_arguments(self, parser):
        parser.add_argument('--from-eval-jee', required=True, dest='source',
                            help='Path to eval_jee.jsonl (local only, never committed).')
        parser.add_argument('--out', default=str(EXAMS_DIR / 'jee_main.yaml'))

    def handle(self, *args, **options):
        source = Path(options['source'])
        if not source.exists():
            raise CommandError(f'{source} not found.')
        try:
            tree, warnings = draft_jee_main_tree(read_rows(source))
            flat = flatten_tree(validate_exam_tree(tree))
        except (ValueError, TaxonomyError) as exc:
            raise CommandError(str(exc)) from exc
        out = Path(options['out'])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            HEADER + yaml.safe_dump(tree, sort_keys=False, allow_unicode=True, width=100),
            encoding='utf-8',
        )
        for warning in warnings:
            self.stderr.write(f'warning: grouped chapter has no questions in the data: {warning}')
        levels = {level: sum(1 for node in flat if node['level'] == level)
                  for level in ('subject', 'sub_subject', 'topic', 'subtopic')}
        out_of_syllabus = sum(1 for node in flat if node['level'] == 'topic' and not node['in_syllabus'])
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {out}: {levels} ({out_of_syllabus} topic(s) out of syllabus).'))
