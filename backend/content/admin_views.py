"""
Admin CRUD view for Content in the Content Builder.
Tenant-admin only, scoped via the subject's course tenant.
"""
import base64
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from core.permissions import IsCourseEditor
from exams.admin_views import TenantAdminModelViewSet
from .models import Content
from .admin_serializers import AdminContentSerializer
from .tasks import dispatch_video_optimization


class AdminImageUploadView(APIView):
    """
    Upload a single image and get back its stored URL.

    Used by the Course Builder's notes editor to insert pasted / dropped images
    inline. Accepts either a multipart ``image`` file or a JSON body with an
    ``image`` data URL. Returns ``{"url": "..."}``.
    """
    permission_classes = [IsCourseEditor]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get('image')
        if upload is None:
            data = request.data.get('image')
            if not isinstance(data, str) or not data.startswith('data:image'):
                return Response({'detail': 'No image provided.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                header, b64 = data.split(';base64,', 1)
                ext = header.split('/')[-1].split('+')[0] or 'png'
                if ext.lower() in ('jpg', 'jpeg'):
                    ext = 'jpg'
                upload = ContentFile(base64.b64decode(b64), name=f'{uuid.uuid4().hex}.{ext}')
            except (ValueError, TypeError, base64.binascii.Error):
                return Response({'detail': 'Invalid base64 image data.'}, status=status.HTTP_400_BAD_REQUEST)

        path = default_storage.save(f'content_images/{uuid.uuid4().hex}_{upload.name}', upload)
        return Response({'url': default_storage.url(path)}, status=status.HTTP_201_CREATED)


class AdminContentViewSet(TenantAdminModelViewSet):
    queryset = Content.objects.select_related('topic', 'subject').all()
    serializer_class = AdminContentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['topic', 'subject', 'content_type', 'difficulty', 'status', 'is_free']
    search_fields = ['title', 'description']
    ordering_fields = ['order', 'created_at', 'views_count', 'title']
    ordering = ['order', '-created_at']
    tenant_lookup = 'subject__course__tenant'
    course_lookup = 'subject__course'

    @action(detail=True, methods=['post'])
    def reprocess_video(self, request, pk=None):
        """Re-run the optimisation pipeline for an uploaded video.

        Optimisation normally runs once, on upload. That leaves two gaps this
        closes: videos uploaded before the pipeline existed, and uploads whose
        job never ran because the worker was down or ffmpeg was missing. Both
        leave a lecture that plays but cannot be seeked, with no way to retry
        from the builder.

        Safe to run on an already-good file: the task detects that cheaply and
        moves straight on to the quality ladder, so the same button also serves
        as a retry for failed HLS packaging.
        """
        content = self.get_object()

        if not content.video_file:
            return Response(
                {'detail': 'This content has no uploaded video to process.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not getattr(settings, 'VIDEO_OPTIMIZATION_ENABLED', True):
            return Response(
                {'detail': 'Video processing is disabled on this server.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Re-queueing mid-encode would have two workers writing the same row.
        if content.video_status in ('pending', 'processing') or content.hls_status == 'processing':
            return Response(
                {'detail': 'This video is already being processed.'},
                status=status.HTTP_409_CONFLICT,
            )

        Content.objects.filter(pk=content.pk).update(
            video_status='pending', video_progress=0,
        )

        if not dispatch_video_optimization(content.pk):
            # Tell the admin now rather than leaving a row stuck on "queued".
            Content.objects.filter(pk=content.pk).update(video_status='failed')
            return Response(
                {'detail': 'Could not reach the processing queue. '
                           'Check that the media worker is running.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        content.refresh_from_db()
        return Response(self.get_serializer(content).data)
