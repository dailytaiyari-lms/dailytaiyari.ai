import {
    BookOpen,
    Brain,
    Award,
    Target,
    Flame,
    Users,
    Sparkles,
    TrendingUp,
    Code2,
    ClipboardCheck,
    FileText,
    Trophy,
    Gift,
    SlidersHorizontal,
    Notebook as NotebookIcon,
} from 'lucide-react'

/**
 * Visual + explanatory metadata for every XPTransaction.transaction_type
 * defined in backend/gamification/models.py.
 */
export const XP_META = {
    quiz_complete: {
        Icon: ClipboardCheck,
        label: 'Quiz completed',
        color: 'text-primary-600 dark:text-primary-400',
        bg: 'bg-primary-100 dark:bg-primary-900/30',
    },
    mock_complete: {
        Icon: FileText,
        label: 'Mock test completed',
        color: 'text-indigo-600 dark:text-indigo-400',
        bg: 'bg-indigo-100 dark:bg-indigo-900/30',
    },
    content_complete: {
        Icon: BookOpen,
        label: 'Study material completed',
        color: 'text-emerald-600 dark:text-emerald-400',
        bg: 'bg-emerald-100 dark:bg-emerald-900/30',
    },
    ai_quiz: {
        Icon: Brain,
        label: 'AI quiz completed',
        color: 'text-violet-600 dark:text-violet-400',
        bg: 'bg-violet-100 dark:bg-violet-900/30',
    },
    coding_solved: {
        Icon: Code2,
        label: 'Coding problem solved',
        color: 'text-cyan-600 dark:text-cyan-400',
        bg: 'bg-cyan-100 dark:bg-cyan-900/30',
    },
    notebook_graded: {
        Icon: NotebookIcon,
        label: 'Notebook completed',
        color: 'text-indigo-600 dark:text-indigo-400',
        bg: 'bg-indigo-100 dark:bg-indigo-900/30',
    },
    assignment_graded: {
        Icon: ClipboardCheck,
        label: 'Assignment graded',
        color: 'text-teal-600 dark:text-teal-400',
        bg: 'bg-teal-100 dark:bg-teal-900/30',
    },
    daily_goal: {
        Icon: Target,
        label: 'Daily goal met',
        color: 'text-green-600 dark:text-green-400',
        bg: 'bg-green-100 dark:bg-green-900/30',
    },
    streak_bonus: {
        Icon: Flame,
        label: 'Streak bonus',
        color: 'text-orange-600 dark:text-orange-400',
        bg: 'bg-orange-100 dark:bg-orange-900/30',
    },
    badge_earned: {
        Icon: Award,
        label: 'Badge earned',
        color: 'text-amber-600 dark:text-amber-400',
        bg: 'bg-amber-100 dark:bg-amber-900/30',
    },
    level_up: {
        Icon: TrendingUp,
        label: 'Level up bonus',
        color: 'text-fuchsia-600 dark:text-fuchsia-400',
        bg: 'bg-fuchsia-100 dark:bg-fuchsia-900/30',
    },
    referral: {
        Icon: Gift,
        label: 'Referral bonus',
        color: 'text-pink-600 dark:text-pink-400',
        bg: 'bg-pink-100 dark:bg-pink-900/30',
    },
    challenge_win: {
        Icon: Trophy,
        label: 'Challenge won',
        color: 'text-yellow-600 dark:text-yellow-400',
        bg: 'bg-yellow-100 dark:bg-yellow-900/30',
    },
    community: {
        Icon: Users,
        label: 'Community activity',
        color: 'text-sky-600 dark:text-sky-400',
        bg: 'bg-sky-100 dark:bg-sky-900/30',
    },
    manual: {
        Icon: SlidersHorizontal,
        label: 'Manual adjustment',
        color: 'text-surface-600 dark:text-surface-300',
        bg: 'bg-surface-100 dark:bg-surface-800',
    },
}

export const getXPMeta = (type) =>
    XP_META[type] || { Icon: Sparkles, label: 'XP earned', color: 'text-surface-600', bg: 'bg-surface-100 dark:bg-surface-800' }

/**
 * Plain-English rules mirroring the server-side XP awards
 * (core/utils.py, content/views.py, analytics/views.py, gamification/services.py).
 */
export const XP_EARNING_RULES = [
    {
        Icon: BookOpen,
        title: 'Finish study material',
        detail: 'Notes, revision & formula sheets 5 XP · PDFs 6 XP · Videos and interactive lessons 8 XP.',
        value: '5–8 XP',
    },
    {
        Icon: ClipboardCheck,
        title: 'Complete a quiz',
        detail: 'Questions × 5, scaled by your accuracy. Capped at 25 XP (40 XP for the daily challenge).',
        value: 'up to 25 XP',
    },
    {
        Icon: FileText,
        title: 'Complete a mock test',
        detail: 'Same as a quiz, then doubled because mock tests are longer.',
        value: 'up to 50 XP',
    },
    {
        Icon: Brain,
        title: 'Complete an AI quiz',
        detail: 'From AI Learning / the doubt solver. Questions × 5 scaled by accuracy, plus an accuracy bonus (+10 at 100%, +5 at 80%, +2 at 60%). Capped at 25 XP per attempt and 75 XP per day.',
        value: 'up to 25 XP',
    },
    {
        Icon: Target,
        title: 'Hit your daily study goal',
        detail: '25 XP base plus a streak bonus of 3 XP per streak day (bonus capped at 25 XP).',
        value: '25–50 XP',
    },
    {
        Icon: Users,
        title: 'Help out in the community',
        detail: 'Asking 5 · polls 5 · quizzes 8 · answering 8 · best answer 20 · each like received 2. Counted in the same total, and each is awarded only once.',
        value: '2–20 XP',
    },
    {
        Icon: Award,
        title: 'Earn a badge',
        detail: 'Each badge carries its own XP reward, granted the moment you unlock it.',
        value: 'varies',
    },
    {
        Icon: TrendingUp,
        title: 'Level up',
        detail: 'A one-off bonus of 20 XP × the new level, every time you reach a new level.',
        value: 'level × 20 XP',
    },
]

/**
 * Mirrors StudentProfile.calculate_level / xp_for_next_level:
 * level 1 needs 100 XP, and every level after needs 50% more than the last.
 */
export const getLevelBounds = (level = 1) => {
    let required = 100
    let start = 0
    for (let l = 1; l < level; l += 1) {
        start += required
        required = Math.floor(required * 1.5)
    }
    return { start, end: start + required, span: required }
}

export const getLevelProgress = (totalXP = 0, level = 1) => {
    const { start, span } = getLevelBounds(level)
    if (!span) return 0
    return Math.max(0, Math.min(100, Math.round(((totalXP - start) / span) * 100)))
}
