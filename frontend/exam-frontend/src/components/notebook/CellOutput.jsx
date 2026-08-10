import { memo } from 'react'
import DOMPurify from 'dompurify'
import { AlertTriangle } from 'lucide-react'

/**
 * Renders nbformat cell outputs: stdout/stderr streams, execute results
 * (including pandas' HTML tables), matplotlib figures, and tracebacks.
 */

const TextBlock = ({ text, tone = 'default' }) => (
  <pre
    className={`whitespace-pre-wrap break-words font-mono text-xs leading-relaxed px-3 py-2 ${
      tone === 'error'
        ? 'text-red-600 dark:text-red-400'
        : tone === 'stderr'
          ? 'text-amber-700 dark:text-amber-400'
          : 'text-surface-700 dark:text-surface-200'
    }`}
  >
    {text}
  </pre>
)

const HtmlBlock = ({ html }) => (
  // Rich reprs (notably pandas DataFrames) are HTML. This HTML is produced by
  // *student* code and is persisted with the submission, so an instructor
  // later views it in the grading UI — sanitize it, or a crafted `_repr_html_`
  // would be stored XSS against staff.
  <div
    className="nb-html-output overflow-x-auto px-3 py-2 text-xs"
    dangerouslySetInnerHTML={{
      __html: DOMPurify.sanitize(String(html), { FORBID_TAGS: ['style', 'form'] }),
    }}
  />
)

const OutputItem = ({ output }) => {
  if (!output) return null

  if (output.output_type === 'stream') {
    return <TextBlock text={output.text} tone={output.name === 'stderr' ? 'stderr' : 'default'} />
  }

  if (output.output_type === 'error') {
    return (
      <div className="border-l-2 border-red-400">
        <TextBlock text={output.traceback || output.evalue || 'Error'} tone="error" />
      </div>
    )
  }

  const data = output.data || {}
  if (data['image/png']) {
    return (
      <div className="px-3 py-2">
        <img
          src={`data:image/png;base64,${data['image/png']}`}
          alt="Figure"
          className="max-w-full rounded-lg bg-white"
        />
      </div>
    )
  }
  if (data['text/html']) return <HtmlBlock html={data['text/html']} />
  if (data['text/plain']) return <TextBlock text={data['text/plain']} />
  return null
}

const CellOutput = ({ outputs, live }) => {
  const hasOutputs = (outputs || []).length > 0
  if (!hasOutputs && !live) return null

  return (
    <div className="border-t border-surface-200 dark:border-surface-700 bg-surface-50/70 dark:bg-surface-900/40 rounded-b-xl max-h-[26rem] overflow-auto">
      {live ? <TextBlock text={live} /> : null}
      {(outputs || []).map((output, index) => (
        <OutputItem key={index} output={output} />
      ))}
    </div>
  )
}

export const OutputWarning = ({ children }) => (
  <div className="flex items-start gap-2 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
    <span>{children}</span>
  </div>
)

export default memo(CellOutput)
