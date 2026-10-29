import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Archive, Check, ChevronDown, ChevronRight, GitMerge, Pencil, Plus } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'

const LEVEL_TEXT = { sub_subject: 'Sub-subject', topic: 'Topic', subtopic: 'Subtopic' }

function useTreeMutation(courseId, fn, success) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
      result?.warnings?.forEach((warning) => toast(warning, { icon: '⚖️' }))
      if (success) toast.success(success)
    },
    onError: (error) => toast.error(errorText(error)),
  })
}

function NodeRow({ node, subject, courseId, depth, siblingsForMerge, subSubjects }) {
  const [open, setOpen] = useState(depth < 1)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(node.name)
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const update = useTreeMutation(courseId, (body) => syllabusService.updateNode(node.id, body))
  const add = useTreeMutation(courseId, (body) => syllabusService.addNode(courseId, body), 'Subtopic added')
  const merge = useTreeMutation(courseId, (into) => syllabusService.mergeNode(node.id, into), 'Merged')
  const children = node.children || []
  const isTopic = node.level === 'topic'

  return (
    <li>
      <div className="flex flex-wrap items-center gap-2 py-1.5" style={{ paddingLeft: depth * 16 }}>
        {children.length > 0 || isTopic ? (
          <button type="button" onClick={() => setOpen(!open)} className="text-surface-400" aria-label="Toggle">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : <span className="w-3.5" />}
        <span className="text-[10px] uppercase tracking-wide text-surface-400 w-20 shrink-0">{LEVEL_TEXT[node.level]}</span>

        {editing ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => { e.preventDefault(); update.mutate({ name }); setEditing(false) }}
          >
            <input value={name} onChange={(e) => setName(e.target.value)} className="input py-1 text-sm" autoFocus />
            <button type="submit" className="p-1 text-success-600"><Check size={14} /></button>
          </form>
        ) : (
          <span className="text-sm font-medium">{node.name}</span>
        )}
        {node.status === 'proposed' && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-50 dark:bg-primary-900/30 text-primary-600">suggested</span>
        )}

        <span className="ml-auto flex items-center gap-1">
          <input
            type="number" min="0" max="1" step="0.05"
            defaultValue={node.weightage || ''}
            placeholder="weight"
            title="Weightage within its parent (0–1)"
            onBlur={(e) => {
              const value = e.target.value === '' ? 0 : Number(e.target.value)
              if (value !== node.weightage) update.mutate({ weightage: value })
            }}
            className="input py-0.5 px-2 text-xs w-20"
          />
          {node.status === 'proposed' && (
            <button type="button" title="Accept suggestion" onClick={() => update.mutate({ status: 'active' })} className="p-1 text-success-600"><Check size={14} /></button>
          )}
          {!isTopic && (
            <button type="button" title="Rename" onClick={() => setEditing(true)} className="p-1 text-surface-400 hover:text-primary-500"><Pencil size={14} /></button>
          )}
          {isTopic && subSubjects.length > 1 && (
            <select
              value={node.parent || ''}
              onChange={(e) => update.mutate({ parent: e.target.value })}
              title="Move to sub-subject"
              className="input py-0.5 text-xs max-w-[10rem]"
            >
              <option value="" disabled>Move to…</option>
              {subSubjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          {node.level === 'subtopic' && siblingsForMerge.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                const target = siblingsForMerge.find((s) => s.id === e.target.value)
                if (target && window.confirm(`Merge "${node.name}" into "${target.name}"? Questions and history move to "${target.name}".`)) {
                  merge.mutate(target.id)
                }
              }}
              title="Merge into…"
              className="input py-0.5 text-xs max-w-[10rem]"
            >
              <option value="">Merge into…</option>
              {siblingsForMerge.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          {!isTopic && (
            <button
              type="button"
              title="Archive"
              onClick={() => window.confirm(`Archive "${node.name}"?`) && update.mutate({ status: 'archived' })}
              className="p-1 text-surface-400 hover:text-error-500"
            >
              <Archive size={14} />
            </button>
          )}
          {isTopic && (
            <button type="button" title="Add subtopic" onClick={() => { setOpen(true); setAdding(true) }} className="p-1 text-surface-400 hover:text-primary-500"><Plus size={14} /></button>
          )}
        </span>
      </div>

      {open && (
        <ul>
          {children.map((child) => (
            <NodeRow
              key={child.id}
              node={{ ...child, parent: node.id }}
              subject={subject}
              courseId={courseId}
              depth={depth + 1}
              subSubjects={subSubjects}
              siblingsForMerge={child.level === 'subtopic'
                ? allSubtopics(subject).filter((s) => s.id !== child.id)
                : []}
            />
          ))}
          {adding && (
            <li style={{ paddingLeft: (depth + 1) * 16 }} className="py-1.5">
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  add.mutate({ subject: subject.id, level: 'subtopic', parent: node.id, name: newName })
                  setNewName('')
                  setAdding(false)
                }}
              >
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New subtopic" className="input py-1 text-sm" autoFocus />
                <button type="submit" className="btn-primary text-xs px-3 py-1">Add</button>
                <button type="button" onClick={() => setAdding(false)} className="text-xs text-surface-500">Cancel</button>
              </form>
            </li>
          )}
        </ul>
      )}
    </li>
  )
}

