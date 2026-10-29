"""My Progress payloads (spec 2B §6.4–6.5): the progress page (student and
teacher) and the class topic heatmap. Thin assembly over ``rollup`` and
``facets``; nothing here is stored.
"""
from collections import Counter, defaultdict

from django.db.models import F, Q

from intelligence import progress_config as C
from intelligence.services import facets, rollup


def _name(student):
    return getattr(student.user, 'full_name', '') or student.user.email


def summarize(counts):
    """Counter of labels → "2 quick guesses, 1 ran out of time"."""
    order = list(C.RECENT_PHRASES)
    parts = []
    for label, count in sorted(counts.items(), key=lambda pair: (-pair[1], order.index(pair[0]))):
        singular, plural = C.RECENT_PHRASES[label]
        parts.append(f'{count} {singular if count == 1 else plural}')
    return ', '.join(parts)


def recent_answers(student, course, *, respect_release=False):
    """The student's last finished attempts in this course, each with a
    plain-language count of its noted answers. Never a bare label.

    With ``respect_release`` (the student's own page), a mock whose results
    are not yet released to the student reports no count and no summary,
    just ``results_pending``.
    """
    from quiz.mock_grading import results_visible_for
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import ResponseDiagnosis
    from intelligence.visibility_config import STUDENT_NOTE_CONFIDENCE

    quizzes = (
        QuizAttempt.objects.filter(student=student, quiz__course=course)
        .exclude(status='in_progress').select_related('quiz')
        .order_by(F('completed_at').desc(nulls_last=True))[:C.RECENT_ATTEMPTS]
    )
    mocks = (
        MockTestAttempt.objects.filter(student=student)
        .filter(Q(mock_test__course=course) | Q(mock_test__courses=course))
        .exclude(status='in_progress').select_related('mock_test').distinct()
        .order_by(F('completed_at').desc(nulls_last=True))[:C.RECENT_ATTEMPTS]
    )
    attempts = [('quiz', attempt, attempt.quiz.title, 'quiz') for attempt in quizzes]
    attempts += [
        ('mock', attempt, attempt.mock_test.title,
         'rich_mock' if attempt.mock_test.items.exists() else 'mock')
        for attempt in mocks
    ]
    attempts.sort(key=lambda row: row[1].completed_at or row[1].started_at, reverse=True)
    attempts = attempts[:C.RECENT_ATTEMPTS]

    counts = defaultdict(Counter)
    for kind, attempt_id, label in ResponseDiagnosis.objects.filter(
        student=student, attempt_id__in=[attempt.id for _, attempt, _, _ in attempts],
        confidence__in=STUDENT_NOTE_CONFIDENCE,
    ).values_list('attempt_kind', 'attempt_id', 'final_label'):
        if label in C.RECENT_PHRASES:
            counts[(kind, attempt_id)][label] += 1

    rows = []
    for kind, attempt, title, review in attempts:
        pending = bool(respect_release and kind == 'mock' and not results_visible_for(attempt))
        noted = Counter() if pending else counts[(kind, attempt.id)]
        done = attempt.completed_at or attempt.started_at
        rows.append({
            'kind': kind, 'attempt_id': str(attempt.id), 'title': title,
            'completed_at': done.isoformat() if done else None, 'review': review,
            'noted': sum(noted.values()), 'summary': summarize(noted),
            'results_pending': pending,
        })
    return rows


def _thresholds():
    return {'weak_below': C.WEAK_BELOW, 'strong_at': C.STRONG_AT, 'min_evidence': C.MIN_EVIDENCE}


def empty_payload():
    return {
        'courses': [], 'course': None, 'subjects': [], 'weak': [], 'strong': [],
        'profiles': [], 'recent_answers': None, 'thresholds': _thresholds(),
    }


def progress_payload(student, course, courses, *, recent, respect_release=False):
    subjects = rollup.rollup_for(student, course)
    weak, strong = rollup.topic_lists(subjects)
    return {
        'courses': [{'id': str(c.id), 'name': c.name} for c in courses],
        'course': {'id': str(course.id), 'name': course.name},
        'subjects': subjects,
        'weak': weak,
        'strong': strong,
        'profiles': facets.profile_for(student, course),
        'recent_answers': (
            recent_answers(student, course, respect_release=respect_release) if recent else None
        ),
        'thresholds': _thresholds(),
    }


def heatmap(course):
    """Topic × mastery-band student counts for one course (spec 2B §6.5)."""
    from users.models import StudentProfile

    from intelligence.models import LearnerConceptState

    students = list(
        StudentProfile.objects.filter(enrollments__course=course, enrollments__status='approved')
        .select_related('user').distinct().order_by('user__email')[:C.HEATMAP_MAX_STUDENTS + 1]
    )
    capped = len(students) > C.HEATMAP_MAX_STUDENTS
    students = students[:C.HEATMAP_MAX_STUDENTS]

    structures = rollup.course_structure(course)
    concept_ids = set()
    for structure in structures:
        concept_ids |= rollup.leaf_concept_ids(structure['node'])
    states = defaultdict(dict)
    for student_id, concept_id, mastery, evidence in LearnerConceptState.objects.filter(
        student__in=students, concept_id__in=concept_ids,
    ).values_list('student_id', 'concept_id', 'mastery', 'effective_evidence'):
        states[student_id][concept_id] = (mastery, evidence)

    rows, coverage = {}, defaultdict(list)
    for structure in structures:   # seed every topic, in tree order
        for node in rollup.iter_nodes(rollup.rollup_node(structure['node'], {})):
            if node['level'] == 'topic':
                rows[node['id']] = {
                    'id': node['id'], 'name': node['name'], 'subject': structure['subject'].name,
                    'coverage': None,
                    'counts': dict.fromkeys(C.HEATMAP_BANDS, 0),
                    'students': {band: [] for band in C.HEATMAP_BANDS},
                }
    for student in students:
        for structure in structures:
            payload = rollup.rollup_node(structure['node'], states.get(student.id, {}))
            for node in rollup.iter_nodes(payload):
                if node['level'] != 'topic':
                    continue
                row = rows[node['id']]
                row['counts'][node['status']] += 1
                row['students'][node['status']].append({'id': str(student.id), 'name': _name(student)})
                if node['coverage'] is not None:
                    coverage[node['id']].append(node['coverage'])
    for topic_id, values in coverage.items():
        rows[topic_id]['coverage'] = round(sum(values) / len(values), 4)

    return {
        'course': {'id': str(course.id), 'name': course.name},
        'students': len(students),
        'capped': capped,
        'bands': list(C.HEATMAP_BANDS),
        'topics': list(rows.values()),
    }
