"""Scoring the v2 tagger against gold files (spec §6). Pure; no database.

Every metric is computed only over gold rows that carry that field; an item
missing from the results (call/parse failure) counts as wrong.
"""
import math

DIFFICULTY_RANK = {'easy': 0, 'medium': 1, 'hard': 2}
TARGET_SUBTOPIC_ACCURACY = 0.8
MIN_BUCKET_N = 5  # calibration buckets smaller than this are too noisy to set the threshold
ROW_DECIMALS = {'cost_per_1000_usd': 4}

ROWS = [
    ('n', 'Questions'),
    ('topic_accuracy', 'Topic accuracy (blind)'),
    ('subtopic_exact', 'Subtopic exact'),
    ('subtopic_hit', 'Subtopic hit'),
    ('thinking_accuracy', 'Thinking level'),
    ('skills.f1', 'Skills micro-F1'),
    ('core_skills.f1', 'Core skills F1'),
    ('difficulty_accuracy', 'Difficulty exact'),
    ('difficulty_within_one', 'Difficulty ±1'),
    ('error_rate', 'Errors (call/parse)'),
    ('invalid_key_rate', 'Invalid-key rate'),
    ('needs_review_rate', 'Needs review'),
    ('suggested_threshold', 'Suggested review threshold'),
    ('tokens_per_question', 'Tokens / question'),
    ('latency_p50_ms', 'Latency p50 (ms per call)'),
    ('latency_p95_ms', 'Latency p95 (ms per call)'),
    ('cost_per_1000_usd', 'Cost / 1,000 questions (USD)'),
]


def _ratio(num, den):
    return round(num / den, 4) if den else None


def _prf(tp, fp, fn):
    return {
        'precision': _ratio(tp, tp + fp),
        'recall': _ratio(tp, tp + fn),
        'f1': _ratio(2 * tp, 2 * tp + fp + fn),
    }


def _gold(row, field):
    return (row.get('gold') or {}).get(field)


def suggest_threshold(buckets, target=TARGET_SUBTOPIC_ACCURACY, min_n=MIN_BUCKET_N):
    """Review threshold from the calibration buckets (spec §5.3).

    Walk the buckets holding at least ``min_n`` items from the top down; the
    threshold is the floor of the lowest bucket reached while every visited
    bucket has subtopic accuracy ≥ ``target``. Stop at the first failing
    bucket. None when the top qualifying bucket already fails, or no bucket
    is big enough.
    """
    threshold = None
    for floor in sorted(buckets, reverse=True):
        bucket = buckets[floor]
        if bucket['n'] < min_n:
            continue
        if bucket['exact'] / bucket['n'] < target:
            break
        threshold = floor / 10
    return threshold


