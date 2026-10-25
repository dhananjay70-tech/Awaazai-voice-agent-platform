import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AGENT_TEMPLATES, templateById, templateToFormValues } from './agentTemplates.js'
import { emptyAgentForm, MAX_DESCRIPTION, MAX_NAME, validateAgentForm } from './agentForm.js'
import { MAX_FIRST_MESSAGE, clearFirstMessageDraft, loadFirstMessageDraft, saveFirstMessageDraft } from './firstMessage.js'
import { voiceLanguageFor } from './languages.js'

test('the four requested templates exist with unique ids', () => {
  assert.deepEqual(AGENT_TEMPLATES.map((template) => template.label), ['Customer Support Agent', 'Personal Assistant', 'Appointment Booking Agent', 'Sales Assistant'])
  assert.equal(new Set(AGENT_TEMPLATES.map((template) => template.id)).size, 4)
})

test('every template produces a form the backend rules accept, in a language the voice service supports', () => {
  for (const template of AGENT_TEMPLATES) {
    const form = { ...emptyAgentForm(), ...templateToFormValues(template) }
    assert.deepEqual(validateAgentForm(form), {}, template.id)
    assert.ok(template.name.length <= MAX_NAME && template.description.length <= MAX_DESCRIPTION)
    assert.ok(voiceLanguageFor(template.language), template.id)
    assert.ok(template.firstMessage.length <= MAX_FIRST_MESSAGE)
  }
})

test('templates make no claims about real capabilities they do not have', () => {
  const booking = templateById('booking')
  assert.match(booking.systemPrompt, /cannot check a real calendar/)
  assert.equal(templateById('missing'), null)
})

function memoryStorage() {
  const data = new Map()
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key), size: () => data.size }
}

test('the first-message draft is stored per agent in the browser only', () => {
  const storage = memoryStorage()
  assert.equal(saveFirstMessageDraft('a1', 'Hello!', storage), true)
  assert.equal(saveFirstMessageDraft('a2', 'Hi there', storage), true)
  assert.equal(loadFirstMessageDraft('a1', storage), 'Hello!')
  assert.equal(loadFirstMessageDraft('a2', storage), 'Hi there')
  assert.equal(loadFirstMessageDraft('missing', storage), '')
  clearFirstMessageDraft('a1', storage)
  assert.equal(loadFirstMessageDraft('a1', storage), '')
  assert.equal(storage.size(), 1)
})

test('blocked storage never throws and reports that nothing was kept', () => {
  const blocked = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') }, removeItem: () => { throw new Error('denied') } }
  assert.equal(saveFirstMessageDraft('a1', 'x', blocked), false)
  assert.equal(loadFirstMessageDraft('a1', blocked), '')
  assert.equal(saveFirstMessageDraft('a1', 'x', null), false)
})
