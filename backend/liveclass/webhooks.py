"""Zoom webhook receiver.

Mounted at ``/api/v1/live-classes/zoom/webhook/`` and exempted from the tenant
header requirement — Zoom cannot send one, so the tenant is resolved from the
meeting id in the payload.

Handled events:
  * ``endpoint.url_validation``       — Zoom's setup challenge.
  * ``meeting.started`` / ``ended``   — records the real occurrence window and
    the occurrence UUID needed by the report API.
  * ``meeting.participant_joined``    — live presence.
  * ``meeting.participant_left``      — accumulates time in call.

Signature verification uses the tenant's Zoom Secret Token. Because the tenant
is only known *after* parsing the payload, we look up the meeting first and then
verify against that tenant's token; unknown meetings are acked (200) so Zoom
stops retrying rather than being told something went wrong.
"""
import json
import logging

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LiveClass
from .services import (
    handle_participant_joined, handle_participant_left, sync_attendance_from_zoom,
)
from .zoom import verify_webhook_signature, webhook_validation_response

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class ZoomWebhookView(APIView):
    """Receive Zoom event notifications. No auth, no tenant header."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_body = request.body
        try:
            body = json.loads(raw_body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return Response({'detail': 'Invalid payload.'}, status=400)

        event = body.get('event') or ''
        payload = body.get('payload') or {}
        obj = payload.get('object') or {}

        if event == 'endpoint.url_validation':
            return self._validate(payload, obj)

        live_class = self._resolve_class(obj)
        if live_class is None:
            # Unknown meeting (e.g. one created outside DailyTaiyari) — ack.
            return Response({'detail': 'Ignored.'}, status=200)

        integration = getattr(live_class.tenant, 'zoom', None)
        secret = getattr(integration, 'webhook_secret_token', '') if integration else ''
        if not verify_webhook_signature(secret, request.headers, raw_body):
            logger.warning('Rejected Zoom webhook with a bad signature (event=%s)', event)
            return Response({'detail': 'Invalid signature.'}, status=401)

        try:
            self._dispatch(event, live_class, obj)
        except Exception:
            # Never 500 at Zoom: it would retry the same broken event for hours.
            logger.exception('Failed to handle Zoom webhook %s for class %s',
                             event, live_class.pk)
        return Response({'detail': 'ok'}, status=200)

    # -------------------------------------------------------------- helpers
    def _validate(self, payload, obj):
        """Answer the URL-validation challenge.

        Zoom does not identify the tenant here, so we try every configured
        Secret Token: whichever tenant owns this endpoint will match on Zoom's
        side, and a wrong hash is simply rejected.
        """
        from core.models import ZoomIntegration
        plain = (payload.get('plainToken') or obj.get('plainToken') or '')
        for integration in ZoomIntegration.objects.exclude(
            webhook_secret_token_encrypted=''
        ):
            token = integration.webhook_secret_token
            if token:
                return Response(webhook_validation_response(token, plain), status=200)
        return Response({'detail': 'No Zoom secret token configured.'}, status=400)

    def _resolve_class(self, obj):
        meeting_id = str(obj.get('id') or '')
        if not meeting_id:
            return None
        return LiveClass.objects.select_related('tenant', 'course').filter(
            zoom_meeting_id=meeting_id
        ).order_by('-created_at').first()

    def _dispatch(self, event, live_class, obj):
        if event == 'meeting.started':
            live_class.zoom_meeting_uuid = obj.get('uuid') or live_class.zoom_meeting_uuid
            live_class.zoom_started_at = timezone.now()
            live_class.save(update_fields=[
                'zoom_meeting_uuid', 'zoom_started_at', 'updated_at',
            ])
        elif event == 'meeting.ended':
            live_class.zoom_meeting_uuid = obj.get('uuid') or live_class.zoom_meeting_uuid
            live_class.zoom_ended_at = timezone.now()
            live_class.save(update_fields=[
                'zoom_meeting_uuid', 'zoom_ended_at', 'updated_at',
            ])
            # Zoom's report is not ready the instant a meeting ends, so this
            # first pass may fail; the admin's "Sync" button and the scheduled
            # task both retry. Failure is recorded on the class, not raised.
            sync_attendance_from_zoom(live_class)
        elif event == 'meeting.participant_joined':
            handle_participant_joined(live_class, obj)
        elif event == 'meeting.participant_left':
            handle_participant_left(live_class, obj)
