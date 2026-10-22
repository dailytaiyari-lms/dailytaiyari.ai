"""Score tagging models on a gold file (spec §6.2). No DB writes except usage metering.

    manage.py evaluate_tagger --gold ../data_dumps/jee_eval/gold_location.jsonl \
        --models gpt-6-luna --mode anchored --exam jee_main --out ../data_dumps/jee_eval/report.json
    manage.py evaluate_tagger --gold ../data_dumps/trackb/gold_dsa.jsonl --models gpt-6-luna \
        --mode anchored --course <id>
"""
import json
import uuid
from itertools import groupby
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from coursegen.generation import GenerationError
from exams.models import Course, Subject
from intelligence.services.eval_jee import read_rows
from intelligence.services.llm import platform_call
from intelligence.services.syllabus import context_from_tree, tagging_context
from intelligence.services.tag_eval import percentile, render_markdown, score
from intelligence.services.tagging_v2 import tag_payloads
from intelligence.services.taxonomy import TaxonomyError, load_exam_tree, load_tags

PAYLOAD_FIELDS = ('id', 'type', 'question', 'options', 'answer')


class Command(BaseCommand):
    help = 'Evaluate tagging models against a gold JSONL file.'

    def add_arguments(self, parser):
        parser.add_argument('--gold', required=True)
        parser.add_argument('--models', required=True, help='Comma-separated platform model names.')
        parser.add_argument('--mode', choices=['anchored', 'blind'], default='anchored')
        tree = parser.add_mutually_exclusive_group(required=True)
        tree.add_argument('--exam', help='Exam tree key (contexts from YAML).')
        tree.add_argument('--course', help='Course id (contexts from its syllabus tree).')
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--out', default=None, help='Write the JSON report here (under data_dumps/).')

    def handle(self, *args, **options):
        out = None
        if options['out']:
            out = Path(options['out']).resolve()
            if 'data_dumps' not in out.parts:
                raise CommandError('--out must be under data_dumps/.')
        rows = read_rows(options['gold'])[:options['limit'] or None]
        if not rows:
            raise CommandError('The gold file is empty.')
        contexts, tenant = self._contexts(options, {row['subject'] for row in rows})
        rows.sort(key=lambda row: str(row['subject']))
        report = {'gold': options['gold'], 'mode': options['mode'], 'models': {}}
        items = {}
        for model in [m.strip() for m in options['models'].split(',') if m.strip()]:
            try:
                call = platform_call(model, tenant)
            except GenerationError as exc:
                raise CommandError(str(exc)) from exc
            results = []
            for subject, group in groupby(rows, key=lambda row: str(row['subject'])):
                payloads = [
                    {**{field: row.get(field) for field in PAYLOAD_FIELDS},
                     'topic_hint': row.get('topic_hint', '') if options['mode'] == 'anchored' else ''}
                    for row in group
                ]
                results.extend(tag_payloads(contexts[subject], payloads, call=call))
            metrics = score(rows, results, mode=options['mode'])
            usage = call.meter.usage
            report['models'][model] = {
                **metrics,
                'tokens_per_question': round(usage.total_tokens / len(rows), 1),
                'latency_p50_ms': percentile(call.latencies_ms, 50),
                'latency_p95_ms': percentile(call.latencies_ms, 95),
                'cost_per_1000_usd': round(call.cost_usd() / len(rows) * 1000, 4),
                'calls': len(call.latencies_ms),
            }
            items[model] = [
                {'id': r.id, 'topic': r.topic_key, 'primary': r.primary_subtopic,
                 'secondary': r.secondary_subtopics, 'thinking_level': r.thinking_level,
                 'skills': [{'key': s['key'], 'role': s['role']} for s in r.skills],
                 'special_format': r.special_format, 'difficulty': r.difficulty,
                 'est_solve_seconds': r.est_solve_seconds, 'confidence': r.confidence,
                 'review_reasons': r.review_reasons, 'proposed_subtopic': r.proposed_subtopic,
                 'error': r.error}
                for r in results
            ]
        self.stdout.write(render_markdown(report))
        if out:
            out.write_text(json.dumps({'report': report, 'items': items}, ensure_ascii=False, indent=1),
                           encoding='utf-8')
            self.stdout.write(f'Report written to {out}')

    def _contexts(self, options, subjects):
        if options['exam']:
            try:
                tags, _ = load_tags()
                tree = load_exam_tree(options['exam'])
                return {key: context_from_tree(tree, key, tags) for key in subjects}, None
            except TaxonomyError as exc:
                raise CommandError('; '.join(exc.errors)) from exc
        try:
            course = Course.objects.filter(id=uuid.UUID(options['course'])).first()
        except ValueError as exc:
            raise CommandError('--course is not a valid id.') from exc
        if course is None:
            raise CommandError('Course not found.')
        by_id = {str(s.id): s for s in Subject.objects.filter(course=course, id__in=list(subjects))}
        missing = sorted(set(subjects) - set(by_id))
        if missing:
            raise CommandError(f'Gold subjects not in this course: {", ".join(missing)}')
        return {sid: tagging_context(subject) for sid, subject in by_id.items()}, course.tenant
