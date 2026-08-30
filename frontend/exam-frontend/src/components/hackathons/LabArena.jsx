import { FlaskConical, ExternalLink, RefreshCw, Loader2, CheckCircle2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { RichContent } from './hackathonShared'

/**
 * Lab round: the work happens in the notebook workspace, so this screen is a
 * launcher plus a "pull my latest score" sync.
 */
const LabArena = ({ stage, participation, onSync, isSyncing }) => {
  const notebook = stage.notebook

  return (
    <div className="max-w-3xl space-y-5">
      <div className="card p-6">
        <div className="flex items-start gap-4">
          <span className="w-12 h-12 rounded-2xl bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center shrink-0">
            <FlaskConical className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">
              {notebook?.title || 'Hands-on lab'}
            </h2>
            <p className="text-sm text-surface-500 mt-1">
              Work through the lab in the notebook workspace. Your best passing score is
              carried into this round automatically — come back here and sync any time.
            </p>

            {notebook ? (
              <div className="flex flex-wrap items-center gap-2 mt-4">
                <Link
                  to={`/notebooks/${notebook.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-primary"
                >
                  Open the lab <ExternalLink className="w-4 h-4" />
                </Link>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={onSync}
                  disabled={isSyncing}
                >
                  {isSyncing
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <RefreshCw className="w-4 h-4" />}
                  Sync my score
                </button>
              </div>
            ) : (
              <p className="text-sm text-amber-600 mt-4">
                The organisers haven't attached a lab notebook to this round yet.
              </p>
            )}
          </div>
        </div>
      </div>

      {stage.instructions && (
        <div className="card p-6">
          <h3 className="font-semibold mb-3">Instructions</h3>
          <RichContent content={stage.instructions} />
        </div>
      )}

      {participation?.status === 'submitted' || participation?.status === 'evaluated' ? (
        <div className="card p-5 flex items-center gap-3 bg-emerald-50/60 dark:bg-emerald-900/10 border-emerald-100 dark:border-emerald-900/30">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <p className="font-medium text-emerald-700 dark:text-emerald-300">
              Your lab progress has been recorded.
            </p>
            {participation.score != null && (
              <p className="text-emerald-600/80 dark:text-emerald-300/70">
                Score {participation.score} / {participation.max_score}
              </p>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default LabArena
