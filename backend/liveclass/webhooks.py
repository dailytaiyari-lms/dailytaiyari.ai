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

Two forms of the URL exist. The tenant-scoped one (``.../zoom/webhook/<tenant
id>/``) is what the settings screen hands out; it pins every event and the
validation challenge to a single academy. The legacy unscoped one still accepts
events (resolved via the meeting id) so existing Zoom apps keep working.

Answering ``endpoint.url_validation`` means HMAC-ing a caller-supplied value
with the very token that signs real events, so it is fenced in three ways: the
plainToken must match Zoom's token shape (:func:`~liveclass.zoom.is_valid_plain_token`),
so it can never be a ``v0:<ts>:<body>`` signing payload; the unscoped URL only
answers while an admin has opened a short verification window; and the scoped
URL only ever uses that one tenant's token.
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
from .zoom import (
    is_valid_plain_token, verify_webhook_signature, webhook_validation_response,
)

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class ZoomWebhookView(APIView):
    """Receive Zoom event notifications. No auth, no tenant header."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, tenant_id=None):
        raw_body = request.body
        try:
            body = json.loads(raw_body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return Response({'detail': 'Invalid payload.'}, status=400)

        event = body.get('event') or ''
        payload = body.get('payload') or {}
        obj = payload.get('object') or {}

        if event == 'endpoint.url_validation':
            return self._validate(payload, obj, tenant_id)

        live_class = self._resolve_class(obj, tenant_id)
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
    def _validate(self, payload, obj, tenant_id=None):
        """Answer the URL-validation challenge.

        The response is ``HMAC(secret, plainToken)``, i.e. exactly the primitive
        that authenticates real events, so this is deliberately narrow:

        * ``plainToken`` must look like a Zoom challenge token, which makes it
          impossible to request the HMAC of a ``v0:<ts>:<body>`` signing payload
          and replay it as ``x-zm-signature``;
        * the tenant-scoped URL uses only that academy's token;
        * the legacy unscoped URL answers only while an admin has opened a
          verification window from the settings screen — outside of it we say no
          rather than trying every tenant's secret in turn.
        """
        from core.models import ZoomIntegration

        plain = (payload.get('plainToken') or obj.get('plainToken') or '')
        if not is_valid_plain_token(plain):
            logger.warning('Rejected Zoom URL validation with an unexpected plainToken.')
            return Response({'detail': 'Invalid plainToken.'}, status=400)

        qs = ZoomIntegration.objects.exclude(webhook_secret_token_encrypted='')
        if tenant_id:
            integration = qs.filter(tenant_id=tenant_id).first()
        else:
            integration = qs.filter(
                webhook_validation_until__gt=timezone.now()
            ).order_by('-webhook_validation_until').first()

        token = integration.webhook_secret_token if integration else ''
        if not token:
            return Response(
                {'detail': 'No Zoom secret token available for validation. Open '
                           'Settings → Integrations → Zoom and start verification, '
                           'or use the tenant-specific webhook URL shown there.'},
                status=400,
            )
        return Response(webhook_validation_response(token, plain), status=200)

    def _resolve_class(self, obj, tenant_id=None):
        meeting_id = str(obj.get('id') or '')
        if not meeting_id:
            return None
        qs = LiveClass.objects.select_related('tenant', 'course').filter(
            zoom_meeting_id=meeting_id
        )
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs.order_by('-created_at').first()

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