def score(gold_rows, results, *, mode):
    by_id = {result.id: result for result in results}
    pairs = [(row, by_id.get(str(row['id']))) for row in gold_rows]
    n = len(pairs)
    metrics = {'n': n, 'mode': mode}
    metrics['error_rate'] = _ratio(sum(1 for _, r in pairs if r is None or r.error), n)
    metrics['invalid_key_rate'] = _ratio(
        sum(1 for _, r in pairs if r is not None and 'invalid_key' in r.review_reasons), n)
    metrics['needs_review_rate'] = _ratio(sum(1 for _, r in pairs if r is None or r.needs_review), n)

    if mode == 'blind':
        rows = [(g, r) for g, r in pairs if _gold(g, 'topic')]
        metrics['topic_accuracy'] = _ratio(
            sum(1 for g, r in rows if r is not None and r.topic_key == _gold(g, 'topic')), len(rows))

    sub_rows = [(g, r) for g, r in pairs if _gold(g, 'subtopic')]
    metrics['subtopic_exact'] = _ratio(
        sum(1 for g, r in sub_rows if r is not None and r.primary_subtopic == _gold(g, 'subtopic')),
        len(sub_rows))
    metrics['subtopic_hit'] = _ratio(
        sum(1 for g, r in sub_rows
            if r is not None and _gold(g, 'subtopic') in [r.primary_subtopic, *r.secondary_subtopics]),
        len(sub_rows))

    level_rows = [(g, r) for g, r in pairs if _gold(g, 'thinking_level')]
    confusion = {}
    for g, r in level_rows:
        predicted = (r.thinking_level if r is not None else '') or '(none)'
        row = confusion.setdefault(_gold(g, 'thinking_level'), {})
        row[predicted] = row.get(predicted, 0) + 1
    metrics['thinking_accuracy'] = _ratio(
        sum(1 for g, r in level_rows if r is not None and r.thinking_level == _gold(g, 'thinking_level')),
        len(level_rows))
    metrics['thinking_confusion'] = confusion

    def skill_score(field, core_only):
        rows = [(g, r) for g, r in pairs if _gold(g, field) is not None]
        if not rows:
            return None
        tp = fp = fn = 0
        for g, r in rows:
            predicted = {s['key'] for s in (r.skills if r is not None else [])
                         if not core_only or s['role'] == 'core'}
            wanted = set(_gold(g, field))
            tp += len(predicted & wanted)
            fp += len(predicted - wanted)
            fn += len(wanted - predicted)
        return _prf(tp, fp, fn)

    metrics['skills'] = skill_score('skills', core_only=False)
    metrics['core_skills'] = skill_score('core_skills', core_only=True)

    diff_rows = [(g, r) for g, r in pairs if _gold(g, 'difficulty') in DIFFICULTY_RANK]
    metrics['difficulty_accuracy'] = _ratio(
        sum(1 for g, r in diff_rows if r is not None and r.difficulty == _gold(g, 'difficulty')),
        len(diff_rows))
    metrics['difficulty_within_one'] = _ratio(
        sum(1 for g, r in diff_rows if r is not None and r.difficulty in DIFFICULTY_RANK
            and abs(DIFFICULTY_RANK[r.difficulty] - DIFFICULTY_RANK[_gold(g, 'difficulty')]) <= 1),
        len(diff_rows))

    fmt_rows = [(g, r) for g, r in pairs if 'special_format' in (g.get('gold') or {})]
    formats = ({_gold(g, 'special_format') for g, _ in fmt_rows}
               | {r.special_format for _, r in fmt_rows if r is not None}) - {'', None}
    special = {}
    for key in sorted(formats):
        tp = sum(1 for g, r in fmt_rows if _gold(g, 'special_format') == key and r is not None
                 and r.special_format == key)
        fp = sum(1 for g, r in fmt_rows if r is not None and r.special_format == key
                 and _gold(g, 'special_format') != key)
        fn = sum(1 for g, r in fmt_rows if _gold(g, 'special_format') == key
                 and (r is None or r.special_format != key))
        special[key] = _prf(tp, fp, fn)
    metrics['special_formats'] = special

    buckets = {}
    for g, r in sub_rows:
        if r is None or r.error:
            continue
        bucket = buckets.setdefault(min(9, int(r.confidence * 10)), {'n': 0, 'exact': 0})
        bucket['n'] += 1
        bucket['exact'] += int(r.primary_subtopic == _gold(g, 'subtopic'))
    metrics['calibration'] = [
        {'from': floor / 10, 'n': v['n'], 'subtopic_exact': _ratio(v['exact'], v['n'])}
        for floor, v in sorted(buckets.items())
    ]
    metrics['suggested_threshold'] = suggest_threshold(buckets)
    return metrics


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def _lookup(entry, path):
    value = entry
    for part in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _cell(value, decimals=None):
    if value is None:
        return '—'
    if decimals is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'{value:.{decimals}f}'
    if isinstance(value, float) and not isinstance(value, bool):
        return f'{value:.3f}' if value <= 1 else f'{value:.1f}'
    return str(value)


def render_markdown(report):
    names = list(report['models'])
    lines = [
        f'Gold: {report["gold"]} · mode: {report["mode"]}',
        '',
        '| Metric | ' + ' | '.join(names) + ' |',
        '|---|' + '---|' * len(names),
    ]
    for path, label in ROWS:
        if path == 'topic_accuracy' and report['mode'] != 'blind':
            continue
        cells = [_cell(_lookup(report['models'][name], path), ROW_DECIMALS.get(path)) for name in names]
        lines.append(f'| {label} | ' + ' | '.join(cells) + ' |')
    for name in names:
        calibration = report['models'][name].get('calibration') or []
        if calibration:
            buckets = ', '.join(f'≥{c["from"]:.1f}: {_cell(c["subtopic_exact"])} (n={c["n"]})' for c in calibration)
            lines += ['', f'Calibration — {name}: {buckets}']
    return '\n'.join(lines)
