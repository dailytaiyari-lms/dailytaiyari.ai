"""Editable, tenant-overridable email templates for enrollment lifecycle emails.

Each templatable email has a *default* (subject / heading / body) defined here
with ``{placeholder}`` tokens. A tenant admin can override any of the three
parts via a ``TenantEmailTemplate`` row; blank parts fall back to the default.

Bodies are authored as plain text with ``{placeholder}`` tokens and blank-line
separated paragraphs. ``render_email`` substitutes the placeholders (HTML-safe),
then converts the text into the ``<p>`` fragment the branded email base expects.
Announcement content is authored per-send and is intentionally NOT templatable.
"""
from django.utils.html import escape

# Templatable email types (must match Notification type identifiers).
TYPE_ENROLLMENT_REQUEST = 'enrollment_request'
TYPE_ENROLLMENT_APPROVED = 'enrollment_approved'
TYPE_ENROLLMENT_REJECTED = 'enrollment_rejected'
TYPE_ACCOUNT_CREATED = 'account_created'
TYPE_COURSE_ASSIGNED = 'course_assigned'
TYPE_CREDENTIALS_RESET = 'credentials_reset'
TYPE_BIRTHDAY_STUDENT = 'birthday_student'
TYPE_BIRTHDAY_PAST_STUDENT = 'birthday_past_student'
TYPE_BIRTHDAY_DIGEST = 'birthday_digest'

TEMPLATE_TYPES = [
    TYPE_ENROLLMENT_REQUEST,
    TYPE_ENROLLMENT_APPROVED,
    TYPE_ENROLLMENT_REJECTED,
    TYPE_ACCOUNT_CREATED,
    TYPE_COURSE_ASSIGNED,
    TYPE_CREDENTIALS_RESET,
    TYPE_BIRTHDAY_STUDENT,
    TYPE_BIRTHDAY_PAST_STUDENT,
    TYPE_BIRTHDAY_DIGEST,
]

# Human labels + the placeholders available to each template, surfaced to the
# admin UI so editors know exactly which tokens they may use.
TEMPLATE_META = {
    TYPE_ENROLLMENT_REQUEST: {
        'label': 'New enrollment request (to admins)',
        'description': 'Sent to your notification address when a student '
                       'requests to join a course.',
        'placeholders': [
            'student_name', 'student_email', 'course_name', 'tenant_name',
        ],
    },
    TYPE_ENROLLMENT_APPROVED: {
        'label': 'Enrollment approved (to student)',
        'description': 'Sent to the student when their enrollment request is '
                       'approved.',
        'placeholders': ['student_name', 'course_name', 'tenant_name'],
    },
    TYPE_ENROLLMENT_REJECTED: {
        'label': 'Enrollment declined (to student)',
        'description': 'Sent to the student when their enrollment request is '
                       'declined. Leave the reason token in to include the '
                       'admin-supplied reason when present.',
        'placeholders': ['student_name', 'course_name', 'reason', 'tenant_name'],
    },
    TYPE_ACCOUNT_CREATED: {
        'label': 'Account created by admin (to student)',
        'description': 'Sent to a student when an admin creates their account. '
                       'Keep the {email} and {password} tokens — they carry the '
                       'sign-in credentials.',
        'placeholders': [
            'student_name', 'email', 'password', 'tenant_name', 'courses',
        ],
    },
    TYPE_COURSE_ASSIGNED: {
        'label': 'Course assigned by admin (to student)',
        'description': 'Sent to a student when an admin enrolls them in a '
                       'course from the admin dashboard.',
        'placeholders': ['student_name', 'course_name', 'tenant_name'],
    },
    TYPE_CREDENTIALS_RESET: {
        'label': 'Password reset by admin (to student)',
        'description': 'Sent when an admin issues a new temporary password for '
                       'a user. Keep the {password} token.',
        'placeholders': ['student_name', 'email', 'password', 'tenant_name'],
    },
    TYPE_BIRTHDAY_STUDENT: {
        'label': 'Birthday wish (to current student)',
        'description': 'Sent on a current student’s birthday when birthday '
                       'greetings are enabled in Settings → Advanced.',
        'placeholders': ['student_name', 'first_name', 'tenant_name', 'age'],
    },
    TYPE_BIRTHDAY_PAST_STUDENT: {
        'label': 'Birthday wish (to past student)',
        'description': 'Sent on the birthday of a former student — someone with '
                       'no active enrolment. A warm way to invite them back, so '
                       'keep the tone celebratory rather than salesy.',
        'placeholders': ['student_name', 'first_name', 'tenant_name', 'age'],
    },
    TYPE_BIRTHDAY_DIGEST: {
        'label': "Today's birthdays (to admins)",
        'description': 'The daily digest of students celebrating a birthday, '
                       'sent to your notification address.',
        'placeholders': ['tenant_name', 'count', 'names', 'date'],
    },
}

