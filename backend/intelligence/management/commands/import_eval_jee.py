"""Dev only: build a local JEE Lab tenant from the eval_jee dataset (D10, Track A).

    manage.py import_eval_jee --file ../data_dumps/jee_eval/eval_jee.jsonl --tenant lab-jee --limit 600

Refuses unless DEBUG is on, the tenant subdomain starts with "lab-" and the
database is local: the dataset has no licence and must never reach a shared
database. The dataset's subtopic labels are never stored (they live only in
gold files), so the tagger cannot see them.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.services.eval_jee import (
    TYPE_MAP, correct_ids, is_usable, out_of_syllabus_chapters, parse_options, read_rows,
    strip_html, stratified_sample, tree_key_index,
)
from intelligence.services.syllabus import instantiate_exam_tree
from intelligence.services.taxonomy import TaxonomyError, flatten_tree, load_exam_tree
from quiz.models import Question, QuestionOption

LOCAL_HOSTS = {'', 'localhost', '127.0.0.1', '::1'}
TAG_PREFIX = 'eval_jee:'


def database_is_local():
    database = connection.settings_dict
    return 'sqlite' in database.get('ENGINE', '') or (database.get('HOST') or '') in LOCAL_HOSTS


class Command(BaseCommand):
    help = 'Dev only: create a local JEE Lab tenant from the eval_jee dataset.'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='Path to the local eval_jee.jsonl.')
        parser.add_argument('--tenant', required=True, help='Lab tenant subdomain; must start with "lab-".')
        parser.add_argument('--limit', type=int, default=None, help='Stratified sample of the pool.')
        parser.add_argument('--seed', type=int, default=7)
        parser.add_argument('--exam', default='jee_main')

    def handle(self, *args, **options):
        subdomain = options['tenant']
        if not settings.DEBUG:
            raise CommandError('import_eval_jee is dev-only: DEBUG must be on.')
        if not subdomain.startswith('lab-'):
            raise CommandError('The lab tenant subdomain must start with "lab-".')
        if not database_is_local():
            raise CommandError('Refusing: the default database is not local.')
        try:
            tree = load_exam_tree(options['exam'])
        except TaxonomyError as exc:
            raise CommandError('; '.join(exc.errors)) from exc

        index = tree_key_index(tree)
        excluded = out_of_syllabus_chapters(tree)
        pool = [row for row in read_rows(options['file'])
                if is_usable(row, excluded) and (row['subject'], row['chapter']) in index]
        if options['limit']:
            pool = stratified_sample(pool, options['limit'], options['seed'])

        with transaction.atomic():
            tenant, _ = Tenant.objects.get_or_create(
                subdomain=subdomain, defaults={'name': 'JEE Lab', 'is_active': True})
            course, _ = Course.objects.get_or_create(
                code=f'{subdomain}-jee-main',
                defaults={'tenant': tenant, 'name': f'{tree["label"]} (Lab)', 'course_type': 'competitive'})
            if course.tenant_id != tenant.id:
                raise CommandError(f'Course {course.code} belongs to another tenant.')
            flat = flatten_tree(tree)
            subjects, topics = {}, {}
            for node in flat:
                if node['level'] == 'subject':
                    subjects[node['local_key']] = Subject.objects.get_or_create(
                        tenant=tenant, course=course, code=node['local_key'],
                        defaults={'name': node['label'], 'order': node['order']})[0]
            for node in flat:
                if node['level'] == 'topic' and node['in_syllabus']:
                    topics[node['key']] = Topic.objects.get_or_create(
                        tenant=tenant, subject=subjects[node['subject']], code=node['local_key'],
                        defaults={'name': node['label'], 'order': node['order']})[0]
            tree_summary = instantiate_exam_tree(course, tree['key'], subjects)

            existing = {
                tag for tags in Question.objects.filter(tenant=tenant).values_list('tags', flat=True)
                for tag in (tags or []) if isinstance(tag, str) and tag.startswith(TAG_PREFIX)
            }
            created = skipped = 0
            for row in pool:
                marker = f'{TAG_PREFIX}{row["question_id"]}'
                topic = topics.get(index[(row['subject'], row['chapter'])])
                if marker in existing or topic is None:
                    continue
                if self._create_question(tenant, course, topic, row, marker):
                    created += 1
                    existing.add(marker)
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'{tenant.name} ({subdomain}): {created} question(s) created, {skipped} skipped; '
            f'tree nodes created {tree_summary["created"]}, updated {tree_summary["updated"]}.'))
        self.stdout.write(f'Tenant id: {tenant.id}  Course id: {course.id}')

    def _create_question(self, tenant, course, topic, row, marker):
        question_type = TYPE_MAP[row['question_type']]
        options = parse_options(row)
        wanted = set(correct_ids(row))
        indices = [str(index) for index, option in enumerate(options) if option['id'] in wanted]
        numerical = None
        if question_type == 'numerical':
            raw = str(row.get('answer') or '').strip()
            try:
                numerical = Decimal(raw)
            except InvalidOperation:
                return False  # ranges / non-numeric answers are left out
            correct = raw
        elif question_type == 'mcq_multi':
            correct = ','.join(indices)
        else:
            correct = indices[0] if indices else ''
        question = Question.objects.create(
            tenant=tenant, subject=topic.subject, topic=topic, question_type=question_type,
            question_text=strip_html(row.get('question')), question_html=row.get('question') or '',
            correct_answer=correct, numerical_answer=numerical,
            explanation=row.get('explanation') or '', status='published',
            tags=['eval_jee', marker, row.get('paper_id') or ''],
        )
        question.courses.set([course])
        if question_type != 'numerical':
            for order, option in enumerate(options):
                QuestionOption.objects.create(
                    tenant=tenant, question=question, option_text=option['text'],
                    is_correct=option['id'] in wanted, order=order)
        return True
