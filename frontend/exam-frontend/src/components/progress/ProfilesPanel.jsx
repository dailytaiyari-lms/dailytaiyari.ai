import { BandBar, STATUS_CLASS, STATUS_TEXT, pct } from './progressUi'

function FacetList({ title, rows }) {
  if (!rows.length) return null
  return (
    <div>
      <p className="text-xs font-semibold text-surface-500 mb-2">{title}</p>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.key}>
            <div className="flex justify-between gap-2 text-sm mb-1">
              <span className="truncate">{row.label}</span>
              <span className={`text-xs shrink-0 ${STATUS_CLASS[row.status]}`}>
                {row.mastery != null ? pct(row.mastery) : STATUS_TEXT.not_enough_data}
              </span>
            </div>
            <BandBar node={row} />
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Skills and thinking levels per subject. */
export default function ProfilesPanel({ profiles }) {
  if (!profiles?.length) return null
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {profiles.map((profile) => (
        <div
          key={profile.subject_id}
          className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700"
        >
          <h3 className="text-sm font-semibold mb-3">{profile.subject}: skills and thinking</h3>
          {profile.status === 'needs_tagging' ? (
            <p className="text-sm text-surface-400">
              This appears once the subject's questions have been tagged.
            </p>
          ) : profile.skills.length || profile.thinking_levels.length ? (
            <div className="space-y-4">
              <FacetList title="Skills" rows={profile.skills} />
              <FacetList title="Thinking levels" rows={profile.thinking_levels} />
            </div>
          ) : (
            <p className="text-sm text-surface-400">No tagged answers yet.</p>
          )}
        </div>
      ))}
    </div>
  )
}
