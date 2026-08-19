"""
Access + autograding helpers for the rich Mock Test attempt flow (Phase 3).

A rich mock test serves a merged, ordered paper composed of:
  * bank questions (via ``MockTestQuestion`` -> shared ``Question``), and
  * inline items (``MockTestItem``), which additionally support subjective and
    coding types.

Bank answers are recorded via the shared ``Answer`` model (auto-graded by
``Answer.check_answer``); inline answers via ``MockTestAnswer``. Subjective inline
items are flagged for manual grading and leave the attempt ``pending_manual``.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Q
from django.utils import timezone

from .models import MockTestItem, MockTestQuestion


def accessible_mock_tests_q(course_ids):
    """Q filtering published mock tests a student may attempt.

    - Linked ``courses`` (M2M) non-empty -> enrolled in one of them.
    - Else legacy ``course`` set -> enrolled in that course (existing behaviour).
    - Else (no course links at all) -> open to all students in the tenant.
    """
    course_ids = list(course_ids or [])
    all_tenant = Q(course__isnull=True) & Q(courses__isnull=True)
    if course_ids:
        return Q(course__in=course_ids) | Q(courses__in=course_ids) | all_tenant
    return all_tenant


def student_can_access(mock_test, course_ids):
    """Bool access check mirroring :func:`accessible_mock_tests_q`."""
    course_ids = set(str(c) for c in (course_ids or []))
    linked = set(str(c) for c in mock_test.courses.values_list('id', flat=True))
    if linked:
        return bool(linked & course_ids)
    if mock_test.course_id:
        return str(mock_test.course_id) in course_ids
    return True  # open to all registered students in the tenant


def _bank_question_payload(mtq):
    q = mtq.question
    options = [
        {'index': i, 'text': o.option_text,
         'image': o.option_image.url if o.option_image else None}
        for i, o in enumerate(q.options.all().order_by('order'))
    ]
    return {
        'kind': 'bank',
        'ref_id': str(q.id),           # what the client sends back as question_id
        'section': mtq.section,
        'order': mtq.order,
        'item_type': q.question_type,
        'question_text': q.question_text,
        'question_html': getattr(q, 'question_html', '') or '',
        'question_image': q.question_image.url if getattr(q, 'question_image', None) else None,
        'marks': float(mtq.effective_marks),
        'negative_marks': float(mtq.effective_negative_marks),
        'options': options,
    }


def _item_payload(item):
    data = {
        'kind': 'item',
        'ref_id': str(item.id),        # what the client sends back as item_id
        'section': item.section,
        'order': item.order,
        'item_type': item.item_type,
        'question_text': item.question_text,
        'question_html': item.question_html or '',
        'question_image': item.question_image.url if item.question_image else None,
        'marks': float(item.marks),
        'negative_marks': float(item.negative_marks),
    }
    if item.item_type in ('mcq', 'mcq_multi'):
        data['options'] = [
            {'index': i, 'text': o.get('text', ''), 'image': o.get('image')}
            for i, o in enumerate(item.options or [])
        ]
    elif item.item_type == 'numerical':
        data['numerical_tolerance'] = float(item.numerical_tolerance)
    elif item.item_type == 'subjective':
        data['max_words'] = item.max_words
    elif item.item_type == 'coding':
        data.update({
            'allowed_languages': item.allowed_languages or [],
            'starter_code': item.starter_code or {},
            'time_limit_ms': item.time_limit_ms,
            'memory_limit_mb': item.memory_limit_mb,
            'sample_test_cases': [
                {'stdin': c.get('stdin', ''),
                 'expected_output': c.get('expected_output', ''),
                 'explanation': c.get('explanation', '')}
                for c in (item.coding_test_cases or []) if c.get('is_sample')
            ],
        })
    return data


def build_paper(mock_test):
    """Merged, ordered question list for the attempt UI (no correct answers)."""
    entries = []
    for mtq in (MockTestQuestion.objects.filter(mock_test=mock_test)
                .select_related('question')
                .prefetch_related('question__options')
                .order_by('section', 'order')):
        entries.append(_bank_question_payload(mtq))
    for item in MockTestItem.objects.filter(mock_test=mock_test).order_by('section', 'order'):
        entries.append(_item_payload(item))
    # Stable merge by (section, order); bank before item on ties.
    entries.sort(key=lambda e: (e['section'], e['order'], 0 if e['kind'] == 'bank' else 1))
    return entries


def has_subjective_items(mock_test):
    return MockTestItem.objects.filter(mock_test=mock_test, item_type='subjective').exists()


# ---------------------------------------------------------------------------
# Inline item grading
# ---------------------------------------------------------------------------

def grade_item_answer(item, ans):
    """Auto-grade (in place) a ``MockTestAnswer`` for its ``MockTestItem``.

    Sets is_correct, is_auto_graded, needs_manual_grading, marks_obtained,
    max_marks and (for coding) coding_results / passed_count / total_count.
    Does not save.
    """
    marks = Decimal(str(item.marks))
    neg = Decimal(str(item.negative_marks))
    ans.max_marks = marks
    ans.is_auto_graded = False
    ans.needs_manual_grading = False
    ans.is_correct = False
    ans.marks_obtained = Decimal('0')

    if item.item_type in ('mcq', 'mcq_multi'):
        selected = set(int(i) for i in (ans.selected_options or []))
        correct = set(item.correct_option_indices)
        ans.is_correct = bool(correct) and selected == correct
        ans.is_auto_graded = True
        ans.marks_obtained = marks if ans.is_correct else (-neg if selected else Decimal('0'))

    elif item.item_type == 'numerical':
        ans.is_auto_graded = True
        if ans.numerical_answer is not None and item.numerical_answer is not None:
            diff = abs(ans.numerical_answer - item.numerical_answer)
            ans.is_correct = diff <= item.numerical_tolerance
        ans.marks_obtained = marks if ans.is_correct else (
            -neg if ans.numerical_answer is not None else Decimal('0'))

    elif item.item_type == 'coding':
        _grade_coding(item, ans, marks)

    elif item.item_type == 'subjective':
        # Manual grading only.
        ans.needs_manual_grading = True
        ans.is_auto_graded = False

    return ans


def _grade_coding(item, ans, marks):
    from django.conf import settings
    if not getattr(settings, 'CODING_ENABLED', True):
        ans.needs_manual_grading = True
        return
    cases = [
        SimpleNamespace(
            stdin=c.get('stdin', ''),
            expected_output=c.get('expected_output', ''),
            points=int(c.get('points', 1) or 1),
            is_sample=bool(c.get('is_sample', False)),
            id=idx,
            order=idx,
        )
        for idx, c in enumerate(item.coding_test_cases or [])
    ]
    if not ans.code or not ans.language or not cases:
        # Nothing to run (blank submission) -> zero, still auto-graded.
        ans.is_auto_graded = True
        ans.total_count = len(cases)
        return
    try:
        from coding.services import run_against_cases, EngineError
    except Exception:
        ans.needs_manual_grading = True
        return
    try:
        result = run_against_cases(
            language=ans.language,
            source=ans.code,
            cases=cases,
            time_limit_ms=item.time_limit_ms,
            memory_limit_mb=item.memory_limit_mb,
            reveal_io=False,   # never leak hidden-case IO to the client
        )
    except EngineError:
        # Execution service unavailable -> defer to manual grading.
        ans.needs_manual_grading = True
        return
    ans.is_auto_graded = True
    ans.coding_results = result['results']
    ans.passed_count = result['passed_count']
    ans.total_count = result['total_count']
    total_points = result['total_points'] or 0
    if total_points > 0:
        fraction = Decimal(result['passed_points']) / Decimal(total_points)
        ans.marks_obtained = (marks * fraction).quantize(Decimal('0.01'))
    ans.is_correct = total_points > 0 and result['passed_points'] == total_points


# ---------------------------------------------------------------------------
# Attempt aggregation + manual-grading finalization (Phase 5)
# ---------------------------------------------------------------------------

def recompute_attempt(attempt):
    """Recompute an attempt's aggregate score fields from its answers.

    Covers both bank answers (shared ``Answer``) and inline ``MockTestAnswer``.
    Answers still flagged ``needs_manual_grading`` contribute 0 and are not
    counted as wrong. Does not save.
    """
    bank_qs = attempt.answers.all()
    item_qs = attempt.item_answers.all()
    bank_marks = sum((x.marks_obtained for x in bank_qs), Decimal('0'))
    item_marks = sum((x.marks_obtained for x in item_qs), Decimal('0'))
    attempt.marks_obtained = bank_marks + item_marks
    attempt.attempted_questions = bank_qs.count() + item_qs.count()
    attempt.correct_answers = (
        bank_qs.filter(is_correct=True).count() + item_qs.filter(is_correct=True).count()
    )
    attempt.wrong_answers = (
        bank_qs.filter(is_correct=False).count()
        + item_qs.filter(is_correct=False, needs_manual_grading=False).count()
    )
    total = float(attempt.mock_test.total_marks) or 0
    attempt.percentage = max(0, (float(attempt.marks_obtained) / total) * 100) if total > 0 else 0
    return attempt


def pending_manual_count(attempt):
    """Number of inline answers still awaiting manual grading."""
    return attempt.item_answers.filter(needs_manual_grading=True).count()


def award_completion_xp(attempt):
    """Award the mock-completion XP for a fully graded attempt, exactly once.

    Shared by the submit path (auto-graded attempts), the admin's
    finalize-attempt action and the AI grading task, so XP can never double
    up whichever of them finishes the grading. Re-attempts earn nothing.
    Returns the XP awarded (0 when nothing was due).
    """
    from core.utils import calculate_xp_for_quiz
    from gamification.models import XPTransaction
    from gamification.services import GamificationService

    if attempt.xp_earned:
        return 0
    if XPTransaction.objects.filter(
        student=attempt.student, transaction_type='mock_complete',
        reference_id=attempt.id,
    ).exists():
        return 0
    already_completed = type(attempt).objects.filter(
        student=attempt.student, mock_test=attempt.mock_test,
        status__in=['completed', 'timed_out'],
    ).exclude(id=attempt.id).exists()
    if already_completed:
        return 0

    xp = calculate_xp_for_quiz(
        float(attempt.percentage), attempt.total_questions, is_daily_challenge=False,
    ) * 2
    attempt.xp_earned = xp
    attempt.save(update_fields=['xp_earned'])
    GamificationService.award_xp(
        attempt.student, xp, 'mock_complete',
        f'Completed mock test: {attempt.mock_test.title}', str(attempt.id),
    )
    return xp


# ---------------------------------------------------------------------------
# Student review (Phase 6)
# ---------------------------------------------------------------------------

def results_visible_for(attempt):
    """Whether a student may see graded results for this attempt."""
    mt = attempt.mock_test
    if attempt.grading_status == 'pending_manual':
        return bool(mt.results_released)
    if mt.results_released:
        return True
    return mt.result_visibility == 'immediate'


def _bank_review(answer):
    q = answer.question
    opts = list(q.options.all().order_by('order'))
    correct_idx = None
    if (q.correct_answer or '').strip().lstrip('-').isdigit():
        correct_idx = int(q.correct_answer)
    sel_idx = None
    if (answer.selected_option or '').strip().lstrip('-').isdigit():
        sel_idx = int(answer.selected_option)
    return {
        'kind': 'bank',
        'item_type': q.question_type,
        'question_text': q.question_text,
        'question_html': getattr(q, 'question_html', '') or '',
        'options': [
            {'index': i, 'text': o.option_text,
             'is_correct': i == correct_idx, 'is_selected': i == sel_idx}
            for i, o in enumerate(opts)
        ],
        'your_answer': answer.selected_option or (
            str(answer.numerical_answer) if answer.numerical_answer is not None else ''),
        'correct_answer': q.correct_answer if q.question_type in ('mcq', 'true_false', 'fill_blank')
                          else (str(q.numerical_answer) if q.numerical_answer is not None else ''),
        'explanation': getattr(q, 'explanation', '') or '',
        'marks_obtained': float(answer.marks_obtained),
        'max_marks': float(q.marks),
        'is_correct': answer.is_correct,
        'needs_manual_grading': False,
        'feedback': '',
    }


def _item_review(ans):
    item = ans.item
    data = {
        'kind': 'item',
        'item_type': item.item_type,
        'question_text': item.question_text,
        'question_html': item.question_html or '',
        'marks_obtained': float(ans.marks_obtained),
        'max_marks': float(ans.max_marks or item.marks),
        'is_correct': ans.is_correct,
        'needs_manual_grading': ans.needs_manual_grading,
        'feedback': ans.feedback or '',
        'explanation': item.explanation or '',
    }
    if item.item_type in ('mcq', 'mcq_multi'):
        correct = set(item.correct_option_indices)
        selected = set(int(i) for i in (ans.selected_options or []))
        data['options'] = [
            {'index': i, 'text': o.get('text', ''),
             'is_correct': i in correct, 'is_selected': i in selected}
            for i, o in enumerate(item.options or [])
        ]
    elif item.item_type == 'numerical':
        data['your_answer'] = str(ans.numerical_answer) if ans.numerical_answer is not None else ''
        data['correct_answer'] = str(item.numerical_answer) if item.numerical_answer is not None else ''
    elif item.item_type == 'subjective':
        data['your_answer'] = ans.answer_text
    elif item.item_type == 'coding':
        data['code'] = ans.code
        data['language'] = ans.language
        data['passed_count'] = ans.passed_count
        data['total_count'] = ans.total_count
    return data


def build_review(attempt):
    """Per-question review payload (correct answers included). Callers must
    gate on :func:`results_visible_for` before exposing this."""
    entries = []
    for a in attempt.answers.select_related('question').prefetch_related('question__options'):
        entries.append(_bank_review(a))
    for ans in attempt.item_answers.select_related('item').order_by('item__section', 'item__order'):
        entries.append(_item_review(ans))
    return entries