DEFAULT_EMAIL_TEMPLATES = {
    TYPE_ENROLLMENT_REQUEST: {
        'subject': 'New enrollment request — {course_name}',
        'heading': 'New enrollment request',
        'body': (
            '{student_name} ({student_email}) has requested to enroll in '
            '{course_name}.\n\n'
            'Review the request and approve or decline it from your admin '
            'dashboard.'
        ),
    },
    TYPE_ENROLLMENT_APPROVED: {
        'subject': "You're enrolled in {course_name} 🎉",
        'heading': 'Enrollment approved',
        'body': (
            'Good news! Your request to join {course_name} has been approved.'
            '\n\n'
            'You now have full access to the course. Jump in and start '
            'learning.'
        ),
    },
    TYPE_ENROLLMENT_REJECTED: {
        'subject': 'Update on your enrollment request — {course_name}',
        'heading': 'Enrollment request declined',
        'body': (
            'Your request to join {course_name} was not approved at this time.'
            '\n\n'
            '{reason}\n\n'
            'If you think this is a mistake, please reach out to your '
            'institute.'
        ),
    },
    TYPE_ACCOUNT_CREATED: {
        'subject': 'Your {tenant_name} account is ready',
        'heading': 'Welcome aboard 👋',
        'body': (
            'Hi {student_name},\n\n'
            'An account has been created for you on {tenant_name}. '
            'Use the credentials below to sign in:\n\n'
            'Email: {email}\n'
            'Temporary password: {password}\n\n'
            '{courses}\n\n'
            'For your security, please change this password from your profile '
            'right after you sign in. Do not share it with anyone.'
        ),
    },
    TYPE_COURSE_ASSIGNED: {
        'subject': "You've been enrolled in {course_name}",
        'heading': 'New course added to your account',
        'body': (
            'Hi {student_name},\n\n'
            'Your institute has enrolled you in {course_name}. '
            'It is now available in your dashboard.\n\n'
            'Sign in to explore the syllabus, study material and practice '
            'tests for this course.'
        ),
    },
    TYPE_CREDENTIALS_RESET: {
        'subject': 'Your {tenant_name} password has been reset',
        'heading': 'New password issued',
        'body': (
            'Hi {student_name},\n\n'
            'An administrator has reset the password for your {tenant_name} '
            'account. Use the new credentials below to sign in:\n\n'
            'Email: {email}\n'
            'Temporary password: {password}\n\n'
            'Please change this password from your profile right after you '
            'sign in. If you did not expect this, contact your institute.'
        ),
    },
    TYPE_BIRTHDAY_STUDENT: {
        'subject': 'Happy Birthday, {first_name}! 🎂',
        'heading': 'Happy Birthday, {first_name}! 🎉',
        'body': (
            'Everyone at {tenant_name} is wishing you a wonderful birthday '
            'today.\n\n'
            'Thank you for the curiosity, the effort and the early mornings you '
            'bring to your preparation. Take a moment to celebrate yourself — '
            'you have earned it.\n\n'
            'Here is to another year of big goals and bigger breakthroughs. '
            'Have a brilliant day!'
        ),
    },
    TYPE_BIRTHDAY_PAST_STUDENT: {
        'subject': 'Happy Birthday, {first_name}! 🎂',
        'heading': 'Happy Birthday from all of us at {tenant_name} 🎉',
        'body': (
            'Hi {first_name},\n\n'
            'It has been a while, and we did not want your birthday to pass '
            'without saying it: we are wishing you a fantastic day.\n\n'
            'You will always be part of the {tenant_name} family. If you ever '
            'feel like picking up where you left off, your account is right '
            'where you left it — and there is plenty of new material waiting '
            'for you.\n\n'
            'Enjoy your day. We would love to see you back.'
        ),
    },
    TYPE_BIRTHDAY_DIGEST: {
        'subject': "Today's birthdays at {tenant_name} — {count} to celebrate 🎂",
        'heading': "Today's birthdays",
        'body': (
            '{count} member(s) of {tenant_name} are celebrating a birthday on '
            '{date}:\n\n'
            '{names}\n\n'
            'They have already received an automatic wish from you. A quick '
            'personal message goes a long way.'
        ),
    },
}


class _SafeDict(dict):
    """dict that renders missing ``{placeholder}`` tokens as empty strings."""

    def __missing__(self, key):
        return ''


def _safe_format(template, context):
    """Format ``template`` with ``context``, tolerating stray braces/keys."""
    try:
        return template.format_map(_SafeDict(context))
    except (ValueError, IndexError, KeyError):
        # Malformed template (e.g. a lone brace) — return it verbatim rather
        # than blow up an email send.
        return template


def text_to_html(text):
    """Convert plain text with blank-line paragraphs into a ``<p>`` fragment.

    Each non-empty line becomes its own escaped paragraph; single newlines
    within a block become ``<br>``. Escaping happens here so template authors
    cannot inject markup.
    """
    if not text:
        return ''
    # Split on blank lines into paragraphs.
    blocks = [b for b in text.replace('\r\n', '\n').split('\n\n')]
    html_blocks = []
    for block in blocks:
        lines = [ln for ln in block.split('\n') if ln.strip()]
        if not lines:
            continue
        html_blocks.append('<p>' + '<br>'.join(escape(ln) for ln in lines) + '</p>')
    return ''.join(html_blocks)


def get_template_parts(tenant, template_type):
    """Return the effective (subject, heading, body) template strings.

    A tenant override supplies any non-blank part; blank parts fall back to the
    packaged default. Never touches the DB for unknown types.
    """
    default = DEFAULT_EMAIL_TEMPLATES.get(template_type, {})
    subject = default.get('subject', '')
    heading = default.get('heading', '')
    body = default.get('body', '')

    override = None
    if tenant is not None and template_type in DEFAULT_EMAIL_TEMPLATES:
        from .models import TenantEmailTemplate
        override = (
            TenantEmailTemplate.objects
            .filter(tenant=tenant, type=template_type)
            .first()
        )
    if override:
        if (override.subject or '').strip():
            subject = override.subject
        if (override.heading or '').strip():
            heading = override.heading
        if (override.body or '').strip():
            body = override.body
    return subject, heading, body


def render_email(tenant, template_type, context):
    """Render (subject, heading, body_html) for an email using the template.

    ``context`` supplies placeholder values. Missing tokens render empty.
    """
    subject_t, heading_t, body_t = get_template_parts(tenant, template_type)
    subject = _safe_format(subject_t, context).strip()
    heading = _safe_format(heading_t, context).strip()
    body_text = _safe_format(body_t, context)
    body_html = text_to_html(body_text)
    return subject, heading, body_html
