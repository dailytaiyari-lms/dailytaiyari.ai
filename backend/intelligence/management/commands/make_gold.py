"""Write a gold JSONL for evaluate_tagger (spec §6.1). Output must be under data_dumps/.

    manage.py make_gold --eval-jee ../data_dumps/jee_eval/eval_jee.jsonl --out ../data_dumps/jee_eval/gold_location.jsonl --n 300
    manage.py make_gold --course <id> --out ../data_dumps/trackb/gold_<name>.jsonl --n 30

Track A rows carry gold topic + subtopic from the dataset's human labels.
Track B rows carry only the gold topic (the course Topic the question sits
in); fill subtopic / thinking_level / skills / difficulty by hand afterwards.
"""
import json
import random
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from exams.models import Course
from intelligence.models import SyllabusNode
from intelligence.services.eval_jee import (
    is_usable, out_of_syllabus_chapters, read_rows, row_to_payload, stratified_sample, tree_key_index,
)
from intelligence.services.taxonomy import TaxonomyError, load_exam_tree
from intelligence.services.tagging_sweep import item_payload


def _checked_out_path(raw):
    path = Path(raw).resolve()
    if 'data_dumps' not in path.parts:
        raise CommandError('Gold files hold licensed or production text: --out must be under data_dumps/.')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Command(BaseCommand):
    help = 'Write a gold JSONL file for evaluate_tagger (from eval_jee, or from a course).'

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--eval-jee', dest='eval_jee', help='Path to the local eval_jee.jsonl.')
        source.add_argument('--course', help='Course id (Track B).')
        parser.add_argument('--out', required=True)
        parser.add_argument('--n', type=int, default=300)
        parser.add_argument('--seed', type=int, default=7)
        parser.add_argument('--exam', default='jee_main')

    def handle(self, *args, **options):
        out = _checked_out_path(options['out'])
        rows = self._from_eval_jee(options) if options['eval_jee'] else self._from_course(options)
        with open(out, 'w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.stdout.write(self.style.SUCCESS(f'Wrote {len(rows)} gold row(s) to {out}'))

    def _from_eval_jee(self, options):
        try:
            tree = load_exam_tree(options['exam'])
        except TaxonomyError as exc:
            raise CommandError('; '.join(exc.errors)) from exc
        index = tree_key_index(tree)
        excluded = out_of_syllabus_chapters(tree)
        pool = [
            row for row in read_rows(options['eval_jee'])
            if is_usable(row, excluded) and (row['subject'], row['chapter'], row['topic']) in index
        ]
        gold = []
        sampled = stratified_sample(pool, options['n'], options['seed'])
        random.Random(options['seed']).shuffle(sampled)
        for row in sampled:
            topic_key = index[(row['subject'], row['chapter'])]
            gold.append({
                **row_to_payload(row),
                'subject': row['subject'],
                'topic_hint': topic_key,
                'gold': {'topic': topic_key, 'subtopic': index[(row['subject'], row['chapter'], row['topic'])]},
                'source': {'paper_id': row.get('paper_id', '')},
            })
        return gold

    def _from_course(self, options):
        from quiz.models import Question

        try:
            course = Course.objects.filter(id=uuid.UUID(options['course'])).first()
        except ValueError as exc:
            raise CommandError('--course is not a valid id.') from exc
        if course is None:
            raise CommandError('Course not found.')
        topic_keys = dict(
            SyllabusNode.objects.filter(subject__course=course, level='topic', status='active',
                                        course_topic__isnull=False)
            .values_list('course_topic_id', 'key')
        )
        if not topic_keys:
            raise CommandError('This course has no syllabus tree yet — run build_course_tree first.')
        questions = {
            str(q.id): q for q in Question.objects.filter(subject__course=course, topic_id__in=list(topic_keys))
            .exclude(status='archived').select_related('subject', 'topic')
        }
        pool = [{'question_id': qid, 'subject': str(q.subject_id), 'chapter': str(q.topic_id)}
                for qid, q in questions.items()]
        gold = []
        sampled = stratified_sample(pool, options['n'], options['seed'])
        random.Random(options['seed']).shuffle(sampled)
        for picked in sampled:
            question = questions[picked['question_id']]
            topic_key = topic_keys[question.topic_id]
            gold.append({
                **item_payload(question),
                'subject': str(question.subject_id),
                'topic_hint': topic_key,
                'gold': {'topic': topic_key},
                'source': {'course': str(course.id), 'topic': question.topic.name},
            })
        return gold
