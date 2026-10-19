"""
Grading + progression engine for hackathon stages.

Three concerns live here so the HTTP layer stays thin:

``build_paper`` / ``grade_answer`` / ``recompute_participation``
    Autograding for ``quiz`` and ``coding`` rounds. Semantics are deliberately
    identical to ``quiz.mock_grading`` (negative marking on wrong MCQ/numerical,
    proportional scoring for partially-passing code, subjective deferred to a
    human) so a participant's experience matches the rest of the platform.

``sync_lab_score``
    Pulls a participant's best ``notebooks.NotebookSubmission`` score into the
    stage. The notebooks app owns lab authoring and grading; we only read.

``apply_qualification`` / ``open_next_stage``
    The progression rules. A round decides its qualifiers by cut-off, top-N, or
    an explicit admin pick, then the next round is unlocked for exactly those
    participants. Everyone else keeps a ``not_qualified`` participation so the
    UI can show a clear "you didn't advance" state instead of an empty page.
"""
import logging
from decimal import Decimal
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from .models import HackathonRegistration, StageParticipation

logger = logging.getLogger(__name__)

ZERO = Decimal('0')


# ---------------------------------------------------------------------------
# Paper building (never leaks answers)
# ---------------------------------------------------------------------------

def item_payload(item, *, reveal_answers=False):
    """Client-safe representation of one stage item."""
    data = {
        'id': str(item.id),
        'item_type': item.item_type,
        'order': item.order,
        'title': item.title or '',
        'question_text': item.question_text or '',
        'question_html': item.question_html or '',
        'question_image': item.question_image.url if item.question_image else None,
        'difficulty': item.difficulty or '',
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
                {
                    'stdin': c.get('stdin', ''),
                    'expected_output': c.get('expected_output', ''),
                    'explanation': c.get('explanation', ''),
                }
                for c in (item.coding_test_cases or []) if c.get('is_sample')
            ],
        })
    if reveal_answers:
        data['explanation'] = item.explanation or ''
        if item.item_type in ('mcq', 'mcq_multi'):
            data['correct_options'] = item.correct_option_indices
        elif item.item_type == 'numerical':
            data['numerical_answer'] = (
                float(item.numerical_answer) if item.numerical_answer is not None else None
            )
        elif item.item_type == 'subjective':
            data['model_answer'] = item.model_answer or ''
    return data


def build_paper(stage, *, reveal_answers=False):
    """Ordered, client-safe item list for a quiz/coding round."""
    items = stage.items.all().order_by('order', 'created_at')
    return [item_payload(i, reveal_answers=reveal_answers) for i in items]


# ---------------------------------------------------------------------------
# Autograding
# ---------------------------------------------------------------------------

def grade_answer(item, ans):
    """Auto-grade a ``StageItemAnswer`` in place. Does not save."""
    marks = Decimal(str(item.marks))
    neg = Decimal(str(item.negative_marks))
    ans.max_marks = marks
    ans.is_auto_graded = False
    ans.needs_manual_grading = False
    ans.is_correct = False
    ans.marks_obtained = ZERO

    if item.item_type in ('mcq', 'mcq_multi'):
        try:
            selected = set(int(i) for i in (ans.selected_options or []))
        except (TypeError, ValueError):
            selected = set()
        correct = set(item.correct_option_indices)
        ans.is_correct = bool(correct) and selected == correct
        ans.is_auto_graded = True
        ans.marks_obtained = marks if ans.is_correct else (-neg if selected else ZERO)

    elif item.item_type == 'numerical':
        ans.is_auto_graded = True
        if ans.numerical_answer is not None and item.numerical_answer is not None:
            diff = abs(ans.numerical_answer - item.numerical_answer)
            ans.is_correct = diff <= item.numerical_tolerance
        ans.marks_obtained = marks if ans.is_correct else (
            -neg if ans.numerical_answer is not None else ZERO
        )

    elif item.item_type == 'coding':
        _grade_coding(item, ans, marks)

    elif item.item_type == 'subjective':
        ans.needs_manual_grading = True

    return ans


