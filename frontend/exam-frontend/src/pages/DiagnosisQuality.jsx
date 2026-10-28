import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { insightsService } from '../services/insightsService'
import Loading from '../components/common/Loading'
import { LABEL_ORDER, LABEL_TEXT } from '../components/insights/labels'

const SELF_REPORTS = ['slipped', 'ran_out_of_time', 'guessed', 'didnt_know']
const SELF_REPORT_TEXT = {
  slipped: 'Slipped', ran_out_of_time: 'Out of time', guessed: 'Guessed', didnt_know: "Didn't know",
}

/** Admin: how well diagnosis labels agree with what students say happened. */
export default function DiagnosisQuality() {
  const [days, setDays] = useState(30)
  const { data, isLoading } = useQuery({
    queryKey: ['diagnosisCalibration', days],
    queryFn: () => insightsService.getCalibration(days),
  })
  if (isLoading) return <Loading fullScreen />
  if (!data) return null

  const labels = LABEL_ORDER.filter((label) => data.labels[label])
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Gauge className="text-primary-500" /> Diagnosis quality
          </h1>
          <p className="text-surface-500 mt-1">
            Classifier v{data.classifier_version} · {data.total} answers ·
            {' '}{data.with_timeline} with timing · {data.stats_usual} with measured usual time
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="px-3 py-2 rounded-xl border border-surface-300 dark:border-surface-600 bg-white dark:bg-surface-800 text-sm"
        >
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>

      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700 overflow-x-auto">
        <h3 className="text-sm font-semibold text-surface-500 mb-3">Labels vs self-reports</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-surface-400 border-b border-surface-200 dark:border-surface-700">
              <th className="py-2 pr-3">Label</th>
              <th className="py-2 pr-3">Answers</th>
              {SELF_REPORTS.map((r) => <th key={r} className="py-2 pr-3">{SELF_REPORT_TEXT[r]}</th>)}
              <th className="py-2">Agreement</th>
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label} className="border-b border-surface-100 dark:border-surface-700/50">
                <td className="py-2 pr-3">{LABEL_TEXT[label]}</td>
                <td className="py-2 pr-3">{data.labels[label]}</td>
                {SELF_REPORTS.map((r) => (
                  <td key={r} className="py-2 pr-3">{data.confusion[label]?.[r] ?? 0}</td>
                ))}
                <td className="py-2">
                  {data.agreement[label] != null ? `${Math.round(data.agreement[label] * 100)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <h3 className="text-sm font-semibold text-surface-500 mb-3">Thresholds in use</h3>
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1 text-sm">
          {Object.entries(data.thresholds).map(([key, value]) => (
            <div key={key} className="flex justify-between gap-2">
              <dt className="text-surface-500">{key}</dt>
              <dd className="font-mono">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