function allSubtopics(subject) {
  const out = []
  const walk = (nodes) => nodes.forEach((n) => {
    if (n.level === 'subtopic') out.push({ id: n.id, name: n.name })
    walk(n.children || [])
  })
  walk(subject.nodes)
  return out
}

function SubjectTree({ subject, courseId, packsAvailable }) {
  const [newGroup, setNewGroup] = useState('')
  const addGroup = useTreeMutation(courseId, (body) => syllabusService.addNode(courseId, body), 'Sub-subject added')
  const savePacks = useTreeMutation(courseId, (keys) => syllabusService.setSkillPacks(courseId, { [subject.id]: keys }), 'Skill packs saved')
  const subSubjects = subject.nodes.filter((n) => n.level === 'sub_subject').map((n) => ({ id: n.id, name: n.name }))

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h3 className="font-semibold">{subject.name}</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-surface-500">Skill packs:</span>
          {packsAvailable.map((pack) => {
            const on = subject.packs.includes(pack.key)
            return (
              <button
                key={pack.key}
                type="button"
                onClick={() => savePacks.mutate(on ? subject.packs.filter((k) => k !== pack.key) : [...subject.packs, pack.key])}
                className={`px-2 py-0.5 rounded-full border ${on ? 'bg-primary-500 border-primary-500 text-white' : 'border-surface-300'}`}
              >
                {pack.label}
              </button>
            )
          })}
        </div>
      </div>
      {!subject.has_tree ? (
        <p className="text-sm text-surface-400">No tree yet.</p>
      ) : (
        <ul>
          {subject.nodes.map((node) => (
            <NodeRow key={node.id} node={node} subject={subject} courseId={courseId} depth={0} subSubjects={subSubjects} siblingsForMerge={[]} />
          ))}
        </ul>
      )}
      {subject.has_tree && (
        <form
          className="flex items-center gap-2 mt-3"
          onSubmit={(e) => { e.preventDefault(); addGroup.mutate({ subject: subject.id, level: 'sub_subject', name: newGroup }); setNewGroup('') }}
        >
          <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} placeholder="New sub-subject" className="input py-1 text-sm" />
          <button type="submit" disabled={!newGroup.trim()} className="btn-secondary text-xs px-3 py-1">Add</button>
        </form>
      )}
    </div>
  )
}

/** Collapsible syllabus tree per subject, with every editor operation. */
export default function TreeEditor({ courseId, tree }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-surface-500">
        Course topics come from the course and can't be renamed here. Editing a suggested subtopic accepts it.
        Adding, renaming, archiving or merging re-tags the affected questions on the next “Tag questions” run.
      </p>
      {tree.subjects.map((subject) => (
        <SubjectTree key={subject.id} subject={subject} courseId={courseId} packsAvailable={tree.skill_packs_available} />
      ))}
    </div>
  )
}