def _coding_cases(item, *, samples_only=False):
    cases = []
    for idx, c in enumerate(item.coding_test_cases or []):
        is_sample = bool(c.get('is_sample', False))
        if samples_only and not is_sample:
            continue
        cases.append(SimpleNamespace(
            stdin=c.get('stdin', ''),
            expected_output=c.get('expected_output', ''),
            points=int(c.get('points', 1) or 1),
            is_sample=is_sample,
            id=idx,
            order=idx,
        ))
    return cases


def _grade_coding(item, ans, marks):
    from django.conf import settings

    if not getattr(settings, 'CODING_ENABLED', True):
        ans.needs_manual_grading = True
        return

    cases = _coding_cases(item)
    if not ans.code or not ans.language or not cases:
        ans.is_auto_graded = True
        ans.total_count = len(cases)
        return

    try:
        from coding.services import EngineError, run_against_cases
    except Exception:  # pragma: no cover - coding app unavailable
        ans.needs_manual_grading = True
        return

    try:
        result = run_against_cases(
            language=ans.language,
            source=ans.code,
            cases=cases,
            time_limit_ms=item.time_limit_ms,
            memory_limit_mb=item.memory_limit_mb,
            reveal_io=False,
        )
    except EngineError:
        # Judge unavailable — never lose the submission, defer to a human.
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


def run_samples(item, *, language, source, stdin=None):
    """Run code against the item's sample cases (or a custom stdin). Not stored."""
    from coding.services import run_against_cases, run_code

    if stdin is not None:
        result = run_code(
            language=language,
            source=source,
            stdin=stdin,
            time_limit_ms=item.time_limit_ms,
            memory_limit_mb=item.memory_limit_mb,
        )
        return {'mode': 'custom', 'result': result}

    cases = _coding_cases(item, samples_only=True)
    if not cases:
        return {'mode': 'samples', 'results': [], 'passed_count': 0, 'total_count': 0}
    outcome = run_against_cases(
        language=language,
        source=source,
        cases=cases,
        time_limit_ms=item.time_limit_ms,
        memory_limit_mb=item.memory_limit_mb,
        reveal_io=True,
    )
    outcome['mode'] = 'samples'
    return outcome


def recompute_participation(participation, *, save=True):
    """Recompute a participation's score from its answers. Optionally saves."""
    answers = list(participation.answers.select_related('item'))
    earned = sum((a.marks_obtained for a in answers), ZERO)
    total = participation.stage.computed_max_score()

    participation.auto_score = max(earned, ZERO)
    participation.score = max(earned, ZERO)
    participation.max_score = Decimal(str(total or 0))
    participation.needs_manual_grading = any(a.needs_manual_grading for a in answers)
    if not participation.needs_manual_grading:
        participation.status = 'evaluated'
        participation.evaluated_at = participation.evaluated_at or timezone.now()
    else:
        participation.status = 'submitted'
    if save:
        participation.save(update_fields=[
            'auto_score', 'score', 'max_score', 'needs_manual_grading',
            'status', 'evaluated_at', 'updated_at',
        ])
    return participation


def sync_lab_score(participation, *, save=True):
    """Pull the participant's best notebook score into a ``lab`` round."""
    stage = participation.stage
    notebook = stage.notebook
    if not notebook:
        return participation
    try:
        from notebooks.models import NotebookCompletion
    except Exception:  # pragma: no cover
        return participation

    completion = NotebookCompletion.objects.filter(
        notebook=notebook, student=participation.registration.participant,
    ).first()
    max_points = Decimal(str(stage.computed_max_score() or 0))
    participation.max_score = max_points
    if completion and (completion.best_total_points or 0) > 0:
        fraction = Decimal(completion.best_passed_points) / Decimal(completion.best_total_points)
        participation.score = (max_points * fraction).quantize(Decimal('0.01'))
        participation.auto_score = participation.score
        participation.status = 'evaluated'
        participation.submitted_at = participation.submitted_at or timezone.now()
        participation.evaluated_at = timezone.now()
    if save:
        participation.save(update_fields=[
            'score', 'auto_score', 'max_score', 'status',
            'submitted_at', 'evaluated_at', 'updated_at',
        ])
    return participation


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------

