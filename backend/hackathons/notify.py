"""
Participant-facing notifications for hackathons.

Every function here is fire-and-forget: a broken mail server must never block a
registration or a result publication. They all reuse the platform's branded
email pipeline (``notifications.emails.send_branded_email`` via
``notifications.services._dispatch_email``) plus the in-app ``Notification``
feed, so hackathon mail carries the tenant's logo and colours like everything
else.
"""
import logging

from django.utils.html import escape

from notifications import emails
from notifications.models import Notification
from notifications.services import _dispatch_email, notify

logger = logging.getLogger(__name__)


def _hackathon_path(hackathon):
    return f'/hackathons/{hackathon.id}'


def _p(text):
    return f'<p>{escape(text)}</p>'


def _safe(fn):
    """Run a notifier, swallowing every failure (with a log line)."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover - notification must never break flow
            logger.exception('hackathon notification failed: %s', fn.__name__)
            return None
    wrapper.__name__ = fn.__name__
    return wrapper


def _emails_enabled(hackathon):
    return bool(getattr(hackathon, 'email_notifications', True))


def _send(hackathon, registration, *, subject, heading, body_html,
          cta_text='View hackathon', path=None):
    if not _emails_enabled(hackathon):
        return
    email = registration.email or getattr(registration.participant.user, 'email', '')
    if not email:
        return
    tenant = hackathon.tenant
    _dispatch_email(
        tenant,
        email,
        subject=subject,
        heading=heading,
        body_html=body_html,
        cta_text=cta_text,
        cta_url=emails.tenant_link(tenant, path or _hackathon_path(hackathon)),
    )


@_safe
def on_registered(registration):
    hackathon = registration.hackathon
    user = registration.participant.user
    name = registration.full_name or user.full_name or 'there'

    notify(
        user,
        tenant=hackathon.tenant,
        type=Notification.TYPE_HACKATHON_REGISTERED,
        title=f'You are registered for {hackathon.title} 🎉',
        body='We will email you before each round begins.',
        link=_hackathon_path(hackathon),
        data={'hackathon_id': str(hackathon.id), 'registration_id': str(registration.id)},
    )

    stages = list(hackathon.stages.filter(status='published').order_by('order', 'created_at'))
    stage_html = ''
    if stages:
        rows = ''.join(
            f'<li><strong>Round {i}:</strong> {escape(s.title)}'
            + (f' — {s.get_stage_type_display()}' if s.stage_type else '')
            + '</li>'
            for i, s in enumerate(stages, start=1)
        )
        stage_html = f'<p><strong>What is ahead</strong></p><ul>{rows}</ul>'

    body = (
        _p(f'Hi {name}, your spot in {hackathon.title} is confirmed.')
        + stage_html
        + _p('Keep an eye on your inbox — we will notify you the moment each round '
             'opens and as soon as results are out.')
    )
    _send(
        hackathon, registration,
        subject=f'Registration confirmed — {hackathon.title}',
        heading='You are in! 🎉',
        body_html=body,
        cta_text='Open hackathon',
    )


@_safe
def on_stage_opened(stage, registrations):
    """Tell qualified participants that a round is now live."""
    hackathon = stage.hackathon
    path = f'{_hackathon_path(hackathon)}/stage/{stage.id}'
    deadline = stage.ends_at.strftime('%d %b %Y, %I:%M %p') if stage.ends_at else None
    for registration in registrations:
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_STAGE,
            title=f'{stage.title} is now live',
            body=f'{hackathon.title} — your next round is open.',
            link=path,
            data={'hackathon_id': str(hackathon.id), 'stage_id': str(stage.id)},
        )
        body = (
            _p(f'{stage.title} of {hackathon.title} is now open.')
            + (_p(f'Deadline: {deadline}') if deadline else '')
            + _p('Give it your best shot!')
        )
        _send(
            hackathon, registration,
            subject=f'{stage.title} is live — {hackathon.title}',
            heading=f'{stage.title} is open 🚀',
            body_html=body,
            cta_text='Start the round',
            path=path,
        )


@_safe
def on_stage_results(stage, qualified, rejected):
    """Notify both the advancing and the eliminated participants."""
    hackathon = stage.hackathon
    nxt_exists = bool(
        hackathon.stages.filter(order__gt=stage.order).exclude(id=stage.id).exists()
    )

    for participation in qualified:
        registration = participation.registration
        score = f'{float(participation.effective_score):g}/{float(participation.max_score or 0):g}'
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_RESULT,
            title=f'You cleared {stage.title}! 🎉',
            body=(f'Score: {score}. '
                  + ('The next round awaits.' if nxt_exists else 'Final results coming soon.')),
            link=_hackathon_path(hackathon),
            data={'hackathon_id': str(hackathon.id), 'stage_id': str(stage.id),
                  'qualified': True},
        )
        body = (
            _p(f'Congratulations — you cleared {stage.title} in {hackathon.title}.')
            + _p(f'Your score: {score}')
            + _p('The next round is unlocked on your hackathon page.'
                 if nxt_exists else 'Final results will be announced shortly.')
        )
        _send(
            hackathon, registration,
            subject=f'You advanced — {stage.title} · {hackathon.title}',
            heading='You are through to the next round 🎉',
            body_html=body,
            cta_text='See what is next',
        )

    for participation in rejected:
        registration = participation.registration
        score = f'{float(participation.effective_score):g}/{float(participation.max_score or 0):g}'
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_RESULT,
            title=f'{stage.title} results are out',
            body=f'You were not shortlisted for the next round. Score: {score}.',
            link=_hackathon_path(hackathon),
            data={'hackathon_id': str(hackathon.id), 'stage_id': str(stage.id),
                  'qualified': False},
        )
        body = (
            _p(f'Results for {stage.title} in {hackathon.title} are out.')
            + _p(f'Your score: {score}')
            + _p('You were not shortlisted for the next round this time. '
                 'Thank you for taking part — we would love to see you in the next one.')
        )
        _send(
            hackathon, registration,
            subject=f'{stage.title} results — {hackathon.title}',
            heading=f'{stage.title} results',
            body_html=body,
            cta_text='View your result',
        )


@_safe
def on_winners_declared(hackathon, winners):
    for registration in winners:
        title = registration.winner_title or 'Winner'
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_WINNER,
            title=f'🏆 {title} — {hackathon.title}',
            body=registration.prize or 'Congratulations on your win!',
            link=_hackathon_path(hackathon),
            data={'hackathon_id': str(hackathon.id), 'rank': registration.final_rank},
        )
        body = (
            _p(f'Congratulations! You have been declared {title} of {hackathon.title}.')
            + (_p(f'Prize: {registration.prize}') if registration.prize else '')
            + _p('Outstanding work — thank you for making this event what it was.')
        )
        _send(
            hackathon, registration,
            subject=f'🏆 You won — {hackathon.title}',
            heading=f'{title} 🏆',
            body_html=body,
            cta_text='See the results',
        )


@_safe
def on_results_announced(hackathon, registrations):
    for registration in registrations:
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_RESULT,
            title=f'Results are out — {hackathon.title}',
            body='The final standings have been published.',
            link=_hackathon_path(hackathon),
            data={'hackathon_id': str(hackathon.id)},
        )
        _send(
            hackathon, registration,
            subject=f'Final results — {hackathon.title}',
            heading='The results are in',
            body_html=_p(f'Final standings for {hackathon.title} have been published.'),
            cta_text='View results',
        )


@_safe
def send_announcement(announcement, registrations):
    hackathon = announcement.hackathon
    body_html = announcement.body or ''
    if body_html and '<' not in body_html:
        body_html = ''.join(_p(line) for line in body_html.splitlines() if line.strip())

    count = 0
    for registration in registrations:
        notify(
            registration.participant.user,
            tenant=hackathon.tenant,
            type=Notification.TYPE_HACKATHON_ANNOUNCEMENT,
            title=announcement.title,
            body=(announcement.body or '')[:300],
            link=_hackathon_path(hackathon),
            data={'hackathon_id': str(hackathon.id),
                  'announcement_id': str(announcement.id)},
        )
        if announcement.send_email:
            _send(
                hackathon, registration,
                subject=f'{announcement.title} — {hackathon.title}',
                heading=announcement.title,
                body_html=body_html,
                cta_text='Open hackathon',
            )
        count += 1
    return count
