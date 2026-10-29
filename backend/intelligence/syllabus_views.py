"""Syllabus & tagging tools (spec 2B §5) at
/api/v1/tenant-admin/intelligence/syllabus/.

Every view needs the ``syllabus_tools`` switch. Course, node, job and
tagging-scoped calls also need ``can_manage_course``: admins manage every
course in the tenant, faculty their assigned courses.
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course

from .access import can_manage_course, teachable_course_ids
from .admin_views import IsTenantAdminOrInstructor
from .models import CourseSyllabus, ItemTagging, SyllabusNode, TaggingRun, TreeBuildJob
from .services.llm import budget_status
from .services.tree_editor import EditError, as_uuid

JOB_HISTORY = 10


class SyllabusToolsPermission(permissions.BasePermission):
    message = 'Syllabus & tagging tools are not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('syllabus_tools'))


SYLLABUS = [permissions.IsAuthenticated, IsTenantAdminOrInstructor, SyllabusToolsPermission]


def _error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'error': message}, status=code)


def _not_found(what):
    return _error(f'{what} not found.', status.HTTP_404_NOT_FOUND)


def _forbidden():
    return _error('Not in your courses.', status.HTTP_403_FORBIDDEN)


def _course(request, course_id):
    """(course, None) or (None, error response)."""
    course = Course.objects.filter(id=course_id, tenant=request.tenant).first()
    if course is None:
        return None, _not_found('Course')
    if not can_manage_course(request.user, course):
        return None, _forbidden()
    return course, None


def _node(request, node_id):
    node = (SyllabusNode.objects.filter(id=node_id, tenant=request.tenant)
            .select_related('subject__course', 'parent').first())
    if node is None:
        return None, _not_found('Node')
    if not can_manage_course(request.user, node.subject.course):
        return None, _forbidden()
    return node, None


def _jobs(course):
    rows = (list(TreeBuildJob.objects.filter(course=course).select_related('started_by')[:JOB_HISTORY])
            + list(TaggingRun.objects.filter(course=course).select_related('started_by')[:JOB_HISTORY]))
    rows.sort(key=lambda job: job.created_at, reverse=True)
    return [job.payload() for job in rows[:JOB_HISTORY]]


def _start(model, course, request, task, options=None):
    """Create a queued job and enqueue it. 409 when one is already active."""
    from .api import enqueue

    active = model.objects.filter(course=course, status__in=model.ACTIVE_STATUSES).first()
    if active is not None:
        return Response({'error': 'A run is already in progress.', 'job': active.payload()},
                        status=status.HTTP_409_CONFLICT)
    job = model.objects.create(tenant=course.tenant, course=course, started_by=request.user,
                               options=options or {})
    try:
        enqueue(task, str(job.id))
    except Exception:  # noqa: BLE001 — broker down: say so, don't leave it queued forever
        job.status = model.STATUS_FAILED
        job.error = 'Could not queue the run. Try again in a minute.'
        job.save(update_fields=['status', 'error', 'updated_at'])
    job.refresh_from_db()
    return Response(job.payload(), status=status.HTTP_202_ACCEPTED)


def _packs_option(data):
    packs = data.get('packs') if isinstance(data, dict) else None
    if packs is None:
        return None
    return [key for key in packs if isinstance(key, str)] if isinstance(packs, list) else None


def _has_built_tree(course):
    return SyllabusNode.objects.filter(
        subject__course=course, source__in=('course', 'llm_proposed', 'manual'),
    ).exclude(status='archived').exists()


def _exam_course(course):
    record = CourseSyllabus.objects.filter(course=course).first()
    return record.exam_tree if record and record.exam_tree else ''


class CourseTreeView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, course_id):
        from .services.tree_editor import tree_payload

        course, error = _course(request, course_id)
        if error:
            return error
        return Response({**tree_payload(course), 'jobs': _jobs(course),
                         'budget': budget_status(request.tenant)})


class TreeEstimateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.course_tree import estimate_build

        course, error = _course(request, course_id)
        if error:
            return error
        return Response({**estimate_build(course, packs=_packs_option(request.data)),
                         'budget': budget_status(request.tenant)})


class TreeBuildView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .tasks import run_tree_build

        course, error = _course(request, course_id)
        if error:
            return error
        exam = _exam_course(course)
        if exam:
            return _error(f'This course uses the {exam} exam syllabus; edit that tree instead.')
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        packs = _packs_option(request.data)
        return _start(TreeBuildJob, course, request, run_tree_build,
                      {'packs': packs} if packs is not None else {})


class ExamMappingView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.syllabus import instantiate_exam_tree
        from .services.taxonomy import TaxonomyError
        from .services.tree_editor import tree_payload

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        if _has_built_tree(course) and not _exam_course(course):
            return _error('This course already has its own built tree.')
        mapping = data.get('subjects')
        if not isinstance(data.get('exam'), str) or not isinstance(mapping, dict) or not mapping:
            return _error('Pick an exam tree and map at least one subject.')
        subjects = {str(s.id): s for s in course.subjects.all()}
        subject_map = {}
        for subject_id, tree_key in mapping.items():
            if str(subject_id) not in subjects or not isinstance(tree_key, str) or not tree_key:
                return _error('Map only this course\'s subjects, each to one tree subject.')
            if tree_key in subject_map:
                return _error('Each tree subject can be mapped once.')
            subject_map[tree_key] = subjects[str(subject_id)]
        try:
            summary = instantiate_exam_tree(course, data['exam'], subject_map)
        except TaxonomyError as exc:
            return _error('; '.join(exc.args[0]) if exc.args and isinstance(exc.args[0], list) else str(exc))
        return Response({'summary': summary, 'tree': tree_payload(course)})


def _node_out(node, warnings=None):
    return {'id': str(node.id), 'key': node.key, 'level': node.level, 'name': node.name,
            'status': node.status, 'weightage': node.weightage,
            'parent': str(node.parent_id) if node.parent_id else None,
            'warnings': warnings or []}


class NodeCreateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.tree_editor import add_node

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        subject_id = as_uuid(data.get('subject'))
        subject = course.subjects.filter(id=subject_id).first() if subject_id else None
        if subject is None:
            return _error('Pick a subject of this course.')
        parent = None
        if data.get('parent'):
            parent_id = as_uuid(data['parent'])
            parent = (SyllabusNode.objects.filter(id=parent_id, subject=subject).first()
                      if parent_id else None)
            if parent is None:
                return _error('That parent is not in this subject.')
        try:
            node = add_node(subject, level=data.get('level'), name=data.get('name'),
                            parent=parent, description=data.get('description', ''))
        except EditError as exc:
            return _error(str(exc))
        return Response(_node_out(node), status=status.HTTP_201_CREATED)


class NodeDetailView(APIView):
    permission_classes = SYLLABUS

    def patch(self, request, node_id):
        from .services.tree_editor import update_node

        node, error = _node(request, node_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        try:
            warnings = update_node(node, data)
        except EditError as exc:
            return _error(str(exc))
        return Response(_node_out(node, warnings))


class NodeMergeView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, node_id):
        from .api import enqueue
        from .services.tree_editor import merge_nodes
        from .tasks import recompute_concept_states

        node, error = _node(request, node_id)
        if error:
            return error
        target_id = as_uuid(request.data.get('into')) if isinstance(request.data, dict) else None
        target = SyllabusNode.objects.filter(id=target_id, subject=node.subject).first() if target_id else None
        if target is None:
            return _error('Pick a subtopic of this subject to merge into.')
        try:
            summary = merge_nodes(node, target)
        except EditError as exc:
            return _error(str(exc))
        try:
            enqueue(recompute_concept_states, summary['concept_id'])
        except Exception:  # noqa: BLE001 — the nightly refresh re-decays states anyway
            pass
        return Response(summary)


class SkillPacksView(APIView):
    permission_classes = SYLLABUS

    def patch(self, request, course_id):
        from .services.tree_editor import set_skill_packs

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        try:
            packs = set_skill_packs(course, data.get('packs'))
        except EditError as exc:
            return _error(str(exc))
        return Response({'skill_packs': packs})


def _treed_subject_ids(course):
    return set(SyllabusNode.objects.filter(
        subject__course=course, level='topic', status='active').values_list('subject_id', flat=True))


class TaggingEstimateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.tagging_sweep import estimate_tagging

        course, error = _course(request, course_id)
        if error:
            return error
        subject_ids = _treed_subject_ids(course)
        estimate = (estimate_tagging(request.tenant, subject_ids) if subject_ids
                    else {'questions': 0, 'approx_tokens': 0})
        return Response({**estimate, 'subjects_with_tree': len(subject_ids),
                         'budget': budget_status(request.tenant)})


class TaggingRunStartView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.taxonomy import current_release
        from .tasks import run_tagging_run

        course, error = _course(request, course_id)
        if error:
            return error
        if not _treed_subject_ids(course):
            return _error('Build or map a syllabus tree for this course first.')
        if current_release() is None:
            return _error('No tag vocabulary is loaded. Ask an admin to run manage.py sync_taxonomy.')
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        return _start(TaggingRun, course, request, run_tagging_run)


class JobDetailView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, job_id):
        job = (TreeBuildJob.objects.filter(id=job_id, tenant=request.tenant).select_related('course').first()
               or TaggingRun.objects.filter(id=job_id, tenant=request.tenant).select_related('course').first())
        if job is None:
            return _not_found('Job')
        if not can_manage_course(request.user, job.course):
            return _forbidden()
        return Response(job.payload())


REVIEW_PAGE = 25


def _scope_q(user):
    """ItemTaggings whose item belongs to one of the user's courses."""
    from django.db.models import Q

    ids = teachable_course_ids(user)
    return Q(question__subject__course_id__in=ids) | Q(mock_item__subject__course_id__in=ids)