def ordered_stages(hackathon):
    return list(hackathon.stages.all().order_by('order', 'created_at'))


def previous_stage(stage):
    stages = ordered_stages(stage.hackathon)
    for idx, s in enumerate(stages):
        if s.id == stage.id:
            return stages[idx - 1] if idx > 0 else None
    return None


def next_stage(stage):
    stages = ordered_stages(stage.hackathon)
    for idx, s in enumerate(stages):
        if s.id == stage.id:
            return stages[idx + 1] if idx + 1 < len(stages) else None
    return None


def stage_index(stage):
    for idx, s in enumerate(ordered_stages(stage.hackathon)):
        if s.id == stage.id:
            return idx
    return 0


def is_eligible_for(stage, registration):
    """Whether a registration may enter ``stage``.

    Round 1 is open to every active registration. Later rounds require a
    ``qualified`` participation in the immediately preceding round.
    """
    if not registration.is_active:
        return False
    prev = previous_stage(stage)
    if prev is None:
        return True
    return StageParticipation.objects.filter(
        stage=prev, registration=registration, qualification='qualified',
    ).exists()


def get_or_create_participation(stage, registration):
    """Fetch (or lazily create) the participation row for a participant."""
    participation, _ = StageParticipation.objects.get_or_create(
        stage=stage,
        registration=registration,
        defaults={
            'tenant': stage.hackathon.tenant,
            'max_score': Decimal(str(stage.computed_max_score() or 0)),
            'status': 'pending' if is_eligible_for(stage, registration) else 'locked',
        },
    )
    return participation


def _ranked(participations):
    return sorted(
        participations,
        key=lambda p: (-float(p.effective_score), p.submitted_at or timezone.now()),
    )


def compute_qualifiers(stage, participations=None):
    """Return the participation ids that ``stage``'s rule would qualify."""
    if participations is None:
        participations = list(
            stage.participations.exclude(status='locked')
            .select_related('registration')
        )
    attempted = [p for p in participations if p.status in ('submitted', 'evaluated')]

    mode = stage.qualification_mode
    if mode == 'all':
        return [p.id for p in attempted]
    if mode == 'cutoff':
        cutoff = Decimal(str(stage.cutoff_score if stage.cutoff_score is not None else 0))
        return [p.id for p in attempted if Decimal(str(p.effective_score)) >= cutoff]
    if mode == 'top_n':
        n = int(stage.top_n or 0)
        if n <= 0:
            return []
        return [p.id for p in _ranked(attempted)[:n]]
    # manual — the admin decides; nothing is auto-selected.
    return []


