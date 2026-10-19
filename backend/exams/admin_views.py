"""
Admin CRUD views for the Course Content Builder.

All endpoints are restricted to tenant admins and scoped to the current tenant
via the Course relationship (child rows may have a null ``tenant`` in legacy data,
so we always scope through ``course``).
"""
from django.db.models import Max, OuterRef, Subquery
from rest_framework import viewsets, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend

from core.permissions import IsCourseEditor, resolve_course_id
from rest_framework.exceptions import PermissionDenied
from .models import Course, Subject, Topic, Chapter, ChapterTopic
from .admin_serializers import (
    AdminCourseSerializer, AdminSubjectSerializer,
    AdminChapterSerializer, AdminTopicSerializer,
)


class BuilderPagination(PageNumberPagination):
    """Larger pages for the content builder; client may override via page_size."""
    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 2000


class TenantAdminModelViewSet(viewsets.ModelViewSet):
    """Base CRUD viewset: editable by tenant admins and assigned instructors,
    tenant-scoped, searchable."""
    permission_classes = [IsCourseEditor]
    pagination_class = BuilderPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['order', 'name', 'created_at']
    ordering = ['order', 'name']

    # Lookup path from the model to the owning Course's tenant.
    tenant_lookup = 'tenant'
    # Lookup path from the model to the owning Course (for instructor scoping).
    # ``None`` means the model *is* a Course.
    course_lookup = None
    # FK that scopes ``order`` for auto-numbering new rows (e.g. 'course' for
    # subjects). ``None`` disables auto-numbering.
    order_scope_field = None

    def _tenant(self):
        return getattr(self.request, 'tenant', None)

    def _is_instructor(self):
        return getattr(self.request.user, 'role', None) == 'instructor'

    def _instructing_course_ids(self):
        return list(self.request.user.instructing_courses.values_list('id', flat=True))

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = self._tenant()
        if not tenant:
            return qs.none()
        qs = qs.filter(**{self.tenant_lookup: tenant})
        # Instructors only see courses they are assigned to.
        if self._is_instructor():
            ids = self._instructing_course_ids()
            if self.course_lookup is None:
                qs = qs.filter(id__in=ids)
            else:
                qs = qs.filter(**{f'{self.course_lookup}__in': ids})
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(tenant=self._tenant())
        # Guard: an instructor must not create content under a course they don't own.
        if self._is_instructor():
            course_id = resolve_course_id(obj, self.course_lookup)
            allowed = {str(i) for i in self._instructing_course_ids()}
            if course_id is None or str(course_id) not in allowed:
                obj.delete()
                raise PermissionDenied('You can only edit courses assigned to you.')
        self._assign_default_order(obj)

    def _assign_default_order(self, obj):
        """Append new rows to the end of their sibling list.

        Ordering is managed by drag & drop in the builder, so the client no
        longer sends ``order``; without this every new row would land at 0.
        """
        if self.order_scope_field is None:
            return
        if str(self.request.data.get('order', '')).strip() not in ('', 'None'):
            return
        scope_id = getattr(obj, f'{self.order_scope_field}_id', None)
        if scope_id is None:
            return
        last = (
            type(obj).objects
            .filter(**{f'{self.order_scope_field}_id': scope_id})
            .exclude(pk=obj.pk)
            .aggregate(m=Max('order'))['m']
        )
        obj.order = 0 if last is None else last + 1
        obj.save(update_fields=['order'])

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Persist a new ordering. Body: {"order": [id1, id2, ...]}."""
        ids = request.data.get('order', [])
        qs = self.get_queryset()
        lookup = {str(obj.id): obj for obj in qs.filter(id__in=ids)}
        updated = []
        for index, obj_id in enumerate(ids):
            obj = lookup.get(str(obj_id))
            if obj is not None:
                obj.order = index
                updated.append(obj)
        if updated:
            type(updated[0]).objects.bulk_update(updated, ['order'])
        return Response({'updated': len(updated)})


class AdminCourseViewSet(TenantAdminModelViewSet):
    queryset = Course.objects.all().order_by('name')
    serializer_class = AdminCourseSerializer
    filterset_fields = ['course_type', 'status', 'is_featured']
    tenant_lookup = 'tenant'
    course_lookup = None  # the object is itself a Course
    ordering = ['name']

    def create(self, request, *args, **kwargs):
        # Only admins create courses; instructors edit assigned ones.
        if request.user.role != 'admin':
            raise PermissionDenied('Only admins can create courses.')
        tenant = self._tenant()
        if tenant is not None and not tenant.can_add('courses'):
            return Response(
                {'detail': 'This academy has reached its course limit. '
                           'Please contact the DailyTaiyari team to add more.',
                 'code': 'quota_exceeded'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            raise PermissionDenied('Only admins can delete courses.')
        return super().destroy(request, *args, **kwargs)

    def perform_update(self, serializer):
        # Instructors may edit course details but never the instructor roster.
        if self.request.user.role != 'admin':
            serializer.validated_data.pop('instructors', None)
        serializer.save()

    @action(detail=True, methods=['post'])
    def copy(self, request, pk=None):
        """Deep-clone this course (whole authored graph) into a new, independent
        course under the same tenant. Body: {"name": "New course name"}. Admin only."""
        if request.user.role != 'admin':
            raise PermissionDenied('Only admins can copy courses.')
        tenant = self._tenant()
        if tenant is not None and not tenant.can_add('courses'):
            return Response(
                {'detail': 'This academy has reached its course limit. '
                           'Please contact the DailyTaiyari team to add more.',
                 'code': 'quota_exceeded'},
                status=status.HTTP_403_FORBIDDEN,
            )
        source = self.get_object()
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response(
                {'name': ['A name for the copied course is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from .course_copy import clone_course
        new_course = clone_course(source, name)
        serializer = self.get_serializer(new_course)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def instructors(self, request):
        """List tenant users with the instructor role (for assignment). Admin only."""
        if request.user.role != 'admin':
            raise PermissionDenied('Only admins can view instructors.')
        from users.models import User
        users = User.objects.filter(tenant=self._tenant(), role='instructor').order_by('first_name', 'email')
        return Response([
            {'id': str(u.id), 'name': u.full_name or u.email, 'email': u.email}
            for u in users
        ])


class AdminSubjectViewSet(TenantAdminModelViewSet):
    queryset = Subject.objects.select_related('course').all()
    serializer_class = AdminSubjectSerializer
    filterset_fields = ['course']
    tenant_lookup = 'course__tenant'
    course_lookup = 'course'
    order_scope_field = 'course'


class AdminChapterViewSet(TenantAdminModelViewSet):
    queryset = Chapter.objects.select_related('subject').all()
    serializer_class = AdminChapterSerializer
    filterset_fields = ['subject', 'grade']
    tenant_lookup = 'subject__course__tenant'
    course_lookup = 'subject__course'
    order_scope_field = 'subject'


class AdminTopicViewSet(TenantAdminModelViewSet):
    queryset = Topic.objects.select_related('subject').prefetch_related('chapter_topics').all()
    serializer_class = AdminTopicSerializer
    filterset_fields = ['subject', 'difficulty', 'importance', 'parent_topic']
    tenant_lookup = 'subject__course__tenant'
    course_lookup = 'subject__course'
    order_scope_field = 'subject'

    def get_queryset(self):
        qs = super().get_queryset()
        chapter_id = self.request.query_params.get('chapter')
        if chapter_id:
            link_order = ChapterTopic.objects.filter(
                chapter_id=chapter_id, topic_id=OuterRef('pk')
            ).values('order')[:1]
            # Inside a chapter the sequence students see is the ChapterTopic
            # order, so the builder must list topics the same way.
            qs = qs.filter(chapter_topics__chapter_id=chapter_id).annotate(
                chapter_order=Subquery(link_order)
            )
            self.ordering = ['chapter_order', 'order', 'name']
        return qs

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Reorder topics. With a ``chapter`` in the body the ChapterTopic
        links are resequenced (that is what students follow); otherwise the
        subject-level ``Topic.order`` is used."""
        chapter_id = request.data.get('chapter')
        if not chapter_id:
            return super().reorder(request)

        chapter = Chapter.objects.filter(
            id=chapter_id, subject__course__tenant=self._tenant()
        ).first()
        if chapter is None:
            return Response({'detail': 'Chapter not found.'}, status=status.HTTP_404_NOT_FOUND)
        if self._is_instructor() and chapter.subject.course_id not in self._instructing_course_ids():
            raise PermissionDenied('You can only edit courses assigned to you.')

        ids = request.data.get('order', [])
        links = {
            str(ct.topic_id): ct
            for ct in ChapterTopic.objects.filter(chapter=chapter, topic_id__in=ids)
        }
        updated = []
        for index, topic_id in enumerate(ids):
            ct = links.get(str(topic_id))
            if ct is not None:
                ct.order = index
                updated.append(ct)
        if updated:
            ChapterTopic.objects.bulk_update(updated, ['order'])
        return Response({'updated': len(updated)})

    def perform_destroy(self, instance):
        ChapterTopic.objects.filter(topic=instance).delete()
        instance.delete()
