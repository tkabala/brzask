import type { ChangeOut } from '@/client/types.gen'

/** The words for each action that can be proposed; others show as logged. */
const ACTIONS = {
  'source.mute': 'mute',
  'source.enable': 'enable',
  'source.reject': 'reject',
  'source.rename': 'rename',
  'source.note': 'note',
  'source.add': 'addSource',
  'interest.add': 'addInterest',
  'interest.update': 'editInterest',
  'digest.pause': 'pause',
  'digest.resume': 'resume',
} as const

export type ActionKey = (typeof ACTIONS)[keyof typeof ACTIONS]

export function actionKey(action: string): ActionKey | null {
  return Object.hasOwn(ACTIONS, action) ? ACTIONS[action as keyof typeof ACTIONS] : null
}

export interface ChangedField {
  name: string
  before: string
  after: string
}

/**
 * Each field the change sets, as it was and as it would be; `-` for nothing.
 *
 * `before` may hold more: a mute keeps the note it saw, so approving can tell
 * whether the source was edited since, but sets the note to its reason. A
 * change that only ends something (a resume) shows what it ends.
 */
export function changedFields(change: ChangeOut): ChangedField[] {
  const before = change.before ?? {}
  const after = change.after ?? {}
  const names = Object.keys(Object.keys(after).length > 0 ? after : before)
  return names.map((name) => ({ name, before: shown(before[name]), after: shown(after[name]) }))
}

function shown(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (Array.isArray(value)) return value.map(shown).join(', ')
  if (typeof value === 'string') return value
  // Numbers, booleans and objects read the same as JSON.
  return JSON.stringify(value)
}

/** `agent:claude` → `claude`. */
export function agentName(actor: string): string {
  return actor.startsWith('agent:') ? actor.slice('agent:'.length) : actor
}