@transaction.atomic
def apply_qualification(stage, *, qualified_ids=None, publish_results=True, actor=None):
    """Decide the qualifiers for ``stage`` and unlock the next round for them.

    ``qualified_ids`` (participation ids) overrides the stage rule — that is the
    manual path the admin uses when ticking people by hand. Returns a summary
    dict the API and the notifier both use.
    """
    participations = list(
        stage.participations.exclude(status='locked').select_related('registration')
    )
    if qualified_ids is None:
        winners = set(compute_qualifiers(stage, participations))
    else:
        winners = set(str(i) for i in qualified_ids)
        winners = {p.id for p in participations if str(p.id) in winners}

    # Rank everyone who took part so the UI can show standings.
    for idx, p in enumerate(_ranked([p for p in participations
                                     if p.status in ('submitted', 'evaluated')]), start=1):
        p.rank = idx

    qualified, rejected = [], []
    for p in participations:
        if p.id in winners:
            p.qualification = 'qualified'
            qualified.append(p)
        else:
            p.qualification = 'not_qualified'
            rejected.append(p)
        if actor is not None:
            p.evaluated_by = actor
        p.evaluated_at = p.evaluated_at or timezone.now()
        p.save(update_fields=['qualification', 'rank', 'evaluated_by',
                              'evaluated_at', 'updated_at'])

    if publish_results and not stage.results_published:
        stage.results_published = True
        stage.results_published_at = timezone.now()
        stage.save(update_fields=['results_published', 'results_published_at', 'updated_at'])

    nxt = next_stage(stage)
    if nxt:
        open_next_stage(nxt, [p.registration for p in qualified])

    return {
        'stage_id': str(stage.id),
        'qualified': len(qualified),
        'not_qualified': len(rejected),
        'next_stage_id': str(nxt.id) if nxt else None,
        'qualified_participations': qualified,
        'rejected_participations': rejected,
    }


def open_next_stage(stage, registrations):
    """Create ``pending`` participations in ``stage`` for the given registrations."""
    existing = set(
        stage.participations.values_list('registration_id', flat=True)
    )
    rows = [
        StageParticipation(
            tenant=stage.hackathon.tenant,
            stage=stage,
            registration=reg,
            status='pending',
            max_score=Decimal(str(stage.computed_max_score() or 0)),
        )
        for reg in registrations if reg.id not in existing
    ]
    if rows:
        StageParticipation.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def recompute_totals(hackathon):
    """Refresh each registration's cumulative score + final rank."""
    from django.db.models import Sum

    totals = (
        StageParticipation.objects
        .filter(stage__hackathon=hackathon)
        .exclude(status='locked')
        .values('registration_id')
        .annotate(total=Sum('score'))
    )
    by_reg = {row['registration_id']: row['total'] or ZERO for row in totals}
    regs = list(hackathon.registrations.filter(status='registered'))
    for reg in regs:
        reg.total_score = by_reg.get(reg.id, ZERO)
    regs.sort(key=lambda r: -float(r.total_score))
    for idx, reg in enumerate(regs, start=1):
        reg.final_rank = idx
    if regs:
        HackathonRegistration.objects.bulk_update(regs, ['total_score', 'final_rank'])
    return regs


def leaderboard(hackathon, *, stage=None, limit=100):
    """Ranked standings for a stage (or the overall event)."""
    if stage is not None:
        qs = (
            stage.participations
            .exclude(status='locked')
            .filter(status__in=['submitted', 'evaluated'])
            .select_related('registration', 'registration__participant__user')
            .order_by('-score', 'submitted_at')[:limit]
        )
        return [
            {
                'rank': idx,
                'registration_id': str(p.registration_id),
                'name': p.registration.full_name or '',
                'score': float(p.effective_score),
                'max_score': float(p.max_score or 0),
                'qualification': p.qualification,
            }
            for idx, p in enumerate(qs, start=1)
        ]

    regs = (
        hackathon.registrations.filter(status='registered')
        .order_by('-total_score', 'registered_at')[:limit]
    )
    return [
        {
            'rank': idx,
            'registration_id': str(r.id),
            'name': r.full_name or '',
            'score': float(r.total_score or 0),
            'is_winner': r.is_winner,
            'winner_title': r.winner_title,
        }
        for idx, r in enumerate(regs, start=1)
    ]


def stage_stats(stage):
    """Counts the admin dashboard renders for one round."""
    qs = stage.participations.exclude(status='locked')
    return {
        'eligible': qs.count(),
        'started': qs.filter(status='in_progress').count(),
        'submitted': qs.filter(status__in=['submitted', 'evaluated']).count(),
        'pending_review': qs.filter(needs_manual_grading=True).count(),
        'qualified': qs.filter(qualification='qualified').count(),
        'not_qualified': qs.filter(qualification='not_qualified').count(),
    }
