/**
 * Shared notebook document helpers for the client.
 *
 * Mirrors backend/notebooks/nbformat_utils.py — keep the two in sync. The
 * document format is standard nbformat v4, with DailyTaiyari authoring
 * metadata under each cell's `metadata.dailytaiyari`.
 */

export const META_KEY = 'dailytaiyari'

export const ROLE_READONLY = 'readonly'
export const ROLE_EDITABLE = 'editable'
export const ROLE_ANSWER = 'answer'
export const CELL_ROLES = [ROLE_READONLY, ROLE_EDITABLE, ROLE_ANSWER]

export const ROLE_LABELS = {
  [ROLE_READONLY]: 'Locked',
  [ROLE_EDITABLE]: 'Scratch',
  [ROLE_ANSWER]: 'Your answer',
}

let uid = 0
export const nextCellKey = () => `c${Date.now().toString(36)}${++uid}`

export const sourceToText = (source) =>
  Array.isArray(source) ? source.join('') : (source ?? '')

export const cellMeta = (cell) => {
  const meta = cell?.metadata?.[META_KEY]
  return meta && typeof meta === 'object' ? meta : {}
}

export const cellRole = (cell) => {
  const role = cellMeta(cell).role
  if (CELL_ROLES.includes(role)) return role
  return cell?.cell_type === 'code' ? ROLE_EDITABLE : ROLE_READONLY
}

export const cellGradeId = (cell) => String(cellMeta(cell).grade_id || '').trim()

export const isEditable = (cell) => cellRole(cell) !== ROLE_READONLY

export const emptyNotebook = () => ({
  cells: [],
  metadata: {
    kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' },
    language_info: { name: 'python', version: '3.11' },
  },
  nbformat: 4,
  nbformat_minor: 5,
})

export const makeCell = (cellType = 'code', role = ROLE_EDITABLE, source = '') => ({
  cell_type: cellType,
  source,
  metadata: { [META_KEY]: { role } },
  ...(cellType === 'code' ? { outputs: [], execution_count: null } : {}),
})

/** Attach a stable client-side key to every cell so React lists stay stable. */
export const withKeys = (document) => {
  const doc = document && typeof document === 'object' ? document : emptyNotebook()
  return {
    ...emptyNotebook(),
    ...doc,
    cells: (doc.cells || []).map((cell) => ({
      ...cell,
      source: sourceToText(cell.source),
      outputs: cell.cell_type === 'code' ? cell.outputs || [] : undefined,
      __key: cell.__key || nextCellKey(),
    })),
  }
}

/** Strip client-only fields before sending a document to the API. */
export const forApi = (document, { includeOutputs = true } = {}) => ({
  ...emptyNotebook(),
  ...document,
  cells: (document?.cells || []).map((cell) => {
    const { __key, ...rest } = cell
    const clean = { ...rest, source: sourceToText(rest.source) }
    if (clean.cell_type === 'code') {
      clean.outputs = includeOutputs ? clean.outputs || [] : []
      clean.execution_count = includeOutputs ? (clean.execution_count ?? null) : null
    } else {
      delete clean.outputs
      delete clean.execution_count
    }
    return clean
  }),
})

/** Concatenated source of every code cell, in order (used by "Run all"). */
export const codeCells = (document) =>
  (document?.cells || [])
    .map((cell, index) => ({ cell, index }))
    .filter(({ cell }) => cell.cell_type === 'code')

/** True when the student has written something into at least one answer cell. */
export const hasAnswers = (document) =>
  (document?.cells || []).some(
    (cell) => cellRole(cell) === ROLE_ANSWER && sourceToText(cell.source).trim().length > 0,
  )

export const downloadNotebook = (document, filename = 'notebook.ipynb') => {
  const blob = new Blob([JSON.stringify(forApi(document), null, 1)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = filename.endsWith('.ipynb') ? filename : `${filename}.ipynb`
  window.document.body.appendChild(link)
  link.click()
  window.document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
