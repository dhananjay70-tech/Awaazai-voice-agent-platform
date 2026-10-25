import assert from 'node:assert/strict'
import { test } from 'node:test'
import { agentToForm, changedFields, fieldLabels, formToPatch, isDirty, unsavedKeys } from './agentForm.js'
import { clearStudioDraft, loadStudioDraft, saveStudioDraft } from './studioDraft.js'

const agent = {
  id: 'a1',
  name: 'Reception',
  description: 'Books visits',
  system_prompt: 'Be helpful.',
  language: 'en',
  voice_config: { provider: null, voice_id: null, speed: 1 },
  is_active: true,
  updated_at: '2026-01-01T00:00:00Z',
}

test('an edit the server could never see is not an unsaved change', () => {
  const base = agentToForm(agent)
  assert.equal(isDirty({ ...base, systemPrompt: 'Be helpful.  \n' }, base), false)
  assert.equal(isDirty({ ...base, name: '  Reception ' }, base), false)
  assert.equal(isDirty({ ...base, description: '' }, { ...base, description: '   ' }), false)
  assert.equal(isDirty({ ...base, speed: '1.0' }, base), false)
})

test('dirty and the PATCH body always agree: dirty means there is something to send, clean means nothing', () => {
  const base = agentToForm(agent)
  const edits = [
    { name: 'Front desk' },
    { description: '' },
    { systemPrompt: 'New' },
    { language: 'hi-Latn' },
    { isActive: false },
    { voiceProvider: 'p' },
    { voiceId: 'v' },
    { speed: 1.5 },
    { systemPrompt: 'Be helpful.   ' },
    { name: ' Reception' },
  ]
  for (const edit of edits) {
    const form = { ...base, ...edit }
    assert.equal(isDirty(form, base), Object.keys(formToPatch(form, agent)).length > 0, JSON.stringify(edit))
  }
})

test('every edited field is in the PATCH body, with voice settings sent as one object', () => {
  const form = {
    ...agentToForm(agent),
    name: 'N',
    description: 'D',
    systemPrompt: 'P',
    language: 'hi',
    isActive: false,
    voiceProvider: 'deepgram',
    voiceId: 'aura',
    speed: '1.4',
  }
  assert.deepEqual(formToPatch(form, agent), {
    name: 'N',
    description: 'D',
    system_prompt: 'P',
    language: 'hi',
    is_active: false,
    voice_config: { provider: 'deepgram', voice_id: 'aura', speed: 1.4 },
  })
})

test('a cleared description is sent as null so the server really clears it', () => {
  assert.deepEqual(formToPatch({ ...agentToForm(agent), description: '' }, agent), { description: null })
})

test('verification lists exactly the fields the server did not store as sent', () => {
  const patch = { name: 'N', language: 'hi', voice_config: { provider: null, voice_id: 'v', speed: 1.4 } }
  const stored = { ...agent, name: 'N', language: 'hi', voice_config: { provider: null, voice_id: 'v', speed: 1.4 } }
  assert.deepEqual(unsavedKeys(patch, stored), [])
  assert.deepEqual(unsavedKeys(patch, { ...stored, language: 'en' }), ['language'])
  assert.deepEqual(unsavedKeys(patch, { ...stored, voice_config: { provider: null, voice_id: 'other', speed: 1.4 } }), ['voice_config'])
  assert.deepEqual(unsavedKeys({ description: null }, { ...agent, description: 'still here' }), ['description'])
})

test('changed-elsewhere detection names the fields that differ between two server copies', () => {
  assert.deepEqual(changedFields(agent, agent), [])
  assert.deepEqual(changedFields(agent, { ...agent, name: 'Other', is_active: false }), ['name', 'is_active'])
  assert.deepEqual(fieldLabels(['name', 'system_prompt', 'voice_config', 'is_active']), ['name', 'system prompt', 'voice settings', 'active status'])
})

function memoryStorage() {
  const data = new Map()
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k) }
}

test('unsaved edits are kept per agent for this tab, restored, and cleared', () => {
  const storage = memoryStorage()
  const form = agentToForm(agent)
  assert.equal(saveStudioDraft('a1', { ...form, name: 'Edited' }, storage), true)
  assert.equal(loadStudioDraft('a1', storage).form.name, 'Edited')
  assert.equal(loadStudioDraft('a2', storage), null)
  clearStudioDraft('a1', storage)
  assert.equal(loadStudioDraft('a1', storage), null)
})

test('a corrupt or foreign draft is ignored and removed; blocked storage never throws', () => {
  const storage = memoryStorage()
  storage.setItem('awaaz.studioDraft.a1', '{not json')
  assert.equal(loadStudioDraft('a1', storage), null)
  storage.setItem('awaaz.studioDraft.a1', JSON.stringify({ form: 'nope' }))
  assert.equal(loadStudioDraft('a1', storage), null)
  assert.equal(storage.getItem('awaaz.studioDraft.a1'), null)
  const blocked = { getItem: () => { throw new Error('x') }, setItem: () => { throw new Error('x') }, removeItem: () => { throw new Error('x') } }
  assert.equal(saveStudioDraft('a1', {}, blocked), false)
  assert.equal(loadStudioDraft('a1', blocked), null)
  assert.doesNotThrow(() => clearStudioDraft('a1', blocked))
  assert.equal(saveStudioDraft('a1', {}, null), false)
})