def _tagging(request, tagging_id):
    from .services.tag_review import course_of

    tagging = (ItemTagging.objects.filter(id=tagging_id, tenant=request.tenant)
               .select_related('question__subject__course', 'question__topic',
                               'mock_item__subject__course', 'mock_item__topic', 'primary_node__parent')
               .first())
    if tagging is None:
        return None, _not_found('Tagging')
    course = course_of(tagging)
    if course is None or not can_manage_course(request.user, course):
        return None, _forbidden()
    return tagging, None


def _enqueue_retag(kind, item_id):
    from .api import enqueue
    from .tasks import retag_item

    enqueue(retag_item, kind, item_id)


class ReviewListView(APIView):
    permission_classes = SYLLABUS

    def get(self, request):
        from django.db.models import Q

        from .services.tag_review import REVIEW_REASONS, row_payload

        rows = (ItemTagging.objects.filter(tenant=request.tenant, review_status='needs_review')
                .filter(_scope_q(request.user)))
        params = request.query_params
        course_id, topic_id = as_uuid(params.get('course')), as_uuid(params.get('topic'))
        if (params.get('course') and not course_id) or (params.get('topic') and not topic_id):
            return _error('Unknown course or topic.')
        if course_id:
            rows = rows.filter(Q(question__subject__course_id=course_id)
                               | Q(mock_item__subject__course_id=course_id))
        if topic_id:
            rows = rows.filter(Q(question__topic_id=topic_id) | Q(mock_item__topic_id=topic_id))
        if params.get('reason') in REVIEW_REASONS:
            rows = rows.filter(review_reasons__icontains=f'"{params["reason"]}"')
        rows = rows.distinct().order_by('confidence', 'created_at')
        total = rows.count()
        pages = max(1, -(-total // REVIEW_PAGE))
        try:
            page = min(pages, max(1, int(params.get('page', 1))))
        except (TypeError, ValueError):
            page = 1
        chunk = rows.select_related(
            'question__topic', 'mock_item__topic', 'primary_node__parent',
        )[(page - 1) * REVIEW_PAGE:page * REVIEW_PAGE]
        return Response({'page': page, 'pages': pages, 'total': total,
                         'results': [row_payload(tagging) for tagging in chunk]})


class ReviewAcceptView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import accept, row_payload

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        return Response(row_payload(accept(tagging)))


class ReviewBulkAcceptView(APIView):
    permission_classes = SYLLABUS

    def post(self, request):
        from .services.tag_review import bulk_accept

        ids = request.data.get('ids') if isinstance(request.data, dict) else None
        if not isinstance(ids, list) or not ids:
            return _error('Pick at least one row.')
        clean = [value for value in (as_uuid(raw) for raw in ids) if value][:REVIEW_PAGE * 4]
        rows = ItemTagging.objects.filter(tenant=request.tenant, id__in=clean).filter(_scope_q(request.user))
        return Response({'accepted': bulk_accept(rows)})


class ReviewDetailView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, tagging_id):
        from .services.tag_review import edit_choices, row_payload, subject_of

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        subject = subject_of(tagging)
        return Response({'row': row_payload(tagging),
                         'choices': edit_choices(subject) if subject else None})

    def put(self, request, tagging_id):
        from .services.tag_review import ReviewError, row_payload, save_manual

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        try:
            save_manual(tagging, request.data)
        except ReviewError as exc:
            return _error(str(exc))
        tagging.refresh_from_db()
        return Response(row_payload(tagging))


class ReviewRetagView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import mark_for_retag

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        item = mark_for_retag(tagging)
        try:
            _enqueue_retag('bank' if tagging.question_id else 'item', str(item.id))
        except Exception:  # noqa: BLE001 — still stale: the weekly sweep picks it up
            return Response({'queued': False, 'reason': 'queue_unavailable'})
        return Response({'queued': True})


class ReviewAddToTreeView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import ReviewError, add_to_tree, row_payload

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        topic = None
        topic_id = as_uuid(request.data.get('topic')) if isinstance(request.data, dict) else None
        if topic_id:
            topic = SyllabusNode.objects.filter(id=topic_id, tenant=request.tenant, level='topic').first()
            if topic is None:
                return _error('That topic is not in the tree.')
        try:
            node = add_to_tree(tagging, topic)
        except ReviewError as exc:
            return _error(str(exc))
        tagging.refresh_from_db()
        return Response({'node': _node_out(node), 'row': row_payload(tagging)})


class ItemTagsView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, kind, item_id):
        from quiz.models import MockTestItem, Question

        from .services.tag_review import row_payload
        from .services.tagging_sweep import _mock_item_subject

        model = {'bank': Question, 'item': MockTestItem}.get(kind)
        item = model.objects.filter(id=item_id, tenant=request.tenant).first() if model else None
        if item is None:
            return _not_found('Question')
        subject = item.subject if kind == 'bank' else _mock_item_subject(item)
        if subject is None or not can_manage_course(request.user, subject.course):
            return _forbidden()
        tagging = getattr(item, 'tagging', None)
        return Response({'tagging': row_payload(tagging) if tagging else None})
