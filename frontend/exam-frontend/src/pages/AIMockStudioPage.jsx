import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Sparkles } from 'lucide-react'
import AIMockStudio from '../components/admin/mockAi/AIMockStudio'

/* ===========================================================================
 * The full-page home of the AI Mock Studio.
 *
 * Creating a paper deserves the whole screen — the composer alone carries a
 * blueprint, sections and marking rules, and the review pane is a full exam
 * paper. Modifying an existing test opens the same studio in a drawer from the
 * builder instead, where the paper's context already lives.
 * ========================================================================= */
export default function AIMockStudioPage() {
    const navigate = useNavigate()

    return (
        <div className="mx-auto max-w-7xl px-4 py-8">
            <button
                onClick={() => navigate('/admin/mock-tests')}
                className="mb-4 flex items-center gap-2 text-sm text-surface-500 hover:text-surface-800 dark:hover:text-surface-200"
            >
                <ArrowLeft className="h-4 w-4" /> All Mock Tests
            </button>

            <div className="mb-6">
                <h1 className="flex items-center gap-2 text-2xl font-bold text-surface-900 dark:text-white">
                    <Sparkles className="h-6 w-6 text-primary-500" /> Generate a mock test with AI
                </h1>
                <p className="mt-1 text-sm text-surface-500">
                    Describe the paper you want, choose the mix of questions, and review every
                    question before anything is saved.
                </p>
            </div>

            <AIMockStudio
                onApplied={(summary) => {
                    if (summary?.mock_test) navigate(`/admin/mock-tests/${summary.mock_test}`)
                }}
            />
        </div>
    )
}
