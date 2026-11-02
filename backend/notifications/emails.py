"""Branded transactional email for tenants.

Every email rendered here carries the tenant's logo + name and an accent colour
derived from the tenant theme, so students/admins get on-brand communication.

``send_branded_email`` is the single entry point: it renders
``emails/base_email.html`` with the branding context and dispatches an
HTML+plain-text multipart message. All callers pass an already-built HTML body
fragment (``body_html``) plus an optional CTA button.
"""
import logging
import re
from email.utils import formataddr, parseaddr
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import escape, strip_tags

logger = logging.getLogger(__name__)

# Accent colour per tenant theme key (kept loosely in sync with the frontend
# theme palette). Falls back to the sunrise orange used across the platform.
_THEME_ACCENTS = {
    'sunrise': '#f97316',
    'ocean': '#2563eb',
    'emerald': '#059669',
    'violet': '#7c3aed',
    'rose': '#e11d48',
    'indigo': '#4f46e5',
    'slate': '#475569',
    'amber': '#d97706',
    'cherry': '#dc2626',
    'lime': '#65a30d',
}
_DEFAULT_ACCENT = '#f97316'


def _absolute_url(url):
    """Make a possibly-relative media URL absolute for use inside an email."""
    if not url:
        return ''
    if url.startswith('http://') or url.startswith('https://'):
        return url
    base = getattr(settings, 'BACKEND_PUBLIC_URL', '') or ''
    if base:
        return f"{base.rstrip('/')}/{url.lstrip('/')}"
    return url


def tenant_logo_url(tenant):
    if tenant and getattr(tenant, 'logo', None):
        try:
            return _absolute_url(tenant.logo.url)
        except Exception:  # noqa: BLE001 - storage may not resolve a URL
            return ''
    return ''


def _normalize_frontend_origin(value):
    origin = str(value or '').strip().rstrip('/')
    if not origin:
        return ''
    parsed = urlparse(origin)
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {'', '/'}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return ''
    return origin


def _request_frontend_origin(request, tenant):
    """Return a safe browser origin for tenant-facing email links."""
    if request is None:
        return ''
    origin = _normalize_frontend_origin(request.headers.get('Origin'))
    if not origin:
        return ''
    parsed = urlparse(origin)

    configured = {
        normalized
        for value in (getattr(tenant, 'allowed_origins', None) or [])
        if (normalized := _normalize_frontend_origin(value))
    }
    if origin in configured:
        return origin

    # A first-party host is safe only when its subdomain belongs to this tenant.
    # Anonymous endpoints select the tenant from X-Tenant-ID, so trusting every
    # platform subdomain would let one tenant inject its origin into another
    # tenant's guardian email.
    host = (parsed.hostname or '').lower()
    subdomain = (getattr(tenant, 'subdomain', '') or '').strip().lower()
    tenant_hosts = {
        f'{subdomain}.dailytaiyari.in',
        f'{subdomain}.dailytaiyari.ai',
    } if subdomain else set()
    if (
        host in tenant_hosts
        and parsed.scheme == 'https'
        and parsed.port in {None, 443}
    ):
        return origin
    return ''


def tenant_frontend_origin(tenant, request=None):
    """Best-effort base URL of the tenant's student/admin frontend.

    Used to build clickable deep links in emails. Prefers the first configured
    ``allowed_origins`` entry, then a global ``FRONTEND_URL`` setting.
    """
    request_origin = _request_frontend_origin(request, tenant)
    if request_origin:
        return request_origin
    origins = getattr(tenant, 'allowed_origins', None) or []
    if isinstance(origins, (list, tuple)):
        for origin in origins:
            normalized = _normalize_frontend_origin(origin)
            if normalized:
                return normalized
    return _normalize_frontend_origin(getattr(settings, 'FRONTEND_URL', ''))


def tenant_link(tenant, path, request=None):
    """Join the tenant frontend origin with a relative path."""
    origin = tenant_frontend_origin(tenant, request=request)
    if not path:
        return origin
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return f"{origin}/{path.lstrip('/')}" if origin else path


