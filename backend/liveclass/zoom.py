"""Zoom REST API client (Server-to-Server OAuth) + webhook helpers.

A thin ``requests`` wrapper — no Zoom SDK — built from a tenant's
:class:`core.models.ZoomIntegration`:

    client = ZoomClient(tenant.zoom)
    meeting = client.create_meeting(topic=..., start_time=..., duration=...)
    reg     = client.add_registrant(meeting_id, email, first_name, last_name)
    parts   = client.get_participants(meeting_id)

Access tokens are short-lived (1h); we cache them in Django's cache keyed by the
integration id so concurrent workers share one token instead of hammering Zoom's
token endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

import requests
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEOUT = 20
OAUTH_URL = 'https://zoom.us/oauth/token'
API_BASE = 'https://api.zoom.us/v2'
# Refresh a little before Zoom's 3600s expiry so a request never races the edge.
TOKEN_SKEW_SECONDS = 120


class ZoomError(Exception):
    """Raised when a Zoom API call fails.

    ``status`` carries the HTTP status when there was a response, so callers can
    distinguish "plan does not include this" (400/403) from "not found" (404).
    """

    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class ZoomClient:
    def __init__(self, integration):
        self.integration = integration
        self.account_id = integration.account_id
        self.client_id = integration.client_id
        self.client_secret = integration.client_secret

    # ------------------------------------------------------------------ auth
    @property
    def _cache_key(self):
        return f'zoom:token:{self.integration.pk}'

    def _fetch_token(self):
        basic = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode()
        ).decode()
        try:
            resp = requests.post(
                OAUTH_URL,
                params={
                    'grant_type': 'account_credentials',
                    'account_id': self.account_id,
                },
                headers={'Authorization': f'Basic {basic}'},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZoomError(f'Could not reach Zoom: {exc}') from exc
        if resp.status_code != 200:
            raise ZoomError(
                _error_message(resp, 'Zoom rejected these credentials'),
                status=resp.status_code,
            )
        data = resp.json()
        token = data.get('access_token')
        if not token:
            raise ZoomError('Zoom did not return an access token.')
        ttl = int(data.get('expires_in') or 3600) - TOKEN_SKEW_SECONDS
        cache.set(self._cache_key, token, max(ttl, 60))
        return token

    def access_token(self, force_refresh=False):
        if not self.integration.is_configured:
            raise ZoomError('Zoom is not fully configured for this academy.')
        if not force_refresh:
            cached = cache.get(self._cache_key)
            if cached:
                return cached
        return self._fetch_token()

    # ----------------------------------------------------------------- calls
    def _request(self, method, path, *, params=None, json=None, _retried=False):
        token = self.access_token(force_refresh=_retried)
        url = path if path.startswith('http') else f'{API_BASE}{path}'
        try:
            resp = requests.request(
                method, url,
                headers={'Authorization': f'Bearer {token}'},
                params=params, json=json, timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ZoomError(f'Could not reach Zoom: {exc}') from exc

        # A cached token can be revoked server-side; retry once with a fresh one.
        if resp.status_code == 401 and not _retried:
            cache.delete(self._cache_key)
            return self._request(method, path, params=params, json=json, _retried=True)

        if resp.status_code == 429:
            # Zoom rate limit — one short backoff, then give up to the caller.
            if not _retried:
                time.sleep(1.5)
                return self._request(method, path, params=params, json=json, _retried=True)
            raise ZoomError('Zoom rate limit reached. Please try again shortly.', status=429)

        if resp.status_code >= 400:
            body = _json_or_empty(resp)
            raise ZoomError(
                _error_message(resp, 'Zoom API call failed'),
                status=resp.status_code,
                code=body.get('code'),
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return _json_or_empty(resp)

    # -------------------------------------------------------------- meetings
    def verify(self):
        """Fetch a token and the host user — used by "Test connection"."""
        self.access_token(force_refresh=True)
        return self._request('GET', f'/users/{self._host()}')

    def _host(self):
        return (self.integration.host_email or '').strip() or 'me'

    def create_meeting(self, *, topic, start_time, duration, agenda='',
                       timezone_name='UTC', with_registration=False):
        """Create a scheduled meeting. ``start_time`` is an aware datetime."""
        payload = {
            'topic': (topic or 'Live class')[:200],
            'type': 2,  # scheduled
            'duration': max(int(duration or 60), 1),
            'timezone': timezone_name or 'UTC',
            'agenda': _plain(agenda)[:2000],
            'settings': {
                'join_before_host': False,
                'waiting_room': False,
                'mute_upon_entry': True,
                'participant_video': False,
                'host_video': True,
                'auto_recording': 'none',
                # 0 = automatically approve registrants, 2 = no registration.
                'approval_type': 0 if with_registration else 2,
                'registration_type': 1,
                'meeting_authentication': False,
            },
        }
        if start_time:
            payload['start_time'] = _zoom_time(start_time)
        return self._request('POST', f'/users/{self._host()}/meetings', json=payload)

    def update_meeting(self, meeting_id, *, topic=None, start_time=None,
                       duration=None, agenda=None, timezone_name=None,
                       with_registration=None):
        payload = {}
        if topic is not None:
            payload['topic'] = topic[:200]
        if start_time is not None:
            payload['start_time'] = _zoom_time(start_time)
        if duration is not None:
            payload['duration'] = max(int(duration), 1)
        if agenda is not None:
            payload['agenda'] = _plain(agenda)[:2000]
        if timezone_name:
            payload['timezone'] = timezone_name
        if with_registration is not None:
            payload['settings'] = {'approval_type': 0 if with_registration else 2}
        if not payload:
            return {}
        self._request('PATCH', f'/meetings/{meeting_id}', json=payload)
        return self.get_meeting(meeting_id)

    def get_meeting(self, meeting_id):
        return self._request('GET', f'/meetings/{meeting_id}')

    def delete_meeting(self, meeting_id):
        return self._request(
            'DELETE', f'/meetings/{meeting_id}',
            params={'schedule_for_reminder': 'false'},
        )

    # ----------------------------------------------------------- registrants
    def add_registrant(self, meeting_id, *, email, first_name, last_name=''):
        """Register a student and return their personal ``join_url``."""
        payload = {
            'email': email,
            'first_name': (first_name or email.split('@')[0])[:64],
            'last_name': (last_name or '')[:64],
            'auto_approve': True,
        }
        return self._request(
            'POST', f'/meetings/{meeting_id}/registrants', json=payload
        )

    # ---------------------------------------------------------- participants
    def get_participants(self, meeting_id):
        """All participants of a *past* meeting, following pagination.

        Tries the authoritative ``/report`` endpoint first (needs a Pro plan and
        the ``report:read:admin`` scope) and falls back to the dashboard
        ``/metrics`` endpoint, then to the past-meeting participants list.
        """
        for path, params in (
            (f'/report/meetings/{meeting_id}/participants',
             {'page_size': 300, 'include_fields': 'registrant_id'}),
            (f'/metrics/meetings/{meeting_id}/participants',
             {'page_size': 300, 'type': 'past'}),
            (f'/past_meetings/{meeting_id}/participants', {'page_size': 300}),
        ):
            try:
                return self._paged(path, params, 'participants')
            except ZoomError as exc:
                # 400/403 usually means "your plan/scope doesn't allow this" —
                # try the next source. Anything else is a real failure.
                if exc.status in (400, 401, 403, 404):
                    logger.info('Zoom participants source %s unavailable: %s', path, exc)
                    continue
                raise
        raise ZoomError(
            'Zoom did not return participant data for this meeting. Attendance '
            'reports require a paid Zoom plan and the report:read:admin scope.',
            status=403,
        )

    def get_past_meeting(self, meeting_id):
        """Summary of the last occurrence (start/end time, participant count)."""
        return self._request('GET', f'/past_meetings/{meeting_id}')

    def _paged(self, path, params, key):
        items, token, guard = [], None, 0
        while guard < 25:
            guard += 1
            call_params = dict(params or {})
            if token:
                call_params['next_page_token'] = token
            data = self._request('GET', path, params=call_params)
            items.extend(data.get(key) or [])
            token = data.get('next_page_token') or ''
            if not token:
                break
        return items


# ---------------------------------------------------------------- helpers
def _json_or_empty(resp):
    try:
        return resp.json() or {}
    except ValueError:
        return {}


def _error_message(resp, prefix):
    body = _json_or_empty(resp)
    detail = body.get('message') or body.get('reason') or resp.text[:200]
    return f'{prefix}: {detail}'.strip()


def _zoom_time(dt):
    """Zoom wants ``YYYY-MM-DDTHH:MM:SSZ`` in UTC."""
    return timezone.localtime(dt, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _plain(html):
    """Strip tags so a rich-HTML description is usable as a Zoom agenda."""
    if not html:
        return ''
    from django.utils.html import strip_tags
    return strip_tags(html).strip()


def verify_webhook_signature(secret_token, headers, raw_body):
    """Validate Zoom's ``x-zm-signature`` header.

    Zoom signs ``v0:<timestamp>:<raw body>`` with the app's Secret Token and
    sends ``x-zm-signature: v0=<hex hmac>``.
    """
    if not secret_token:
        return False
    signature = headers.get('x-zm-signature') or headers.get('X-Zm-Signature') or ''
    ts = headers.get('x-zm-request-timestamp') or headers.get('X-Zm-Request-Timestamp') or ''
    if not signature or not ts:
        return False
    body = raw_body.decode('utf-8', 'replace') if isinstance(raw_body, bytes) else (raw_body or '')
    message = f'v0:{ts}:{body}'
    digest = hmac.new(
        secret_token.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f'v0={digest}', signature)


def webhook_validation_response(secret_token, plain_token):
    """Answer Zoom's ``endpoint.url_validation`` challenge."""
    encrypted = hmac.new(
        (secret_token or '').encode(), (plain_token or '').encode(), hashlib.sha256
    ).hexdigest()
    return {'plainToken': plain_token, 'encryptedToken': encrypted}
