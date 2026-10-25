import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  agentToForm,
  backendFieldsToForm,
  emptyAgentForm,
  formToCreatePayload,
  formToPatch,
  isDirty,
  MAX_SYSTEM_PROMPT,
  validateAgentForm,
  FIELD_TAB,
} from './agentForm.js'
import { languageOptions, voiceLanguageFor } from './languages.js'

const saved = {
  id: 'a1',
  owner_id: 'u1',
  name: 'Reception',
  description: null,
  system_prompt: 'Be helpful.',
  language: 'en',
  voice_config: { provider: null, voice_id: null, speed: 1 },
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const valid = { ...emptyAgentForm(), name: 'Reception', systemPrompt: 'Be helpful.' }

test('an empty form fails validation for name and instructions only', () => {
  assert.deepEqual(Object.keys(validateAgentForm(emptyAgentForm())).sort(), ['name', 'systemPrompt'])
  assert.deepEqual(validateAgentForm(valid), {})
})

test('limits mirror the backend schema', () => {
  assert.ok(validateAgentForm({ ...valid, name: 'x'.repeat(101) }).name)
  assert.ok(validateAgentForm({ ...valid, description: 'x'.repeat(501) }).description)
  assert.ok(validateAgentForm({ ...valid, systemPrompt: 'x'.repeat(MAX_SYSTEM_PROMPT + 1) }).systemPrompt)
  assert.equal(validateAgentForm({ ...valid, systemPrompt: 'x'.repeat(MAX_SYSTEM_PROMPT) }).systemPrompt, undefined)
  assert.ok(validateAgentForm({ ...valid, language: 'english please' }).language)
})

test('voice speed must stay within 0.5 to 2.0', () => {
  for (const speed of [0.4, 2.1, '', 'fast']) assert.ok(validateAgentForm({ ...valid, speed }).speed, String(speed))
  for (const speed of [0.5, 1, 2, '1.5']) assert.equal(validateAgentForm({ ...valid, speed }).speed, undefined, String(speed))
})

test('create payload trims text and turns blanks into null', () => {
  const payload = formToCreatePayload({ ...valid, name: '  Reception ', description: '  ', voiceProvider: ' ', voiceId: ' v1 ', speed: '1.25' })
  assert.deepEqual(payload, {
    name: 'Reception',
    description: null,
    system_prompt: 'Be helpful.',
    language: 'en',
    voice_config: { provider: null, voice_id: 'v1', speed: 1.25 },
    is_active: true,
  })
  assert.equal('owner_id' in payload, false) // ownership is decided by the server, never the client
})

test('loading an agent and saving it unchanged produces an empty patch', () => {
  assert.deepEqual(formToPatch(agentToForm(saved), saved), {})
})

test('patch contains only changed fields; voice settings are sent together', () => {
  const form = { ...agentToForm(saved), name: 'Front desk', isActive: false, speed: 1.5 }
  assert.deepEqual(formToPatch(form, saved), {
    name: 'Front desk',
    is_active: false,
    voice_config: { provider: null, voice_id: null, speed: 1.5 },
  })
  assert.deepEqual(formToPatch({ ...agentToForm(saved), description: '' }, saved), {}) // null -> blank is not a change
})

test('dirty tracking compares against the saved baseline', () => {
  const baseline = agentToForm(saved)
  assert.equal(isDirty({ ...baseline }, baseline), false)
  assert.equal(isDirty({ ...baseline, name: 'x' }, baseline), true)
  assert.equal(isDirty({ ...baseline, speed: '1.0' }, baseline), false) // slider strings are not edits
  assert.equal(isDirty({ ...baseline, speed: '1.2' }, baseline), true)
})

test('backend field names are mapped to form field names', () => {
  assert.deepEqual(backendFieldsToForm({ system_prompt: 'a', 'voice_config.speed': 'b', unknown: 'c' }), { systemPrompt: 'a', speed: 'b' })
})

test('languages map to a verified voice mode and unknown values are kept when editing', () => {
  assert.equal(voiceLanguageFor('hi-Latn'), 'hinglish')
  assert.equal(voiceLanguageFor('fr'), null)
  assert.equal(languageOptions('en').length, 3)
  assert.equal(languageOptions('fr').at(-1).value, 'fr')
})

test('every form field is shown on the Agent tab of the studio', () => {
  for (const tab of Object.values(FIELD_TAB)) assert.equal(tab, 'agent')
  assert.equal(Object.keys(FIELD_TAB).length, 8)
})
