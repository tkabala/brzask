import type { ChangeOut } from '@/client/types.gen'

import { actionKey, agentName, changedFields } from './describe'

function change(fields: Partial<ChangeOut>): ChangeOut {
  return {
    id: 1,
    created_at: '2026-11-12T08:00:00Z',
    actor: 'agent:claude',
    action: 'source.mute',
    entity_type: 'source',
    entity_id: '3',
    entity: 'Blog',
    before: null,
    after: null,
    reason: null,
    status: 'proposed',
    decided_at: null,
    ...fields,
  }
}

describe('describing a change', () => {
  it('names known actions and leaves others as they are', () => {
    expect(actionKey('source.mute')).toBe('mute')
    expect(actionKey('interest.update')).toBe('editInterest')
    expect(actionKey('source.move')).toBeNull()
  })

  it('lists every field it changes, before and after', () => {
    expect(
      changedFields(
        change({ before: { status: 'active', note: 'fine' }, after: { status: 'muted' } }),
      ),
    ).toEqual([
      { name: 'status', before: 'active', after: 'muted' },
      { name: 'note', before: 'fine', after: '-' },
    ])
  })

  it('shows an addition with nothing before', () => {
    expect(
      changedFields(
        change({
          action: 'interest.add',
          after: { topic: 'Go', keywords: ['go', 'golang'], notes: '', active: true },
        }),
      ),
    ).toEqual([
      { name: 'topic', before: '-', after: 'Go' },
      { name: 'keywords', before: '-', after: 'go, golang' },
      { name: 'notes', before: '-', after: '-' },
      { name: 'active', before: '-', after: 'true' },
    ])
  })

  it('names the agent without its prefix', () => {
    expect(agentName('agent:claude')).toBe('claude')
    expect(agentName('user')).toBe('user')
  })
})