def from_address(tenant, display_name=None):
    """Sender address showing the tenant's name as the display name.

    The mailbox itself must stay on the platform's verified sending domain
    (Azure Communication Services only signs that domain), so only the display
    name is tenant-specific: ``CodeMinors <DoNotReply@dailytaiyari.in>``.
    Falls back to the configured address unchanged when no tenant name exists.
    """
    configured = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or ''
    default_name, addr = parseaddr(configured)
    if not addr:
        return configured or None
    display = (
        str(display_name).strip()
        if display_name is not None
        else (getattr(tenant, 'name', '') or '').strip()
    ) or default_name
    return formataddr((display, addr)) if display else addr


def _accent_for(tenant):
    theme = getattr(tenant, 'theme', None)
    return _THEME_ACCENTS.get(theme, _DEFAULT_ACCENT)


def celebration_body_html(tenant, body_html, *, badge='🎂', banner_text=''):
    """Wrap an email body in a festive, table-based celebration card.

    Used by the birthday emails so they feel like a greeting card rather than a
    transactional notice, while still rendering identically across Outlook /
    Gmail (no flexbox, no background images, inline styles only). The accent
    colour comes from the tenant theme so the card stays on brand.
    """
    accent = _accent_for(tenant)
    banner = ''
    if banner_text:
        banner = (
            '<p style="margin:12px 0 0; font-size:15px; font-weight:600; '
            f'color:{accent}; letter-spacing:0.3px;">{escape(banner_text)}</p>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="margin:0 0 24px;">'
        '<tr><td align="center" '
        f'style="padding:28px 20px; border-radius:16px; background-color:#fff7ed; '
        f'border:1px solid {accent}33;">'
        f'<div style="font-size:52px; line-height:1;">{escape(badge)}</div>'
        f'{banner}'
        '</td></tr></table>'
        f'{body_html or ""}'
    )


def send_branded_email(tenant, to, subject, heading, body_html,
                       cta_text=None, cta_url=None, preheader=None,
                       tenant_name_override=None, hide_tenant_logo=False):
    """Render and send one branded HTML email.

    Returns True on success, False on failure (never raises to the caller so a
    mail hiccup can't roll back the triggering action).
    """
    recipients = [to] if isinstance(to, str) else [r for r in (to or []) if r]
    if not recipients:
        return False

    if tenant_name_override is not None:
        tenant_name = str(tenant_name_override).strip() or 'Your institution'
    else:
        tenant_name = (getattr(tenant, 'name', '') or '').strip() or 'DailyTaiyari'
    context = {
        'subject': subject,
        'title': heading or subject,
        'preheader': preheader or heading or subject,
        'heading': heading,
        'body_html': body_html,
        'cta_text': cta_text,
        'cta_url': cta_url,
        'tenant_name': tenant_name,
        'logo_url': '' if hide_tenant_logo else tenant_logo_url(tenant),
        'accent': _accent_for(tenant),
    }

    try:
        html_body = render_to_string('emails/base_email.html', context)
    except Exception:  # noqa: BLE001
        logger.exception('Failed to render branded email template')
        return False

    # Derive a readable plain-text alternative from the HTML fragment. Block
    # boundaries must become newlines first, otherwise strip_tags runs adjacent
    # paragraphs together into one unreadable line.
    text_source = re.sub(r'<br\s*/?>', '\n', body_html or '')
    text_source = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n\n', text_source, flags=re.I)
    text_parts = [heading or subject, '', strip_tags(text_source).strip()]
    if cta_url:
        text_parts += ['', f'{cta_text or "Open"}: {cta_url}']
    text_body = '\n'.join(p for p in text_parts if p is not None).strip()

    from_email = from_address(tenant, display_name=tenant_name)
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=recipients,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001
        logger.exception('Failed to send branded email to %s', recipients)
        return False
